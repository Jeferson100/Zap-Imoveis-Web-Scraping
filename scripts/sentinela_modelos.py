"""Sentinela de estagnacao: avisa (e falha) quando uma cidade para de publicar modelo.

Motivo: em 13/11/2026 a Joinville estava sem modelo novo desde 11/11 e ninguem
percebeu — o congelamento era silencioso. Este script transforma silencio em
sinal no Actions.

Usa a DATA DO NOME DO ARQUIVO (`*_modelo_geral_2026-11.joblib`), nao o mtime:
mtime de checkout e a hora do clone, nao a data da publicacao.

Uso:
    python scripts/sentinela_modelos.py [--limite 60] [--aviso 45]
    python scripts/sentinela_modelos.py --json
"""
import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

MES_RE = re.compile(r"(\d{4})-(\d{2})")
# diretorios que vivem em dados/ mas nao sao cidades
NAO_CIDADES = {"agente_avaliacoes", "imagens_cache", "modelo_fotos", "modelos", "cache"}


def fim_do_mes(ano, mes):
    if mes == 12:
        return date(ano, 12, 31)
    return date(ano, mes + 1, 1).fromordinal(date(ano, mes + 1, 1).toordinal() - 1)


def avaliar(dados_dir, hoje=None, limite=60, aviso=45):
    hoje = hoje or date.today()
    linhas = []
    for pasta in sorted(p for p in dados_dir.iterdir() if p.is_dir()):
        if pasta.name in NAO_CIDADES:
            continue
        modelos = list(pasta.glob("*_modelo_geral_*.joblib"))
        tem_dados = bool(list(pasta.glob("*_imoveis_limpo_*.parquet")))
        if not modelos:
            if tem_dados:
                linhas.append({
                    "cidade": pasta.name, "modelo": None, "idade_dias": None,
                    "status": "SEM MODELO", "cobertura": None, "mes": None,
                })
            continue

        # o mais recente pelo mes no nome do arquivo
        def mes_de(p):
            m = MES_RE.search(p.name)
            return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

        recente = max(modelos, key=mes_de)
        ano, mes = mes_de(recente)
        idade = (hoje - fim_do_mes(ano, mes)).days if ano else None

        cobertura = None
        estado = pasta / f"{pasta.name}_{ano:04d}-{mes:02d}_busca_estado.json"
        if estado.exists():
            try:
                est = json.loads(estado.read_text(encoding="utf-8"))
                blocos = len(est.get("blocos_concluidos") or [])
                planejado = int(est.get("total_planejado") or 0)
                if planejado:
                    cobertura = blocos / planejado
            except Exception:
                pass

        if idade is None:
            status = "SEM DATA"
        elif idade > limite:
            status = "ESTAGNADO"
        elif idade > aviso:
            status = "ATRASADO"
        else:
            status = "ok"

        linhas.append({
            "cidade": pasta.name, "modelo": recente.name, "idade_dias": idade,
            "status": status, "cobertura": cobertura, "mes": f"{ano:04d}-{mes:02d}",
        })
    return linhas


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", default="dados")
    ap.add_argument("--limite", type=int, default=60, help="dias para FALHAR")
    ap.add_argument("--aviso", type=int, default=45, help="dias para AVISAR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dados = Path(args.dados)
    if not dados.exists():
        print(f"dados/ nao encontrado em {dados.resolve()}", file=sys.stderr)
        return 2

    linhas = avaliar(dados, limite=args.limite, aviso=args.aviso)
    if args.json:
        print(json.dumps(linhas, default=str, indent=2, ensure_ascii=False))
    else:
        print(f"{'cidade':<24} {'mes':<8} {'idade':>6} {'cob.':>6}  status")
        print("-" * 62)
        for l in linhas:
            idade = "-" if l["idade_dias"] is None else f"{l['idade_dias']}d"
            cob = "-" if l["cobertura"] is None else f"{100*l['cobertura']:.0f}%"
            print(f"{l['cidade']:<24} {str(l['mes'] or '-'):<8} {idade:>6} {cob:>6}  {l['status']}")

    estagnados = [l for l in linhas if l["status"] in ("ESTAGNADO", "SEM MODELO")]
    atrasados = [l for l in linhas if l["status"] == "ATRASADO"]
    for l in atrasados:
        print(f"::warning title=Modelo atrasado::{l['cidade']} ha {l['idade_dias']} dias "
              f"(limite {args.aviso})")
    for l in estagnados:
        msg = ("sem modelo publicado" if l["status"] == "SEM MODELO"
               else f"ha {l['idade_dias']} dias sem modelo novo (limite {args.limite})")
        print(f"::error title=Modelo estagnado::{l['cidade']} {msg}")

    return 1 if estagnados else 0


if __name__ == "__main__":
    sys.exit(main())
