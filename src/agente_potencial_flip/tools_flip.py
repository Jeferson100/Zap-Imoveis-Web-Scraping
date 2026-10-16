"""Tools do ReAct flip: matematica deterministica fora do LLM + wrappers.

Principio hibrido: ROI/ARV/descontos sao calculados em Python puro
(`calcular_metricas_flip`); o LLM so julga. Importado pelo notebook
(`Notebooks/react_agent_valiador.ipynb`, celula de metricas) e pelo
modulo `react_agent_flip.py`.
"""

import json
import logging
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


def calcular_metricas_flip(dados: Dict[str, Any]) -> Dict[str, Any]:
    """Matematica deterministica do flip. Sem LLM.

    Cruza preco_por_m2 com valor_m2_predicao e valor_m2_bairro (espelho de
    `preparar_dados` + descontos do workflow) e aplica a regra de ouro:
    ROI conservador >= 15% (assume 10% de custos ocultos/reforma sobre o ARV).
    """
    d = converter_numpy(dict(dados or {}))
    metragem = d.get("metragem", 0) or d.get("area_estimada", 0) or 0
    valor = d.get("valor_imovel", 0) or 0
    pred = d.get("valor_predito", 0) or 0
    p50 = d.get("p50_bairro", 0) or 0
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
    return json.dumps(
        converter_numpy(calcular_metricas_flip(json.loads(dados_imovel_json))),
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
        return json.dumps({"possui_erros": "True", "observacoes": f"fallback sombra: {e}"},
                          ensure_ascii=False)
    v = ValidacaoDados(**r) if isinstance(r, dict) else r
    return v.model_dump_json() if v is not None else '{"possui_erros": "True"}'
