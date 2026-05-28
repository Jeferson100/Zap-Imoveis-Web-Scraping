import json

with open(r'C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\Notebooks\modelos_preco_imoveis.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        src = ''.join(cell['source'])
        if 'nomes_features_shap = preprocessor.get_feature_names_out()' in src:
            old = "nomes_features_shap = preprocessor.get_feature_names_out()"
            new = (
                "cat_encoder = preprocessor.named_transformers_['cat'].named_steps['ohe']\n"
                "cat_feature_names = cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES)\n"
                "nomes_features_shap = list(NUMERIC_FEATURES) + list(cat_feature_names)\n"
                "print(f'Features: {len(nomes_features_shap)} ({len(NUMERIC_FEATURES)} num + {len(cat_feature_names)} cat)')"
            )
            new_src = src.replace(old, new)
            cell['source'] = new_src.splitlines(keepends=True)
            print('Fixed: manual feature names extraction')
            break

with open(r'C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\Notebooks\modelos_preco_imoveis.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, ensure_ascii='ascii', indent=1)
print('Done')
