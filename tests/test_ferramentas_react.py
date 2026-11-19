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
