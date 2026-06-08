import os
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv


load_dotenv()


class MLflowManager:
    """Gerencia conexao com MLflow (local ou Databricks)."""

    def __init__(
        self,
        nome_experimento="preco-imoveis-joinville",
        mlruns_dir=None,
        databricks_workspace_path=None,
    ):
        self.nome_experimento = nome_experimento
        self.mlruns_dir = Path(mlruns_dir) if mlruns_dir else Path.cwd().parent / "mlruns"
        self.databricks_workspace_path = (
            databricks_workspace_path
            or f"/Users/sehnemjeferson@gmail.com/{nome_experimento}"
        )
        self._conectado = False

    # ── metodos publicos ──

    def conectar(self):
        """Configura tracking URI e experimento. Tenta Databricks primeiro, fallback local."""
        import mlflow

        host, token, profile = self._ler_credenciais()

        if host and token:
            return self._conectar_databricks_token(host, token, mlflow)
        elif profile:
            return self._conectar_databricks_profile(profile, mlflow)
        else:
            return self._conectar_local(mlflow)

    def is_conectado(self):
        return self._conectado

    def get_tracking_uri(self):
        import mlflow

        return mlflow.get_tracking_uri()

    def get_experimento(self):
        import mlflow

        return mlflow.get_experiment_by_name(self.nome_experimento)

    def listar_runs(self, max_results=50):
        from mlflow.tracking import MlflowClient

        import mlflow

        client = MlflowClient(mlflow.get_tracking_uri())
        experiment = client.get_experiment_by_name(self.nome_experimento)
        if not experiment:
            return []
        return client.search_runs(
            experiment_ids=[experiment.experiment_id],
            max_results=max_results,
        )

    def criar_run(self, run_name=None, nested=False, tags=None):
        import mlflow

        if not self._conectado:
            self.conectar()
        return mlflow.start_run(run_name=run_name, nested=nested, tags=tags)

    def log_feature_history(self, X, run_name=None):
        import mlflow

        try:
            cols = list(X.columns) if hasattr(X, "columns") else []
            mlflow.set_tag("feature_history_run_name", run_name or "")
            mlflow.set_tag("feature_history_num_columns", len(cols))
            if cols:
                mlflow.set_tag("feature_history_columns", ",".join(cols[:50]))
                if len(cols) > 50:
                    mlflow.set_tag("feature_history_columns_truncated", "true")
                path = Path(tempfile.mkdtemp()) / "feature_history.csv"
                pd.DataFrame({"feature": cols}).to_csv(path, index=False)
                mlflow.log_artifact(str(path), artifact_path="feature_history")
        except Exception as exc:
            print(f"Falha ao logar feature history: {exc}")

    def log_feature_store(self, X, run_name=None, feature_group_name="joinville_imoveis",
                          description=None, source="joinville_historico_imoveis"):
        import mlflow

        try:
            mlflow.set_tag("feature_store_run_name", run_name or "")
            mlflow.set_tag("feature_store_group_name", feature_group_name)
            mlflow.set_tag("feature_store_description", description)
            mlflow.set_tag("feature_store_source", source)
            mlflow.set_tag("feature_store_num_columns", X.shape[1] if hasattr(X, "shape") else None)
            cols = list(X.columns) if hasattr(X, "columns") else []
            if cols:
                path = Path(tempfile.mkdtemp()) / "feature_store.csv"
                pd.DataFrame({"feature": cols}).to_csv(path, index=False)
                mlflow.log_artifact(str(path), artifact_path="feature_store")
        except Exception as exc:
            print(f"Falha ao logar feature store: {exc}")

    # ── alias para compatibilidade com codigo antigo ──
    _log_feature_history = log_feature_history
    _log_feature_store = log_feature_store

    def listar_experimentos(self):
        from mlflow.tracking import MlflowClient
        import mlflow

        client = MlflowClient(mlflow.get_tracking_uri())
        experiments = client.search_experiments()
        print(f"Total de experimentos: {len(experiments)}\n")
        for exp in experiments:
            print(f"Experimento: {exp.name} (ID: {exp.experiment_id})")
            runs = client.search_runs(experiment_ids=[exp.experiment_id], max_results=10)
            print(f"   Runs: {len(runs)}")
            for run in runs[:5]:
                status = "OK" if run.info.status == "FINISHED" else "..."
                rmse = run.data.metrics.get("rmse", None)
                rmse_str = f"{rmse:.4f}" if rmse else "N/A"
                print(f"   {status} {run.info.run_name} - RMSE: {rmse_str}")
            if len(runs) > 5:
                print(f"   ... e mais {len(runs) - 5} runs")
            print()

    def _buscar_experimento(self, nome):
        from mlflow.tracking import MlflowClient
        import mlflow

        client = MlflowClient(mlflow.get_tracking_uri())
        experiment = client.get_experiment_by_name(nome)
        if experiment:
            return experiment

        experiments = client.search_experiments()
        matches = [
            exp for exp in experiments
            if exp.name == nome or exp.name.endswith(nome) or nome in exp.name
        ]
        if len(matches) == 1:
            print(f"Usando experimento encontrado: {matches[0].name} (ID: {matches[0].experiment_id})")
            return matches[0]
        if len(matches) > 1:
            print(f"Varios experimentos correspondem a '{nome}':")
            for exp in matches:
                print(f" - {exp.name} (ID: {exp.experiment_id})")
            print(f"Usando o primeiro: {matches[0].name}")
            return matches[0]
        return None

    def comparar_modelos(self, nome_experimento=None):
        from mlflow.tracking import MlflowClient
        import mlflow

        nome = nome_experimento or self.nome_experimento
        experiment = self._buscar_experimento(nome)
        if not experiment:
            print(f"Experimento '{nome}' nao encontrado")
            return

        client = MlflowClient(mlflow.get_tracking_uri())
        runs = client.search_runs(experiment_ids=[experiment.experiment_id])

        resultados = []
        for run in runs:
            if run.data.metrics:
                resultados.append({
                    "run_name": run.info.run_name,
                    "rmse": run.data.metrics.get("rmse"),
                    "mae": run.data.metrics.get("mae"),
                    "mape": run.data.metrics.get("mape"),
                    "mdape": run.data.metrics.get("mdape"),
                    "r2": run.data.metrics.get("r2"),
                    "parametros": run.data.params,
                    "feature_sampled": run.data.tags.get("feature_sample"),
                    "modelo": run.data.tags.get("modelo"),
                    "status": run.info.status,
                })

        df = pd.DataFrame(resultados).sort_values("rmse", na_position="last")
        if df.empty:
            print(f"Nenhum run com metricas para '{experiment.name}'")
        else:
            print("Comparacao de modelos treinados:")
            print(df.to_string(index=False))
        return df

    # ── metodos privados ──

    @staticmethod
    def _normalizar_host(host):
        if not host:
            return host
        parsed = urlparse(host.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return host.strip().rstrip("/")

    def _ler_credenciais(self):
        raw_host = os.getenv("DATABRICKS_HOST", "")
        host = self._normalizar_host(raw_host)
        token = os.getenv("DATABRICKS_TOKEN", os.getenv("API_KEY_DATABRICKS", ""))
        profile = os.getenv("DATABRICKS_CONFIG_PROFILE", "")
        return host, token, profile

    def _conectar_local(self, mlflow):
        self.mlruns_dir.mkdir(parents=True, exist_ok=True)
        tracking_uri = f"file:///{self.mlruns_dir}"
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(self.nome_experimento)
        self._conectado = True
        print(f"[MLflow] Local: {tracking_uri}")
        print(f"[MLflow] Experimento: {self.nome_experimento}")
        return tracking_uri

    def _conectar_databricks_token(self, host, token, mlflow):
        os.environ["DATABRICKS_HOST"] = host
        os.environ["DATABRICKS_TOKEN"] = token
        os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "30"
        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(self.databricks_workspace_path)
        self._conectado = True
        print(f"[MLflow] Databricks (token): {host}")
        print(f"[MLflow] Experimento: {self.databricks_workspace_path}")
        return "databricks"

    def _conectar_databricks_profile(self, profile, mlflow):
        os.environ["DATABRICKS_CONFIG_PROFILE"] = profile
        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(self.databricks_workspace_path)
        self._conectado = True
        print(f"[MLflow] Databricks (profile): {profile}")
        print(f"[MLflow] Experimento: {self.databricks_workspace_path}")
        return "databricks"
