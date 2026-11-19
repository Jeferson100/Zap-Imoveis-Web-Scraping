import asyncio
import logging
import time
from typing import Any, Dict, Literal

from langgraph.graph import END, StateGraph

from roteador_llms.roteador_llms import LlmRouter

from .config import (
            #MODEL_TEXTO_EXTRACAO, 
            JULGADOR,
            TAMANHO_LOTE, 
            TIMEOUT_LLM)
from .julgador_classificador import disponivel as classificador_disponivel
from .julgador_classificador import julgar_fotos
from .julgador_laya import LayaIndisponivel
from .julgador_laya import disponivel as laya_disponivel
from .julgador_laya import julgar_descricao
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
            api_nvidia_models=None,  # seleção dinâmica via catálogo
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


async def julgar_imagens(state: SubgrafoImagensState) -> Dict[str, Any]:
    """Julga a descrição com perguntas tipadas (Laya) ou cai para o LLM.

    `IMAGENS_JULGADOR=laya` (padrão) usa o julgador local; `=llm` mantém o
    comportamento antigo. Se o pacote `laya` não estiver instalado, usa o LLM.
    """
    if JULGADOR != "laya":
        return await extrair_analise(state)

    if not laya_disponivel():
        logger.warning(
            "IMAGENS_JULGADOR=laya, mas o pacote laya nao esta instalado; "
            "usando extrair_analise (LLM)."
        )
        return await extrair_analise(state)

    descricao = state.descricao_foto if state.descricao_foto else "Nenhuma foto disponivel."
    if state.feedback:
        descricao = f"{descricao}\n\nFeedback da revisao anterior:\n{state.feedback}"

    inicio = time.perf_counter()
    # `predict` do Laya é síncrono e usa CPU: roda fora do event loop.
    try:
        analise = await asyncio.to_thread(julgar_descricao, descricao)
    except LayaIndisponivel as exc:
        logger.warning("Julgar via Laya indisponivel (%s); usando extrair_analise.", exc)
        return await extrair_analise(state)
    except Exception as exc:
        logger.error("Julgador Laya falhou (%s); usando extrair_analise.", exc)
        return await extrair_analise(state)
    logger.info(
        "julgar_imagens (laya): aceitavel=%s conservacao=%.1f duracao=%.2fs",
        analise.imagem_aceitavel,
        analise.score_conservacao,
        time.perf_counter() - inicio,
    )
    return {"analise": analise}


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
            api_nvidia_models=None,  # seleção dinâmica via catálogo
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


def decidir_apos_julgamento(
    state: SubgrafoImagensState,
) -> Literal["refletor_imagens", "__end__"]:
    if state.max_tentativas == 0:
        logger.info("MAX_TENTATIVAS=0: refletor_imagens ignorado.")
        return "__end__"
    logger.info("MAX_TENTATIVAS=%d: encaminhando para refletor_imagens.", state.max_tentativas)
    return "refletor_imagens"


# Compatibilidade: o nome antigo continua exportado (testes/imports existentes).
decidir_apos_extracao = decidir_apos_julgamento


async def julgar_classificador(state: SubgrafoImagensState) -> Dict[str, Any]:
    """Avalia as fotos com o classificador ConvNeXt (conservação + ambiente)."""
    if not state.fotos_urls:
        return {"analise": _analise_fallback("Sem foto para o classificador")}

    inicio = time.perf_counter()
    try:
        analise = await asyncio.to_thread(julgar_fotos, list(state.fotos_urls))
    except Exception as exc:
        logger.error("Classificador de fotos falhou (%s); usando extrair_analise.", exc)
        return await extrair_analise(state)

    logger.info(
        "julgar_classificador: ambiente=%s classe=%s conf=%.2f duracao=%.2fs",
        analise.ambiente,
        analise.classe_conservacao,
        analise.confianca_conservacao,
        time.perf_counter() - inicio,
    )
    return {"analise": analise}


def rotear_entrada(
    state: SubgrafoImagensState,
) -> Literal["descrever_fotos", "julgar_classificador"]:
    """O classificador não precisa de descrição: entra direto quando disponível."""
    if JULGADOR == "classificador" and classificador_disponivel():
        return "julgar_classificador"
    if JULGADOR == "classificador":
        logger.warning(
            "IMAGENS_JULGADOR=classificador, mas os checkpoints estao ausentes; "
            "usando o caminho com descricao."
        )
    return "descrever_fotos"


builder = StateGraph(SubgrafoImagensState)

builder.add_node("descrever_fotos", descrever_fotos)
builder.add_node("julgar_imagens", julgar_imagens)
builder.add_node("julgar_classificador", julgar_classificador)
builder.add_node("refletor_imagens", refletor_imagens)

builder.set_conditional_entry_point(
    rotear_entrada,
    {
        "descrever_fotos": "descrever_fotos",
        "julgar_classificador": "julgar_classificador",
    },
)

builder.add_edge("descrever_fotos", "julgar_imagens")
builder.add_conditional_edges(
    "julgar_imagens",
    decidir_apos_julgamento,
    {"refletor_imagens": "refletor_imagens", "__end__": END},
)

# O classificador é determinístico e não tem descrição para auditar: termina aqui.
builder.add_edge("julgar_classificador", END)

builder.add_conditional_edges(
    "refletor_imagens",
    decidir_proximo_imagens,
    {
        "descrever_fotos": "descrever_fotos",
        "__end__": END,
    },
)

subgrafo_imagens = builder.compile()
