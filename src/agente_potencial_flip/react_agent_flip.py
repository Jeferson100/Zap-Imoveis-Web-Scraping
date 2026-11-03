"""ReAct flip isolado (sombra/canario): supervisor investidor + 2 subagentes.

Diferencas para `deep_agent_flip.py` (workflow oficial, intocado):
  1. Supervisor com teto+retry+fallback (`asyncio.wait_for` + 2 tentativas):
     `SocketTimeoutError` no no `model` vira fallback sombra, nunca crash.
     Cada tentativa usa `thread_id` proprio (`<id>-t1`, `<id>-t2`): retry limpo,
     sem retomar checkpoint parcial nem duplicar a instrucao.
  2. Matematica (ROI/ARV/regra 15%) em `tools_flip.calcular_metricas_flip`
     — o LLM so julga (principio hibrido). As metricas vao INLINE na
     mensagem como `METRICAS_JSON` e a regra de ouro e travada em Python
     (`ajustar_saida_pela_regra`): `passa_regra_15pct=false` sempre vira
     `potencial_house_flip="False"`, independente do texto do LLM.
  3. Delegacao com payload INLINE (subagentes sao stateless): fotos_urls e
     JSON vao na instrucao de cada `task()`, e cada subagente devolve
     relatorio autocontido.
  4. `write_todos` nas 3 etapas (TodoListMiddleware, default on) + `think_tool`
     para registrar o raciocinio antes de cada task e antes do veredito.
  5. `name="flip-investidor"` + `thread_id` por imovel + checkpointer
     (resumable + time-travel debug).

Observabilidade: `task()` roda o subagente com `ainvoke` DENTRO da tool, entao
o interior dos subagentes nao aparece em `astream(subgraphs=True)`. Use
`trace_flip.TrilhaFlip` em `callbacks=` para ver thought/action/observation
(inclusive dentro dos subagentes).

Contrato de saida: dict `AnalisePotencialFlip` (igual ao workflow oficial)
+ `metricas_flip` (auditoria), para comparar com o parquet na coluna sombra.

Env:
    FLIP_MODEL / FLIP_BASE_URL / FLIP_API_KEY / FLIP_TIMEOUT  -> modelo (modelo_llm.py)
    FLIP_TIMEOUT_TENTATIVA  -> teto por tentativa (default 420s)
    FLIP_DEBUG              -> trace do grafo do LangGraph (default off)
    FLIP_EXIGE_PENSAMENTO   -> gate duro de think_tool antes de `task` (default off)
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from shared.serialization import converter_numpy

from .modelo_llm import criar_modelo_flip, modelo_flip_padrao
from .schemas import AnalisePotencialFlip
from .tools_flip import (
    ROI_MINIMO,
    ajustar_saida_pela_regra,
    calcular_metricas_flip,
    descrever_fotos_tool,
    limpar_nan,
    metricas_flip_tool,
    think_tool,
    validar_dados_tool,
)
from .trace_flip import ExigePensamento

logger = logging.getLogger(__name__)

#SUPERVISOR_MODEL = modelo_flip_padrao()
TEMPO_MAX_TENTATIVA_S = int(os.environ.get("FLIP_TIMEOUT_TENTATIVA", "420"))
TENTATIVAS = 2
PAUSA_ENTRE_TENTATIVAS_S = 5
MAX_FOTOS_MSG = 6
MAX_DESCRICAO_CHARS = 2000

# Gate duro opcional (custa 1 round-trip por violacao). Desligado por padrao:
# o prompt ja pede think_tool antes de cada task e do veredito.
EXIGE_PENSAMENTO = os.environ.get("FLIP_EXIGE_PENSAMENTO", "").strip().lower() in (
    "1", "true", "yes", "on",
)

SYSTEM_REACT_FLIP = """Voce e um investidor senior de Fix & Flip em loop ReAct
(Thought -> Action(tool ou task) -> Observation -> veredito). Avalie em
EXATAMENTE 3 etapas, nesta ordem — registre cada uma com write_todos antes.
ANTES de cada task() e ANTES do veredito final, chame think_tool com
`pensamento` (1-3 frases) e `proxima_acao`. Nao repita dados: sintetize.
ETAPA 1: delegue ao fotografo via task(), passando AS FOTOS_URLS INLINE na
  instrucao (o subagente e stateless e nao enxerga seu contexto).
