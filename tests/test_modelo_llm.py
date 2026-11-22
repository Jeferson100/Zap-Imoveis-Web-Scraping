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
    # Deterministico: nao deixa o .env (GOOGLE_API_KEY) anexar o Google aqui.
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/a, modelo/b")
    assert m.modelos_fallback() == ["modelo/a", "modelo/b"]

    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/c")
    assert m.modelos_fallback() == ["modelo/c"]


def test_separar_provedor():
    assert m.separar_provedor("google:gemini-2.5-flash") == ("google", "gemini-2.5-flash")
    assert m.separar_provedor("nvidia:modelo/x") == ("nvidia", "modelo/x")
    # sem prefixo reconhecido o id fica intacto (inclusive sufixo :free)
    assert m.separar_provedor("meta-llama/x:free") == ("nvidia", "meta-llama/x:free")


def test_google_entra_como_ultimo_fallback_com_chave(monkeypatch):
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/a, modelo/b")
    monkeypatch.setenv("GOOGLE_API_KEY", "chave-teste")
    monkeypatch.delenv("FLIP_GOOGLE_MODEL", raising=False)

    assert m.modelos_fallback() == ["modelo/a", "modelo/b", "google:gemini-2.5-flash"]


def test_google_nao_entra_sem_chave(monkeypatch):
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/a")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert m.modelos_fallback() == ["modelo/a"]


def test_google_explicito_nao_duplica(monkeypatch):
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.setenv("FLIP_MODEL_FALLBACKS", "modelo/a, google:gemini-2.5-pro")
    monkeypatch.setenv("GOOGLE_API_KEY", "chave-teste")

    assert m.modelos_fallback() == ["modelo/a", "google:gemini-2.5-pro"]


def test_modelo_google_usa_endpoint_e_chave_google(monkeypatch):
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.setenv("GOOGLE_API_KEY", "chave-google")
    monkeypatch.delenv("GOOGLE_BASE_URL", raising=False)

    modelo = m.criar_modelo_flip("google:gemini-2.5-pro")

    assert modelo.model_name == "gemini-2.5-pro"
    assert modelo.openai_api_base == m.BASE_URL_GOOGLE
    assert modelo.openai_api_key.get_secret_value() == "chave-google"


def test_modelo_sem_prefixo_continua_nvidia(monkeypatch):
    monkeypatch.setattr(m, "_carregar_env", lambda: None)
    monkeypatch.delenv("FLIP_BASE_URL", raising=False)

    modelo = m.criar_modelo_flip("nvidia/nemotron-3.5-bolt-e4b")

    assert modelo.model_name == "nvidia/nemotron-3.5-bolt-e4b"
    assert modelo.openai_api_base == m.BASE_URL_PADRAO


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
