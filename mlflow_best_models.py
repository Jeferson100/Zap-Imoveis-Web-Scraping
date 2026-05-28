import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

keras = None
layers = None
try:
    from tensorflow import keras
    from tensorflow.keras import layers
except ImportError:
    try:
        import keras
        from keras import layers
    except ImportError:
        keras = None
        layers = None

import mlflow
from mlflow.tracking import MlflowClient


def _parse_param_value(value: Any) -> Any:
    """Converte strings de parâmetros para int/float quando possível."""
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        lowered = value.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
    return value


def parse_mlflow_params(params: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _parse_param_value(v) for k, v in params.items()}


def build_keras_from_params(params: Dict[str, Any], input_dim: int):
    """Reconstrói um modelo Keras MLP a partir de parâmetros de trial."""
    if keras is None or layers is None:
        raise ImportError(
            "TensorFlow/Keras não está instalado no ambiente. Instale 'tensorflow' ou 'keras' para reconstruir modelos Keras."
        )
    num_camadas = int(params.get("num_camadas", 1))
    model = keras.Sequential()
    model.add(keras.Input(shape=(input_dim,)))

    for i in range(num_camadas):
        unidades = int(params.get(f"unidades_{i}", 64))
        model.add(layers.Dense(unidades, activation="relu"))
        dropout = float(params.get(f"dropout_{i}", 0.0))
        if dropout > 0:
            model.add(layers.Dropout(dropout))

    model.add(layers.Dense(1))
    learning_rate = float(params.get("learning_rate", 0.001))
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate),
        loss="mse",
        metrics=["mae"],
    )
    return model


def build_and_fit_keras_model(
    params: Dict[str, Any],
    input_dim: int,
    X_train,
    y_train,
    X_val,
    y_val,
    epochs: int = 200,
    patience: int = 15,
    verbose: int = 0,
):
    """Reconstrói e treina o modelo Keras a partir de parâmetros de trial."""
    model = build_keras_from_params(params, input_dim)
    batch_size = int(params.get("batch_size", 256))
    early_stop = keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=patience, restore_best_weights=True
    )
    model.fit(
        X_train,
        y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=[early_stop],
        verbose=verbose,
    )
    return model


def get_top_runs_from_mlflow(
    experiment_name: str,
    top_n: int = 3,
    modelo_tag: str = "keras",
    order_by: str = "metrics.rmse asc",
) -> List[Dict[str, Any]]:
    client = MlflowClient(tracking_uri=mlflow.get_tracking_uri())
    experiment = client.get_experiment_by_name(experiment_name)
    if experiment is None:
        raise ValueError(f"Experimento '{experiment_name}' não encontrado no MLflow.")

    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.modelo = '{modelo_tag}'",
        order_by=[order_by],
        max_results=top_n,
    )

    results = []
    for run in runs:
        results.append(
            {
                "run_id": run.info.run_id,
                "run_name": run.info.run_name,
                "rmse": run.data.metrics.get("rmse"),
                "mae": run.data.metrics.get("mae"),
                "mape": run.data.metrics.get("mape"),
                "r2": run.data.metrics.get("r2"),
                "params": parse_mlflow_params(run.data.params),
                "feature_sampled": run.data.tags.get("feature_sample"),
                "modelo": run.data.tags.get("modelo"),
                "status": run.info.status,
            }
        )
    return results


def reconstruct_best_keras_models(
    experiment_name: str,
    input_dim: int,
    top_n: int = 3,
    save_dir: Optional[Path] = None,
) -> List[Tuple[str, Any, Dict[str, Any]]]:
    models = []
    best_runs = get_top_runs_from_mlflow(experiment_name, top_n=top_n, modelo_tag="keras")
    if save_dir:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    for run_info in best_runs:
        model = build_keras_from_params(run_info["params"], input_dim)
        model_name = run_info["run_name"].replace(" ", "_").replace("/", "_")
        if save_dir:
            model_path = save_dir / f"{model_name}.keras"
            model.save(model_path)
            print(f"Salvo modelo reconstruído: {model_path}")
        models.append((run_info["run_name"], model, run_info["params"]))

    return models


def save_keras_models(models: List[Tuple[str, Any, Dict[str, Any]]], save_dir: Path) -> None:
    save_dir.mkdir(parents=True, exist_ok=True)
    for run_name, model, _params in models:
        model_name = run_name.replace(" ", "_").replace("/", "_")
        model_path = save_dir / f"{model_name}.keras"
        model.save(model_path)
        print(f"Modelo salvo: {model_path}")