ETAPA 2: delegue ao dados via task(), passando O JSON + DESCRICAO INLINE.
ETAPA 3: com os dois relatorios, de o veredito final.
Regras da decisao (metricas ja vem calculadas em METRICAS_JSON):
1) Trate METRICAS_JSON da mensagem como fonte UNICA de verdade numerica:
   NAO recalcule ROI/ARV/preco_por_m2. Se precisar reconferir, delegue ao
   `dados` (metricas_flip_tool).
2) Sem fotos, PULE visao (avaliacao so numerica + descricao).
3) So valide dados se numero suspeito.
4) REGRA DE OURO 15% ROI: potencial_house_flip="True" SOMENTE se
   METRICAS_JSON.passa_regra_15pct=true; sem dados suficientes responda "False".
   Nunca invente custo de reforma; assuma patologias ocultas.
Responda em portugues, SOMENTE no formato estruturado.
"""

fotos_subagent = {
    "name": "fotografo",
    "description": (
        "Descreve fotos do imovel: conservacao, acabamento, problemas "
        "visiveis, pontos fortes. Receba as URLs inline na instrucao e "
        "devolva relatorio autocontido. Use para a ETAPA 1."
    ),
    "system_prompt": (
        "Voce descreve fotos de imoveis. Chame descrever_fotos_tool com as "
        "URLs da instrucao e devolva relatorio autocontido: conservacao, "
        "acabamento, problemas_visiveis, pontos_fortes. Registre o raciocinio "
        "com think_tool antes de chamar a tool."
    ),
    "tools": [descrever_fotos_tool, think_tool],
}

dados_subagent = {
    "name": "dados",
    "description": (
        "Confere os numeros do anuncio + metricas deterministicas de flip "
        "(ROI, ARV, descontos). Receba o JSON inline na instrucao e devolva "
        "resumo autocontido. Use para a ETAPA 2."
    ),
    "system_prompt": (
        "Voce organiza os dados do imovel. Chame metricas_flip_tool (sempre "
        "primeiro) e formate/valide com o JSON da instrucao; devolva numeros "
        "+ metricas_flip (roi_conservador, passa_regra_15pct) + benchmarks. "
        "Use think_tool antes de cada tool."
    ),
    "tools": [metricas_flip_tool, validar_dados_tool, think_tool],
}

agente_react_flip = create_deep_agent(
    name="flip-investidor",
    #model = "nvidia:poolside/laguna-xs-2.1",
    model = "nvidia:nvidia/nemotron-3.5-bolt-e4b",
    #model="nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    tools=[think_tool],
    subagents=[fotos_subagent, dados_subagent],
    middleware=[ExigePensamento()] if EXIGE_PENSAMENTO else [],
    system_prompt=SYSTEM_REACT_FLIP,
    response_format=AnalisePotencialFlip,
    checkpointer=MemorySaver(),
    debug=bool(os.environ.get("FLIP_DEBUG")),
)

FALLBACK_SOMBRA: Dict[str, Any] = {
    "score_potencial_flip": 0.0,
    "potencial_house_flip": "False",
    "justificativa_potencial": "",
    "riscos": ["Falha tecnica do agente ReAct (sombra)"],
    "recomendacoes": [],
    "observacoes": "Fallback sombra — workflow oficial continua valendo",
}

# Sinais de erro que nao adiantam repetir (modelo EOL/inexistente/sem acesso).
MARCAS_ERRO_PERMANENTE = (
    "410", "gone", "404", "end of life", "end-of-life",
    "no longer available", "not found", "does not exist", "decommissioned",
)


def erro_permanente(exc: Exception) -> bool:
    """True se repetir a chamada nao resolve (modelo morto/inexistente)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(m in msg for m in MARCAS_ERRO_PERMANENTE)


