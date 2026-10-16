"""Union-resolve de parquets flip em push com corrida.

Para cada arquivo casado pelo(s) glob(s), concatena a versão local com a
versão já commitada em origin/main e remove duplicadas por url (fica a
mais recente). Sem correspondente no main, o arquivo é mantido intacto.

Uso (no CI, dentro do repo):
    uv run codigos_rodando/joinville/union_flip_parquet.py "<glob>" [...]
"""
import glob
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


def unir(arquivo: str, ref: str = "origin/main") -> None:
    try:
        base = subprocess.run(
            ["git", "show", f"{ref}:{arquivo}"],
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return  # novo no main: nada a unir
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp.write(base)
        tmp_path = tmp.name
    try:
        a = pd.read_parquet(arquivo)
        b = pd.read_parquet(tmp_path)
        u = pd.concat([b, a], ignore_index=True).drop_duplicates("url", keep="last")
        if len(u) != len(a):
            u.to_parquet(arquivo, index=False)
            print(f"union {arquivo}: {len(a)} -> {len(u)}", flush=True)
    except Exception as e:
        print(f"union pulado {arquivo}: {e}", flush=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main(patterns: list) -> None:
    for pat in patterns:
        for f in sorted(glob.glob(pat)):
            unir(f)


if __name__ == "__main__":
    main(sys.argv[1:])
