"""Tools do ReAct flip: matematica deterministica fora do LLM + wrappers.

Principio hibrido: ROI/ARV/descontos sao calculados em Python puro
(`calcular_metricas_flip`) e a regra de ouro e travada em
`ajustar_saida_pela_regra`; o LLM so julga. Importado pelo notebook
(`Notebooks/react_agent_valiador.ipynb`, celula de metricas) e pelo
modulo `react_agent_flip.py`.
"""

import json
import logging
import math
import os
from typing import Any, Dict, List, Optional

from langchain.tools import tool
from pydantic import BaseModel, Field

from agente_avaliacao_imagens.prompts import PROMPT_DESCREVER_FOTO
from agente_avaliacao_imagens.utils import processar_todos_lotes
from agente_validacao.prompts import PROMPT_VALIDAR_DADOS
from agente_validacao.schemas import ValidacaoDados
from roteador_llms.roteador_llms import LlmRouter
from shared.serialization import converter_numpy

logger = logging.getLogger(__name__)

FOTOS_POR_LOTE = 5
MAX_FOTOS_TOOL = 6
ROI_MINIMO = 0.15  # REGRA DE OURO 15%
# Custo de reforma explicito, por metro quadrado. Default R$ 1500/m2, ajustavel
# por `FLIP_CUSTO_REFORMA_M2`. A reserva de 10% do ARV continua cobrindo custos
# ocultos (patologias, titulo, ITBI); a reforma e um custo tangivel e auditavel.
# O valor e resolvido A CADA CHAMADA (`custo_reforma_m2()`): ler so no import
# congelava o valor e ignorava overrides feitos depois (celula de notebook,
# `os.environ[...] = ...` em runtime).
CUSTO_REFORMA_PADRAO_M2 = 1500.0


