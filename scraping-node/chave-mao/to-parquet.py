"""Converte JSON de coleta em parquet idêntico ao do pipeline Python.
Uso: python to-parquet.py <entrada.json> <saida.parquet>
"""
import json
import sys
from pathlib import Path

import pandas as pd


def main():
    if len(sys.argv) != 3:
        print("Uso: python to-parquet.py <entrada.json> <saida.parquet>")
        sys.exit(1)
    entrada, saida = Path(sys.argv[1]), Path(sys.argv[2])
    with open(entrada, encoding="utf-8") as f:
        dados = json.load(f)
    if isinstance(dados, dict):
        dados = [dados]
    df = pd.DataFrame(dados)
    saida.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(saida, index=False, compression="snappy")
    print(f"{len(df)} registros -> {saida.name}")


if __name__ == "__main__":
    main()
