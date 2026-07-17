import json
import logging
from typing import Any, Dict, Optional, Literal

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from .schemas import AnalisePotencialFlip, FeedbackPotencialFlip
from .prompts import PROMPT_AVALIAR_POTENCIAL_FLIP, PROMPT_REFLEXAO_POTENCIAL_FLIP
from roteador_llms.roteador_llms import LlmRouter
from shared.serialization import converter_numpy

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 2


class GrafoPotencialFlipState(BaseModel):
    dados_imovel: Dict[str, Any] = {}
    analise_imagens: Optional[Any] = None
    analise_validacao: Optional[Any] = None
    dados_finais: Dict[str, Any] = {}
    validacao_obs: str = ""
    analise: Optional[AnalisePotencialFlip] = None
    consistente_house_flip: Literal["True", "False"] = "False"
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None


async def preparar_dados(state: GrafoPotencialFlipState) -> Dict[str, Any]:
    dados = converter_numpy(dict(state.dados_imovel))
    validacao = state.analise_validacao

    if validacao and getattr(validacao, "possui_erros", "False") == "True":
        dados_finais = dict(dados)
        for campo, attr in [
            ("metragem", "metragem_corrigida"),
            ("vagas", "vagas_corrigidas"),
            ("quartos", "quartos_corrigidos"),
            ("valor_imovel", "valor_imovel_corrigido"),
            ("tipo_imovel", "tipo_imovel_corrigido"),
            ("bairro", "bairro_corrigido"),
        ]:
            valor = getattr(validacao, attr, None)
            if valor is not None:
                dados_finais[campo] = valor
        validacao_obs = (
            f"Dados corrigidos. Inconsistencias: {validacao.inconsistencias_encontradas}. "
            f"Confianca: {validacao.confianca_validacao}. Obs: {validacao.observacoes}"
        )
    else:
        dados_finais = dados
        validacao_obs = getattr(validacao, "observacoes", "N/A") if validacao else "N/A"

    metragem = dados_finais.get("metragem", 0) or dados_finais.get("area_estimada", 0)
    valor_imovel = dados_finais.get("valor_imovel", 0)
    if metragem and valor_imovel:
        dados_finais["preco_por_m2"] = round(valor_imovel / metragem, 2)

    valor_predito = dados_finais.get("valor_predito", 0)
    if metragem and valor_predito:
        dados_finais["valor_m2_predicao"] = round(valor_predito / metragem, 2)
    else:
        dados_finais["valor_m2_predicao"] = 0
    dados_finais["valor_m2_bairro"] = dados_finais.get("p50_bairro", 0)

    return {"dados_finais": dados_finais, "validacao_obs": validacao_obs}


async def avaliar_potencial_flip(state: GrafoPotencialFlipState) -> Dict[str, Any]:
    prompt = PROMPT_AVALIAR_POTENCIAL_FLIP.format(
        dados_imovel=json.dumps(converter_numpy(state.dados_finais), indent=2, ensure_ascii=False),
        analise_imagens=(
            state.analise_imagens.model_dump_json(indent=2)
            if state.analise_imagens else "N/A"
        ),
    )
    if state.feedback:
        prompt += f"\n\nFeedback da revisao anterior:\n{state.feedback}"

    router = LlmRouter(
        messages=prompt,
        strutured_output=AnalisePotencialFlip,
        api_key=state.api_key,
        api_nvidia_models=[
            "deepseek-ai/deepseek-v4-flash",
            "deepseek-ai/deepseek-v4-pro",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "google/gemma-4-31b-it",
        ],
    )
    resultado = await router.llm_router()

    if resultado:
        analise = (
            AnalisePotencialFlip(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"analise": analise, "tentativa": state.tentativa + 1}

    return {
        "analise": AnalisePotencialFlip(
            score_potencial_flip=0,
            potencial_house_flip="False",
            justificativa_potencial="Falha na geracao da analise",
            riscos=["Nao foi possivel avaliar o potencial de house flip"],
            recomendacoes=[],
            observacoes="Falha na extracao estruturada",
        ),
        "tentativa": state.tentativa + 1,
    }


async def refletor_potencial_flip(state: GrafoPotencialFlipState) -> Dict[str, Any]:
    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    prompt = PROMPT_REFLEXAO_POTENCIAL_FLIP.format(
        analise_json=state.analise.model_dump_json(indent=2),
        dados_imovel=json.dumps(converter_numpy(state.dados_finais), indent=2, ensure_ascii=False),
        analise_imagens=(
            state.analise_imagens.model_dump_json(indent=2)
            if state.analise_imagens else "N/A"
        ),
        validacao_obs=state.validacao_obs or "N/A",
    )

    router = LlmRouter(
        messages=prompt,
        strutured_output=FeedbackPotencialFlip,
        api_key=state.api_key,
        api_nvidia_models=[
            "deepseek-ai/deepseek-v4-flash",
            "deepseek-ai/deepseek-v4-pro",
            "mistralai/mistral-large-3-675b-instruct-2512",
            "google/gemma-4-31b-it",
        ],
    )
    resultado = await router.llm_router()

    if resultado:
        fb = (
            FeedbackPotencialFlip(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"feedback": fb.feedback,
                "consistente_house_flip": fb.consistente,}
    return {"feedback": None}


def decidir_proximo_potencial_flip(
    state: GrafoPotencialFlipState,
) -> Literal["avaliar_potencial_flip", "__end__"]:
    if state.consistente_house_flip == "True" and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa, state.max_tentativas,
        )
        return "avaliar_potencial_flip"
    logger.info("Avaliacao de potencial flip concluida.")
    return "__end__"


builder = StateGraph(GrafoPotencialFlipState)
builder.add_node("preparar_dados", preparar_dados)
builder.add_node("avaliar_potencial_flip", avaliar_potencial_flip)
builder.add_node("refletor_potencial_flip", refletor_potencial_flip)
builder.set_entry_point("preparar_dados")
builder.add_edge("preparar_dados", "avaliar_potencial_flip")
builder.add_edge("avaliar_potencial_flip", "refletor_potencial_flip")
builder.add_conditional_edges(
    "refletor_potencial_flip",
    decidir_proximo_potencial_flip,
    {"avaliar_potencial_flip": "avaliar_potencial_flip", "__end__": END},
)
subgrafo_potencial_flip = builder.compile()
