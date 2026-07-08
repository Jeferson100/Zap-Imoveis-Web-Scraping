import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from ..schemas import AnaliseDados, FeedbackDados
from ..prompts import PROMPT_ANALISAR_DADOS, PROMPT_REFLEXAO_DADOS

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 2


class SubgrafoDadosState(BaseModel):
    dados_imovel: Dict[str, Any] = {}
    analise: Optional[AnaliseDados] = None
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None


async def analisar_dados(state: SubgrafoDadosState) -> Dict[str, Any]:
    import roteador_api_nvidia

    dados_json = str(state.dados_imovel)
    prompt = PROMPT_ANALISAR_DADOS.format(dados_json=dados_json)
    if state.feedback:
        prompt += f"\n\nFeedback da revisao anterior:\n{state.feedback}"

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        strutured_output=AnaliseDados,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        analise = (
            AnaliseDados(**resultado) if isinstance(resultado, dict) else resultado
        )
        return {"analise": analise, "tentativa": state.tentativa + 1}

    return {
        "analise": AnaliseDados(
            endereco_formatado=str(state.dados_imovel.get("endereco", "")),
            bairro=str(state.dados_imovel.get("bairro", "")),
            cidade=str(state.dados_imovel.get("cidade", "")),
            score_localizacao=0,
            score_infraestrutura=0,
            demanda_bairro=0,
            pontos_positivos=[],
            pontos_negativos=["Nao foi possivel analisar os dados"],
            observacoes="Falha na extracao estruturada",
        ),
        "tentativa": state.tentativa + 1,
    }


async def refletor_dados(state: SubgrafoDadosState) -> Dict[str, Any]:
    import roteador_api_nvidia

    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    prompt = PROMPT_REFLEXAO_DADOS.format(
        analise_json=state.analise.model_dump_json(indent=2),
        dados_json=str(state.dados_imovel),
    )

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        strutured_output=FeedbackDados,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        fb = FeedbackDados(**resultado) if isinstance(resultado, dict) else resultado
        return {"feedback": fb.feedback if not fb.consistente else None}
    return {"feedback": None}


def decidir_proximo_dados(
    state: SubgrafoDadosState,
) -> Literal["analisar_dados", "__end__"]:
    if state.feedback and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa,
            state.max_tentativas,
        )
        return "analisar_dados"
    logger.info("Analise de dados concluida.")
    return "__end__"


builder = StateGraph(SubgrafoDadosState)

builder.add_node("analisar_dados", analisar_dados)
builder.add_node("refletor_dados", refletor_dados)

builder.set_entry_point("analisar_dados")

builder.add_edge("analisar_dados", "refletor_dados")

builder.add_conditional_edges(
    "refletor_dados",
    decidir_proximo_dados,
    {
        "analisar_dados": "analisar_dados",
        "__end__": END,
    },
)

subgrafo_dados = builder.compile()
