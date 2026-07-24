import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.agente_potencial_flip import grafo_principal, EstadoGlobal
from shared.serialization import converter_numpy
from datetime import datetime
from phoenix.otel import register

load_dotenv()

tracer_provider = register(
  project_name="agente-imoveis",
  auto_instrument=True
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

MAX_CONCORRENCIA = int(os.getenv("MAX_CONCORRENCIA_FLIP", "2"))
SEMAFORO = asyncio.Semaphore(MAX_CONCORRENCIA)

CIDADE = "joinville"
MES_REF = os.getenv("MES_REF") or datetime.now().strftime("%Y-%m")
LIMITE_IMOVEIS = int(os.getenv("LIMITE_FLIP", "50"))
LIMITE_INFERIOR = int(os.getenv("LIMITE_INFERIOR_FLIP", "0"))
LIMITE_SUPERIOR = int(os.getenv("LIMITE_SUPERIOR_FLIP", str(LIMITE_INFERIOR + LIMITE_IMOVEIS)))

bairro_selecao = os.getenv("BAIRRO_SELECAO")

ARQUIVO_DADOS = (
    BASE_DIR / "dados" / CIDADE / f"{CIDADE}_imoveis_limpo_{MES_REF}.parquet"
)

RANGE_SUFIXO = f"_{LIMITE_INFERIOR}_{LIMITE_SUPERIOR}"

if bairro_selecao:
    ARQUIVO_RESULTADO = (
        BASE_DIR / "dados" / CIDADE / f"{CIDADE}_avaliacao_flip_{MES_REF}{RANGE_SUFIXO}_{bairro_selecao}.parquet"
    )
else:
    ARQUIVO_RESULTADO = (
        BASE_DIR / "dados" / CIDADE / f"{CIDADE}_avaliacao_flip_{MES_REF}{RANGE_SUFIXO}.parquet"
    )



def carregar_imoveis() -> pd.DataFrame:
    df = pd.read_parquet(ARQUIVO_DADOS)
    if os.getenv("SNAPSHOT_DATA"):
        snapshot_path = ARQUIVO_DADOS.with_suffix(".snapshot.parquet")
        if not snapshot_path.exists():
            df.to_parquet(snapshot_path)
        df = pd.read_parquet(snapshot_path)
    mask = df["tipo_imovel"].str.lower().isin(
        ["apartamento"]
    )
    df = df[mask].sort_values(by="preco_por_m2")
    if bairro_selecao:
        mask = df["bairro"].str.lower().str.contains(bairro_selecao)
        df = df[mask]
    df = df.iloc[LIMITE_INFERIOR:min(LIMITE_SUPERIOR, len(df))]
    logger.info(
        "Carregados %d imoveis de %s (filtrados de %d, range %d:%d)",
        len(df), CIDADE, mask.sum(), LIMITE_INFERIOR, LIMITE_INFERIOR + len(df),
    )
    return df.reset_index(drop=True)


def montar_estado(linha: pd.Series) -> EstadoGlobal:
    dados_imovel = converter_numpy({
        "metragem": linha.get("metragem", 0),
        "banheiros": linha.get("banheiros", 0),
        "vagas": linha.get("vagas", 0),
        "quartos": linha.get("quartos", 0),
        "valor_imovel": linha.get("valor_imovel", 0),
        "bairro": str(linha.get("bairro", "") or ""),
        "tipo_imovel": str(linha.get("tipo_imovel", "") or ""),
        "valor_predito": linha.get("valor_predito", 0),
        "p50_bairro": linha.get("p50_bairro", 0),
        "preco_por_m2": linha.get("preco_por_m2", 0),
    })

    fotos = linha.get("fotos")
    if isinstance(fotos, np.ndarray):
        fotos_urls = [str(u) for u in fotos if u]
    elif isinstance(fotos, list):
        fotos_urls = [str(u) for u in fotos if u]
    else:
        fotos_urls = []

    descricao = linha.get("descricao", "")
    descricao_texto = str(descricao) if pd.notna(descricao) else ""

    return EstadoGlobal(
        fotos_urls=fotos_urls,
        dados_imovel=dados_imovel,
        descricao_texto=descricao_texto,
    )


async def processar_um(linha: pd.Series, idx: int, total: int) -> dict:
    async with SEMAFORO:
        estado = montar_estado(linha)
        url = str(linha.get("url", ""))
        logger.info("[%d/%d] %s", idx + 1, total, url)

        try:
            resultado = await grafo_principal.ainvoke(estado)
            analise = resultado.get("analise_flip")

            if analise:
                return {
                    "url": url,
                    "score_potencial_flip": analise.score_potencial_flip,
                    "potencial_house_flip": analise.potencial_house_flip,
                    "justificativa": analise.justificativa_potencial,
                    "riscos": json.dumps(analise.riscos, ensure_ascii=False),
                    "recomendacoes": json.dumps(analise.recomendacoes, ensure_ascii=False),
                    "observacoes": analise.observacoes,
                    "erro": None,
                }
            return {
                "url": url,
                "score_potencial_flip": None,
                "potencial_house_flip": None,
                "justificativa": None,
                "riscos": "[]",
                "recomendacoes": "[]",
                "observacoes": "Analise vazia retornada",
                "erro": "Resultado sem analise_flip",
            }

        except Exception as e:
            logger.error("Falha no imovel %s: %s", url, e)
            return {
                "url": url,
                "score_potencial_flip": None,
                "potencial_house_flip": None,
                "justificativa": None,
                "riscos": "[]",
                "recomendacoes": "[]",
                "observacoes": None,
                "erro": str(e),
            }


async def main():
    df = carregar_imoveis()
    if df.empty:
        logger.warning("Nenhum imovel encontrado para avaliacao.")
        return

    tarefas = [processar_um(df.iloc[i], i, len(df)) for i in range(len(df))]
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)

    linhas = [r for r in resultados if isinstance(r, dict)]
    df_resultado = pd.DataFrame(linhas)
    df_resultado.to_parquet(ARQUIVO_RESULTADO, index=False)

    logger.info(
        "Processados %d/%d imoveis. Resultado salvo em %s",
        len(linhas), len(df), ARQUIVO_RESULTADO,
    )

    aprovados = df_resultado[
        df_resultado.get("potencial_house_flip") == "True"
    ]
    if not aprovados.empty:
        logger.info("IMOVEIS APROVADOS PARA FLIP (%d):", len(aprovados))
        for _, row in aprovados.iterrows():
            logger.info("  %s | score: %s", row["url"], row["score_potencial_flip"])
    else:
        logger.info("Nenhum imovel aprovado para flip nesta leva.")


if __name__ == "__main__":
    asyncio.run(main())
