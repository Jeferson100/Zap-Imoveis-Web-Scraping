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
    # BLEND: (6000 + 4800) / 2 = 5400/m2 * 100 m2 (o antigo max dava 600000)
    assert m["arv_estimado"] == 540000
    assert m["arv_fonte"] == "blend_mediana_predicao"
    # 540k * 0.90 - 200k (compra) - 150k (reforma 1500/m2 * 100m2)
    assert m["custo_reforma_estimado"] == 150000.0
    assert m["lucro_projetado"] == 136000.0
    assert m["roi_conservador"] == 0.68
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
    # sem reforma: ARV blend 490000 * 0.90 - 380000 = 61000 -> roi 0.16
    # com reforma: 441000 - 380000 - 150000 = -89000 -> reprova
    assert m["lucro_projetado"] == -89000.0
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


def test_custo_reforma_lido_na_chamada(monkeypatch):
    """Override por env vale mesmo DEPOIS do import (o valor nao e congelado)."""
    from agente_potencial_flip import tools_flip

    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "2000")
    dados = {"valor_imovel": 200000, "metragem": 100, "valor_predito": 600000}
    m = tools_flip.calcular_metricas_flip(dados)
    assert tools_flip.custo_reforma_m2() == 2000.0
    assert m["custo_reforma_por_m2"] == 2000.0
    assert m["custo_reforma_estimado"] == 200000.0
    assert m["lucro_projetado"] == 600000 * 0.90 - 200000 - 200000


def test_custo_reforma_env_invalido_volta_ao_padrao(monkeypatch):
    from agente_potencial_flip.tools_flip import (
        CUSTO_REFORMA_PADRAO_M2,
        custo_reforma_m2,
    )

    for ruim in ("", "abc", "0", "-1500", "nan", "inf"):
        monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", ruim)
        assert custo_reforma_m2() == CUSTO_REFORMA_PADRAO_M2


def test_custo_reforma_argumento_explicito():
    """Cenario what-if sem tocar no ambiente."""
    dados = {"valor_imovel": 200000, "metragem": 100, "valor_predito": 600000}
    m = calcular_metricas_flip(dados, custo_m2=2500)
    assert m["custo_reforma_por_m2"] == 2500.0
    assert m["custo_reforma_estimado"] == 250000.0
    assert m["lucro_projetado"] == 600000 * 0.90 - 200000 - 250000


def test_explicar_metricas_tem_oito_passos(monkeypatch):
    from agente_potencial_flip.tools_flip import PASSOS_METRICAS, explicar_metricas

    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "1500")
    dados = {"valor_imovel": 800000, "metragem": 120,
             "valor_predito": 888000, "p50_bairro": 6900}
    det = explicar_metricas(dados)
    assert [o["passo"] for o in det["operacoes"]] == list(PASSOS_METRICAS)
    assert len(det["operacoes"]) == 8
    assert det["roi_conservador"] == calcular_metricas_flip(dados)["roi_conservador"]
    passo_regra = next(o for o in det["operacoes"] if o["passo"] == "passa_regra_15pct")
    assert det["passa_regra_15pct"] is passo_regra["resultado"]


def test_preco_maximo_para_regra_e_a_regua_de_negociacao(monkeypatch):
    """O teto de compra sai da tool: sem ele o modelo inventa o alvo (ja inventou)."""
    from agente_potencial_flip.tools_flip import ROI_MINIMO, explicar_metricas

    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "1500")
    dados = {"valor_imovel": 330000, "metragem": 46,
             "valor_predito": 331892.67, "p50_bairro": 6973.12}
    m = calcular_metricas_flip(dados)
    esperado = round((m["arv_estimado"] * 0.90 - m["custo_reforma_estimado"])
                     / (1 + ROI_MINIMO), 2)
    assert m["preco_maximo_para_regra"] == esperado
    assert m["preco_maximo_para_regra"] < dados["valor_imovel"]  # compra acima do teto
    assert m["passa_regra_15pct"] is False

    # comprar pelo teto fecha os 15% (com folga de 1 real para o arredondamento)
    no_teto = calcular_metricas_flip({**dados, "valor_imovel": esperado - 1})
    assert no_teto["passa_regra_15pct"] is True
    assert abs(no_teto["roi_conservador"] - ROI_MINIMO) < 0.01

    det = explicar_metricas(dados)
    teto = next(o for o in det["operacoes"] if o["passo"] == "preco_maximo_para_regra")
    assert teto["resultado"] == esperado
    assert set(teto["entradas"]) == {"arv_estimado", "custo_reforma_estimado", "ROI_MINIMO"}


def test_compra_bem_abaixo_do_arv_aprova_flip(monkeypatch):
    """Sem um caso aprovado, o ramo 'True' do G4 nunca roda."""
    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "1500")
    m = calcular_metricas_flip({"valor_imovel": 165946.0, "metragem": 46,
                                "valor_predito": 331892.67, "p50_bairro": 6973.12})
    assert m["passa_regra_15pct"] is True
    assert m["roi_conservador"] > 0.15
    assert m["margem_vs_arv_pct"] > 45


def test_contexto_tem_comparativos_e_bairro_arredondado(monkeypatch):
    from agente_potencial_flip.tools_flip import CONTEXTO_METRICAS, explicar_metricas

    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "1500")
    dados = {"valor_imovel": 330000, "metragem": 46,
             "valor_predito": 331892.67, "p50_bairro": 6973.118279569892}
    det = explicar_metricas(dados)
    assert tuple(det["contexto"]) == CONTEXTO_METRICAS
    assert det["contexto"]["valor_m2_bairro"] == 6973.12
    assert det["contexto"]["discount_vs_bairro_pct"] == round(
        (6973.118279569892 - det["preco_por_m2"]) / 6973.118279569892 * 100, 2)
    assert det["contexto"]["margem_vs_arv_pct"] == round(
        (det["arv_estimado"] - 330000) / det["arv_estimado"] * 100, 2)


def test_explicar_metricas_mostra_passo_da_reforma(monkeypatch):
    from agente_potencial_flip.tools_flip import explicar_metricas

    monkeypatch.setenv("FLIP_CUSTO_REFORMA_M2", "1500")
    dados = {"valor_imovel": 800000, "metragem": 120,
             "valor_predito": 888000, "p50_bairro": 6900}
    det = explicar_metricas(dados)

    reforma = next(o for o in det["operacoes"] if o["passo"] == "custo_reforma_estimado")
    assert reforma["entradas"] == {"custo_reforma_por_m2": 1500.0, "metragem": 120.0}
    assert reforma["resultado"] == 180000.0
    assert "custo_reforma_por_m2 * metragem" in reforma["formula"]

    lucro = next(o for o in det["operacoes"] if o["passo"] == "lucro_projetado")
    assert lucro["entradas"]["custo_reforma_estimado"] == 180000.0
    esperado = det["arv_estimado"] * 0.90 - 800000 - 180000
    assert abs(lucro["resultado"] - esperado) < 0.02
