"""Roda o ReAct flip (sombra) direto de 1+ imoveis, sem passar pelo notebook.

Uso:
    uv run python scripts/rodar_react_flip.py --dry-run          # sem LLM (so payload + metricas)
    uv run python scripts/rodar_react_flip.py                    # 1 imovel (idx=10 do centro/apartamento)
    uv run python scripts/rodar_react_flip.py --bairro americana --n 3
    uv run python scripts/rodar_react_flip.py --idx 0 --json sombra.json

Chave: OPENROUTER_API_KEY (ou FLIP_API_KEY) no `.env` da raiz ou no ambiente;
o import de `agente_potencial_flip` ja carrega o `.env` via `roteador_llms`.

Custo: cada imovel = 1 avaliacao ReAct (ate 6 chamadas de visao + texto).
`--n 5` nao e barato nem rapido (1-4 min por imovel).
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CAMPOS_NUM = (
    "metragem", "banheiros", "vagas", "quartos",
    "valor_imovel", "valor_predito", "p50_bairro", "preco_por_m2",
)
CAMPOS_TXT = ("bairro", "tipo_imovel")


def raiz_repo() -> Path:
    """Sobe diretorios ate achar a raiz do repo (a que tem `dados/`)."""
    for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        if (p / "dados").is_dir():
            return p
    return Path(__file__).resolve().parents[1]


RAIZ = raiz_repo()
for _p in (str(RAIZ / "src"), str(RAIZ)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from agente_potencial_flip import (  # noqa: E402
    TrilhaFlip,
    avaliar_imovel_react,
    calcular_metricas_flip,
)
from shared.serialization import converter_numpy  # noqa: E402


def payload_de(linha) -> Dict[str, Any]:
    """Monta o payload (shape EstadoGlobal) a partir de uma linha do df."""
    fotos = linha.get("fotos")
    try:
        fotos_urls = [str(u) for u in list(fotos) if u]
    except TypeError:
        fotos_urls = []
    dados = converter_numpy({c: linha.get(c, 0) for c in CAMPOS_NUM})
    dados.update({c: str(linha.get(c, "") or "") for c in CAMPOS_TXT})
    return {
        "fotos_urls": fotos_urls,
        "dados_imovel": dados,
        "descricao_texto": str(linha.get("descricao", "") or ""),
    }


def selecionar(
    cidade: str,
    bairro: Optional[str],
    tipo: Optional[str],
    idx: int,
    n: int,
    parquet: Optional[str],
) -> tuple[pd.DataFrame, Path]:
    pasta = RAIZ / "dados" / cidade
    if parquet:
        caminho = Path(parquet)
    else:
        candidatos = sorted(pasta.glob(f"{cidade}_imoveis_limpo_*.parquet"))
        if not candidatos:
            raise SystemExit(f"Sem parquet em {pasta}. Rode a etapa de limpeza da cidade.")
        caminho = candidatos[-1]

    df = pd.read_parquet(caminho)
    if bairro:
        df = df[df["bairro"] == bairro]
    if tipo:
        df = df[df["tipo_imovel"] == tipo]
    df = df.sort_values("preco_por_m2")
    if df.empty:
        raise SystemExit(f"Nenhum imovel com bairro={bairro!r} tipo={tipo!r} em {caminho.name}.")
    if idx >= len(df):
        raise SystemExit(f"idx={idx} fora do range ({len(df)} imoveis).")
    return df.iloc[idx:idx + n], caminho


async def rodar(fatia: pd.DataFrame, cidade: str, json_saida: Optional[str]) -> List[Dict[str, Any]]:
    resultados: List[Dict[str, Any]] = []
    for pos, (_, linha) in enumerate(fatia.iterrows(), start=1):
        url = str(linha.get("url", "") or "")
        payload = payload_de(linha)
        metricas = calcular_metricas_flip(payload["dados_imovel"])
        trilha = TrilhaFlip()

        inicio = time.perf_counter()
        saida = await avaliar_imovel_react(
            payload, thread_id=f"flip-{url or 'linha'}", callbacks=[trilha]
        )
        duracao = time.perf_counter() - inicio

        m = saida.get("metricas_flip") or metricas
        trava_ok = (str(saida.get("potencial_house_flip")) == "True") == bool(
            m.get("passa_regra_15pct")
        )
        print(
            f"[{pos}/{len(fatia)}] {duracao:5.1f}s "
            f"score={saida.get('score_potencial_flip')} "
            f"flip={saida.get('potencial_house_flip')} "
            f"roi={m.get('roi_conservador')} "
            f"passa15={m.get('passa_regra_15pct')} "
            f"trava={'OK' if trava_ok else 'VIOLADA'} "
            f"erro={saida.get('erro', '-')} "
            f"| {url[:70]}"
        )
        for p in trilha.pensamentos():
            print(f"      THINK[{p['proxima_acao']}] {p['pensamento'][:180]}")

        resultados.append({
            "url": url,
            "cidade": cidade,
            "duracao_s": round(duracao, 1),
            "saida": converter_numpy(saida),
            "metricas": converter_numpy(m),
            "trava_ok": trava_ok,
            "pensamentos": trilha.pensamentos(),
            "trilha": trilha.resumo(),
        })

    if json_saida:
        destino = Path(json_saida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(resultados, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nJSON salvo em {destino}")
    return resultados


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cidade", default="joinville")
    parser.add_argument("--bairro", default="centro")
    parser.add_argument("--tipo", default="apartamento")
    parser.add_argument("--idx", type=int, default=10, help="posicao (preco_por_m2 asc)")
    parser.add_argument("--n", type=int, default=1, help="quantos imoveis a partir de --idx")
    parser.add_argument("--parquet", default=None, help="caminho explicito do parquet")
    parser.add_argument("--json", dest="json_saida", default=None, help="salva o resultado")
    parser.add_argument("--dry-run", action="store_true", help="so payload + metricas, sem LLM")
    args = parser.parse_args()

    fatia, caminho = selecionar(
        args.cidade, args.bairro, args.tipo, args.idx, args.n, args.parquet
    )
    print(f"{len(fatia)} imovel(is) de {caminho.name}\n")

    if args.dry_run:
        for _, linha in fatia.iterrows():
            payload = payload_de(linha)
            metricas = calcular_metricas_flip(payload["dados_imovel"])
            print(f"url={str(linha.get('url', ''))[:80]}")
            print(json.dumps(converter_numpy(metricas), indent=2, ensure_ascii=False))
            print(f"fotos={len(payload['fotos_urls'])} "
                  f"descricao={len(payload['descricao_texto'])} chars\n")
        return

    asyncio.run(rodar(fatia, args.cidade, args.json_saida))


if __name__ == "__main__":
    main()
