from pathlib import Path

from mlflow_best_models import reconstruct_best_keras_models


EXPERIMENT_NAME = "joinville_precos"  # altere para o nome do seu experimento MLflow
INPUT_DIM = 16  # ajuste para o número de features usadas pelo modelo
SAVE_DIR = Path("models/best_keras")
TOP_N = 3


if __name__ == "__main__":
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    modelos = reconstruct_best_keras_models(
        experiment_name=EXPERIMENT_NAME,
        input_dim=INPUT_DIM,
        top_n=TOP_N,
        save_dir=SAVE_DIR,
    )
    print(f"Reconstituídos {len(modelos)} modelos e salvos em {SAVE_DIR}")
