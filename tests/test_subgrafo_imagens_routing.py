"""
Property-based tests for subgrafo_imagens routing logic.

Feature: otimizacao-agente-imagens

Property 1: MAX_TENTATIVAS=0 nunca executa o refletor
Property 2: Limite de iterações do refletor é respeitado

Validates: Requirements 1.2, 1.3, 1.6
"""
import asyncio
import os
import sys
from typing import Any, Dict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from langgraph.graph import END, StateGraph

from agente_avaliacao_imagens.schemas import AnaliseImagens, SubgrafoImagensState
import agente_avaliacao_imagens.subgrafo_imagens as subgrafo_mod


def _make_analise() -> AnaliseImagens:
    return AnaliseImagens(
        score_conservacao=5.0,
        score_acabamento=5.0,
        score_potencial_reforma=5.0,
        confianca_imagem=5.0,
        imagem_aceitavel=True,
        problemas_visiveis=[],
        pontos_fortes=[],
        observacoes="ok",
    )


def _build_and_run_subgrafo(max_tentativas: int) -> dict:
    """
    Builds a fresh LangGraph graph using the real router functions
    (decidir_apos_extracao and decidir_proximo_imagens) from the module,
    but replaces the three node coroutines with lightweight mocks that
    track invocation counts.

    Returns a dict with keys 'descrever', 'extrair', 'refletor'.
    """
    counters = {"descrever": 0, "extrair": 0, "refletor": 0}

    async def fake_descrever_fotos(state: SubgrafoImagensState) -> Dict[str, Any]:
        counters["descrever"] += 1
        return {"descricao_foto": "desc", "tentativa": state.tentativa + 1}

    async def fake_extrair_analise(state: SubgrafoImagensState) -> Dict[str, Any]:
        counters["extrair"] += 1
        return {"analise": _make_analise()}

    async def fake_refletor_imagens(state: SubgrafoImagensState) -> Dict[str, Any]:
        counters["refletor"] += 1
        # Always return feedback=None → no further iteration
        return {"feedback": None}

    # Build a fresh graph wiring the real routing functions with fake nodes
    local_builder = StateGraph(SubgrafoImagensState)
    local_builder.add_node("descrever_fotos", fake_descrever_fotos)
    local_builder.add_node("extrair_analise", fake_extrair_analise)
    local_builder.add_node("refletor_imagens", fake_refletor_imagens)
    local_builder.set_entry_point("descrever_fotos")
    local_builder.add_edge("descrever_fotos", "extrair_analise")
    local_builder.add_conditional_edges(
        "extrair_analise",
        subgrafo_mod.decidir_apos_extracao,
        {"refletor_imagens": "refletor_imagens", "__end__": END},
    )
    local_builder.add_conditional_edges(
        "refletor_imagens",
        subgrafo_mod.decidir_proximo_imagens,
        {"descrever_fotos": "descrever_fotos", "__end__": END},
    )
    compiled = local_builder.compile()

    initial_state = SubgrafoImagensState(
        fotos_urls=["https://example.com/img.jpg"],
        max_tentativas=max_tentativas,
    )

    async def run():
        return await compiled.ainvoke(initial_state)

    asyncio.run(run())
    return counters


# ---------------------------------------------------------------------------
# Property 1: MAX_TENTATIVAS=0 nunca executa o refletor
# Validates: Requirements 1.2
# ---------------------------------------------------------------------------

@settings(max_examples=20)
@given(st.integers(min_value=0, max_value=3))
def test_property1_max_tentativas_zero_nunca_chama_refletor(max_tentativas: int):
    """
    **Validates: Requirements 1.2**

    Property 1: MAX_TENTATIVAS=0 nunca executa o refletor.
    Para max_tentativas=0 o contador de invocações de refletor_imagens deve ser 0.
    """
    if max_tentativas != 0:
        return  # este teste é específico para o caso 0

    counters = _build_and_run_subgrafo(max_tentativas)
    assert counters["refletor"] == 0, (
        f"refletor_imagens foi chamado {counters['refletor']} vez(es) com max_tentativas=0"
    )


# ---------------------------------------------------------------------------
# Property 2: Limite de iterações do refletor é respeitado
# Validates: Requirements 1.3, 1.6
# ---------------------------------------------------------------------------

@settings(max_examples=50)
@given(st.integers(min_value=0, max_value=3))
def test_property2_limite_iteracoes_refletor(max_tentativas: int):
    """
    **Validates: Requirements 1.3, 1.6**

    Property 2: Para qualquer max_tentativas em [0, 3], o número de invocações
    de refletor_imagens deve ser <= max_tentativas.
    """
    counters = _build_and_run_subgrafo(max_tentativas)
    assert counters["refletor"] <= max_tentativas, (
        f"refletor_imagens chamado {counters['refletor']} vez(es), mas max_tentativas={max_tentativas}"
    )


# ---------------------------------------------------------------------------
# Property 1+2 combinada: cobertura completa do intervalo
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(st.integers(min_value=0, max_value=3))
def test_property1_and_2_roteamento_subgrafo(max_tentativas: int):
    """
    **Validates: Requirements 1.2, 1.3, 1.6**

    Combina as duas propriedades:
    - Para max_tentativas=0: n_refletor == 0
    - Para max_tentativas>=1: n_refletor <= max_tentativas
    """
    counters = _build_and_run_subgrafo(max_tentativas)

    if max_tentativas == 0:
        assert counters["refletor"] == 0, (
            f"refletor_imagens foi chamado {counters['refletor']} vez(es) com max_tentativas=0"
        )
    else:
        assert counters["refletor"] <= max_tentativas, (
            f"refletor_imagens chamado {counters['refletor']} vez(es), mas max_tentativas={max_tentativas}"
        )
