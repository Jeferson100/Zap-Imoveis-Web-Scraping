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
from agente_potencial_flip.tools_flip import (
    ajustar_saida_pela_regra,
    calcular_metricas_flip,
)


def test_metricas_regra_15pct_aprovado():
    m = calcular_metricas_flip({
        "valor_imovel": 200000, "metragem": 100,
        "valor_predito": 600000, "p50_bairro": 4800,
    })
    assert m["preco_por_m2"] == 2000.0
    assert m["valor_m2_predicao"] == 6000.0
    assert m["arv_estimado"] == 600000
    # 600k * 0.90 - 200k (compra) - 150k (reforma 1500/m2 * 100m2)
    assert m["custo_reforma_estimado"] == 150000.0
    assert m["lucro_projetado"] == 190000.0
    assert m["roi_conservador"] == 0.95
    assert m["passa_regra_15pct"] is True


def test_custo_reforma_1500_por_m2():
    m = calcular_metricas_flip({
        "valor_imovel": 200000, "metragem": 80, "valor_predito": 600000,
    })
    assert m["custo_reforma_por_m2"] == 1500.0
    assert m["custo_reforma_estimado"] == 120000.0
    assert m["lucro_projetado"] == 600000 * 0.90 - 200000 - 120000
    sem_area = calcular_metricas_flip({"valor_imovel": 200000})
    assert sem_area["custo_reforma_estimado"] == 0.0


def test_custo_reforma_reprova_imovel_que_passaria():
    """Reforma explicita derruba ROI de imovel que passava sem ela."""
    m = calcular_metricas_flip({
        "valor_imovel": 380000, "metragem": 100,
        "valor_predito": 500000, "p50_bairro": 4800,
    })
    # sem reforma: 450000 - 380000 = 70000 -> roi 0.18
    # com reforma: 450000 - 380000 - 150000 = -80000 -> reprova
    assert m["lucro_projetado"] == -80000.0
    assert m["passa_regra_15pct"] is False


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


def test_metricas_nan_valor_predito_cai_no_bairro():
    """valor_predito nulo NAO pode reprovar o imovel nem vazar NaN."""
    m = calcular_metricas_flip({
        "valor_imovel": 200000, "metragem": 100,
        "valor_predito": float("nan"), "p50_bairro": 4800,
    })
    assert m["valor_m2_predicao"] == 0
    assert m["arv_estimado"] == 480000  # 4800 * 100, benchmark do bairro
    # 480k * 0.90 - 200k - 150k (reforma) = 82k -> roi 0.41
    assert m["lucro_projetado"] == 82000.0
    assert m["roi_conservador"] == 0.41
    assert m["passa_regra_15pct"] is True


def test_nan_nao_vaza_para_json_estrito():
    import json

    m = calcular_metricas_flip({"valor_imovel": 300000, "metragem": float("nan")})
    assert m["metragem"] is None
    json.loads(json.dumps(m, allow_nan=False))


def test_trava_regra_15pct_sobrescreve_llm():
    saida = {
        "score_potencial_flip": 0.9,
        "potencial_house_flip": "True",
        "justificativa_potencial": "otimo",
        "riscos": [],
        "recomendacoes": [],
        "observacoes": "",
    }
    out = ajustar_saida_pela_regra(
        saida, {"passa_regra_15pct": False, "roi_conservador": 0.03}
    )
    assert out["potencial_house_flip"] == "False"
    assert "Trava regra 15%" in out["observacoes"]
    assert out["metricas_flip"]["roi_conservador"] == 0.03


def test_trava_regra_15pct_preserva_aprovado():
    saida = {"potencial_house_flip": "True", "score_potencial_flip": 0.7,
             "observacoes": "ok"}
    out = ajustar_saida_pela_regra(saida, {"passa_regra_15pct": True})
    assert out["potencial_house_flip"] == "True"
    assert out["observacoes"] == "ok"


def test_avaliar_imovel_trava_regra_no_resultado(monkeypatch):
    """LLM dizendo "True" com ROI reprovado NAO passa: a trava roda no fim."""

    async def _ok(*a, **k):
        return {"structured_response": {
            "score_potencial_flip": 0.9,
            "potencial_house_flip": "True",
            "justificativa_potencial": "otimo negocio",
            "riscos": [],
            "recomendacoes": [],
            "observacoes": "",
        }}

    monkeypatch.setattr(react_agent_flip.agente_react_flip, "ainvoke", _ok)
    out = asyncio.run(react_agent_flip.avaliar_imovel_react({
        "dados_imovel": {"valor_imovel": 480000, "metragem": 100,
                         "valor_predito": 500000},
    }))
    assert out["metricas_flip"]["passa_regra_15pct"] is False
    assert out["potencial_house_flip"] == "False"
    assert "Trava regra 15%" in out["observacoes"]


