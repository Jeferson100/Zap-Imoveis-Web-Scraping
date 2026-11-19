"""Fallback do modelo principal (with_fallbacks)."""

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

import agente_potencial_flip.modelo_llm as m


class ModeloFalso:
    def __init__(self, nome, falhar=False):
        self.nome = nome
        self.falhar = falhar
        self.chamado = 0

    def invoke(self, mensagens, **kwargs):
        self.chamado += 1
        if self.falhar:
            raise APIStatusError(
                "429",
                response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
                body=None,
            )
        return f"resposta de {self.nome}"


class ChainFalso:
    """Simula RunnableWithFallbacks: tenta o principal e depois os fallbacks."""

    def __init__(self, principal, fallbacks, excecoes):
        self.pecas = [principal, *fallbacks]
        self.excecoes = excecoes

    def invoke(self, mensagens, **kwargs):
        ultimo = None
        for peca in self.pecas:
            try:
                return peca.invoke(mensagens, **kwargs)
            except self.excecoes as exc:
                ultimo = exc
        raise ultimo


def test_fallback_acionado_em_429(monkeypatch):
    principal = ModeloFalso("principal", falhar=True)
    fallback = ModeloFalso("fallback")
    feitos = [principal, fallback]
    monkeypatch.setattr(m, "criar_modelo_flip", lambda model=None: feitos.pop(0))
    monkeypatch.setattr(m, "modelos_fallback", lambda: ["fallback"])

    def _with_fallbacks(fallbacks, *, exceptions_to_handle):
        return ChainFalso(principal, fallbacks, exceptions_to_handle)

    principal.with_fallbacks = _with_fallbacks
    chain = m.criar_modelo_flip_com_fallbacks()
    assert chain.invoke("oi") == "resposta de fallback"
    assert principal.chamado == 1
    assert fallback.chamado == 1


def test_env_lida_por_chamada(monkeypatch):
    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/a, modelo/b")
    assert m.modelos_fallback() == ["modelo/a", "modelo/b"]

    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/c")
    assert m.modelos_fallback() == ["modelo/c"]


def test_excecoes_explicitas(monkeypatch):
    capturado = {}

    class Fake:
        def with_fallbacks(self, fallbacks, *, exceptions_to_handle):
            capturado["ex"] = exceptions_to_handle
            return self

    monkeypatch.setattr(m, "criar_modelo_flip", lambda model=None: Fake())
    monkeypatch.setattr(m, "modelos_fallback", lambda: ["x"])
    m.criar_modelo_flip_com_fallbacks()

    assert set(capturado["ex"]) == {APIStatusError, APITimeoutError, APIConnectionError}
