import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Literal

import httpx
from langchain_core.messages import HumanMessage
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from ..schemas import AnaliseImagens, FeedbackImagens, CategoriaConservacao
from ..prompts import (
    PROMPT_DESCREVER_FOTO,
    PROMPT_EXTRAIR_ANALISE,
    PROMPT_REFLEXAO_IMAGENS,
)

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 1
TIMEOUT_DOWNLOAD = 15
TAMANHO_LOTE = 5


class SubgrafoImagensState(BaseModel):
    fotos_urls: List[str] = []
    descricoes: List[str] = []
    analise: Optional[AnaliseImagens] = None
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None
    model_nome: str = "qwen/qwen3.5-122b-a10b"


async def _baixar(client: httpx.AsyncClient, url: str) -> Optional[str]:
    try:
        resp = await client.get(url, timeout=TIMEOUT_DOWNLOAD)
        ct = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ct.startswith("image/"):
            return base64.b64encode(resp.content).decode("utf-8")
        logger.warning("URL invalida: %s (%s)", url[:60], ct)
    except Exception as e:
        logger.warning("Erro ao baixar %s: %s", url[:60], e)
    return None


async def _processar_lote(
    model: ChatNVIDIA, client: httpx.AsyncClient,
    urls: list[str], prompt: str, idx: int,
) -> str:
    bases64 = await asyncio.gather(*[_baixar(client, url) for url in urls])
    bases64 = [b for b in bases64 if b]
    if not bases64:
        return ""

    conteudo = [{"type": "text", "text": f"{prompt}\n\n(Lote {idx+1})"}]
    for b64 in bases64:
        conteudo.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    response = await model.ainvoke([HumanMessage(content=conteudo)])
    return response.content


async def descrever_fotos(state: SubgrafoImagensState) -> Dict[str, Any]:
    if not state.fotos_urls:
        logger.error("Nenhuma URL de foto disponivel.")
        return {"descricoes": [""], "tentativa": state.tentativa + 1}

    prompt = PROMPT_DESCREVER_FOTO
    if state.feedback:
        prompt += f"\n\nObservacoes da revisao anterior:\n{state.feedback}"

    model = ChatNVIDIA(
        model=state.model_nome,
        use_responses_api=True,
        nvidia_api_key=state.api_key,
    )

    lotes = [
        state.fotos_urls[i:i + TAMANHO_LOTE]
        for i in range(0, len(state.fotos_urls), TAMANHO_LOTE)
    ]

    async with httpx.AsyncClient() as client:
        tarefas = [
            _processar_lote(model, client, lote, prompt, idx)
            for idx, lote in enumerate(lotes)
        ]
        textos = await asyncio.gather(*tarefas)

    textos = [t for t in textos if t]
    descricao = "\n\n---\n\n".join(textos) if textos else ""
    descricoes = [descricao] if descricao else [""]

    if not descricao:
        logger.error("Nao foi possivel descrever as fotos.")
    return {"descricoes": descricoes, "tentativa": state.tentativa + 1}


async def extrair_analise(state: SubgrafoImagensState) -> Dict[str, Any]:
    import roteador_api_nvidia

    descricao_unificada = state.descricoes[0] if state.descricoes and state.descricoes[0] else "Nenhuma foto disponivel."

    prompt = PROMPT_EXTRAIR_ANALISE.format(descricao=descricao_unificada)
    if state.feedback:
        prompt += f"\n\nFeedback para considerar:\n{state.feedback}"

    try:
        RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
        router = RouterApiNvidia(
            messages=prompt,
            model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            strutured_output=AnaliseImagens,
            api_key=state.api_key,
        )
        resultado = await router.ainvoke()
        if resultado:
            analise = (
                AnaliseImagens(**resultado)
                if isinstance(resultado, dict)
                else resultado
            )
            return {"analise": analise}
    except Exception as e:
        logger.error("Erro ao extrair analise: %s", e)

    return {
        "analise": AnaliseImagens(
            score_conservacao=0,
            score_acabamento=0,
            score_potencial_reforma=0,
            confianca_imagem=0,
            imagem_aceitavel=False,
            categorias_conservacao=[
                CategoriaConservacao(
                    nome="geral",
                    score=0,
                    severidade="ALTA",
                    evidencias=["Falha na análise das fotos"],
                    necessidade_reparo=True,
                )
            ],
            problemas_visiveis=["Nao foi possivel analisar as fotos"],
            pontos_fortes=[],
            observacoes="Falha na extracao estruturada",
        )
    }


async def refletor_imagens(state: SubgrafoImagensState) -> Dict[str, Any]:
    import roteador_api_nvidia

    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    descricao_unificada = state.descricoes[0] if state.descricoes and state.descricoes[0] else ""

    prompt = PROMPT_REFLEXAO_IMAGENS.format(
        analise_json=state.analise.model_dump_json(indent=2),
        descricao=descricao_unificada,
    )

    try:
        RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
        router = RouterApiNvidia(
            messages=prompt,
            model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            strutured_output=FeedbackImagens,
            api_key=state.api_key,
        )
        resultado = await router.ainvoke()
        if resultado:
            feedback_obj = (
                FeedbackImagens(**resultado)
                if isinstance(resultado, dict)
                else resultado
            )
            return {
                "feedback": feedback_obj.feedback if not feedback_obj.consistente else None,
            }
    except Exception as e:
        logger.error("Erro no refletor de imagens: %s", e)

    return {"feedback": None}


def decidir_proximo_imagens(
    state: SubgrafoImagensState,
) -> Literal["descrever_fotos", "__end__"]:
    if state.feedback and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa, state.max_tentativas,
        )
        return "descrever_fotos"
    logger.info("Analise de imagens concluida.")
    return "__end__"


builder = StateGraph(SubgrafoImagensState)

builder.add_node("descrever_fotos", descrever_fotos)
builder.add_node("extrair_analise", extrair_analise)
builder.add_node("refletor_imagens", refletor_imagens)

builder.set_entry_point("descrever_fotos")

builder.add_edge("descrever_fotos", "extrair_analise")
builder.add_edge("extrair_analise", "refletor_imagens")

builder.add_conditional_edges(
    "refletor_imagens",
    decidir_proximo_imagens,
    {
        "descrever_fotos": "descrever_fotos",
        "__end__": END,
    },
)

subgrafo_imagens = builder.compile()
