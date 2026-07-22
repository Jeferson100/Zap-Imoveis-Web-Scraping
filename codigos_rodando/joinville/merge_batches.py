import logging
import os
from pathlib import Path
from datetime import datetime

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PASTA_DADOS = BASE_DIR / "dados" / "joinville"

MES_REF = os.getenv("MES_REF") or datetime.now().strftime("%Y-%m")

BAIRRO = os.getenv("BAIRRO_SELECAO") or "atiradores"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
)

logger = logging.getLogger(__name__)


def main():
    pattern = f"joinville_avaliacao_flip_*_*_{BAIRRO}.parquet"
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


    saida = PASTA_DADOS / f"avaliacao_flip_{MES_REF}_{BAIRRO}.parquet"
    
    merged.to_parquet(saida, index=False)

    for f in arquivos:
        f.unlink()

    logger.info(
        "Merge: %d linhas (%d batches) → %s. Batches deletados.",
        len(merged), len(arquivos), saida,
    )


if __name__ == "__main__":
    main()
