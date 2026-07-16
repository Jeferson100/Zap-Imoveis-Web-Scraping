import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Literal
from pydantic import BaseModel

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from .schemas import ValidacaoDados, FeedbackValidacao
from .prompts import PROMPT_VALIDAR_DADOS, PROMPT_REFLEXAO_VALIDACAO
from roteador_llms.roteador_llms import LlmRouter

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 2


class SubgrafoValidacaoState(BaseModel):
    dados_imovel: Dict[str, Any] = {}
    descricao_texto: str = ""
    analise: Optional[ValidacaoDados] = None
    # "True" = há erros nos dados (re-validar), "False" = dados ok (encerrar)
    consistente: Literal["True", "False"] = "False"
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None
    metragem_corrigida: Optional[float] = None
    vagas_corrigidas: Optional[int] = None
    quartos_corrigidos: Optional[int] = None
    valor_imovel_corrigido: Optional[float] = None
    tipo_imovel_corrigido: Optional[str] = None
    bairro_corrigido: Optional[str] = None


async def validar_dados(state: SubgrafoValidacaoState) -> Dict[str, Any]:
    
    prompt = PROMPT_VALIDAR_DADOS.format(
        dados_json=str(state.dados_imovel),
        descricao_texto=state.descricao_texto or "Nenhuma descricao fornecida.",
    )
    if state.feedback:
        prompt += f"\n\nFeedback da revisao anterior:\n{state.feedback}"
    router = LlmRouter(
        messages=prompt,
        strutured_output=ValidacaoDados,
        api_key=state.api_key,
        api_nvidia_models=[
                "z-ai/glm-5.2",
                "deepseek-ai/deepseek-v4-flash",
                "z-ai/glm-5.2",
                "mistralai/mistral-large-3-675b-instruct-2512",
                "google/gemma-4-31b-it",
                "deepseek-ai/deepseek-v4-pro",
                "qwen/qwen3.5-397b-a17b",
            ],
    )
    resultado = await router.llm_router()
    if resultado:
        analise = (
            ValidacaoDados(**resultado) if isinstance(resultado, dict) else resultado
        )
        return {
            "analise": analise,
            "possui_erros": analise.possui_erros,
            "metragem_corrigida": analise.metragem_corrigida,
            "vagas_corrigidas": analise.vagas_corrigidas,
            "quartos_corrigidos": analise.quartos_corrigidos,
            "valor_imovel_corrigido": analise.valor_imovel_corrigido,
            "tipo_imovel_corrigido": analise.tipo_imovel_corrigido,
            "bairro_corrigido": analise.bairro_corrigido,
            "tentativa": state.tentativa + 1,
        }

    return {
        "analise": ValidacaoDados(
            dados_corrigidos=state.dados_imovel,
            dados_consistentes=False,
            possui_erros="True",
            inconsistencias_encontradas=["Nao foi possivel validar os dados"],
            confianca_validacao=0,
            observacoes="Falha na extracao estruturada",
        ),
        "possui_erros": "True",
        "tentativa": state.tentativa + 1,
    }


async def refletor_validacao(state: SubgrafoValidacaoState) -> Dict[str, Any]:

    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    prompt = PROMPT_REFLEXAO_VALIDACAO.format(
        analise_json=state.analise.model_dump_json(indent=2),
        dados_json=str(state.dados_imovel),
        descricao_texto=state.descricao_texto or "Nenhuma descricao fornecida.",
    )
    router = LlmRouter(
        messages=prompt,
        strutured_output=FeedbackValidacao,
        api_key=state.api_key,
        api_nvidia_models=[
                "z-ai/glm-5.2",
                "deepseek-ai/deepseek-v4-flash",
                "z-ai/glm-5.2",
                "mistralai/mistral-large-3-675b-instruct-2512",
                "google/gemma-4-31b-it",
                "deepseek-ai/deepseek-v4-pro",
                "qwen/qwen3.5-397b-a17b",
            ],
    )
    resultado = await router.llm_router()
    if resultado:
        fb = (
            FeedbackValidacao(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"feedback": fb.feedback if not fb.consistente else None,
                "consistente": fb.consistente,}
    return {"feedback": None}


def decidir_proximo_validacao(
    state: SubgrafoValidacaoState,
) -> Literal["validar_dados", "__end__"]:
    # "True" = há erros nos dados → re-validar se ainda há tentativas
    if state.consistente == "True" and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor encontrou erros, re-validando (tentativa %d/%d)",
            state.tentativa, state.max_tentativas,
        )
        return "validar_dados"

    logger.info("Validacao de dados concluida.")
    return "__end__"


builder = StateGraph(SubgrafoValidacaoState)
builder.add_node("validar_dados", validar_dados)
builder.add_node("refletor_validacao", refletor_validacao)
builder.set_entry_point("validar_dados")
builder.add_edge("validar_dados", "refletor_validacao")
builder.add_conditional_edges(
    "refletor_validacao",
    decidir_proximo_validacao,
    {"validar_dados": "validar_dados", "__end__": END},
)
subgrafo_validacao = builder.compile()
