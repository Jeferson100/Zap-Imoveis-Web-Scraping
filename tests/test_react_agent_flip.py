"""Testes do ReAct flip isolado (sombra). Padrao asyncio.run + monkeypatch."""
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from agente_potencial_flip import react_agent_flip
from agente_potencial_flip.tools_flip import calcular_metricas_flip


def test_metricas_regra_15pct_aprovado():
    m = calcular_metricas_flip({
        "valor_imovel": 300000, "metragem": 100,
        "valor_predito": 500000, "p50_bairro": 4800,
    })
    assert m["preco_por_m2"] == 3000.0
    assert m["valor_m2_predicao"] == 5000.0
    assert m["arv_estimado"] == 500000
    assert m["roi_conservador"] == 0.5
    assert m["passa_regra_15pct"] is True


def test_metricas_regra_15pct_reprovado():
    m = calcular_metricas_flip({
        "valor_imovel": 480000, "metragem": 100,
        "valor_predito": 500000, "p50_bairro": 4800,
    })
    assert m["passa_regra_15pct"] is False


def test_metricas_sem_metragem_nao_quebra():
    m = calcular_metricas_flip({"valor_imovel": 300000})
    assert m["preco_por_m2"] == 0
    assert m["passa_regra_15pct"] is False


def test_mensagem_tem_payload_inline():
    msg = react_agent_flip.montar_mensagem({
        "dados_imovel": {"valor_imovel": 1},
        "descricao_texto": "x",
        "fotos_urls": ["http://f1"],
    })
    assert "DADOS_IMOVEL_JSON=" in msg and "FOTOS_URLS=" in msg
    assert "http://f1" in msg


def test_agente_nomeado():
    assert react_agent_flip.agente_react_flip.name == "flip-investidor"


def test_fallback_sombra_sob_timeout(monkeypatch):
    async def _boom(*a, **k):
        raise TimeoutError("socket travado")

    async def _nosleep(*a, **k):
        return None

    monkeypatch.setattr(react_agent_flip.agente_react_flip, "ainvoke", _boom)
    monkeypatch.setattr(react_agent_flip.asyncio, "sleep", _nosleep)
    out = asyncio.run(
        react_agent_flip.avaliar_imovel_react({"dados_imovel": {}})
    )
    assert out["potencial_house_flip"] == "False"
    assert out["score_potencial_flip"] == 0.0
    assert "sombra" in out["observacoes"]
