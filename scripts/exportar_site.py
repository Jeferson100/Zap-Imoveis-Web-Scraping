"""
Exporta dados + modelo para o site estatico.
Chamado pelo workflow de exportacao mensal.

Uso:
    CIDADE_PASTA=joinville python scripts/exportar_site.py
"""
import os
import sys
import subprocess
from pathlib import Path


def main():
    cidade = os.environ.get('CIDADE_PASTA', '').strip().lower()
    if not cidade:
        print('Erro: variavel CIDADE_PASTA nao definida.')
        sys.exit(1)

    base_dir = Path(__file__).resolve().parent.parent
    scripts_dir = base_dir / 'scripts'

    print(f'=== Exportando site para: {cidade} ===')

    print('\n[1/2] Exportando dados...')
    env = os.environ.copy()
    env['CIDADE_EXPORTAR'] = cidade
    r = subprocess.run(
        [sys.executable, str(scripts_dir / 'exportar_dados.py')],
        env=env,
        cwd=str(base_dir),
    )
    if r.returncode != 0:
        print(f'Erro ao exportar dados (rc={r.returncode})')
        sys.exit(1)

    print('\n[2/2] Exportando modelo...')
    r = subprocess.run(
        [sys.executable, str(scripts_dir / 'exportar_modelo_js.py'), cidade],
        cwd=str(base_dir),
    )
    if r.returncode != 0:
        print(f'Erro ao exportar modelo (rc={r.returncode})')
        sys.exit(1)

    print(f'\n=== Concluido: {cidade} ===')


if __name__ == '__main__':
    main()
