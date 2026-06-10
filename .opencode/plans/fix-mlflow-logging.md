# Fix MLflow Logging — Mudanças Necessárias

## 1. `src/mlflow_manager.py` — Linha 221

**Antes:**
```python
tracking_uri = f"file:///{self.mlruns_dir}"
```

**Depois:**
```python
tracking_uri = self.mlruns_dir.as_uri()
```

**Motivo:** No Windows, `Path.as_uri()` gera URI correta (`file:///C:/...`) com forward slashes.

---

## 2. `src/teste_incremental_features_async.py`

### 2a. `_conectar_mlflow_async` (linhas 254-256)

**Antes:**
```python
        except Exception as e:
            logger.warning("MLflow nao disponivel: %s", e)
            self.mlflow_mgr = None
```

**Depois:**
```python
        except Exception as e:
            logger.warning("MLflow nao disponivel: %s", e)
            logger.exception("Detalhes da falha MLflow:")
            self.mlflow_mgr = None
```

### 2b. Exception handler em `executar_combo` (linhas 666-668)

**Antes:**
```python
                    except Exception as exc:
                        logger.debug("Falha %s %s feat%s: %s",
                                     mod_name or "MLP_opt", trat["nome"], col, exc)
```

**Depois:**
```python
                    except Exception as exc:
                        logger.warning("Falha %s %s feat%s: %s",
                                       mod_name or "MLP_opt", trat["nome"], col, exc)
                        logger.exception("Traceback completo:")
```

### 2c. Envolver bloco MLflow em `_combo_optuna` em try/except (linhas 751-772)

**Antes:**
```python
            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", mod_name)
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_param("transform", transf_name)
                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in estudo.best_params.items()})
                mlflow.log_metrics({**met, **cv_met})
                encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                mlflow.set_tag("feature_transform_map",
                               self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                import mlflow.data
                train_df = pd.concat([X_tr.reset_index(drop=True),
                                      pd.Series(y_train, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                test_df = pd.concat([X_te.reset_index(drop=True),
                                     pd.Series(y_test, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()
```

**Depois:**
```python
            if self.mlflow_mgr:
                try:
                    self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                    mlflow.set_tag("teste", "tratamentos_modelos")
                    mlflow.log_param("tratamento", trat["nome"])
                    mlflow.log_param("modelo", mod_name)
                    mlflow.log_param("n_features", n_features)
                    mlflow.log_param("ultima_feature", col)
                    mlflow.log_param("transform", transf_name)
                    mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in estudo.best_params.items()})
                    mlflow.log_metrics({**met, **cv_met})
                    encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                    mlflow.set_tag("feature_transform_map",
                                   self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                    import mlflow.data
                    train_df = pd.concat([X_tr.reset_index(drop=True),
                                          pd.Series(y_train, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                    test_df = pd.concat([X_te.reset_index(drop=True),
                                         pd.Series(y_test, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                    self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    mlflow.end_run()
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")
```

### 2d. Remover `best_rmse_cv` dos returns

**No return de `_combo_optuna` (linhas 774-783):**

**Antes:**
```python
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                "best_rmse_cv": float(estudo.best_value),
                **cv_met,
                **met,
            }
```

**Depois:**
```python
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                **cv_met,
                **met,
            }
```

**No return de `_combo_mlp` (linhas 941-951):**

**Antes:**
```python
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP_opt",
                "transform": transf_name,
                "best_rmse_cv": float(study.best_value),
                **cv_met,
                **met,
            }
```

**Depois:**
```python
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP_opt",
                "transform": transf_name,
                **cv_met,
                **met,
            }
```

### 2e. Envolver bloco MLflow em `_combo_simples` em try/except (linhas 825-845)

**Antes:**
```python
            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", mod_name)
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_param("transform", transf_name)
                mlflow.log_metrics({**met, **cv_met})
                encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                mlflow.set_tag("feature_transform_map",
                               self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                import mlflow.data
                train_df = pd.concat([X_tr.reset_index(drop=True),
                                      pd.Series(y_train, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                test_df = pd.concat([X_te.reset_index(drop=True),
                                     pd.Series(y_test, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()
```

**Depois:**
```python
            if self.mlflow_mgr:
                try:
                    self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                    mlflow.set_tag("teste", "tratamentos_modelos")
                    mlflow.log_param("tratamento", trat["nome"])
                    mlflow.log_param("modelo", mod_name)
                    mlflow.log_param("n_features", n_features)
                    mlflow.log_param("ultima_feature", col)
                    mlflow.log_param("transform", transf_name)
                    mlflow.log_metrics({**met, **cv_met})
                    encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                    mlflow.set_tag("feature_transform_map",
                                   self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                    import mlflow.data
                    train_df = pd.concat([X_tr.reset_index(drop=True),
                                          pd.Series(y_train, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                    test_df = pd.concat([X_te.reset_index(drop=True),
                                         pd.Series(y_test, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                    self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    mlflow.end_run()
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")
```

### 2f. Envolver bloco MLflow em `_combo_mlp` em try/except (linhas 922-943)

