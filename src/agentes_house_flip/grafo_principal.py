import logging
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

from langgraph.graph import StateGraph, END
from pydantic import BaseModel

from .schemas import (
    AnaliseImagens,
    AnaliseDados,
    AnaliseDescricao,
    AnaliseFinal,
)
from .subgrafos.subgrafo_imagens import subgrafo_imagens, SubgrafoImagensState
from .subgrafos.subgrafo_dados import subgrafo_dados, SubgrafoDadosState
from .subgrafos.subgrafo_descricao import subgrafo_descricao, SubgrafoDescricaoState
from agente_validacao.subgrafo_validacao import subgrafo_validacao, SubgrafoValidacaoState
from agente_validacao.schemas import ValidacaoDados

_PATH_ROTEADOR = str(Path(__file__).resolve().parent.parent / "roteador_llms")
if _PATH_ROTEADOR not in sys.path:
    sys.path.insert(0, _PATH_ROTEADOR)

logger = logging.getLogger(__name__)


class EstadoGlobal(BaseModel):
    fotos_urls: List[str] = []
    dados_imovel: Dict[str, Any] = {}
    descricao_texto: str = ""
    analise_imagens: Optional[AnaliseImagens] = None
    analise_dados: Optional[AnaliseDados] = None
    analise_descricao: Optional[AnaliseDescricao] = None
    analise_validacao: Optional[ValidacaoDados] = None
    analise_final: Optional[AnaliseFinal] = None
    cross_feedback: List[str] = []
    api_key: Optional[str] = None


async def executar_subgrafo_imagens(state: EstadoGlobal) -> Dict[str, Any]:
    sub_state = SubgrafoImagensState(
        fotos_urls=state.fotos_urls,
        api_key=state.api_key,
    )
    result = await subgrafo_imagens.ainvoke(sub_state)
    analise = result.get("analise") if isinstance(result, dict) else None
    return {"analise_imagens": analise}


async def executar_subgrafo_dados(state: EstadoGlobal) -> Dict[str, Any]:
    sub_state = SubgrafoDadosState(
        dados_imovel=state.dados_imovel,
        api_key=state.api_key,
    )
    result = await subgrafo_dados.ainvoke(sub_state)
    analise = result.get("analise") if isinstance(result, dict) else None
    return {"analise_dados": analise}


async def executar_subgrafo_descricao(state: EstadoGlobal) -> Dict[str, Any]:
    sub_state = SubgrafoDescricaoState(
        descricao_texto=state.descricao_texto,
        api_key=state.api_key,
    )
    result = await subgrafo_descricao.ainvoke(sub_state)
    analise = result.get("analise") if isinstance(result, dict) else None
    return {"analise_descricao": analise}


async def executar_subgrafo_validacao(state: EstadoGlobal) -> Dict[str, Any]:
    sub_state = SubgrafoValidacaoState(
        dados_imovel=state.dados_imovel,
        descricao_texto=state.descricao_texto,
        api_key=state.api_key,
    )
    result = await subgrafo_validacao.ainvoke(sub_state)
    analise = result.get("analise") if isinstance(result, dict) else None
    return {"analise_validacao": analise}


async def cross_refletir(state: EstadoGlobal) -> Dict[str, Any]:
    import roteador_api_nvidia

    prompt = (
        "Voce e um coordenador de equipe de avaliacao imobiliaria.\n"
        "Abaixo estao tres analises do mesmo imovel:\n\n"
        "--- ANALISE DE IMAGENS ---\n"
        f"{state.analise_imagens.model_dump_json(indent=2) if state.analise_imagens else 'N/A'}\n\n"
        "--- ANALISE DE DADOS ---\n"
        f"{state.analise_dados.model_dump_json(indent=2) if state.analise_dados else 'N/A'}\n\n"
        "--- ANALISE DE DESCRICAO ---\n"
        f"{state.analise_descricao.model_dump_json(indent=2) if state.analise_descricao else 'N/A'}\n\n"
        "--- VALIDACAO (DADOS vs DESCRICAO) ---\n"
        f"{state.analise_validacao.model_dump_json(indent=2) if state.analise_validacao else 'N/A'}\n\n"
        "Identifique inconsistencias entre as analises. "
        "Retorne uma lista de pontos de conflito ou 'NENHUMA INCONSISTENCIA' se estiver tudo coerente."
    )

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        api_key=state.api_key,
    )
    texto = await router.ainvoke()
    feedback = [texto] if texto and texto.strip().upper() != "NENHUMA INCONSISTENCIA" else []
    return {"cross_feedback": feedback}


async def gerar_conclusao_final(state: EstadoGlobal) -> Dict[str, Any]:
    import roteador_api_nvidia

    prompt = (
        "Com base nas analises abaixo, produza uma conclusao final de house flipping.\n\n"
        "--- ANALISE DE IMAGENS ---\n"
        f"{state.analise_imagens.model_dump_json(indent=2) if state.analise_imagens else 'N/A'}\n\n"
        "--- ANALISE DE DADOS ---\n"
        f"{state.analise_dados.model_dump_json(indent=2) if state.analise_dados else 'N/A'}\n\n"
        "--- ANALISE DE DESCRICAO ---\n"
        f"{state.analise_descricao.model_dump_json(indent=2) if state.analise_descricao else 'N/A'}\n\n"
        "--- CROSS FEEDBACK ---\n"
        + ("\n".join(state.cross_feedback) if state.cross_feedback else "Nenhuma inconsistencia.")
        + "\n\n"
        "Retorne: score_geral (0-10), potencial_house_flip (BAIXO/MEDIO/ALTO/ALTISSIMO), "
        "custo_reforma_estimado, valor_estimado_pos_reforma, roi_estimado (percentual), "
        "riscos, recomendacoes, observacoes_finais."
    )

    RouterApiNvidia = roteador_api_nvidia.RouterApiNvidia
    router = RouterApiNvidia(
        messages=prompt,
        model_llm="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        strutured_output=AnaliseFinal,
        api_key=state.api_key,
    )
    resultado = await router.ainvoke()
    if resultado:
        analise = AnaliseFinal(**resultado) if isinstance(resultado, dict) else resultado
        return {"analise_final": analise}
    return {
        "analise_final": AnaliseFinal(
            score_geral=0,
            potencial_house_flip="BAIXO",
            custo_reforma_estimado=0,
            valor_estimado_pos_reforma=0,
            roi_estimado=0,
            riscos=["Falha na geracao da conclusao"],
            recomendacoes=[],
            observacoes_finais="Nao foi possivel gerar conclusao",
        )
    }


builder = StateGraph(EstadoGlobal)

builder.add_node("executar_subgrafo_imagens", executar_subgrafo_imagens)
builder.add_node("executar_subgrafo_dados", executar_subgrafo_dados)
builder.add_node("executar_subgrafo_descricao", executar_subgrafo_descricao)
builder.add_node("executar_subgrafo_validacao", executar_subgrafo_validacao)
builder.add_node("cross_refletir", cross_refletir)
builder.add_node("gerar_conclusao_final", gerar_conclusao_final)

builder.set_entry_point("executar_subgrafo_imagens")

builder.add_edge("executar_subgrafo_imagens", "executar_subgrafo_dados")
builder.add_edge("executar_subgrafo_dados", "executar_subgrafo_descricao")
builder.add_edge("executar_subgrafo_descricao", "executar_subgrafo_validacao")
builder.add_edge("executar_subgrafo_validacao", "cross_refletir")
builder.add_edge("cross_refletir", "gerar_conclusao_final")
builder.add_edge("gerar_conclusao_final", END)

grafo_principal = builder.compile()
