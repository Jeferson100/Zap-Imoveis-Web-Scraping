"""Exporta POIs do cache p/ o site calcular scores ao vivo (~15KB/cidade).

Lê o mesmo cache do pipeline (CriandoIndicesIndividuais: dict categoria ->
GeoDataFrame salvo como pickle, apesar da extensão .parquet) e grava só
coordenadas [lat, lng] em JSON compacto.

Uso:
    CIDADE_PASTA=joinville python scripts/exportar_pois.py
    (sem env: exporta joinville por padrão)
"""
import json
import os
import pickle
import sys
from pathlib import Path

# Espelha CriandoIndicesIndividuais.configuracao (categoria -> raios em metros).
CATEGORIAS = {
    "escolas_privadas": [500],
    "escolas_publicas": [500],
    "hospital": [1000],
    "mercado": [500],
    "farmacia": [300],
    "parque": [1000],
    "policia": [500],
}


def exportar_pois(cidade_pasta: str, base_dir: Path) -> Path:
    pasta = base_dir / "dados" / cidade_pasta
    candidatos = sorted(pasta.glob("pois_*.parquet"),
                      key=lambda p: p.stat().st_size, reverse=True)
    if not candidatos:
        raise FileNotFoundError(f"Nenhum cache de POIs em {pasta}")
    pois = None
    cache = candidatos[0]
    for cand in candidatos:
        try:
            with open(cand, "rb") as f:
                tentativa = pickle.load(f)
            n = sum(len(tentativa.get(c, [])) for c in CATEGORIAS) \
                if isinstance(tentativa, dict) else 0
            if n > 0:
                pois, cache = tentativa, cand
                break
        except Exception as e:
            print(f"Ignorado {cand.name}: {e}")
    if not pois:
        raise ValueError(f"Nenhum POI utilizável em {[c.name for c in candidatos]}")
    print(f"Lendo cache: {cache.name}...")

    saida = {}
    for cat in CATEGORIAS:
        gdf = pois.get(cat) if isinstance(pois, dict) else None
        pts = []
        if gdf is not None:
            geo = gdf.geometry if hasattr(gdf, "geometry") else gdf
            for p in geo:
                try:
                    # O cache salva geometry como string WKT; o pipeline usa o
                    # centroid (ver _extrair_coordenadas) — mesma paridade aqui.
                    if isinstance(p, str):
                        from shapely import wkt as _wkt
                        p = _wkt.loads(p)
                    c = p.centroid if hasattr(p, "centroid") else p
                    pts.append([round(float(c.y), 6), round(float(c.x), 6)])  # [lat, lng]
                except Exception:
                    continue
        saida[cat] = pts

    total = sum(len(v) for v in saida.values())
    out = base_dir / "site_estatico" / "data" / f"pois_{cidade_pasta}.json"
    out.write_text(json.dumps(saida, separators=(",", ":")), encoding="utf-8")
    print(f"Gravado {out.name}: {total} POIs ({out.stat().st_size / 1024:.1f} KB)")
    return out


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    cidade = os.environ.get("CIDADE_PASTA", "joinville").strip().lower() or "joinville"
    exportar_pois(cidade, base_dir)


if __name__ == "__main__":
    sys.exit(main())
