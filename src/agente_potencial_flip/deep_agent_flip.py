"""Deep agent da avaliação flip: supervisor investidor + 2 subagentes, sem tools no main.

Fluxo forçado pelo desenho:
  ETAPA 1 → subagente `fotografo` (descreve as fotos via visão LLM).
  ETAPA 2 → subagente `dados` (formata/confere números + descrição).
  ETAPA 3 → supervisor (regras de PROMPT_AVALIAR_POTENCIAL_FLIP) dá o veredito
             em `AnalisePotencialFlip` via response_format.

Uso no notebook:
    from src.agente_potencial_flip.deep_agent_flip import avaliar_imovel_deep
    analise = await avaliar_imovel_deep(estado.model_dump())  # dict no shape de EstadoGlobal
"""

import json
import logging
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent
from langchain.tools import tool
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from pydantic import BaseModel, Field

from agente_avaliacao_imagens.prompts import PROMPT_DESCREVER_FOTO
from agente_avaliacao_imagens.utils import processar_todos_lotes
from shared.serialization import converter_numpy

from .schemas import AnalisePotencialFlip

logger = logging.getLogger(__name__)

SUPERVISOR_MODEL = "moonshotai/kimi-k2-instruct"  # tools: True (tabela langchain-nvidia)
FOTOS_POR_LOTE = 5
MAX_FOTOS_MSG = 6


class EntradaFotos(BaseModel):
    fotos_urls: List[str] = Field(description="URLs das fotos do anúncio")


class EntradaDados(BaseModel):
    dados_imovel: str = Field(
        description="JSON: metragem, banheiros, vagas, quartos, valor_imovel, "
                    "bairro, tipo_imovel, valor_predito, p50_bairro, preco_por_m2"
    )
    descricao_texto: str = ""


@tool(args_schema=EntradaFotos)
async def descrever_fotos_tool(fotos_urls: List[str]) -> str:
    """Descreve as fotos do imóvel (conservação, acabamento, problemas visíveis)."""
    if not fotos_urls:
        return "Nenhuma URL de foto fornecida."
    descricao = await processar_todos_lotes(
        fotos_urls or [], FOTOS_POR_LOTE, prompt=PROMPT_DESCREVER_FOTO
    )
    if not descricao:
        logger.error("Não foi possível descrever as fotos.")
        return "Falha ao descrever as fotos."
    return descricao


@tool(args_schema=EntradaDados)
async def formatar_dados_tool(dados_imovel: str, descricao_texto: str = "") -> str:
    """Formata os números do anúncio + descrição para a avaliação."""
    return json.dumps(
        {
            "dados_imovel": converter_numpy(json.loads(dados_imovel)),
            "descricao": descricao_texto or "",
        },
        ensure_ascii=False,
    )


fotos_subagent = {
    "name": "fotografo",
    "description": (
        "Descreve as fotos do imóvel: conservação, acabamento, "
        "problemas visíveis, pontos fortes. Use para a ETAPA 1."
    ),
    "system_prompt": (
        "Você descreve fotos de imóveis. Chame descrever_fotos_tool com as URLs "
        "e devolva relatório estruturado: conservacao, acabamento, "
        "problemas_visiveis, pontos_fortes."
    ),
    "tools": [descrever_fotos_tool],
}

dados_subagent = {
    "name": "dados",
    "description": (
        "Formata e confere os números do anúncio (m², quartos, valores, "
        "benchmarks). Use para a ETAPA 2."
    ),
    "system_prompt": (
        "Você organiza os dados do imóvel. Chame formatar_dados_tool e devolva "
        "os números + benchmarks (preco_por_m2, valor_m2_predicao, valor_m2_bairro)."
    ),
    "tools": [formatar_dados_tool],
}

# Trecho das regras de PROMPT_AVALIAR_POTENCIAL_FLIP como base do supervisor.
REGRAS_INVESTIMENTO = """
Core Investment Guidelines & Math (de PROMPT_AVALIAR_POTENCIAL_FLIP):
1. ARV: cruze preco_por_m2 (valor_imovel/metragem) com valor_m2_predicao e
   valor_m2_bairro; exija margem entre o preço atual e o topo do bairro.
2. Conservador: não invente custos de reforma em dinheiro; assuma patologias ocultas.
3. Alinhe problemas_visiveis + score de conservação com potencial de reforma
   (conservação baixa + potencial alto = candidato prime).
4. REGRA DE OURO 15% ROI: potencial_house_flip="True" SOMENTE se ROI conservador >= 15%.
Responda em português, SOMENTE no formato estruturado.
"""

SYSTEM_INVESTIDOR = """Você é um investidor sênior de Fix & Flip. Avalie em EXATAMENTE 3 etapas, nesta ordem:
ETAPA 1: delegue ao fotografo (task) as fotos_urls.
ETAPA 2: delegue ao dados (task) o JSON + descrição.
ETAPA 3: com os dois relatórios, dê o veredito final.
""" + REGRAS_INVESTIMENTO

agente_avaliacao_flip = create_deep_agent(
    model=ChatNVIDIA(model=SUPERVISOR_MODEL),
    subagents=[fotos_subagent, dados_subagent],
    system_prompt=SYSTEM_INVESTIDOR,
    response_format=AnalisePotencialFlip,
)


async def avaliar_imovel_deep(estado: Dict[str, Any]) -> Dict[str, Any]:
    """Roda o deep agent p/ 1 imóvel. `estado`: dict no shape de EstadoGlobal.

    Retorna o veredito como dict (AnalisePotencialFlip).
    """
    mensagem = (
        "Avalie este imóvel para flip.\n"
        f"DADOS_IMOVEL_JSON={json.dumps(converter_numpy(estado.get('dados_imovel', {})), ensure_ascii=False)}\n"
        f"DESCRICAO={str(estado.get('descricao_texto', ''))[:2000]}\n"
        f"FOTOS_URLS={json.dumps(list(estado.get('fotos_urls', []) or [])[:MAX_FOTOS_MSG])}"
    )
    res = await agente_avaliacao_flip.ainvoke(
        {"messages": [{"role": "user", "content": mensagem}]}
    )
    sr = res.get("structured_response") if isinstance(res, dict) else None
    if sr is None:
        raise RuntimeError("Deep agent sem structured_response")
    return sr if isinstance(sr, dict) else sr.model_dump()
