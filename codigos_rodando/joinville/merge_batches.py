import logging
import os
from pathlib import Path
from datetime import datetime

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PASTA_DADOS = BASE_DIR / "dados" / "joinville"

MES_REF = os.getenv("MES_REF") or datetime.now().strftime("%Y-%m")

BAIRRO = os.getenv("BAIRRO_SELECAO") or "atiradores"
bairro_slug = BAIRRO.replace(" ", "_")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
)

logger = logging.getLogger(__name__)


def mes_anterior(mes_ref: str) -> str:
    """Calcula o mês anterior a partir de uma string 'YYYY-MM'."""
    ano, mes = int(mes_ref[:4]), int(mes_ref[5:7])
    if mes == 1:
        return f"{ano - 1}-12"
    return f"{ano}-{mes - 1:02d}"


def main():
    pattern = f"joinville_avaliacao_flip_*_*_{bairro_slug}.parquet"
    arquivos = sorted(PASTA_DADOS.glob(pattern))

    if not arquivos:
        logger.warning("Nenhum batch encontrado para bairro '%s' em %s", BAIRRO, PASTA_DADOS)
        return

    dfs = [pd.read_parquet(f) for f in arquivos]
    merged = pd.concat(dfs, ignore_index=True)
    merged = merged.drop_duplicates(subset=["url"]).reset_index(drop=True)

    def extrair_range(path):
        partes = path.stem.split("_")
        return int(partes[-3]), int(partes[-2])

    saida = PASTA_DADOS / f"avaliacao_flip_{MES_REF}_{bairro_slug}.parquet"

    merged.to_parquet(saida, index=False)

    # Apagar os dados do mês anterior do MESMO bairro, somente após salvar o atual
    mes_anterior_ref = mes_anterior(MES_REF)
    arquivo_anterior = PASTA_DADOS / f"avaliacao_flip_{mes_anterior_ref}_{bairro_slug}.parquet"

    if arquivo_anterior.exists():
        arquivo_anterior.unlink()
        logger.info("Dados do mês anterior apagados: %s", arquivo_anterior.name)
    else:
        logger.info("Nenhum arquivo do mês anterior (%s) para o bairro '%s'.", mes_anterior_ref, bairro_slug)

    for f in arquivos:
        f.unlink()

    logger.info(
        "Merge: %d linhas (%d batches) → %s. Batches deletados.",
        len(merged), len(arquivos), saida,
    )


if __name__ == "__main__":
    main()
