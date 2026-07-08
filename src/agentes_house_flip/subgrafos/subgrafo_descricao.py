import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from ..schemas import AnaliseDescricao, FeedbackDescricao
from ..prompts import PROMPT_ANALISAR_DESCRICAO, PROMPT_REFLEXAO_DESCRICAO

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 2


class SubgrafoDescricaoState(BaseModel):
    descricao_texto: str = ""
    analise: Optional[AnaliseDescricao] = None
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None


async def analisar_descricao(state: SubgrafoDescricaoState) -> Dict[str, Any]:
    import roteador_api_nvidia

    descricao = state.descricao_texto or "Nenhuma descricao fornecida."
    prompt = PROMPT_ANALISAR_DESCRICAO.format(descricao_texto=descricao)
    if state.feedback:
        prompt += f"\n\nFeedback da revisao anterior:\n{state.feedback}"

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        strutured_output=AnaliseDescricao,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        analise = (
            AnaliseDescricao(**resultado) if isinstance(resultado, dict) else resultado
        )
        return {"analise": analise, "tentativa": state.tentativa + 1}

    return {
        "analise": AnaliseDescricao(
            caracteristicas_extraidas={},
            qualidade_texto=0,
            exageros_identificados=[],
            info_relevante=[],
            conclusao="Nao foi possivel analisar a descricao.",
        ),
        "tentativa": state.tentativa + 1,
    }


async def refletor_descricao(state: SubgrafoDescricaoState) -> Dict[str, Any]:
    import roteador_api_nvidia

    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    prompt = PROMPT_REFLEXAO_DESCRICAO.format(
        analise_json=state.analise.model_dump_json(indent=2),
        descricao_texto=state.descricao_texto or "Nenhuma descricao fornecida.",
    )

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        strutured_output=FeedbackDescricao,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        fb = (
            FeedbackDescricao(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"feedback": fb.feedback if not fb.consistente else None}
    return {"feedback": None}


def decidir_proximo_descricao(
    state: SubgrafoDescricaoState,
) -> Literal["analisar_descricao", "__end__"]:
    if state.feedback and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa,
            state.max_tentativas,
        )
        return "analisar_descricao"
    logger.info("Analise de descricao concluida.")
    return "__end__"


builder = StateGraph(SubgrafoDescricaoState)

builder.add_node("analisar_descricao", analisar_descricao)
builder.add_node("refletor_descricao", refletor_descricao)

builder.set_entry_point("analisar_descricao")

builder.add_edge("analisar_descricao", "refletor_descricao")

builder.add_conditional_edges(
    "refletor_descricao",
    decidir_proximo_descricao,
    {
        "analisar_descricao": "analisar_descricao",
        "__end__": END,
    },
)

subgrafo_descricao = builder.compile()
