"""Testes do Loop explicito do flip (Loop 1 + Loop 2).

Padrao `asyncio.run` (sem pytest-asyncio, ausente no pyproject). Nenhum teste
toca rede: `_MODELO_CACHE` e as tools sao substituidos por dublês.
"""
import asyncio
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from agente_potencial_flip import langgraph_flip
from agente_potencial_flip.langgraph_flip import (
    avaliar_imovel_flip_loop,
    prompt_veredito,
    verificar_veredito,
)
from agente_potencial_flip.tools_flip import calcular_metricas_flip


# --------------------------------------------------------------- dublês
class _Msg:
    def __init__(self, content: str):
        self.content = content


class _Pensar:
    """Modelo de texto da fase de pensamento (sem structured output)."""

    def __init__(self):
        self.chamadas = 0

    async def ainvoke(self, msgs, config=None, **k):
        self.chamadas += 1
        return _Msg("vou executar esta fase")


class _Veredito:
    """Modelo de veredito: devolve a resposta configurada por tentativa."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0
        self.prompts = []

    async def ainvoke(self, msgs, config=None, **k):
        self.chamadas += 1
        self.prompts.append(str(msgs[-1][1]) if isinstance(msgs[-1], tuple) else "")
        r = self.respostas[min(self.chamadas - 1, len(self.respostas) - 1)]
        if isinstance(r, BaseException):
            raise r
        return r


class _Fotos:
    """Dublê da tool async de visão (a tool real exige rede + imagens)."""

    def __init__(self):
        self.urls = None

    async def ainvoke(self, args, config=None, **k):
        self.urls = args["fotos_urls"]
        return "Sala reformada, banheiro antigo, sem infiltracao."


def _cache(pensar=None, veredito=None):
    if veredito is not None:
        langgraph_flip._MODELO_CACHE["veredito"] = veredito
    if pensar is not None:
        langgraph_flip._MODELO_CACHE["pensar"] = pensar


def _metricas_aprovadas():
    # 600k * 0.90 - 200k - 150k(reforma) = 190k -> roi 0.95
    return calcular_metricas_flip(
        {"valor_imovel": 200000, "metragem": 100,
         "valor_predito": 600000, "p50_bairro": 4800}
    )


def _metricas_reprovadas():
    # 450k - 480k - 150k = -180k -> roi -0.375
    return calcular_metricas_flip(
        {"valor_imovel": 480000, "metragem": 100,
         "valor_predito": 500000, "p50_bairro": 4800}
    )


def _veredito_ok(m, **over):
    v = {
        "score_potencial_flip": 7.5,
        "potencial_house_flip": "True",
        "justificativa_potencial": f"{langgraph_flip._carimbo(m)} compra boa.",
        "riscos": ["reforma eletrica"],
        "recomendacoes": ["orcamento com engenheiro"],
        "observacoes": "",
    }
    v.update(over)
    return v


# ----------------------------------------------------------------- testes
def test_loop_aprovado_sem_fotos(monkeypatch):
    m = _metricas_aprovadas()
    veredito = _Veredito([_veredito_ok(m)])
    _cache(_Pensar(), veredito)

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800}},
        thread_id="t-aprovado",
    ))

    assert out["potencial_house_flip"] == "True"
    assert out["metricas_flip"]["passa_regra_15pct"] is True
    assert out["verificacao"] == "aprovada"
    assert out["trilho_loop"]["tentativas_veredito"] == 1
    assert out["erro"] == ""
    # carimbo de auditoria NAO vaza para a saida
    assert "valor_imovel=" not in out["justificativa_potencial"]
    # 3 fases registraram pensamento
    fases = [e["fase"] for e in out["trilho_loop"]["fases"] if e["tipo"] == "thought"]
    assert fases == ["visao", "dados", "veredito"]


def test_loop_com_fotos_usa_relatorio_visual(monkeypatch):
    m = _metricas_aprovadas()
    fotos = _Fotos()
    monkeypatch.setattr(langgraph_flip, "descrever_fotos_tool", fotos)
    _cache(_Pensar(), _Veredito([_veredito_ok(m)]))

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800},
         "fotos_urls": ["http://f1", "http://f2"]},
        thread_id="t-fotos",
    ))

    assert fotos.urls == ["http://f1", "http://f2"]
    obs = [
        e for e in out["trilho_loop"]["fases"]
        if e["fase"] == "visao" and e["tipo"] == "observacao"
    ]
    assert "banheiro antigo" in obs[0]["conteudo"]


def test_carimbo_divergente_forca_retry(monkeypatch):
    """Carimbo com outro imovel = G2 reprova e o LLM reavalia 1x."""
    m = _metricas_aprovadas()
    errado = _veredito_ok(m, justificativa_potencial=(
        "[valor_imovel=999999.0|metragem=100.0m2|roi=0.95"
        "|reforma=150000.0] imovel do historico"
    ))
    veredito = _Veredito([errado, _veredito_ok(m)])
    _cache(_Pensar(), veredito)

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800}},
        thread_id="t-retry-carimbo",
    ))

    assert veredito.chamadas == 2
    assert out["verificacao"] == "aprovada"
    assert out["trilho_loop"]["tentativas_veredito"] == 2
    assert len(out["trilho_loop"]["gradores"]) == 2
    assert out["trilho_loop"]["gradores"][0]["aprovado"] is False
    # o retry precisa carregar o feedback do grader no prompt
    assert "FEEDBACK_DO_GRADER" in veredito.prompts[1]


def test_flip_true_sem_riscos_forca_retry(monkeypatch):
    m = _metricas_aprovadas()
    sem_risco = _veredito_ok(m, riscos=[])
    veredito = _Veredito([sem_risco, _veredito_ok(m)])
    _cache(_Pensar(), veredito)

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800}},
        thread_id="t-retry-riscos",
    ))

    assert veredito.chamadas == 2
    assert "riscos" in out["trilho_loop"]["gradores"][0]["feedback"]
    assert out["verificacao"] == "aprovada"


def test_trava_15pct_sobrescreve_veredito(monkeypatch):
    """LLM diz 'True' com ROI reprovado: G1 trava a saida mesmo aprovada no G2."""
    m = _metricas_reprovadas()
    assert m["passa_regra_15pct"] is False
    _cache(_Pensar(), _Veredito([_veredito_ok(m, score_potencial_flip=8.0)]))

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 480000, "metragem": 100,
                          "valor_predito": 500000, "p50_bairro": 4800}},
        thread_id="t-trava",
    ))

    assert out["potencial_house_flip"] == "False"
    assert "Trava regra 15%" in out["observacoes"]
    assert out["metricas_flip"]["roi_conservador"] == -0.375
    assert out["verificacao"] == "aprovada"  # o veredito em si passou no G2


def test_score_fora_do_range_e_clampado_no_fim(monkeypatch):
    m = _metricas_aprovadas()
    ruim = _veredito_ok(m, potencial_house_flip="False", score_potencial_flip=12,
                        riscos=[], recomendacoes=[])
    veredito = _Veredito([ruim, ruim])
    _cache(_Pensar(), veredito)

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800}},
        thread_id="t-score",
    ))

    assert veredito.chamadas == 2
    assert out["verificacao"] == "falhou_apos_retries_com_trava"
    assert out["score_potencial_flip"] == 10.0
    assert "score corrigido p/ [0,10]" in out["observacoes"]
    assert out["trilho_loop"]["gradores"][-1]["tentativa"] == "final"


def test_fallback_em_erro_tecnico(monkeypatch):
    _cache(_Pensar(), _Veredito([TimeoutError("socket travado")]))

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100}},
        thread_id="t-fallback",
    ))

    assert out["potencial_house_flip"] == "False"
    assert out["score_potencial_flip"] == 0.0
    assert "sombra" in out["observacoes"]
    assert "socket travado" in out["erro"]
    assert "metricas_flip" in out


def test_grader_deterministico_unitario():
    m = _metricas_aprovadas()
    base = _veredito_ok(m)

    ok, fb = verificar_veredito(base, m)
    assert ok is True and fb == ""

    ok, fb = verificar_veredito({**base, "justificativa_potencial": "otimo"}, m)
    assert ok is False and "Carimbo ausente" in fb

    ok, fb = verificar_veredito({**base, "potencial_house_flip": "True",
                                 "riscos": []}, m)
    assert ok is False and "riscos" in fb

    ok, fb = verificar_veredito({**base, "score_potencial_flip": -1}, m)
    assert ok is False and "fora de [0,10]" in fb

    ok, fb = verificar_veredito({**base, "score_potencial_flip": "abc"}, m)
    assert ok is False and "invalido" in fb


def test_dados_suspeitos_entram_no_prompt():
    m = calcular_metricas_flip(
        {"valor_imovel": 340000, "metragem": 60, "valor_predito": 879000}
    )
    assert m["discount_vs_predicao_pct"] > langgraph_flip.LIMITE_SUSPEITA_PCT
    obs = langgraph_flip._fase_dados({"metricas": m})
    assert any("DADOS_SUSPEITOS" in o for o in obs)

    estado = {
        "payload": {"dados_imovel": {"valor_imovel": 340000, "metragem": 60}},
        "metricas": {**m, "passa_regra_15pct": False},
        "relatorio_visual": "",
        "obs_dados": obs,
        "justificativa_feedback": "",
    }
    prompt = prompt_veredito(estado)
    assert "DADOS_SUSPEITOS" in prompt
    assert langgraph_flip._carimbo(m) in prompt


def test_thread_id_por_imovel(monkeypatch):
    vistos = []
    m = _metricas_aprovadas()

    async def _fake(estado, config=None, **k):
        vistos.append(config["configurable"]["thread_id"])
        return {
            "veredito": _veredito_ok(m),
            "aprovado": True,
            "tentativas_veredito": 0,
            "grader_eventos": [],
            "trilha_events": [],
            "erro": "",
        }

    monkeypatch.setattr(langgraph_flip.GRAFO, "ainvoke", _fake)
    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000}},
        thread_id="imovel-42",
    ))
    assert vistos == ["imovel-42"]
    assert out["verificacao"] == "aprovada"


def test_pensar_desligado_nao_chama_llm(monkeypatch):
    m = _metricas_aprovadas()
    pensar = _Pensar()
    _cache(pensar, _Veredito([_veredito_ok(m)]))
    monkeypatch.setattr(langgraph_flip, "PENSAR_ATIVO", False)

    out = asyncio.run(avaliar_imovel_flip_loop(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 600000, "p50_bairro": 4800}},
        thread_id="t-sem-pensar",
    ))

    assert pensar.chamadas == 0
    pensamentos = [e for e in out["trilho_loop"]["fases"] if e["tipo"] == "thought"]
    assert len(pensamentos) == 3  # rotulos fixos, sem LLM
    assert out["verificacao"] == "aprovada"
