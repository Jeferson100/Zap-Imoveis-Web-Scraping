import asyncio
import logging
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from .schemas import AnaliseImagens
from .utils import converter_numpy
from .subgrafos.subgrafo_imagens import subgrafo_imagens, SubgrafoImagensState
from agente_validacao.subgrafo_validacao import (
    subgrafo_validacao,
    SubgrafoValidacaoState,
)
from agente_validacao.schemas import ValidacaoDados
from agente_potencial_flip.subgrafo_potencial_flip import (
    subgrafo_potencial_flip,
    SubgrafoPotencialFlipState,
)
from agente_potencial_flip.schemas import AnalisePotencialFlip

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)


class EstadoGlobal(BaseModel):
    fotos_urls: List[str] = []
    dados_imovel: Dict[str, Any] = {}
    descricao_texto: str = ""
    analise_imagens: Optional[AnaliseImagens] = None
    analise_validacao: Optional[ValidacaoDados] = None
    analise_potencial_flip: Optional[AnalisePotencialFlip] = None
    api_key: Optional[str] = None


async def analisar_imagens_e_validar(state: EstadoGlobal) -> Dict[str, Any]:
    fotos_state = SubgrafoImagensState(
        fotos_urls=state.fotos_urls,
        api_key=state.api_key,
    )
    val_state = SubgrafoValidacaoState(
        dados_imovel=converter_numpy(state.dados_imovel),
        descricao_texto=state.descricao_texto,
        api_key=state.api_key,
    )

    fotos_result, val_result = await asyncio.gather(
        subgrafo_imagens.ainvoke(fotos_state),
        subgrafo_validacao.ainvoke(val_state),
    )

    return {
        "analise_imagens": fotos_result.get("analise") if isinstance(fotos_result, dict) else None,
        "analise_validacao": val_result.get("analise") if isinstance(val_result, dict) else None,
    }


async def executar_subgrafo_potencial_flip(state: EstadoGlobal) -> Dict[str, Any]:
    sub_state = SubgrafoPotencialFlipState(
        dados_imovel=converter_numpy(state.dados_imovel),
        analise_imagens=state.analise_imagens,
        analise_validacao=state.analise_validacao,
        api_key=state.api_key,
    )
    result = await subgrafo_potencial_flip.ainvoke(sub_state)
    analise = result.get("analise") if isinstance(result, dict) else None
    return {"analise_potencial_flip": analise}


builder = StateGraph(EstadoGlobal)

builder.add_node("analisar_imagens_e_validar", analisar_imagens_e_validar)
builder.add_node("executar_subgrafo_potencial_flip", executar_subgrafo_potencial_flip)

builder.set_entry_point("analisar_imagens_e_validar")

builder.add_edge("analisar_imagens_e_validar", "executar_subgrafo_potencial_flip")
builder.add_edge("executar_subgrafo_potencial_flip", END)

grafo_principal = builder.compile()
