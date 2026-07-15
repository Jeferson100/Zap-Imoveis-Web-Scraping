import logging
import time
from typing import Any, Dict, Literal

from langgraph.graph import END, StateGraph

from roteador_llms.roteador_llms import LlmRouter

from .config import (
            #MODEL_TEXTO_EXTRACAO, 
            TAMANHO_LOTE, 
            TIMEOUT_LLM)
from .prompts import (
    PROMPT_EXTRAIR_ANALISE,
    PROMPT_REFLEXAO_IMAGENS,
    PROMPT_DESCREVER_FOTO,
)
from .schemas import AnaliseImagens, FeedbackImagens, SubgrafoImagensState
from .utils import processar_todos_lotes
from .retry_handler import retry_com_backoff

logger = logging.getLogger(__name__)

_FEEDBACK_FALHA_REFLEXAO = (
    "Falha tecnica na auditoria. Refaca a descricao e a extracao com mais rigor."
)


def _analise_fallback(mensagem: str) -> AnaliseImagens:
    return AnaliseImagens(
        score_conservacao=0,
        score_acabamento=0,
        score_potencial_reforma=0,
        confianca_imagem=0,
        imagem_aceitavel=False,
        problemas_visiveis=[mensagem],
        pontos_fortes=[],
        observacoes=mensagem,
    )


async def descrever_fotos(state: SubgrafoImagensState) -> Dict[str, Any]:
    if not state.fotos_urls:
        logger.error("Nenhuma URL de foto disponivel.")
        return {"descricao_foto": "", "tentativa": state.tentativa + 1}

    prompt = PROMPT_DESCREVER_FOTO
    if state.feedback:
        prompt += f"\n\nObservacoes da revisao anterior:\n{state.feedback}"


    inicio = time.perf_counter()
    descricao = await processar_todos_lotes(state.fotos_urls, TAMANHO_LOTE)
    logger.info(
        "descrever_fotos: tentativa=%d fotos=%d lotes~=%d duracao=%.2fs",
        state.tentativa + 1,
        len(state.fotos_urls),
        (len(state.fotos_urls) + TAMANHO_LOTE - 1) // TAMANHO_LOTE,
        time.perf_counter() - inicio,
    )

    if not descricao:
        logger.error("Nao foi possivel descrever as fotos.")
    return {"descricao_foto": descricao, "tentativa": state.tentativa + 1}


async def extrair_analise(state: SubgrafoImagensState) -> Dict[str, Any]:
    descricao_unificada = (
        state.descricao_foto if state.descricao_foto else "Nenhuma foto disponivel."
    )

    prompt = PROMPT_EXTRAIR_ANALISE.format(descricao=descricao_unificada)
    if state.feedback:
        prompt += f"\n\nFeedback para considerar:\n{state.feedback}"

    async def _chamar_extracao():
        router = LlmRouter(
            messages=prompt,
            #model_llm=MODEL_TEXTO_EXTRACAO,
            strutured_output=AnaliseImagens,
            api_key=state.api_key,
            timeout=TIMEOUT_LLM,
            api_nvidia_models=[
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
            return (
                AnaliseImagens(**resultado)
                if isinstance(resultado, dict)
                else resultado
            )

    try:
        analise = await retry_com_backoff(
            _chamar_extracao,
            max_attempts=2,
            base_delay=1.0,
            max_delay=30.0
        )
        if analise:
            return {"analise": analise}
    except Exception as e:
        logger.error("Erro ao extrair analise apos retries: %s", e)

    return {"analise": _analise_fallback("Falha na extracao estruturada")}


async def refletor_imagens(state: SubgrafoImagensState) -> Dict[str, Any]:
    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    descricao_unificada = (
        state.descricao_foto if state.descricao_foto else "Nenhuma foto disponivel."
    )

    prompt = PROMPT_REFLEXAO_IMAGENS.format(
        analise_json=state.analise.model_dump_json(indent=2),
        descricao=descricao_unificada,
    )

    async def _chamar_reflexao():
        router = LlmRouter(
            messages=prompt,
            #model_llm=MODEL_TEXTO_EXTRACAO,
            strutured_output=FeedbackImagens,
            api_key=state.api_key,
            timeout=TIMEOUT_LLM,
            api_nvidia_models=[
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
            return (
                FeedbackImagens(**resultado)
                if isinstance(resultado, dict)
                else resultado
            )

    try:
        feedback_obj = await retry_com_backoff(
            _chamar_reflexao,
            max_attempts=2,
            base_delay=1.0,
            max_delay=30.0
        )
        
        if feedback_obj:
            if feedback_obj.consistente:
                return {"feedback": None}
            partes = []
            if feedback_obj.feedback:
                partes.append(feedback_obj.feedback)
            if feedback_obj.inconsistencias:
                partes.append("Inconsistencias: " + "; ".join(feedback_obj.inconsistencias))
            return {"feedback": "\n".join(partes) if partes else _FEEDBACK_FALHA_REFLEXAO}
    except Exception as e:
        logger.error("Erro no refletor de imagens apos retries: %s", e)
        if state.tentativa < state.max_tentativas:
            return {"feedback": _FEEDBACK_FALHA_REFLEXAO}

    return {"feedback": None}


def decidir_proximo_imagens(
    state: SubgrafoImagensState,
) -> Literal["descrever_fotos", "__end__"]:
    if state.feedback and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa,
            state.max_tentativas,
        )
        return "descrever_fotos"
    logger.info("Analise de imagens concluida.")
    return "__end__"


def decidir_apos_extracao(
    state: SubgrafoImagensState,
) -> Literal["refletor_imagens", "__end__"]:
    if state.max_tentativas == 0:
        logger.info("MAX_TENTATIVAS=0: refletor_imagens ignorado.")
        return "__end__"
    logger.info("MAX_TENTATIVAS=%d: encaminhando para refletor_imagens.", state.max_tentativas)
    return "refletor_imagens"


builder = StateGraph(SubgrafoImagensState)

builder.add_node("descrever_fotos", descrever_fotos)
builder.add_node("extrair_analise", extrair_analise)
builder.add_node("refletor_imagens", refletor_imagens)

builder.set_entry_point("descrever_fotos")

builder.add_edge("descrever_fotos", "extrair_analise")
builder.add_conditional_edges(
    "extrair_analise",
    decidir_apos_extracao,
    {"refletor_imagens": "refletor_imagens", "__end__": END},
)

builder.add_conditional_edges(
    "refletor_imagens",
    decidir_proximo_imagens,
    {
        "descrever_fotos": "descrever_fotos",
        "__end__": END,
    },
)

subgrafo_imagens = builder.compile()
