"""Valida os artefatos gerados em site_estatico/ antes da publicacao.

Uso:
    python scripts/validar_site.py

Sai com codigo 1 (falha o CI) quando encontra:
  - marcadores de conflito git (<<<<<<<, =======, >>>>>>>) em qualquer arquivo
  - JSON invalido em site_estatico/data
  - modelo de predicao com estrutura incompleta
  - dados/stats ausentes para alguma cidade do index.html
"""
import json
import re
import sys
from pathlib import Path

CONFLITO_RE = re.compile(rb'^(?:<<<<<<< |=======$|>>>>>>> )', re.MULTILINE)
MODO_VALORES = {'venda', 'aluguel', 'predicao'}
ARQUIVOS_TEXTO = {'.html', '.js', '.json', '.css', '.md'}


def validar_conflitos(base_dir):
    erros = []
    for arq in sorted(base_dir.rglob('*')):
        if not arq.is_file() or arq.suffix.lower() not in ARQUIVOS_TEXTO:
            continue
        data = arq.read_bytes()
        for match in CONFLITO_RE.finditer(data):
            linha = data.count(b'\n', 0, match.start()) + 1
            erros.append(f'marcador de conflito: {arq.relative_to(base_dir)}:{linha}')
    return erros


def validar_json(pasta_data):
    erros = []
    for arq in sorted(pasta_data.glob('*.json')):
        try:
            with open(arq, encoding='utf-8') as f:
                json.load(f)
        except Exception as exc:
            erros.append(f'JSON invalido: data/{arq.name} ({exc})')
    return erros


def validar_modelos(pasta_data):
    erros = []
    for arq in sorted(pasta_data.glob('modelo_*.json')):
        try:
            with open(arq, encoding='utf-8') as f:
                modelo = json.load(f)
        except Exception:
            continue  # ja reportado por validar_json

        features = modelo.get('feature_names') or []
        if not features:
            erros.append(f'modelo sem feature_names: data/{arq.name}')
        if not isinstance(modelo.get('preprocessor'), dict):
            erros.append(f'modelo sem preprocessor: data/{arq.name}')

        ensemble = modelo.get('ensemble') or {}
        tipo = ensemble.get('type')
        if tipo == 'gradient_boosting':
            trees = ensemble.get('trees') or []
            if not trees:
                erros.append(f'ensemble sem trees: data/{arq.name}')
            elif ensemble.get('n_estimators') != len(trees):
                erros.append(
                    f'n_estimators ({ensemble.get("n_estimators")}) != trees ({len(trees)}): data/{arq.name}'
                )
            for chave in ('learning_rate', 'init'):
                if chave not in ensemble:
                    erros.append(f'ensemble sem {chave}: data/{arq.name}')
        elif tipo == 'decision_tree':
            if not ensemble.get('children_left') or not ensemble.get('children_right'):
                erros.append(f'decision_tree incompleta: data/{arq.name}')
        else:
            erros.append(f'ensemble desconhecido ({tipo}): data/{arq.name}')
    return erros


def cidades_do_index(base_dir):
    html = (base_dir / 'index.html').read_text(encoding='utf-8')
    return sorted({
        valor for valor in re.findall(r'<option value="([a-z0-9_]+)"', html)
        if valor not in MODO_VALORES
    })


def validar_cidades(base_dir, pasta_data):
    erros = []
    cidades = cidades_do_index(base_dir)
    if not cidades:
        return ['nenhuma cidade encontrada em index.html']

    for cidade in cidades:
        for nome in (f'dados_{cidade}.js', f'stats_{cidade}.js'):
            if not (pasta_data / nome).exists():
                erros.append(f'arquivo ausente: data/{nome}')

        modelo = pasta_data / f'modelo_{cidade}.json'
        if modelo.exists():
            for nome in (
                f'bairro_stats_{cidade}.json',
                f'modelo_{cidade}.json',
                f'cluster_{cidade}.json',
            ):
                if not (pasta_data / nome).exists():
                    erros.append(f'arquivo ausente para predicao: data/{nome}')

    aluguel = pasta_data / 'config_aluguel.json'
    if aluguel.exists():
        with open(aluguel, encoding='utf-8') as f:
            config = json.load(f)
        for cidade in config.get('cidades', []):
            if not (pasta_data / f'dados_aluguel_{cidade}.js').exists():
                erros.append(f'arquivo ausente: data/dados_aluguel_{cidade}.js')
    return erros


def main():
    base_dir = Path(__file__).resolve().parent.parent / 'site_estatico'
    pasta_data = base_dir / 'data'

    if not base_dir.exists() or not pasta_data.exists():
        print(f'ERRO: pasta nao encontrada: {base_dir}')
        return 1

    erros = []
    erros.extend(validar_conflitos(base_dir))
    erros.extend(validar_json(pasta_data))
    erros.extend(validar_modelos(pasta_data))
    erros.extend(validar_cidades(base_dir, pasta_data))

    if erros:
        print(f'Validacao falhou ({len(erros)} problema(s)):')
        for erro in erros:
            print(f'  - {erro}')
        return 1

    cidades = len(cidades_do_index(base_dir))
    print(f'Validacao OK: {cidades} cidades, {len(list(pasta_data.glob("*.json")))} JSONs.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