**Antes:**
```python
            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", "MLP_opt")
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_param("transform", transf_name)
                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in study.best_params.items()})
                mlflow.log_metrics({**met, **cv_met})
                encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                mlflow.set_tag("feature_transform_map",
                               self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                import mlflow.data
                train_df = pd.concat([X_tr.reset_index(drop=True),
                                      pd.Series(y_train, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                test_df = pd.concat([X_te.reset_index(drop=True),
                                     pd.Series(y_test, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()
```

**Depois:**
```python
            if self.mlflow_mgr:
                try:
                    self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
                    mlflow.set_tag("teste", "tratamentos_modelos")
                    mlflow.log_param("tratamento", trat["nome"])
                    mlflow.log_param("modelo", "MLP_opt")
                    mlflow.log_param("n_features", n_features)
                    mlflow.log_param("ultima_feature", col)
                    mlflow.log_param("transform", transf_name)
                    mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in study.best_params.items()})
                    mlflow.log_metrics({**met, **cv_met})
                    encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]).__name__ else "ohe"
                    mlflow.set_tag("feature_transform_map",
                                   self._build_transform_map(num_feats, cat_fixas, transf_name, encoder_name))
                    import mlflow.data
                    train_df = pd.concat([X_tr.reset_index(drop=True),
                                          pd.Series(y_train, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                    test_df = pd.concat([X_te.reset_index(drop=True),
                                         pd.Series(y_test, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                    self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    mlflow.end_run()
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")
```

### 2g. Envolver bloco MLflow em `_log_executar_resultado` em try/except (linhas 537-561)

**Antes:**
```python
        self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
        mlflow.set_tag("teste", "incremental_features")
        mlflow.log_param("n_features", n_feats)
        mlflow.log_param("ultima_feature", ultima_feature)
        mlflow.log_param("escalador", esc_name)
        mlflow.log_param("modelo", mod_name)
        mlflow.log_param("transform", transf_name)
        if feats_num or cat_fixas:
            mlflow.set_tag("feature_transform_map",
                           self._build_transform_map(feats_num, cat_fixas, transf_name))
        if y_train is not None and X_te_sel is not None and y_test is not None:
            import mlflow.data
            train_df = pd.concat([X_tr_sel.reset_index(drop=True),
                                  pd.Series(y_train, name="target")], axis=1)
            mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
            test_df = pd.concat([X_te_sel.reset_index(drop=True),
                                 pd.Series(y_test, name="target")], axis=1)
            mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
        mlflow.log_metrics(met)
        if hasattr(modelo, "get_params"):
            mlflow.log_params({
                f"modelo__{k}": str(v)[:80] for k, v in modelo.get_params().items()
            })
        self.mlflow_mgr.log_feature_history(X_tr_sel, run_name=run_name)
        mlflow.end_run()
```

**Depois:**
```python
        try:
            self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
            mlflow.set_tag("teste", "incremental_features")
            mlflow.log_param("n_features", n_feats)
            mlflow.log_param("ultima_feature", ultima_feature)
            mlflow.log_param("escalador", esc_name)
            mlflow.log_param("modelo", mod_name)
            mlflow.log_param("transform", transf_name)
            if feats_num or cat_fixas:
                mlflow.set_tag("feature_transform_map",
                               self._build_transform_map(feats_num, cat_fixas, transf_name))
            if y_train is not None and X_te_sel is not None and y_test is not None:
                import mlflow.data
                train_df = pd.concat([X_tr_sel.reset_index(drop=True),
                                      pd.Series(y_train, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                test_df = pd.concat([X_te_sel.reset_index(drop=True),
                                     pd.Series(y_test, name="target")], axis=1)
                mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
            mlflow.log_metrics(met)
            if hasattr(modelo, "get_params"):
                mlflow.log_params({
                    f"modelo__{k}": str(v)[:80] for k, v in modelo.get_params().items()
                })
            self.mlflow_mgr.log_feature_history(X_tr_sel, run_name=run_name)
            mlflow.end_run()
        except Exception as e_mlflow:
            logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
            logger.exception("Detalhes:")
```

---

## 3. `src/teste_incremental_features.py` (sync)

### 3a. Envolver blocos MLflow em try/except

**Localizar os 4 blocos que começam com:**
```python
        if self.mlflow_mgr:
            self.mlflow_mgr.criar_run(run_name=run_name, nested=False)
```

**Para cada um, adicionar `try:` antes de `self.mlflow_mgr.criar_run` e `except Exception as e_mlflow:` com `logger.warning` + `logger.exception` antes do `mlflow.end_run()`** (mesmo padrão do async).

### 3b. Remover `best_rmse_cv` dos returns

**Localizar e remover a linha `"best_rmse_cv": float(estudo.best_value),` nos returns dos métodos de combo.**

---

## 4. Verificação

Após aplicar todas as mudanças, rodar:
```bash
python -c "
import ast
for f in [
    'src/mlflow_manager.py',
    'src/teste_incremental_features_async.py',
    'src/teste_incremental_features.py'
]:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```
