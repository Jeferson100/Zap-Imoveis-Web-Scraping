"""Avaliacao de flip no CI com o agente ReAct (create_agent + 5 ferramentas).

Mesmo contrato de env/parquet/checkpoint do joinville_avaliacao_flip.py.
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
import sys

sys.path.insert(0, str(BASE_DIR))

from agente_potencial_flip.runner_react import avaliar_imovel_agente  # noqa: E402
from shared.serialization import converter_numpy  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ESTADO_AGENTE e global por modulo: concorrencia > 1 mistura imoveis.
MAX_CONCORRENCIA = 1

CIDADE = "joinville"
MES_REF = os.getenv("MES_REF") or datetime.now().strftime("%Y-%m")
LIMITE_INFERIOR = int(os.getenv("LIMITE_INFERIOR_FLIP", "0"))
LIMITE_SUPERIOR = int(os.getenv("LIMITE_SUPERIOR_FLIP", "100"))
BAIRRO = os.getenv("BAIRRO_SELECAO", "")
BAIRRO_SLUG = BAIRRO.replace(" ", "_") if BAIRRO else ""

ARQUIVO_DADOS = BASE_DIR / "dados" / CIDADE / f"{CIDADE}_imoveis_limpo_{MES_REF}.parquet"
ARQUIVO_RESULTADO = (
    BASE_DIR / "dados" / CIDADE
    / f"{CIDADE}_avaliacao_flip_{MES_REF}_{LIMITE_INFERIOR}_{LIMITE_SUPERIOR}_{BAIRRO_SLUG}.parquet"
)


def carregar_imoveis() -> pd.DataFrame:
    df = pd.read_parquet(ARQUIVO_DADOS)
    if os.getenv("SNAPSHOT_DATA"):
        snap = ARQUIVO_DADOS.with_suffix(".snapshot.parquet")
        if not snap.exists():
            df.to_parquet(snap)
        df = pd.read_parquet(snap)
    # Mesmo contrato do script original: filtrar -> ordenar por preco_por_m2 ->
    # fatiar por POSICAO (iloc). O indice do parquet e esparso (atiradores tem
    # indices 469, 727, 918...), entao filtrar por df.index selecionaria zero
    # imoveis com LIMITE_INFERIOR=0 / LIMITE_SUPERIOR=10.
    # Sanidade (mesma regra da selecao do notebook): sem isso a ordenacao por
    # preco_por_m2 comeca em R$ 0 / R$ 8.000 (locacao/anuncio sem preco).
    valor = pd.to_numeric(df["valor_imovel"], errors="coerce")
    ppm2 = pd.to_numeric(df["preco_por_m2"], errors="coerce")
    pred = pd.to_numeric(df["valor_predito"], errors="coerce")
    metr = pd.to_numeric(df["metragem"], errors="coerce")
    sano = (valor > 0) & (ppm2 >= 1500) & (pred > 0) & (metr >= 30)
    df = df[sano]
    df = df[df["tipo_imovel"].str.lower().isin(["apartamento"])]
    df = df.sort_values(by="preco_por_m2")
    if BAIRRO:
        df = df[df["bairro"].str.lower().str.contains(BAIRRO.strip().lower())]
    df = df.iloc[LIMITE_INFERIOR:min(LIMITE_SUPERIOR, len(df))]

    # Retomada: um batch interrompido (timeout de 360 min do workflow) nao deve
    # reavaliar o que o checkpoint ja tem -- e o rerun nao pode duplicar.
    feitas = urls_ja_avaliadas()
    if feitas:
        antes = len(df)
        df = df[~df["url"].astype(str).isin(feitas)]
        logger.info("Checkpoint: %d de %d imoveis ja avaliados; faltam %d",
                    antes - len(df), antes, len(df))
    return df


def urls_ja_avaliadas() -> set:
    """URLs presentes no checkpoint parcial (retomada de batch interrompido)."""
    if ARQUIVO_RESULTADO.exists():
        try:
            return set(
                pd.read_parquet(ARQUIVO_RESULTADO, columns=["url"])["url"].astype(str)
            )
        except Exception as exc:  # noqa: BLE001 - checkpoint ilegivel recomeca
            logger.warning("Checkpoint ilegivel (%s) - recomecando do zero.", exc)
    return set()


def salvar_checkpoint(saida: dict) -> None:
    # Descarta runs com falha/incompletos (sem decisao valida ou com erro) sem gravar arquivo extra.
    tem_decisao = (
        saida.get("score_potencial_flip") is not None
        and saida.get("potencial_house_flip") in ("True", "False")
        and not saida.get("erro")
        and saida.get("justificativa") not in (None, "", "flip indisponivel")
    )
    if not tem_decisao:
        logger.warning("Run sem decisao valida ignorado (nao salvo no parquet): %s", saida.get("url"))
        return

    linha = pd.DataFrame([saida])
    if ARQUIVO_RESULTADO.exists():
        try:
            linha = pd.concat([pd.read_parquet(ARQUIVO_RESULTADO), linha], ignore_index=True)
        except Exception:
            pass
    # Rerun/retry nao pode duplicar o mesmo anuncio no parquet.
    linha = linha.drop_duplicates(subset=["url"], keep="last")
    linha.to_parquet(ARQUIVO_RESULTADO, index=False)


def montar_payload(linha: pd.Series) -> dict:
    fotos = linha.get("fotos")
    urls = [str(u) for u in fotos if u] if isinstance(fotos, (np.ndarray, list)) else []
    return {
        "_id": str(linha.get("url", "")),
        "dados_imovel": converter_numpy({
            "metragem": linha.get("metragem", 0),
            "valor_imovel": linha.get("valor_imovel", 0),
            "valor_predito": linha.get("valor_predito", 0),
            "p50_bairro": linha.get("p50_bairro", 0),
            "preco_por_m2": linha.get("preco_por_m2", 0),
            "quartos": linha.get("quartos", 0),
            "banheiros": linha.get("banheiros", 0),
            "vagas": linha.get("vagas", 0),
            "bairro": str(linha.get("bairro", "") or ""),
            "tipo_imovel": str(linha.get("tipo_imovel", "") or ""),
        }),
        "fotos_urls": urls,
        "descricao_texto": str(linha.get("descricao", "") or ""),
    }


async def processar_um(linha: pd.Series, i: int, total: int) -> dict:
    url = str(linha.get("url", ""))
    logger.info("[%d/%d] %s", i + 1, total, url)
    try:
        saida = await avaliar_imovel_agente(montar_payload(linha), max_tentativas=2)
        metricas = saida.graders.get("metricas_tool") or {}
        erro = None
    except Exception as exc:  # noqa: BLE001
        import traceback
        logger.error("Falha no imovel %s: %s", url, exc)
        logger.error("traceback:\n%s", traceback.format_exc())
        saida, metricas, erro = None, {}, str(exc)

    registro = {
        "url": url,
        "score_potencial_flip": getattr(saida, "score_potencial_flip", None),
        "potencial_house_flip": getattr(saida, "potencial_house_flip", None),
        "justificativa": getattr(saida, "justificativa_potencial", None),
        "riscos": json.dumps(getattr(saida, "riscos", []), ensure_ascii=False),
        "recomendacoes": json.dumps(getattr(saida, "recomendacoes", []), ensure_ascii=False),
        "observacoes": getattr(saida, "observacoes", None),
        "valor_m2_blend": metricas.get("valor_m2_blend"),
        "arv_fonte": metricas.get("arv_fonte"),
        # Auditoria: sem estas colunas nao da para saber pelo parquet se o
        # veredito passou nos graders nem se a analise de imagem foi real.
        "aprovado_graders": getattr(saida, "aprovado_graders", None),
        "tentativas": getattr(saida, "tentativas", None),
        "ambiente_fotos": getattr(saida, "ambiente_fotos", None),
        "conservacao_fotos": getattr(saida, "conservacao_fotos", None),
        "metricas_base": metricas.get("base_dados"),
        "erro": erro,
    }
    salvar_checkpoint(registro)
    return registro


async def main() -> None:
    df = carregar_imoveis()
    if df.empty:
        logger.warning("Nenhum imovel encontrado")
        return
    registros = []
    for i in range(len(df)):
        registros.append(await processar_um(df.iloc[i], i, len(df)))
    logger.info("Processados %d/%d imoveis -> %s", len(registros), len(df), ARQUIVO_RESULTADO)


if __name__ == "__main__":
    asyncio.run(main())
