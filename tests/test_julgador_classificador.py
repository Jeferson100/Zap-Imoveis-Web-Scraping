"""Testes offline do julgador com o classificador de fotos.

Não carrega ConvNeXt nem baixa imagem: `_prever_tarefa` é substituído por um
dublê e os arquivos são temporários.
"""

import asyncio
import importlib
import os
import sys

import numpy as np
import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import agente_avaliacao_imagens.julgador_classificador as jc
from agente_avaliacao_imagens.schemas import AnaliseImagens, SubgrafoImagensState

sub = importlib.import_module("agente_avaliacao_imagens.subgrafo_imagens")


# ---------------------------------------------------------------------------
# Conversão das probabilidades
# ---------------------------------------------------------------------------


def test_montar_analise_converte_classes_e_nota():
    analise = jc.montar_analise(
        np.array([0.1, 0.2, 0.3, 0.4]),
        np.array([0.7, 0.3]),
    )

    assert isinstance(analise, AnaliseImagens)
    assert analise.classe_conservacao == "precário"
    assert analise.score_conservacao == 3.3          # 0.1*10 + 0.2*6.7 + 0.3*3.3
    assert analise.score_acabamento == 3.3           # proxy
    assert analise.score_potencial_reforma == 6.7    # complemento
    assert analise.confianca_conservacao == 0.4
    assert analise.ambiente == "interna"
    assert analise.confianca_ambiente == 0.7
    assert analise.imagem_aceitavel is True


def test_montar_analise_melhor_estado():
    analise = jc.montar_analise(
        np.array([0.9, 0.05, 0.03, 0.02]),
        np.array([0.1, 0.9]),
    )

    assert analise.classe_conservacao == "bem conservado"
    assert analise.ambiente == "externa"
    assert analise.score_conservacao == 9.4
    assert analise.score_potencial_reforma == 0.6


def test_montar_analise_rejeita_formato_errado():
    with pytest.raises(ValueError):
        jc.montar_analise(np.array([0.5, 0.5]), np.array([0.5, 0.5]))


# ---------------------------------------------------------------------------
# Disponibilidade e fallback
# ---------------------------------------------------------------------------


def test_disponivel_falso_sem_checkpoints(monkeypatch):
    monkeypatch.setattr(jc, "_folds", lambda tarefa: [])
    assert jc.disponivel() is False


def test_julgar_foto_levanta_quando_indisponivel(monkeypatch):
    monkeypatch.setattr(jc, "_folds", lambda tarefa: [])
    with pytest.raises(jc.ClassificadorIndisponivel):
        jc.julgar_foto("https://example.com/x.jpg")


def test_julgar_fotos_sem_urls_devolve_fallback():
    analise = jc.julgar_fotos([])

    assert analise.imagem_aceitavel is False
    assert "Sem fotos" in analise.observacoes


def test_carregar_falha_rapido_sem_pesos(monkeypatch):
    """Sem fold*.pt o CI recebia nan 0-d e o float(np.dot(...)) estourava."""
    monkeypatch.setattr(jc, "_MODELOS", None)
    monkeypatch.setattr(jc, "_folds", lambda tarefa: [])

    with pytest.raises(jc.ClassificadorIndisponivel):
        jc._carregar()


