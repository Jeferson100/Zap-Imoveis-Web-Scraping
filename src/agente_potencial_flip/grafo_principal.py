import asyncio
import logging
from typing import Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from agente_avaliacao_imagens.schemas import AnaliseImagens
from agente_avaliacao_imagens.subgrafo_imagens import (
    subgrafo_imagens,
    SubgrafoImagensState,
)
from agente_validacao.subgrafo_validacao import (
    subgrafo_validacao,
    SubgrafoValidacaoState,
)
from .grafo_potencial_flip import (
    subgrafo_potencial_flip,
    GrafoPotencialFlipState,
)
from .schemas import AnalisePotencialFlip
from shared.serialization import converter_numpy

logger = logging.getLogger(__name__)


class EstadoGlobal(BaseModel):
    fotos_urls: List[str] = []
    dados_imovel: Dict[str, Any] = {}
    descricao_texto: str = ""
    api_key: Optional[str] = None
    analise_imagens: Optional[AnaliseImagens] = None
    analise_validacao: Optional[Any] = None
    analise_flip: Optional[AnalisePotencialFlip] = None


async def analisar_imagens_e_validar(state: EstadoGlobal) -> Dict[str, Any]:
    img_state = SubgrafoImagensState(
        fotos_urls=state.fotos_urls,
        api_key=state.api_key,
    )
    val_state = SubgrafoValidacaoState(
        dados_imovel=converter_numpy(state.dados_imovel),
        descricao_texto=state.descricao_texto or "",
        api_key=state.api_key,
    )

    img_task, val_task = await asyncio.gather(
        subgrafo_imagens.ainvoke(img_state),
        subgrafo_validacao.ainvoke(val_state),
        return_exceptions=True,
    )

    analise_imagens = (
        img_task.get("analise")
        if isinstance(img_task, dict) and img_task.get("analise")
        else None
    )
    analise_validacao = (
        val_task.get("analise")
        if isinstance(val_task, dict) and val_task.get("analise")
        else None
    )

    return {
        "analise_imagens": analise_imagens,
        "analise_validacao": analise_validacao,
    }


async def avaliar_flip(state: EstadoGlobal) -> Dict[str, Any]:
    flip_state = GrafoPotencialFlipState(
        dados_imovel=state.dados_imovel,
        analise_imagens=state.analise_imagens,
        analise_validacao=state.analise_validacao,
        api_key=state.api_key,
    )
    resultado = await subgrafo_potencial_flip.ainvoke(flip_state)
    return {
        "analise_flip": (
            resultado.get("analise")
            if isinstance(resultado, dict)
            else resultado
        )
    }


builder = StateGraph(EstadoGlobal)
builder.add_node("analisar_imagens_e_validar", analisar_imagens_e_validar)
builder.add_node("avaliar_flip", avaliar_flip)
builder.set_entry_point("analisar_imagens_e_validar")
builder.add_edge("analisar_imagens_e_validar", "avaliar_flip")
builder.add_edge("avaliar_flip", END)

grafo_principal = builder.compile()