def _num(valor: Any, default: float = 0.0) -> float:
    """float seguro: None/NaN/inf/str invalida viram `default`."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) or math.isinf(f) else f


def custo_reforma_m2() -> float:
    """R$/m2 de reforma, lido na chamada. Env valido vence; ruido cai no padrao."""
    valor = _num(os.environ.get("FLIP_CUSTO_REFORMA_M2", ""), 0.0)
    return valor if valor > 0 else CUSTO_REFORMA_PADRAO_M2


# Alias legado (import-time), usado apenas para exibicao em mensagens.
CUSTO_REFORMA_M2 = custo_reforma_m2()


def limpar_nan(d: Dict[str, Any]) -> Dict[str, Any]:
    """NaN/inf -> None, para o JSON que o LLM le ser valido (strict)."""
    return {
        k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
        for k, v in d.items()
    }


def calcular_metricas_flip(
    dados: Dict[str, Any], custo_m2: Optional[float] = None
) -> Dict[str, Any]:
    """Matematica deterministica do flip. Sem LLM.

    Cruza preco_por_m2 com valor_m2_predicao e valor_m2_bairro (mesmas contas
    de `preparar_dados`) e aplica a regra de ouro: ROI >= 15% sobre o valor de
    compra, reservando 10% do ARV para custos ocultos e descontando o custo de
    reforma explicito (`custo_reforma_m2() * metragem`, default R$ 1500/m2).

    `custo_m2` permite testar cenario ("e se a reforma for 2500/m2?") sem
    mexer no ambiente; quando omitido, usa o valor vigente por chamada.

    NaN/None/inf nunca propagam: viram 0 na conta (o imovel cai no benchmark
    do bairro) e None na saida. Sem isso, um `valor_predito` nulo reprovava o
    imovel em silencio e emitia `NaN` (JSON invalido) para o LLM.
    """
    d = limpar_nan(converter_numpy(dict(dados or {})))
    metragem = _num(d.get("metragem")) or _num(d.get("area_estimada"))
    valor = _num(d.get("valor_imovel"))
    pred = _num(d.get("valor_predito"))
    p50 = _num(d.get("p50_bairro"))
    custo = _num(custo_m2, 0.0) if custo_m2 is not None else 0.0
    custo = custo or custo_reforma_m2()
    pm2 = round(valor / metragem, 2) if metragem and valor else 0
    m2p = round(pred / metragem, 2) if metragem and pred else 0
    # BLEND com degradacao graciosa: os dois -> media; faltando um, usa o outro
    # (a predicao DESTE imovel vale mais que zerar a conta); faltando os dois,
    # nao inventa ARV. `arv_fonte` documenta qual ancora foi usada.
    if m2p and p50:
        m2_arv, fonte = (m2p + p50) / 2, "blend_mediana_predicao"
    elif m2p:
        m2_arv, fonte = m2p, "predicao_sem_bairro"
    elif p50:
        m2_arv, fonte = p50, "bairro_sem_predicao"
    else:
        m2_arv, fonte = 0, "sem_ancora"
    arv = m2_arv * metragem if metragem and m2_arv else 0
    custo_reforma = round(custo * metragem, 2) if metragem else 0.0
    lucro = arv * 0.90 - valor - custo_reforma if arv and valor else 0
    roi = (lucro / valor) if valor else 0.0
    # Teto de compra que ainda fecha a regra de 15%: sem este numero o modelo
    # inventa a recomendacao de negociacao (ja recomendou "abaixo de 250k"
    # quando o correto era 199.742).
    preco_maximo = (round((arv * 0.90 - custo_reforma) / (1 + ROI_MINIMO), 2)
                    if arv else 0.0)
    margem_arv = round((arv - valor) / arv * 100, 2) if arv and valor else 0.0
    return {
        **d,
        "metragem_usada": metragem,
        "preco_por_m2": pm2,
        "valor_m2_predicao": m2p,
        "valor_m2_bairro": round(p50, 2),
        "valor_m2_blend": round((m2p + p50) / 2, 2) if m2p and p50 else 0.0,
        "arv_fonte": fonte if arv else "sem_ancora",
        "discount_vs_predicao_pct": round((m2p - pm2) / m2p * 100, 2) if m2p else 0.0,
        "discount_vs_bairro_pct": round((p50 - pm2) / p50 * 100, 2) if p50 else 0.0,
        "arv_estimado": round(arv, 2),
        "custo_reforma_estimado": custo_reforma,
        "custo_reforma_por_m2": custo,
        "regra_reforma": (
            f"R$ {custo:.0f}/m2 x metragem, descontado do lucro ANTES da regra de 15%"
        ),
        "lucro_projetado": round(lucro, 2),
        "roi_conservador": round(roi, 4),
        "passa_regra_15pct": bool(roi >= ROI_MINIMO),
        "preco_maximo_para_regra": preco_maximo,
        "margem_vs_arv_pct": margem_arv,
    }


# Passos auditaveis da conta, na ordem em que acontecem.
PASSOS_METRICAS = (
    "preco_por_m2",
    "valor_m2_predicao",
    "arv_estimado",
    "custo_reforma_estimado",
    "lucro_projetado",
    "roi_conservador",
    "passa_regra_15pct",
    "preco_maximo_para_regra",
)

# Numeros de contexto que o veredito precisa mas nao sao passos da conta.
CONTEXTO_METRICAS = (
    "valor_m2_bairro",
    "discount_vs_predicao_pct",
    "discount_vs_bairro_pct",
    "margem_vs_arv_pct",
    "valor_m2_blend",
    "arv_fonte",
)

FORMULAS_METRICAS = {
    "preco_por_m2": "valor_imovel / metragem",
    "valor_m2_predicao": "valor_predito / metragem",
    "arv_estimado": "(valor_m2_predicao + valor_m2_bairro) / 2 * metragem",
    "custo_reforma_estimado": "custo_reforma_por_m2 * metragem",
    "lucro_projetado": "arv_estimado * 0.90 - valor_imovel - custo_reforma_estimado",
    "roi_conservador": "lucro_projetado / valor_imovel",
    "passa_regra_15pct": "roi_conservador >= ROI_MINIMO",
    "preco_maximo_para_regra": (
        "(arv_estimado * 0.90 - custo_reforma_estimado) / (1 + ROI_MINIMO)"
    ),
}

ENTRADAS_METRICAS = {
    "preco_por_m2": ("valor_imovel", "metragem"),
    "valor_m2_predicao": ("valor_predito", "metragem"),
    "arv_estimado": ("valor_m2_predicao", "valor_m2_bairro", "metragem"),
    "custo_reforma_estimado": ("custo_reforma_por_m2", "metragem"),
    "lucro_projetado": ("arv_estimado", "valor_imovel", "custo_reforma_estimado"),
    "roi_conservador": ("lucro_projetado", "valor_imovel"),
    "passa_regra_15pct": ("roi_conservador", "ROI_MINIMO"),
    "preco_maximo_para_regra": ("arv_estimado", "custo_reforma_estimado", "ROI_MINIMO"),
}


def explicar_metricas(
    dados: Dict[str, Any], custo_m2: Optional[float] = None
) -> Dict[str, Any]:
    """`calcular_metricas_flip` + memoria de calculo passo a passo.

    Mesma aritmetica (fonte unica, nada duplicado aqui) com `operacoes`: cada
    passo traz a formula, as entradas usadas e o resultado. Serve para o LLM
    auditar o numero sem fazer a conta. `contexto` carrega os comparativos
    (descontos e margem vs ARV) que orientam a negociacao.
    """
    r = calcular_metricas_flip(dados, custo_m2=custo_m2)
    valores = {**r, "ROI_MINIMO": ROI_MINIMO}
    valores["metragem"] = r.get("metragem_usada") or r.get("metragem")
    operacoes = [
        {
            "passo": passo,
            "formula": FORMULAS_METRICAS[passo],
            "entradas": {k: valores.get(k) for k in ENTRADAS_METRICAS[passo]},
            "resultado": r.get(passo),
        }
        for passo in PASSOS_METRICAS
    ]
    return {
        **{k: r.get(k) for k in PASSOS_METRICAS},
        # Os graders (G5) conferem a conta a partir destas duas entradas.
        "metragem_usada": r.get("metragem_usada"),
        "valor_imovel": r.get("valor_imovel"),
        "custo_reforma_por_m2": r.get("custo_reforma_por_m2"),
        "regra_reforma": r.get("regra_reforma"),
        # O blend e sua fonte precisam chegar ao LLM e ao grader G7.
        "valor_m2_blend": r.get("valor_m2_blend"),
        "arv_fonte": r.get("arv_fonte"),
        "contexto": {k: r.get(k) for k in CONTEXTO_METRICAS},
        "operacoes": operacoes,
    }


def ajustar_saida_pela_regra(
    saida: Dict[str, Any], metricas: Dict[str, Any]
) -> Dict[str, Any]:
    """Trava a REGRA DE OURO: passa_regra_15pct=False => potencial="False".

    O LLM ainda julga (score, riscos, justificativa), mas o veredito booleano
    deixa de depender de ele copiar corretamente um bool. Quando a trava
    corrige o LLM, a divergencia fica registrada em `observacoes`.
    """
    out = dict(saida or {})
    out["metricas_flip"] = metricas
    if metricas.get("passa_regra_15pct"):
        return out

    if str(out.get("potencial_house_flip")) == "True":
        partes = [
            str(out.get("observacoes", "") or "").strip(),
            f"Trava regra 15%: roi_conservador={metricas.get('roi_conservador')} "
            f"< {ROI_MINIMO} — potencial forcado para False.",
        ]
        out["observacoes"] = " | ".join(p for p in partes if p)
    out["potencial_house_flip"] = "False"
    return out


class EntradaFotos(BaseModel):
    fotos_urls: List[str] = Field(description="URLs das fotos do anuncio")


class EntradaMetricas(BaseModel):
    dados_imovel_json: str = Field(description="JSON: metragem, valor_imovel, valor_predito, p50_bairro, ...")


class EntradaValidacao(BaseModel):
    dados_imovel_json: str = Field(description="JSON dos numeros do anuncio")
    descricao_texto: str = ""


@tool(args_schema=EntradaMetricas)
def metricas_flip_tool(dados_imovel_json: str) -> str:
    """Calcula preco_por_m2, descontos vs predicao/bairro, ARV e ROI. Chame PRIMEIRO, sempre."""
    try:
        dados = json.loads(dados_imovel_json)
    except (TypeError, ValueError) as e:
        # JSON invalido nao pode derrubar o nos do subagente: devolve erro
        # acionavel e o modelo reenvia.
        return json.dumps(
            {"erro": f"JSON invalido em dados_imovel_json: {e}", "recebido": str(dados_imovel_json)[:200]},
            ensure_ascii=False,
        )
    return json.dumps(
        converter_numpy(calcular_metricas_flip(dados)),
        ensure_ascii=False,
    )


@tool(args_schema=EntradaFotos)
async def descrever_fotos_tool(fotos_urls: List[str]) -> str:
    """Descreve conservacao/acabamento/problemas visiveis. Pule se lista vazia."""
    if not fotos_urls:
        return "Sem fotos no anuncio — avaliacao so numerica + descricao."
    desc = await processar_todos_lotes(
        fotos_urls[:MAX_FOTOS_TOOL], FOTOS_POR_LOTE, prompt=PROMPT_DESCREVER_FOTO
    )
    return desc or "Falha ao descrever as fotos."


@tool(args_schema=EntradaValidacao)
async def validar_dados_tool(dados_imovel_json: str, descricao_texto: str = "") -> str:
    """Confere numeros vs descricao. Chame so se algum numero for suspeito."""
    prompt = PROMPT_VALIDAR_DADOS.format(
        dados_json=dados_imovel_json[:2000],
        descricao_texto=(descricao_texto or "Nenhuma descricao fornecida.")[:2000],
    )
    try:
        r = await LlmRouter(messages=prompt, strutured_output=ValidacaoDados).llm_router()
    except Exception as e:
        # Falha tecnica NAO e "os dados estao errados": `possui_erros="True"`
        # dispara correcao de numeros que podem estar certos.
        return json.dumps(
            {
                "possui_erros": "False",
                "validacao_indisponivel": True,
                "observacoes": f"validacao indisponivel (falha tecnica): {e}",
            },
            ensure_ascii=False,
        )
    v = ValidacaoDados(**r) if isinstance(r, dict) else r
    return v.model_dump_json() if v is not None else '{"possui_erros": "False"}'


class EntradaPensamento(BaseModel):
    pensamento: str = Field(
        description="Raciocinio em 1-3 frases: o que ja sei, o que falta, o que vou fazer."
    )
    proxima_acao: str = Field(
        description="task:fotografo | task:dados | metricas_flip_tool | veredito_final"
    )


@tool(args_schema=EntradaPensamento)
def think_tool(pensamento: str, proxima_acao: str) -> str:
    """Registre o raciocinio ANTES de cada task/tool e ANTES do veredito.

    Nao calcula nada e nao decide nada: serve para a trilha ficar auditavel
    (o pensamento fica no estado do grafo e nos logs).
    """
    logger.info("THINK[%s] %s", proxima_acao, pensamento)
    return "registrado"

