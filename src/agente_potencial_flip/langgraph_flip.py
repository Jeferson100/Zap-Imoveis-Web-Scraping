"""Loop explicito do flip com loop engineering (artigo "The Art of Loop
Engineering", LangChain, jun/2026): empilha Loop 1 (agent loop) + Loop 2
(verification loop).

Diferencas para `react_agent_flip.py` (deepagents, intocado):
  - Loop 1: o roteamento das fases (visao -> dados -> veredito) e um
    `StateGraph` dirigido por Python — o LLM nao escolhe tools nem navega o
    historico. Visao roda no roteador de imagens; dados nao gasta LLM; so o
    veredito (e o pensamento opcional) chama modelo de texto.
  - Loop 2: grader DETERMINISTICO depois do veredito, com feedback e 1 retry.
    Graders baratos porque a matematica e nossa:
      G1 trava regra 15%    — `ajustar_saida_pela_regra` (custo zero)
      G2 carimbo de imovel  — o LLM ecoa valor/metragem/roi/reforma do imovel
          ATUAL no inicio da justificativa; carimbo errado = imovel errado
          avaliado (bug real visto no notebook com thread fixo "flip": o run
          10 devolveu o veredito byte-a-byte do run 8)
      G3 completude         — flip=True exige riscos+recomendacoes
      G4 sanidade do score  — limite [0, 10]
  - `thread_id` por imovel: sem heranca de historico entre imoveis.

Env:
    FLIP_MODEL/FLIP_BASE_URL/FLIP_API_KEY/FLIP_TIMEOUT -> modelo_llm.py
    FLIP_LOOP_TIMEOUT   -> teto por chamada LLM em s (default 240)
    FLIP_PENSAR=0       -> corta as chamadas LLM de pensamento (default ON)
    FLIP_LOOP_DEBUG     -> log do grafo (default off)

Custo por imovel: 1 chamada de veredito (+1 por retry do grader) + 1 chamada
curta de pensamento por fase + visao (roteador de imagens, so com fotos).
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from shared.serialization import converter_numpy

from .modelo_llm import criar_modelo_flip, modelo_flip_padrao
from .schemas import AnalisePotencialFlip
from .tools_flip import (
    CUSTO_REFORMA_M2,
    MAX_FOTOS_TOOL,
    ROI_MINIMO,
    ajustar_saida_pela_regra,
    calcular_metricas_flip,
    descrever_fotos_tool,
    limpar_nan,
)

logger = logging.getLogger(__name__)

TEMPO_MAX_CALL_S = int(os.environ.get("FLIP_LOOP_TIMEOUT", "240"))
TENTATIVAS_VEREDITO = 2
PENSAR_ATIVO = os.environ.get("FLIP_PENSAR", "1").strip().lower() not in (
    "0", "false", "no", "off",
)
DEBUG = bool(os.environ.get("FLIP_LOOP_DEBUG"))

# Desconto vs predicao acima disso = outlier do valor_predito (caso real do
# notebook: R$879k predito para imovel de R$340k). Nao trava a decisao; so
# aviso obrigatorio no prompt do veredito.
LIMITE_SUSPEITA_PCT = 50.0

FALLBACK_LOOP: Dict[str, Any] = {
    "score_potencial_flip": 0.0,
    "potencial_house_flip": "False",
    "justificativa_potencial": "",
    "riscos": ["Falha tecnica do Loop explicito (sombra)"],
    "recomendacoes": [],
    "observacoes": "Fallback sombra — workflow oficial continua valendo",
}

SYSTEM_LOOP = (
    "Voce e um investidor senior de Fix & Flip. Julgue o imovel e responda "
    "SOMENTE no formato estruturado, em portugues. As metricas vao "
    "pre-calculadas em METRICAS_JSON: NAO recalcule nada."
)

ROTEIRO = ("visao", "dados", "veredito")


class LoopFlipState(TypedDict):
    """Estado do grafo (serializavel; callbacks vao no `config`)."""

    payload: Dict[str, Any]
    metricas: Dict[str, Any]
    fase: int                      # 0=visao, 1=dados, 2=veredito
    ultima_etapa: str              # etapa executada no ultimo no_acao
    relatorio_visual: str
    obs_dados: List[str]
    justificativa_feedback: str    # feedback do grader p/ o retry do veredito
    tentativas_veredito: int
    veredito: Dict[str, Any]
    aprovado: bool
    grader_eventos: List[Dict[str, Any]]
    trilha_events: List[Dict[str, str]]
    erro: str


# ------------------------------------------------------------------- modelo
_MODELO_CACHE: Dict[str, Any] = {}


def _modelo(label: str):
    """1 instancia por papel ('pensar' | 'veredito'). Testes offline
    substituem `_MODELO_CACHE` diretamente."""
    if label not in _MODELO_CACHE:
        m = criar_modelo_flip(modelo_flip_padrao())
        if label == "veredito":
            # function_calling = caminho comprovado com gpt-oss no OpenRouter
            # (o deepagents produz `AnalisePotencialFlip` como tool call).
            m = m.with_structured_output(
                AnalisePotencialFlip, method="function_calling"
            )
        _MODELO_CACHE[label] = m
    return _MODELO_CACHE[label]


# -------------------------------------------------------------------- fases
async def _pensar_llm(estado: LoopFlipState, etapa: str, cfg: RunnableConfig) -> str:
    rotulos = {
        "visao": "Vou obter a descricao visual das fotos (se existirem).",
        "dados": "Conferindo os numeros e metricas pre-calculados.",
        "veredito": "Juntando relatorio visual + metricas no veredito final.",
    }
    if not PENSAR_ATIVO:
        return rotulos.get(etapa, "")
    prompt = (
        "Loop ReAct, fase " + etapa + ". Estado: " + json.dumps(
            {
                "tem_fotos": bool(estado["payload"].get("fotos_urls")),
                "roi_conservador": estado["metricas"].get("roi_conservador"),
                "passa_regra_15pct": estado["metricas"].get("passa_regra_15pct"),
            },
            ensure_ascii=False,
        ) + ". Em 1-2 frases, o que fara nesta fase e por que. Nada mais."
    )
    res = await asyncio.wait_for(
        _modelo("pensar").ainvoke([("user", prompt)], config=cfg),
        timeout=TEMPO_MAX_CALL_S,
    )
    return str(getattr(res, "content", res) or "").strip()


async def _fase_visao(estado: LoopFlipState, cfg: RunnableConfig) -> str:
    urls = list(estado["payload"].get("fotos_urls", []) or [])[:MAX_FOTOS_TOOL]
    if not urls:
        return "(sem fotos — avaliacao so numerica + descricao)"
    rel = await asyncio.wait_for(
        descrever_fotos_tool.ainvoke({"fotos_urls": urls}, config=cfg),
        timeout=TEMPO_MAX_CALL_S,
    )
    return str(rel or "(falha ao descrever as fotos)")


def _fase_dados(estado: LoopFlipState) -> List[str]:
    """Fase 2 sem LLM: a matematica ja saiu de `calcular_metricas_flip`.

    `validar_dados_tool` (LlmRouter, ~2min no trace real) fica fora por
    padrao; o grader G2 cobre avaliacao de imovel errado.
    """
    m = estado["metricas"]
    obs = [
        f"roi_conservador={m.get('roi_conservador')}",
        f"passa_regra_15pct={m.get('passa_regra_15pct')}",
        f"discount_vs_predicao_pct={m.get('discount_vs_predicao_pct')}",
        f"discount_vs_bairro_pct={m.get('discount_vs_bairro_pct')}",
        f"custo_reforma_estimado={m.get('custo_reforma_estimado')} "
        f"(R$ {m.get('custo_reforma_por_m2')}/m2 x metragem)",
    ]
    if (m.get("discount_vs_predicao_pct") or 0) > LIMITE_SUSPEITA_PCT:
        obs.append(
            f"DADOS_SUSPEITOS: desconto vs predicao > {LIMITE_SUSPEITA_PCT:.0f}% "
            "— valor_predito provavel outlier; use o benchmark do bairro como "
            "cenario base."
        )
    return obs


def _carimbo(metricas: Dict[str, Any]) -> str:
    return (
        f"[valor_imovel={metricas.get('valor_imovel')}"
        f"|metragem={metricas.get('metragem')}m2"
        f"|roi={metricas.get('roi_conservador')}"
        f"|reforma={metricas.get('custo_reforma_estimado')}]"
    )


def prompt_veredito(estado: LoopFlipState) -> str:
    dados = limpar_nan(
        converter_numpy(dict(estado["payload"].get("dados_imovel", {}) or {}))
    )
    m = estado["metricas"]
    desc = str(estado["payload"].get("descricao_texto", "") or "")[:2000]
    feedback = estado.get("justificativa_feedback", "")
    aviso = f"\nFEEDBACK_DO_GRADER (corrija e leve a serio): {feedback}\n" if feedback else ""
    return (
        "Avalie este imovel para flip.\n"
        f"DADOS_IMOVEL_JSON={json.dumps(dados, ensure_ascii=False)}\n"
        f"METRICAS_JSON={json.dumps(converter_numpy(m), ensure_ascii=False)}\n"
        f"REGRA_15PCT: passa_regra_15pct={m.get('passa_regra_15pct')} "
        f"(roi_conservador={m.get('roi_conservador')}, minimo={ROI_MINIMO})\n"
        f"CUSTO_REFORMA: {m.get('custo_reforma_estimado')} "
        f"(R$ {CUSTO_REFORMA_M2}/m2), ja descontado do lucro em METRICAS_JSON\n"
        f"RELATORIO_VISUAL={estado['relatorio_visual'] or '(sem fotos)'}\n"
        f"OBS_DADOS={json.dumps(estado.get('obs_dados', []), ensure_ascii=False)}\n"
        f"DESCRICAO={desc}{aviso}"
        "Regras:\n"
        "1) potencial_house_flip='True' SOMENTE se passa_regra_15pct=true; "
        "sem dados suficientes, 'False'. Nunca invente custo de reforma; "
        "assuma patologias ocultas.\n"
        "2) Se houver DADOS_SUSPEITOS em OBS_DADOS, trate o benchmark do "
        "bairro como cenario base e registre o risco.\n"
        "3) OBRIGATORIO: comece a justificativa_potencial com o carimbo "
        f"{_carimbo(m)} seguido de espaco. Ele prova que voce avaliou ESTE "
        "imovel (e auditado pelo grader)."
    )


# ------------------------------------------------------- grader (Loop 2, puro)
_CARIMBO_RE = re.compile(
    r"^\[valor_imovel=(-?[0-9.]+)\|metragem=(-?[0-9.]+)m2"
    r"\|roi=(-?[0-9.]+)\|reforma=(-?[0-9.]+)\]"
)


def verificar_veredito(
    veredito: Dict[str, Any], metricas: Dict[str, Any]
) -> Tuple[bool, str]:
    """Grader deterministico do Loop 2 (sem LLM).

    Retorna `(aprovado, feedback)`; `feedback` vazio quando aprovado. No
    retry, o feedback entra no prompt do veredito.
    """
    just = str(veredito.get("justificativa_potencial", "") or "")
    m = _CARIMBO_RE.match(just.strip())
    if not m:
        return (
            False,
            "Carimbo ausente: a justificativa deve COMECAR com "
            f"{_carimbo(metricas)} seguido de espaco. Isto prova que voce "
            "avaliou o imovel desta mensagem, nao um imovel do historico.",
        )
    v, met, roi, reforma = (float(x) for x in m.groups())
    refs = [
        ("valor_imovel", v, metricas.get("valor_imovel")),
        ("metragem", met, metricas.get("metragem")),
        ("roi_conservador", roi, metricas.get("roi_conservador")),
        ("custo_reforma_estimado", reforma, metricas.get("custo_reforma_estimado")),
    ]
    divergentes = [
        f"{campo} citado={c} vs calculado={r}"
        for campo, c, r in refs
        if r is not None and abs(float(c) - float(r)) > 0.02
    ]
    if divergentes:
        return (
            False,
            "Carimbo divergente das METRICAS_JSON do imovel atual ("
            + "; ".join(divergentes)
            + "). Voce provavelmente avaliou outro imovel: reavalie SOMENTE "
            "os dados desta mensagem e ignore qualquer historico.",
        )
    flip = str(veredito.get("potencial_house_flip"))
    if flip == "True" and not veredito.get("riscos"):
        return (False, "flip='True' com `riscos` vazio: liste ao menos 1 risco.")
    if flip == "True" and not veredito.get("recomendacoes"):
        return (
            False,
            "flip='True' com `recomendacoes` vazio: liste ao menos 1 recomendacao.",
        )
    try:
        score = float(veredito.get("score_potencial_flip", 0) or 0)
    except (TypeError, ValueError):
        return (False, "score_potencial_flip invalido; reemita a analise.")
    if not 0.0 <= score <= 10.0:
        return (False, f"score={score} fora de [0,10]; reemita a analise.")
    return (True, "")


# ------------------------------------------------------------------ nos
async def no_pensar(state: LoopFlipState, config: RunnableConfig) -> Dict[str, Any]:
    etapa = ROTEIRO[min(state["fase"], 2)]
    pens = await _pensar_llm(state, etapa, config)
    ev = list(state.get("trilha_events", []))
    ev.append({"tipo": "thought", "fase": etapa, "conteudo": pens})
    return {"trilha_events": ev}


async def no_acao(state: LoopFlipState, config: RunnableConfig) -> Dict[str, Any]:
    fase = state["fase"]
    etapa = ROTEIRO[min(fase, 2)]
    ev = list(state.get("trilha_events", []))
    upd: Dict[str, Any] = {}
    if etapa == "visao":
        rel = await _fase_visao(state, config)
        ev.append({"tipo": "observacao", "fase": etapa, "conteudo": rel[:800]})
        upd = {"relatorio_visual": rel, "fase": fase + 1}
    elif etapa == "dados":
        obs = _fase_dados(state)
        ev.append({"tipo": "observacao", "fase": etapa, "conteudo": "; ".join(obs)})
        upd = {"obs_dados": obs, "fase": fase + 1}
    else:  # veredito
        if state.get("tentativas_veredito"):
            ev.append({
                "tipo": "observacao",
                "fase": "veredito-retry",
                "conteudo": str(state.get("justificativa_feedback", ""))[:200],
            })
        sr = await asyncio.wait_for(
            _modelo("veredito").ainvoke(
                [("system", SYSTEM_LOOP), ("user", prompt_veredito(state))],
                config=config,
            ),
            timeout=TEMPO_MAX_CALL_S,
        )
        saida = sr if isinstance(sr, dict) else sr.model_dump()
        ev.append({
            "tipo": "veredito",
            "fase": etapa,
            "conteudo": json.dumps(
                {
                    "score_potencial_flip": saida.get("score_potencial_flip"),
                    "potencial_house_flip": saida.get("potencial_house_flip"),
                },
                ensure_ascii=False,
            ),
        })
        upd = {"veredito": saida}
    upd["trilha_events"] = ev
    upd["ultima_etapa"] = etapa
    return upd


def rotear_pos_acao(state: LoopFlipState) -> str:
    """Loop 1 em Python: veredito pronto vai para o grader; visao/dados
    voltam ao `pensar`; erro encerra."""
    if state.get("erro"):
        return END
    return "grader" if state.get("ultima_etapa") == "veredito" else "pensar"


async def no_grader(state: LoopFlipState, config: RunnableConfig) -> Dict[str, Any]:
    ok, feedback = verificar_veredito(state["veredito"], state["metricas"])
    tentativa = state.get("tentativas_veredito", 0) + 1
    evg = list(state.get("grader_eventos", []))
    evg.append({
        "tentativa": tentativa,
        "aprovado": ok,
        "feedback": feedback[:400],
    })
    if ok:
        return {"grader_eventos": evg, "aprovado": True}
    if tentativa >= TENTATIVAS_VEREDITO:
        evg.append({
            "tentativa": "final",
            "aprovado": False,
            "feedback": "esgotadas as tentativas — sai com trava + nota",
        })
        return {
            "grader_eventos": evg,
            "aprovado": False,
            "tentativas_veredito": tentativa,
        }
    return {
        "grader_eventos": evg,
        "justificativa_feedback": feedback,
        "tentativas_veredito": tentativa,
    }


def rotear_grader(state: LoopFlipState) -> str:
    if state.get("erro") or state.get("aprovado"):
        return END
    if state.get("tentativas_veredito", 0) >= TENTATIVAS_VEREDITO:
        return END
    return "acao"  # volta direto ao veredito com o feedback (sem re-pensar)


def montar_grafo():
    g = StateGraph(LoopFlipState)
    g.add_node("pensar", no_pensar)
    g.add_node("acao", no_acao)
    g.add_node("grader", no_grader)
    g.add_edge(START, "pensar")
    g.add_edge("pensar", "acao")
    g.add_conditional_edges(
        "acao", rotear_pos_acao, {"grader": "grader", "pensar": "pensar", END: END}
    )
    g.add_conditional_edges("grader", rotear_grader, {"acao": "acao", END: END})
    return g.compile(checkpointer=MemorySaver())


GRAFO = montar_grafo()


# -------------------------------------------------------------- entrada/saida
def _tirar_carimbo(just: str) -> str:
    return _CARIMBO_RE.sub("", str(just or ""), count=1).strip()


async def avaliar_imovel_flip_loop(
    estado_in: Dict[str, Any],
    thread_id: str = "flip-loop-1",
    callbacks: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """Loop 1+2 para 1 imovel. Contrato igual ao `avaliar_imovel_react`:
    dict `AnalisePotencialFlip` + `metricas_flip` (+ `trilho_loop`, auditoria
    do grader). Nunca levanta: falha tecnica -> fallback sombra."""
    metricas = calcular_metricas_flip(estado_in.get("dados_imovel", {}))
    estado0: LoopFlipState = {
        "payload": converter_numpy(dict(estado_in)),
        "metricas": metricas,
        "fase": 0,
        "ultima_etapa": "",
        "relatorio_visual": "",
        "obs_dados": [],
        "justificativa_feedback": "",
        "tentativas_veredito": 0,
        "veredito": {},
        "aprovado": False,
        "grader_eventos": [],
        "trilha_events": [],
        "erro": "",
    }
    cfg = {
        "configurable": {"thread_id": thread_id},
        "callbacks": list(callbacks or []),
        "recursion_limit": max(8, 4 * len(ROTEIRO) + 4),
    }
    t0 = time.perf_counter()
    try:
        fin = await asyncio.wait_for(
            GRAFO.ainvoke(estado0, config=cfg),
            timeout=TEMPO_MAX_CALL_S * (TENTATIVAS_VEREDITO + 3),
        )
    except Exception as e:  # noqa: BLE001 — sombra nunca crasha o pipeline
        logger.warning("Loop explicito falhou: %s: %s", type(e).__name__, e)
        out = dict(FALLBACK_LOOP)
        out["justificativa_potencial"] = f"Falha tecnica do Loop explicito: {e}"
        out["erro"] = str(e)
        out["metricas_flip"] = metricas
        return out

    veredito = fin.get("veredito") or {}
    if not isinstance(veredito, dict) or not veredito:
        out = dict(FALLBACK_LOOP)
        out["erro"] = "sem veredito estruturado no fim do loop"
        out["metricas_flip"] = metricas
        return out

    # saida: trava regra 15% (G1) sempre por cima do veredito do LLM
    saida = ajustar_saida_pela_regra(veredito, metricas)
    saida["justificativa_potencial"] = _tirar_carimbo(
        saida.get("justificativa_potencial", "")
    )
    try:
        score = float(saida.get("score_potencial_flip", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    if not 0.0 <= score <= 10.0:
        saida["score_potencial_flip"] = min(max(score, 0.0), 10.0)
        saida["observacoes"] = " | ".join(
            p for p in (
                str(saida.get("observacoes", "") or ""),
                "score corrigido p/ [0,10] pelo grader",
            ) if p
        )
    saida["verificacao"] = (
        "aprovada" if fin.get("aprovado") else "falhou_apos_retries_com_trava"
    )
    saida["trilho_loop"] = {
        "duracao_s": round(time.perf_counter() - t0, 1),
        "tentativas_veredito": (
            fin.get("tentativas_veredito", 0) + (1 if fin.get("aprovado") else 0)
        ),
        "gradores": fin.get("grader_eventos", []),
        "fases": fin.get("trilha_events", []),
    }
    saida["erro"] = fin.get("erro", "")
    return saida
