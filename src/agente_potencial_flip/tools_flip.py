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
from typing import Any, Dict, List

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


def _num(valor: Any, default: float = 0.0) -> float:
    """float seguro: None/NaN/inf/str invalida viram `default`."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) or math.isinf(f) else f


def limpar_nan(d: Dict[str, Any]) -> Dict[str, Any]:
    """NaN/inf -> None, para o JSON que o LLM le ser valido (strict)."""
    return {
        k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v)
        for k, v in d.items()
    }


def calcular_metricas_flip(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Matematica deterministica do flip. Sem LLM.

    Cruza preco_por_m2 com valor_m2_predicao e valor_m2_bairro (mesmas contas
    de `preparar_dados`) e aplica a regra de ouro: ROI >= 15% sobre o valor de
    compra, reservando 10% do ARV para custos ocultos/reforma.

    NaN/None/inf nunca propagam: viram 0 na conta (o imovel cai no benchmark
    do bairro) e None na saida. Sem isso, um `valor_predito` nulo reprovava o
    imovel em silencio e emitia `NaN` (JSON invalido) para o LLM.
    """
    d = limpar_nan(converter_numpy(dict(dados or {})))
    metragem = _num(d.get("metragem")) or _num(d.get("area_estimada"))
    valor = _num(d.get("valor_imovel"))
    pred = _num(d.get("valor_predito"))
    p50 = _num(d.get("p50_bairro"))
    pm2 = round(valor / metragem, 2) if metragem and valor else 0
    m2p = round(pred / metragem, 2) if metragem and pred else 0
    arv = (max(m2p, p50) * metragem) if metragem and (m2p or p50) else 0
    lucro = arv * 0.90 - valor if arv and valor else 0
    roi = (lucro / valor) if valor else 0.0
    return {
        **d,
        "preco_por_m2": pm2,
        "valor_m2_predicao": m2p,
        "valor_m2_bairro": p50,
        "discount_vs_predicao_pct": round((m2p - pm2) / m2p * 100, 2) if m2p else 0.0,
        "discount_vs_bairro_pct": round((p50 - pm2) / p50 * 100, 2) if p50 else 0.0,
        "arv_estimado": round(arv, 2),
        "roi_conservador": round(roi, 4),
        "passa_regra_15pct": bool(roi >= ROI_MINIMO),
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