def montar_mensagem(
    estado: Dict[str, Any], metricas: Dict[str, Any] | None = None
) -> str:
    """Monta a mensagem com payload inline completo (subagentes stateless).

    `metricas` vai como fonte de verdade numerica: o supervisor nao precisa
    (nem deve) recalcular ROI/ARV a partir do JSON. NaN/inf viram `null` para
    o prompt ser JSON estrito.
    """
    dados = limpar_nan(converter_numpy(dict(estado.get("dados_imovel", {}) or {})))
    if metricas is None:
        metricas = calcular_metricas_flip(dados)
    return (
        "Avalie este imovel para flip.\n"
        f"DADOS_IMOVEL_JSON={json.dumps(dados, ensure_ascii=False)}\n"
        f"METRICAS_JSON={json.dumps(converter_numpy(metricas), ensure_ascii=False)}\n"
        f"REGRA_15PCT: passa_regra_15pct={metricas.get('passa_regra_15pct')} "
        f"(roi_conservador={metricas.get('roi_conservador')}, minimo={ROI_MINIMO})\n"
        f"DESCRICAO={str(estado.get('descricao_texto', ''))[:MAX_DESCRICAO_CHARS]}\n"
        f"FOTOS_URLS={json.dumps(list(estado.get('fotos_urls', []) or [])[:MAX_FOTOS_MSG])}"
    )


async def avaliar_imovel_react(
    estado: Dict[str, Any],
    thread_id: str = "flip-1",
    callbacks: List[Any] | None = None,
) -> Dict[str, Any]:
    """Roda o ReAct p/ 1 imovel com teto+retry+fallback sombra.

    `estado`: dict no shape de EstadoGlobal. `callbacks`: handlers LangChain
    (ex.: `trace_flip.TrilhaFlip`) que atravessam os subagentes.
    Retorna o veredito como dict (AnalisePotencialFlip) + `metricas_flip`.
    Nunca levanta por timeout: esgotadas as tentativas, retorna FALLBACK_SOMBRA.
    """
    metricas = calcular_metricas_flip(estado.get("dados_imovel", {}))
    mensagem = montar_mensagem(estado, metricas)
    ultimo_erro: Exception | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        # thread_id por tentativa: nao retoma checkpoint parcial nem duplica
        # a instrucao no estado; cada tentativa fica auditavel separadamente.
        config = {
            "configurable": {"thread_id": f"{thread_id}-t{tentativa}"},
            "callbacks": list(callbacks or []),
        }
        try:
            res = await asyncio.wait_for(
                agente_react_flip.ainvoke(
                    {"messages": [{"role": "user", "content": mensagem}]}, config=config
                ),
                timeout=TEMPO_MAX_TENTATIVA_S,
            )
            sr = res.get("structured_response") if isinstance(res, dict) else None
            if sr is None:
                raise RuntimeError("ReAct sem structured_response")
            saida = sr if isinstance(sr, dict) else sr.model_dump()
            return ajustar_saida_pela_regra(saida, metricas)
        except Exception as e:  # inclui asyncio.TimeoutError / SocketTimeoutError
            ultimo_erro = e
            logger.warning("ReAct flip tentativa %s/%s falhou: %s: %s",
                           tentativa, TENTATIVAS, type(e).__name__, e)
            if erro_permanente(e):
                logger.error("ReAct flip: erro permanente (modelo morto/inexistente) — sem retry.")
                break
            if tentativa < TENTATIVAS:
                await asyncio.sleep(PAUSA_ENTRE_TENTATIVAS_S)
    logger.error("ReAct flip esgotou tentativas — fallback sombra.")
    out = dict(FALLBACK_SOMBRA)
    out["justificativa_potencial"] = f"Falha tecnica do ReAct (sombra): {ultimo_erro}"
    out["erro"] = str(ultimo_erro)
    out["metricas_flip"] = metricas
    return out
