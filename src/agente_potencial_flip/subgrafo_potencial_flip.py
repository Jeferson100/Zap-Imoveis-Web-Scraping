import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from .schemas import AnalisePotencialFlip, FeedbackPotencialFlip
from .prompts import PROMPT_AVALIAR_POTENCIAL_FLIP, PROMPT_REFLEXAO_POTENCIAL_FLIP

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)

MAX_TENTATIVAS = 2


class SubgrafoPotencialFlipState(BaseModel):
    dados_imovel: Dict[str, Any] = {}
    analise_imagens: Optional[Any] = None
    analise_validacao: Optional[Any] = None
    dados_finais: Dict[str, Any] = {}
    validacao_obs: str = ""
    analise: Optional[AnalisePotencialFlip] = None
    feedback: Optional[str] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None


async def preparar_dados(state: SubgrafoPotencialFlipState) -> Dict[str, Any]:
    dados = dict(state.dados_imovel)

    validacao = state.analise_validacao
    if validacao and validacao.possui_erros == "True":
        dados_finais = dict(dados)
        if validacao.metragem_corrigida is not None:
            dados_finais["metragem"] = validacao.metragem_corrigida
        if validacao.vagas_corrigidas is not None:
            dados_finais["vagas"] = validacao.vagas_corrigidas
        if validacao.quartos_corrigidos is not None:
            dados_finais["quartos"] = validacao.quartos_corrigidos
        if validacao.valor_imovel_corrigido is not None:
            dados_finais["valor_imovel"] = validacao.valor_imovel_corrigido
        if validacao.tipo_imovel_corrigido is not None:
            dados_finais["tipo_imovel"] = validacao.tipo_imovel_corrigido
        if validacao.bairro_corrigido is not None:
            dados_finais["bairro"] = validacao.bairro_corrigido
        validacao_obs = (
            f"Dados corrigidos. Inconsistencias: {validacao.inconsistencias_encontradas}. "
            f"Confianca: {validacao.confianca_validacao}. Obs: {validacao.observacoes}"
        )
    else:
        dados_finais = dados
        validacao_obs = validacao.observacoes if validacao else "N/A"

    # recalcular preco_por_m2 com dados finais
    metragem = dados_finais.get("metragem", 0) or dados_finais.get("area_estimada", 0)
    valor_imovel = dados_finais.get("valor_imovel", 0)
    if metragem and valor_imovel:
        dados_finais["preco_por_m2"] = round(valor_imovel / metragem, 2)

    # calcular campos adicionais de m2
    valor_predito = dados_finais.get("valor_predito", 0)
    if metragem and valor_predito:
        dados_finais["valor_m2_predicao"] = round(valor_predito / metragem, 2)
    else:
        dados_finais["valor_m2_predicao"] = 0
    dados_finais["valor_m2_bairro"] = dados_finais.get("p50_bairro", 0)

    return {"dados_finais": dados_finais, "validacao_obs": validacao_obs}


async def avaliar_potencial_flip(state: SubgrafoPotencialFlipState) -> Dict[str, Any]:
    import roteador_api_nvidia

    prompt = PROMPT_AVALIAR_POTENCIAL_FLIP.format(
        dados_imovel=json.dumps(state.dados_finais, indent=2, ensure_ascii=False),
        analise_imagens=(
            state.analise_imagens.model_dump_json(indent=2)
            if state.analise_imagens else "N/A"
        ),
    )
    if state.feedback:
        prompt += f"\n\nFeedback da revisao anterior:\n{state.feedback}"

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="deepseek-ai/deepseek-v4-flash",
        strutured_output=AnalisePotencialFlip,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        analise = (
            AnalisePotencialFlip(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"analise": analise, "tentativa": state.tentativa + 1}

    return {
        "analise": AnalisePotencialFlip(
            score_house_flip=0,
            potencial_house_flip="BAIXO",
            justificativa_potencial="Falha na geracao da analise",
            custo_reforma_estimado=0,
            valor_estimado_pos_reforma=0,
            roi_estimado=0,
            riscos=["Nao foi possivel avaliar o potencial de house flip"],
            recomendacoes=[],
            observacoes="Falha na extracao estruturada",
        ),
        "tentativa": state.tentativa + 1,
    }


async def refletor_potencial_flip(state: SubgrafoPotencialFlipState) -> Dict[str, Any]:
    import roteador_api_nvidia

    if state.analise is None:
        return {"feedback": "Analise vazia, refaca."}

    prompt = PROMPT_REFLEXAO_POTENCIAL_FLIP.format(
        analise_json=state.analise.model_dump_json(indent=2),
        dados_imovel=json.dumps(state.dados_finais, indent=2, ensure_ascii=False),
        analise_imagens=(
            state.analise_imagens.model_dump_json(indent=2)
            if state.analise_imagens else "N/A"
        ),
        validacao_obs=state.validacao_obs or "N/A",
    )

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="deepseek-ai/deepseek-v4-flash",
        strutured_output=FeedbackPotencialFlip,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        fb = (
            FeedbackPotencialFlip(**resultado)
            if isinstance(resultado, dict)
            else resultado
        )
        return {"feedback": fb.feedback if not fb.consistente else None}
    return {"feedback": None}


def decidir_proximo_potencial_flip(
    state: SubgrafoPotencialFlipState,
) -> Literal["avaliar_potencial_flip", "__end__"]:
    if state.feedback and state.tentativa < state.max_tentativas:
        logger.info(
            "Refletor pediu refinamento (tentativa %d/%d)",
            state.tentativa, state.max_tentativas,
        )
        return "avaliar_potencial_flip"
    logger.info("Avaliacao de potencial flip concluida.")
    return "__end__"


builder = StateGraph(SubgrafoPotencialFlipState)

builder.add_node("preparar_dados", preparar_dados)
builder.add_node("avaliar_potencial_flip", avaliar_potencial_flip)
builder.add_node("refletor_potencial_flip", refletor_potencial_flip)

builder.set_entry_point("preparar_dados")

builder.add_edge("preparar_dados", "avaliar_potencial_flip")
builder.add_edge("avaliar_potencial_flip", "refletor_potencial_flip")

builder.add_conditional_edges(
    "refletor_potencial_flip",
    decidir_proximo_potencial_flip,
    {
        "avaliar_potencial_flip": "avaliar_potencial_flip",
        "__end__": END,
    },
)

subgrafo_potencial_flip = builder.compile()
