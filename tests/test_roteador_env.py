"""Env de fallback do roteador so vale para texto com schema."""

import pytest

from agente_potencial_flip.schemas import AnalisePotencialFlip
from roteador_llms.roteador_llms import LlmRouter


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
