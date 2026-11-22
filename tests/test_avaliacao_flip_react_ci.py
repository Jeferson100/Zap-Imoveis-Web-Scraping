"""Retomada do entrypoint do CI: checkpoint nao reavalia nem duplica."""

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for p in (REPO, REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

_sp = importlib.util.spec_from_file_location(
    "flip_react_ci",
    REPO / "codigos_rodando" / "joinville" / "joinville_avaliacao_flip_react.py",
)
ep = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(ep)


def _dados() -> pd.DataFrame:
    return pd.DataFrame([
        {"url": "u1", "valor_imovel": 300_000, "preco_por_m2": 3000,
         "valor_predito": 400_000, "metragem": 100,
         "tipo_imovel": "apartamento", "bairro": "Atiradores"},
        {"url": "u2", "valor_imovel": 320_000, "preco_por_m2": 3200,
         "valor_predito": 420_000, "metragem": 100,
         "tipo_imovel": "apartamento", "bairro": "Atiradores"},
    ])


def _preparar(tmp_path, monkeypatch):
    monkeypatch.delenv("SNAPSHOT_DATA", raising=False)
    arquivo = tmp_path / "dados.parquet"
    _dados().to_parquet(arquivo, index=False)
    resultado = tmp_path / "resultado.parquet"
    monkeypatch.setattr(ep, "ARQUIVO_DADOS", arquivo)
    monkeypatch.setattr(ep, "ARQUIVO_RESULTADO", resultado)
    monkeypatch.setattr(ep, "BAIRRO", "atiradores")
    monkeypatch.setattr(ep, "LIMITE_INFERIOR", 0)
    monkeypatch.setattr(ep, "LIMITE_SUPERIOR", 100)
    return resultado


def test_carregar_imoveis_pula_urls_do_checkpoint(tmp_path, monkeypatch):
    resultado = _preparar(tmp_path, monkeypatch)
    pd.DataFrame([{"url": "u1"}]).to_parquet(resultado, index=False)

    df = ep.carregar_imoveis()

    assert list(df["url"]) == ["u2"]


def test_carregar_imoveis_sem_checkpoint_traz_tudo(tmp_path, monkeypatch):
    _preparar(tmp_path, monkeypatch)

    df = ep.carregar_imoveis()

    assert list(df["url"]) == ["u1", "u2"]


def test_salvar_checkpoint_nao_duplica_url(tmp_path, monkeypatch):
    resultado = _preparar(tmp_path, monkeypatch)

    ep.salvar_checkpoint({"url": "u1", "score_potencial_flip": 1.0})
    ep.salvar_checkpoint({"url": "u1", "score_potencial_flip": 2.0})
    ep.salvar_checkpoint({"url": "u2", "score_potencial_flip": 3.0})

    df = pd.read_parquet(resultado)

    assert list(df["url"]) == ["u1", "u2"]
    assert float(df.loc[df["url"] == "u1", "score_potencial_flip"].iloc[0]) == 2.0


def test_urls_ja_avaliadas_checkpoint_ilegivel(tmp_path, monkeypatch):
    resultado = _preparar(tmp_path, monkeypatch)
    resultado.write_bytes(b"nao e parquet")

    assert ep.urls_ja_avaliadas() == set()