def test_julgar_fotos_sem_checkpoints_devolve_fallback(monkeypatch, tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(jc, "_MODELOS", None)
    monkeypatch.setattr(jc, "_folds", lambda tarefa: [])

    analise = jc.julgar_fotos([str(p)])

    assert analise.imagem_aceitavel is False
    assert "ausentes" in analise.observacoes.lower()
    assert analise.score_conservacao == 0


def test_julgar_fotos_detalhado_sem_checkpoints_devolve_fallback(monkeypatch, tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")
    monkeypatch.setattr(jc, "_MODELOS", None)
    monkeypatch.setattr(jc, "_folds", lambda tarefa: [])

    resultado = jc.julgar_fotos_detalhado([str(p)])

    assert resultado["por_foto"] == []
    assert resultado["agregado"].imagem_aceitavel is False
    assert "ausentes" in resultado["agregado"].observacoes.lower()


def test_resumo_grupo_rejeita_formato_errado():
    with pytest.raises(ValueError):
        jc._resumo_grupo([np.array([0.5, 0.5])])


def test_julgar_fotos_media_e_voto_majoritario(monkeypatch, tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    c = tmp_path / "c.jpg"
    for p in (a, b, c):
        p.write_bytes(b"x")

    probs = {
        "a.jpg": (np.array([0.7, 0.2, 0.1, 0.0]), np.array([0.9, 0.1])),
        "b.jpg": (np.array([0.6, 0.3, 0.1, 0.0]), np.array([0.8, 0.2])),
        "c.jpg": (np.array([0.1, 0.2, 0.3, 0.4]), np.array([0.2, 0.8])),
    }

    def fake_prever(tarefa, caminho):
        pc, pa = probs[caminho.name]
        return pc if tarefa == "conservacao" else pa

    monkeypatch.setattr(jc, "_prever_tarefa", fake_prever)
    monkeypatch.setattr(jc, "disponivel", lambda: True)
    monkeypatch.setattr(jc, "CLASSIFICADOR_MAX_FOTOS", 3)

    analise = jc.julgar_fotos([str(a), str(b), str(c)])

    # ambiente: 2 votos interna vs 1 externa
    assert analise.ambiente == "interna"
    # conservação: média das três distribuições favorece "bem conservado"
    assert analise.classe_conservacao == "bem conservado"


def test_julgar_foto_tolera_falha_e_devolve_fallback(monkeypatch, tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")

    monkeypatch.setattr(jc, "disponivel", lambda: True)

    def explodir(*a, **k):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(jc, "_prever_tarefa", explodir)

    analise = jc.julgar_foto(str(p))

    assert analise.imagem_aceitavel is False
    assert "Falha no classificador" in analise.observacoes


# ---------------------------------------------------------------------------
# Nó do grafo e roteamento
# ---------------------------------------------------------------------------


def _estado(**kw) -> SubgrafoImagensState:
    return SubgrafoImagensState(
        fotos_urls=["https://example.com/foto.jpg"],
        descricao_foto="descricao qualquer",
        **kw,
    )


def test_rotear_entrada_classificador(monkeypatch):
    monkeypatch.setattr(sub, "JULGADOR", "classificador")
    monkeypatch.setattr(sub, "classificador_disponivel", lambda: True)
    assert sub.rotear_entrada(_estado()) == "julgar_classificador"


def test_rotear_entrada_cai_para_descricao_sem_checkpoints(monkeypatch):
    monkeypatch.setattr(sub, "JULGADOR", "classificador")
    monkeypatch.setattr(sub, "classificador_disponivel", lambda: False)
    assert sub.rotear_entrada(_estado()) == "descrever_fotos"


def test_rotear_entrada_modo_laya(monkeypatch):
    monkeypatch.setattr(sub, "JULGADOR", "laya")
    monkeypatch.setattr(sub, "classificador_disponivel", lambda: True)
    assert sub.rotear_entrada(_estado()) == "descrever_fotos"


def test_no_julgar_classificador_usa_o_modelo(monkeypatch):
    analise = jc.montar_analise(np.array([0.9, 0.05, 0.03, 0.02]), np.array([0.1, 0.9]))
    monkeypatch.setattr(sub, "julgar_fotos", lambda urls: analise)

    resultado = asyncio.run(sub.julgar_classificador(_estado()))

    assert resultado["analise"] is analise


def test_no_julgar_classificador_fallback_em_erro(monkeypatch):
    def explodir(urls):
        raise RuntimeError("boom")

    async def fake_extrair(state):
        return {"analise": jc._fallback("fallback llm")}

    monkeypatch.setattr(sub, "julgar_fotos", explodir)
    monkeypatch.setattr(sub, "extrair_analise", fake_extrair)

    resultado = asyncio.run(sub.julgar_classificador(_estado()))

    assert resultado["analise"].observacoes == "fallback llm"


def test_grafo_tem_caminho_do_classificador():
    grafo = sub.subgrafo_imagens.get_graph()
    arestas = {(a.source, a.target) for a in grafo.edges}

    assert "julgar_classificador" in grafo.nodes
    assert ("julgar_classificador", "__end__") in arestas


# ---------------------------------------------------------------------------
# Saida por foto (julgar_fotos_detalhado)
# ---------------------------------------------------------------------------


def test_detalhado_devolve_uma_entrada_por_foto(monkeypatch, tmp_path):
    a = tmp_path / "a.jpg"; a.write_bytes(b"x")
    b = tmp_path / "b.jpg"; b.write_bytes(b"x")

    probs = {
        "a.jpg": (np.array([0.9, 0.05, 0.03, 0.02]), np.array([0.1, 0.9])),   # bem, externa
        "b.jpg": (np.array([0.1, 0.2, 0.6, 0.1]), np.array([0.8, 0.2])),     # desgastado, interna
    }

    def fake_prever(tarefa, caminho):
        pc, pa = probs[caminho.name]
        return pc if tarefa == "conservacao" else pa

    monkeypatch.setattr(jc, "_prever_tarefa", fake_prever)
    monkeypatch.setattr(jc, "_carregar_foto", lambda url: __import__("pathlib").Path(url))
    monkeypatch.setattr(jc, "CLASSIFICADOR_MAX_FOTOS", 3)

    res = jc.julgar_fotos_detalhado([str(a), str(b)])

    assert len(res["por_foto"]) == 2
    assert res["por_foto"][0]["ambiente"] == "externa"
    assert res["por_foto"][0]["conservacao"] == "bem conservado"
    assert res["por_foto"][1]["ambiente"] == "interna"
    assert res["por_foto"][1]["conservacao"] == "desgastado"
    # agregado: ambiente por voto (1x1 -> empate fica com a primeira) e conservacao pela media
    assert isinstance(res["agregado"], AnaliseImagens)
    assert res["agregado"].ambiente in ("interna", "externa")


def test_detalhado_registra_erro_da_foto_sem_derrubar_as_outras(monkeypatch, tmp_path):
    a = tmp_path / "a.jpg"; a.write_bytes(b"x")

    def fake_carregar(url):
        if "ruim" in url:
            raise RuntimeError("download falhou")
        return a

    monkeypatch.setattr(jc, "_carregar_foto", fake_carregar)
    monkeypatch.setattr(jc, "_prever_tarefa", lambda t, c: np.array([0.25, 0.25, 0.25, 0.25]) if t == "conservacao" else np.array([0.5, 0.5]))
    monkeypatch.setattr(jc, "CLASSIFICADOR_MAX_FOTOS", 3)

    res = jc.julgar_fotos_detalhado(["u/ruim.jpg", "u/boa.jpg"])

    assert res["por_foto"][0]["erro"].startswith("RuntimeError")
    assert "conservacao" in res["por_foto"][1]
    assert res["agregado"].imagem_aceitavel is True


def test_detalhado_sem_fotos(monkeypatch):
    monkeypatch.setattr(jc, "CLASSIFICADOR_MAX_FOTOS", 3)
    res = jc.julgar_fotos_detalhado([])
    assert res["por_foto"] == []
    assert res["agregado"].imagem_aceitavel is False


def test_max_fotos_zero_avalia_todas(monkeypatch, tmp_path):
    """IMAGENS_CLASSIFICADOR_MAX_FOTOS=0 significa 'sem limite'."""
    caminhos = []
    for i in range(5):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"x")
        caminhos.append(str(p))

    monkeypatch.setattr(jc, "_prever_tarefa", lambda t, c: np.array([0.25, 0.25, 0.25, 0.25])
                        if t == "conservacao" else np.array([0.5, 0.5]))
    monkeypatch.setattr(jc, "_carregar_foto", lambda url: __import__("pathlib").Path(url))
    monkeypatch.setattr(jc, "CLASSIFICADOR_MAX_FOTOS", 0)

    res = jc.julgar_fotos_detalhado(caminhos)

    assert len(res["por_foto"]) == 5


def test_agregado_separa_conservacao_por_ambiente(monkeypatch, tmp_path):
    """2 fotos internas + 1 externa: notas separadas e contagem por ambiente."""
    caminhos = []
    for nome in ("a.jpg", "b.jpg", "c.jpg"):
        p = tmp_path / nome
        p.write_bytes(b"x")
        caminhos.append(str(p))

    probs = {
        "a.jpg": (np.array([0.90, 0.05, 0.03, 0.02]), np.array([0.90, 0.10])),  # bem, interna
        "b.jpg": (np.array([0.10, 0.20, 0.60, 0.10]), np.array([0.80, 0.20])),  # desgastado, interna
        "c.jpg": (np.array([0.05, 0.70, 0.20, 0.05]), np.array([0.10, 0.90])),  # leve, externa
    }

    def fake_prever(tarefa, caminho):
        pc, pa = probs[caminho.name]
        return pc if tarefa == "conservacao" else pa

    monkeypatch.setattr(jc, "_prever_tarefa", fake_prever)
    monkeypatch.setattr(jc, "_carregar_foto", lambda url: __import__("pathlib").Path(url))
    monkeypatch.setenv("IMAGENS_CLASSIFICADOR_MAX_FOTOS", "0")

    a = jc.julgar_fotos_detalhado(caminhos)["agregado"]

    assert a.fotos_por_ambiente == {"interna": 2, "externa": 1}
    # interna: media de [0.90,0.05,0.03,0.02] e [0.10,0.20,0.60,0.10]
    assert a.score_conservacao_interna == 6.9
    assert a.classe_conservacao_interna == "bem conservado"   # 0.50 no argmax
    # externa: uma foto so
    assert a.score_conservacao_externa == 5.8  # round(5.85, 1) cai para 5.8 em float
    assert a.classe_conservacao_externa == "desgaste leve"
    # global continua sendo a media das tres
    assert a.score_conservacao == 6.5
    assert a.score_acabamento == a.score_conservacao
    assert a.score_potencial_reforma == 3.5


def test_sem_fotos_de_um_ambiente_fica_none(monkeypatch, tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(b"x")

    monkeypatch.setattr(jc, "_prever_tarefa", lambda t, c: np.array([0.7, 0.2, 0.05, 0.05])
                        if t == "conservacao" else np.array([0.9, 0.1]))
    monkeypatch.setattr(jc, "_carregar_foto", lambda url: __import__("pathlib").Path(url))
    monkeypatch.setenv("IMAGENS_CLASSIFICADOR_MAX_FOTOS", "0")

    a = jc.julgar_foto(str(p))

    assert a.ambiente == "interna"
    assert a.fotos_por_ambiente == {"interna": 1, "externa": 0}
    assert a.score_conservacao_interna is not None
    assert a.score_conservacao_externa is None


def test_resumo_tem_cinco_chaves_e_grupos(monkeypatch, tmp_path):
    caminhos = []
    for nome in ("a.jpg", "b.jpg", "c.jpg"):
        p = tmp_path / nome
        p.write_bytes(b"x")
        caminhos.append(str(p))

    probs = {
        "a.jpg": (np.array([0.90, 0.05, 0.03, 0.02]), np.array([0.90, 0.10])),
        "b.jpg": (np.array([0.10, 0.20, 0.60, 0.10]), np.array([0.80, 0.20])),
        "c.jpg": (np.array([0.05, 0.70, 0.20, 0.05]), np.array([0.10, 0.90])),
    }

    monkeypatch.setattr(jc, "_prever_tarefa",
                        lambda t, c: probs[c.name][0] if t == "conservacao" else probs[c.name][1])
    monkeypatch.setattr(jc, "_carregar_foto", lambda url: __import__("pathlib").Path(url))
    monkeypatch.setenv("IMAGENS_CLASSIFICADOR_MAX_FOTOS", "0")

    r = jc.julgar_fotos_detalhado(caminhos)["agregado"].resumo()

    assert set(r) == {"conservacao", "nota", "confianca", "interna", "externa"}
    assert r["conservacao"] == "bem conservado"
    assert r["nota"] == 6.5
    assert r["interna"] == {"nota": 6.9, "conservacao": "bem conservado", "fotos": 2}
    assert r["externa"] == {"nota": 5.8, "conservacao": "desgaste leve", "fotos": 1}
