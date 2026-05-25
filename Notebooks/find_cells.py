import json

nb = json.load(open('modelos_preco_imoveis.ipynb', encoding='utf-8'))
for i, c in enumerate(nb['cells']):
    source_str = ''.join(c.get('source', []))
    if 'def metricas' in source_str:
        print(f'Cell {i}: {c.get("id", "N/A")}')
        print('---')
        print(source_str[:500])
        print('...')
        break
