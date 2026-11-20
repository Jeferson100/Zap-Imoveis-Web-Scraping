"""Testes das ferramentas ReAct e da retomada HITL (padrao do repo, sem rede)."""
import json
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from agente_potencial_flip import ferramentas_react as fr
from agente_potencial_flip import runner_react as rr


def _payload():
    return {
        "dados_imovel": {
            "metragem": 100,
            "valor_imovel": 200000,
            "valor_predito": 600000,
            "p50_bairro": 4800,
            "preco_por_m2": 2000,
        }
    }


def test_metricas_com_json_do_modelo_nao_perde_ancoras():
    """O JSON explicito complementa o payload; nao pode zerar o ARV (sem_ancora)."""
    fr.ESTADO_AGENTE.clear()
    fr.ESTADO_AGENTE["payload"] = _payload()

    saida = json.loads(fr.calcular_metricas_tool.invoke({
        "dados_imovel_json": json.dumps({"metragem": 100, "valor_imovel": 200000}),
    }))

    assert saida["arv_fonte"] == "blend_mediana_predicao"
    assert saida["arv_estimado"] == 540000
    assert saida["valor_m2_predicao"] == 6000.0


def test_metricas_json_nao_sobrescreve_ancoras_do_anuncio():
    fr.ESTADO_AGENTE.clear()
    fr.ESTADO_AGENTE["payload"] = _payload()

    saida = json.loads(fr.calcular_metricas_tool.invoke({
        "dados_imovel_json": json.dumps({
            "metragem": 100, "valor_imovel": 200000,
            "valor_predito": 1, "p50_bairro": 1,
        }),
    }))

    assert saida["valor_m2_predicao"] == 6000.0
    assert saida["arv_fonte"] == "blend_mediana_predicao"


class _Interrupt:
    def __init__(self, value):
        self.value = value


def test_decisoes_para_uma_por_tool_chamada_pendente():
    req = _Interrupt({
        "action_requests": [{"name": "registrar_decisao"}, {"name": "registrar_decisao"}],
        "review_configs": [{}, {}],
    })

    assert rr._decisoes_para(req, "approve") == [{"type": "approve"}] * 2


def test_decisoes_para_sem_metadados_usa_uma():
    assert rr._decisoes_para(_Interrupt({}), "reject") == [{"type": "reject"}]
    assert rr._decisoes_para(None, "approve") == [{"type": "approve"}]


class _Flip:
    """Dublê mínimo do AnalisePotencialFlip (model_copy do pydantic)."""
    def __init__(self, justificativa="", riscos=None, recomendacoes=None):
        self.potencial_house_flip = "True"
        self.score_potencial_flip = 8.0
        self.justificativa_potencial = justificativa
        self.riscos = list(riscos or [])
        self.recomendacoes = list(recomendacoes or [])
        self.observacoes = ""

    def model_copy(self, update=None):
        novo = _Flip(self.justificativa_potencial, self.riscos, self.recomendacoes)
        for k, v in (update or {}).items():
            setattr(novo, k, v)
        return novo


def _sessao(flip):
    return {
        "flip": flip,
        "imagem": None,
        "validacao": None,
        "historico": [],
        "pensamentos": [],
        "solicitacoes": [],
        "decisao_humana": "approve",
        "metricas_tool": {
            "arv_estimado": 540000, "roi_conservador": 0.2,
            "preco_maximo_para_regra": 400000, "passa_regra_15pct": True,
            "metragem": 100, "custo_reforma_estimado": 150000,
            "custo_reforma_por_m2": 1500,
        },
    }


def _graders():
    return {"passou": {"G1": False}, "ok": False, "erros": {"G3": ["justificativa vazia"]}}


def test_saida_preenche_justificativa_vazia():
    fr.ESTADO_AGENTE.clear()
    sessao = _sessao(_Flip(justificativa=""))

    saida = rr._saida(sessao, _graders())

    assert saida.justificativa_potencial.strip()
    assert "ARV" in saida.justificativa_potencial or "ROI" in saida.justificativa_potencial
    assert saida.riscos  # herdados do veredito deterministico


def test_saida_mantem_justificativa_do_modelo():
    fr.ESTADO_AGENTE.clear()
    sessao = _sessao(_Flip(justificativa="texto do modelo", riscos=["r1"]))

    saida = rr._saida(sessao, _graders())

    assert saida.justificativa_potencial == "texto do modelo"


def test_saida_trata_reticencias_como_vazia():
    fr.ESTADO_AGENTE.clear()
    sessao = _sessao(_Flip(justificativa="..."))

    saida = rr._saida(sessao, _graders())

    assert saida.justificativa_potencial != "..."
    assert len(saida.justificativa_potencial) > 20


def test_timeout_imovel_le_env(monkeypatch):
    monkeypatch.setenv("FLIP_LOOP_TIMEOUT_S", "600")
    assert rr._timeout_imovel() == 600.0
    monkeypatch.setenv("FLIP_LOOP_TIMEOUT_S", "abc")
    assert rr._timeout_imovel() == 0.0
    monkeypatch.delenv("FLIP_LOOP_TIMEOUT_S", raising=False)
    assert rr._timeout_imovel() == 0.0


def test_saida_por_timeout_sintetiza_veredito():
    fr.ESTADO_AGENTE.clear()
    fr.ESTADO_AGENTE["payload"] = _payload()

    saida = rr._saida_por_timeout(600)

    assert saida.potencial_house_flip in ("True", "False")
    assert saida.graders["timeout_s"] == 600
    assert "timeout" in saida.justificativa_potencial.lower()


def test_saida_por_timeout_anexa_metricas_ao_graders():
    """O parquet do imovel que estourou o tempo nao pode sair sem arv_fonte."""
    fr.ESTADO_AGENTE.clear()
    fr.ESTADO_AGENTE["payload"] = _payload()

    saida = rr._saida_por_timeout(600)
    metricas = saida.graders["metricas_tool"]

    assert metricas["arv_fonte"] == "blend_mediana_predicao"
    assert metricas["valor_m2_blend"] > 0
    assert saida.graders["metricas_base"] == "bruto_sem_validacao"