def test_mensagem_tem_metricas_inline():
    msg = react_agent_flip.montar_mensagem({"dados_imovel": {"valor_imovel": 1}})
    assert "METRICAS_JSON=" in msg and "REGRA_15PCT:" in msg


def test_thread_id_por_tentativa(monkeypatch):
    vistos = []

    async def _boom(*a, config=None, **k):
        vistos.append(config["configurable"]["thread_id"])
        raise TimeoutError("socket travado")

    async def _nosleep(*a, **k):
        return None

    monkeypatch.setattr(react_agent_flip.agente_react_flip, "ainvoke", _boom)
    monkeypatch.setattr(react_agent_flip.asyncio, "sleep", _nosleep)
    asyncio.run(react_agent_flip.avaliar_imovel_react({"dados_imovel": {}},
                                                     thread_id="flip-x"))
    assert vistos == ["flip-x-t1", "flip-x-t2"]


def test_fallback_leva_metricas(monkeypatch):
    async def _boom(*a, **k):
        raise TimeoutError("socket travado")

    async def _nosleep(*a, **k):
        return None

    monkeypatch.setattr(react_agent_flip.agente_react_flip, "ainvoke", _boom)
    monkeypatch.setattr(react_agent_flip.asyncio, "sleep", _nosleep)
    out = asyncio.run(react_agent_flip.avaliar_imovel_react(
        {"dados_imovel": {"valor_imovel": 200000, "metragem": 100,
                          "valor_predito": 500000}}
    ))
    assert out["metricas_flip"]["passa_regra_15pct"] is True
    assert "erro" in out


def test_middleware_exige_pensamento():
    from langchain_core.messages import AIMessage, HumanMessage

    from agente_potencial_flip.trace_flip import _pensou_antes

    sem = [HumanMessage("avalia"), AIMessage("", tool_calls=[
        {"name": "task", "args": {}, "id": "1"}])]
    assert _pensou_antes(sem) is False

    com = [HumanMessage("avalia"), AIMessage("", tool_calls=[
        {"name": "think_tool", "args": {}, "id": "0"},
        {"name": "task", "args": {}, "id": "1"}])]
    assert _pensou_antes(com) is True


def test_trilha_coleta_pensamento():
    from agente_potencial_flip.trace_flip import TrilhaFlip

    class _Msg:
        content = "vou ver as fotos"
        additional_kwargs = {"reasoning_content": "primeiro foto, depois dados"}
        tool_calls = [
            {"name": "think_tool", "args": {
                "pensamento": "preciso da visao", "proxima_acao": "task:fotografo"}},
            {"name": "task", "args": {"subagent_type": "fotografo"}},
        ]

    class _Gen:
        message = _Msg()

    class _Resp:
        generations = [[_Gen()]]

    t = TrilhaFlip()
    t.on_chat_model_end(_Resp())
    pensamentos = t.pensamentos()
    assert pensamentos[0]["proxima_acao"] == "task:fotografo"
    assert t.eventos[0]["raciocinio"] == "primeiro foto, depois dados"


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

def test_modelo_flip_default_openrouter():
    from agente_potencial_flip.modelo_llm import BASE_URL_PADRAO, criar_modelo_flip

    m = criar_modelo_flip()
    base = str(getattr(m, 'openai_api_base', '') or getattr(m, 'base_url', ''))
    assert BASE_URL_PADRAO in base
    assert m.model_name


def test_erro_permanente_classificacao():
    assert react_agent_flip.erro_permanente(Exception('[410] Gone: end of life'))
    assert react_agent_flip.erro_permanente(Exception('404 model not found'))
    assert not react_agent_flip.erro_permanente(TimeoutError('socket travado'))
    assert not react_agent_flip.erro_permanente(Exception('503 Service Unavailable'))


def test_sem_retry_em_erro_permanente(monkeypatch):
    chamadas = {'n': 0}

    async def _boom(*a, **k):
        chamadas['n'] += 1
        raise Exception('[410] Gone: model reached its end of life')

    async def _nosleep(*a, **k):
        return None

    monkeypatch.setattr(react_agent_flip.agente_react_flip, 'ainvoke', _boom)
    monkeypatch.setattr(react_agent_flip.asyncio, 'sleep', _nosleep)
    out = asyncio.run(react_agent_flip.avaliar_imovel_react({'dados_imovel': {}}))
    assert chamadas['n'] == 1
    assert out['potencial_house_flip'] == 'False'
