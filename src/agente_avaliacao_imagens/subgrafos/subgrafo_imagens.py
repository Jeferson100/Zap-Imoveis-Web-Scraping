import asyncio
import base64
import logging
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any, Literal

import httpx
import requests
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


class SubgrafoImagensState(BaseModel):
    fotos_urls: List[str] = []
    fotos_base64: List[str] = []
    usar_url_direto: bool = True
    descricoes: List[str] = []
    analise: Optional[AnaliseImagens] = None
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None


async def _baixar_foto(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url, timeout=TIMEOUT_DOWNLOAD,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code == 200:
            b64 = base64.b64encode(resp.content).decode("utf-8")
            logger.info("Foto baixada: %s (%d bytes)", url[:60], len(resp.content))
            return b64
        logger.warning("Foto nao acessivel (HTTP %d): %s", resp.status_code, url)
    except Exception as e:
        logger.warning("Erro ao baixar foto %s: %s", url[:60], e)
    return None


async def baixar_fotos(state: SubgrafoImagensState) -> Dict[str, Any]:
    if state.fotos_base64 or state.usar_url_direto:
        return {"fotos_base64": state.fotos_base64}

    resultados = await asyncio.gather(*[_baixar_foto(url) for url in state.fotos_urls])
    base64_list = [r for r in resultados if r is not None]
    return {"fotos_base64": base64_list}


async def _enviar_vision(
    router_vision: Any, content: list, model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 1500,
    }
    try:
        headers = dict(router_vision._headers)
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                router_vision.base_url,
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        texto = response.json()["choices"][0]["message"]["content"]
        logger.info("Vision OK (%d caracteres)", len(texto))
        return texto
    except Exception as e:
        logger.warning("Falha no vision call: %s", e)
        return ""


async def descrever_fotos(state: SubgrafoImagensState) -> Dict[str, Any]:
    import roteador_api_nvidia

    feedback = state.feedback or ""
    prompt = PROMPT_DESCREVER_FOTO
    if feedback:
        prompt += f"\n\nObservacoes da revisao anterior:\n{feedback}"

    use_urls = state.usar_url_direto and bool(state.fotos_urls)
    sources = state.fotos_urls if use_urls else state.fotos_base64
    if not sources:
        logger.error("Nenhuma foto disponivel para descrever.")
        return {"descricoes": [""], "tentativa": state.tentativa + 1}

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router_vision = RouterApiNvidia(
        messages="",
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        api_key=state.api_key,
    )

    async def _descrever_uma(source: str, idx: int) -> str:
        if use_urls:
            image_payload = {"type": "image_url", "image_url": {"url": source}}
        else:
            image_payload = {
                "type": "image_url",
                "image_url": {"url": f"data:image/webp;base64,{source}"},
            }

        content = [
            {"type": "text", "text": f"{prompt}\n\n(Foto {idx+1} de {len(sources)})"},
            image_payload,
        ]
        return await _enviar_vision(router_vision, content)

    logger.info("Descrevendo %d fotos em paralelo...", len(sources))
    textos = await asyncio.gather(*[
        _descrever_uma(src, i) for i, src in enumerate(sources)
    ])
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

builder.add_node("baixar_fotos", baixar_fotos)
builder.add_node("descrever_fotos", descrever_fotos)
builder.add_node("extrair_analise", extrair_analise)
builder.add_node("refletor_imagens", refletor_imagens)

builder.set_entry_point("baixar_fotos")

builder.add_edge("baixar_fotos", "descrever_fotos")
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
