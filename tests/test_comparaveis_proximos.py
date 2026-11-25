"""Testes dos comparaveis proximos (mesma rua / raio 300m) e integracao no ARV."""

import importlib.util
import json
import os
import sys

import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for p in (ROOT_DIR, SRC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import direto do modulo (evita disparar __init__ do pacote em ambiente offline).
_spec = importlib.util.spec_from_file_location(
    "comparaveis_proximos",
    os.path.join(SRC_DIR, "agente_potencial_flip", "comparaveis_proximos.py"),
)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


def _df_exemplo():
    linhas = [
        # Alvo na Rua Marari
        {"url": "u0", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 100, "valor_imovel": 450000, "preco_por_m2": 4500, "quartos": 3,
         "lat": -26.3000, "lng": -48.8500},
        # 5 vizinhos na mesma rua (mediana 7500/m2)
        {"url": "u1", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 95, "valor_imovel": 665000, "preco_por_m2": 7000, "quartos": 3,
         "lat": -26.3001, "lng": -48.8501},
        {"url": "u2", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 105, "valor_imovel": 756000, "preco_por_m2": 7200, "quartos": 3,
         "lat": -26.3002, "lng": -48.8502},
        {"url": "u3", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 100, "valor_imovel": 750000, "preco_por_m2": 7500, "quartos": 3,
         "lat": -26.3003, "lng": -48.8503},
        {"url": "u4", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 110, "valor_imovel": 858000, "preco_por_m2": 7800, "quartos": 3,
         "lat": -26.3004, "lng": -48.8504},
        {"url": "u5", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 120, "valor_imovel": 960000, "preco_por_m2": 8000, "quartos": 3,
         "lat": -26.3005, "lng": -48.8505},
        # Duplicata de u3 em outro portal (deve ser deduplicada)
        {"url": "u3_dup", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 100, "valor_imovel": 750000, "preco_por_m2": 7500, "quartos": 3,
         "lat": -26.3003, "lng": -48.8503},
        # Anuncio sujo (preco_por_m2 < 1500) -> deve ser descartado do pool
        {"url": "u_sujo", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "marari",
         "metragem": 100, "valor_imovel": 8000, "preco_por_m2": 80, "quartos": 3,
         "lat": -26.3001, "lng": -48.8501},
        # Imovel em rua diferente a ~100m (para testar fallback de raio)
        {"url": "u_outra", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "rua unica",
         "metragem": 100, "valor_imovel": 500000, "preco_por_m2": 5000, "quartos": 2,
         "lat": -26.3008, "lng": -48.8500},
        # Sem rua ('s/r')
        {"url": "u_sr", "tipo_imovel": "apartamento", "bairro": "atiradores", "rua": "s/r",
         "metragem": 100, "valor_imovel": 500000, "preco_por_m2": 5000, "quartos": 2,
         "lat": -26.3000, "lng": -48.8500},
    ]
    return pd.DataFrame(linhas)


def test_sem_rua_retorna_none():
    df = _df_exemplo()
    pool = cp.preparar_pool_comparaveis(df)
    alvo_sr = df[df["url"] == "u_sr"].iloc[0]
    assert cp.buscar_comparaveis_proximos(alvo_sr, pool) is None


def test_mesma_rua_exclui_self_duplicata_e_sujo():
    df = _df_exemplo()
    pool = cp.preparar_pool_comparaveis(df)
    alvo = df[df["url"] == "u0"].iloc[0]
    res = cp.buscar_comparaveis_proximos(alvo, pool)

    assert res is not None
    assert res["origem"] == "mesma_rua"
    assert res["rua_anuncio"] == "marari"
    assert res["n_comparaveis"] == 5
    assert res["p50_m2_proximos"] == 7500.0
    assert res["desconto_vs_proximos_pct"] == 40.0
    assert len(res["exemplos_proximos"]) == 5


def test_fallback_raio_quando_rua_tem_poucos():
    df = _df_exemplo()
    pool = cp.preparar_pool_comparaveis(df)
    alvo = df[df["url"] == "u_outra"].iloc[0]
    res = cp.buscar_comparaveis_proximos(alvo, pool, min_rua=3, raio_m=300.0)

    assert res is not None
    assert res["origem"] == "raio_300m"
    assert res["n_comparaveis"] >= 5
    assert res["p50_m2_proximos"] > 0


def test_calcular_metricas_usa_p50_proximos_no_arv_quando_n_ge_5(monkeypatch):
    from agente_potencial_flip import ferramentas_react as fr

    fr.ESTADO_AGENTE.clear()
    fr.ESTADO_AGENTE["payload"] = {
        "dados_imovel": {
            "metragem": 100,
            "valor_imovel": 450000,
            "valor_predito": 600000,   # 6000/m2
            "p50_bairro": 10000,       # bairro 10000/m2 -> blend bairro = 8000/m2
            "preco_por_m2": 4500,
            "rua": "marari",
        },
        "comparaveis_proximos": {
            "origem": "mesma_rua",
            "rua_anuncio": "marari",
            "n_comparaveis": 11,
            "p25_m2_proximos": 7000.0,
            "p50_m2_proximos": 7500.0,  # blend prox = (6000+7500)/2 = 6750/m2
            "p75_m2_proximos": 8000.0,
            "desconto_vs_proximos_pct": 40.0,
            "exemplos_proximos": [],
        },
    }

    saida = json.loads(fr.calcular_metricas_tool.invoke({}))
    assert saida["valor_m2_blend"] == 6750.0
    assert saida["arv_estimado"] == 675000.0
    assert saida["comparaveis_proximos"]["usado_no_arv"] is True
    assert saida["comparaveis_proximos"]["p50_bairro_original"] == 10000

    # Com FLIP_ARV_USAR_PROXIMOS=0 mantem p50_bairro mas ainda envia o bloco de contexto
    monkeypatch.setenv("FLIP_ARV_USAR_PROXIMOS", "0")
    fr.ESTADO_AGENTE.pop("metricas_tool", None)
    saida_ctx = json.loads(fr.calcular_metricas_tool.invoke({}))
    assert saida_ctx["valor_m2_blend"] == 8000.0
    assert saida_ctx["comparaveis_proximos"]["usado_no_arv"] is False
