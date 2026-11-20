"""Env de fallback do roteador so vale para texto com schema."""

import pytest

from agente_potencial_flip.schemas import AnalisePotencialFlip
from roteador_llms.roteador_groq import RouterGroq
from roteador_llms.roteador_llms import LlmRouter
from roteador_llms.roteador_openai_nvidia import RouterOpenaiNvidia


def test_env_substitui_lista_nvidia(monkeypatch):
    monkeypatch.setenv(
        "ROTEADOR_MODELOS_TEXTO_NVIDIA", "modelo/a, modelo/b"
    )
    r = LlmRouter("oi", strutured_output=AnalisePotencialFlip)
    assert r.models["API_Nvidia"] == ["modelo/a", "modelo/b"]


def test_sem_env_mantem_catalogo(monkeypatch):
    monkeypatch.delenv("ROTEADOR_MODELOS_TEXTO_NVIDIA", raising=False)
    r = LlmRouter("oi", strutured_output=AnalisePotencialFlip)
    assert r.models["API_Nvidia"] is None  # resolvido pelo catalogo em llm_router()


def test_visao_nao_e_afetada(monkeypatch):
    monkeypatch.setenv("ROTEADOR_MODELOS_TEXTO_NVIDIA", "modelo/a")
    r = LlmRouter([{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
                  strutured_output=AnalisePotencialFlip)
    assert r.models["API_Nvidia"] is None


def test_router_groq_sem_chave_levanta_no_init_nao_no_import(monkeypatch):
    """Sem GROQ_API_KEY o modulo importa; o erro fica no __init__ (router pula)."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        RouterGroq("oi", "modelo/x", None)


def test_router_openai_nvidia_sem_chave_levanta_no_init(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
        RouterOpenaiNvidia("oi", "modelo/x", None)
