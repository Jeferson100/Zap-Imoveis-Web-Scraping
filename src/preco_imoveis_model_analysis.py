import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score, median_absolute_error, explained_variance_score


class PrecoImoveisModelAnalyzer:
    def __init__(self, dados: pd.DataFrame):
        if not isinstance(dados, pd.DataFrame):
            raise TypeError('dados deve ser um pandas DataFrame')
        self.dados = dados.copy()

    def _ensure_columns(self, columns):
        missing = [col for col in columns if col not in self.dados.columns]
        if missing:
            raise KeyError(f'Colunas faltando no DataFrame: {missing}')

    def _compute_residuals(self, df: pd.DataFrame, actual_col: str, pred_col: str) -> pd.DataFrame:
        self._ensure_columns([actual_col, pred_col])
        df = df.copy()
        df['residuo'] = df[pred_col] - df[actual_col]
        df['residuo_pct'] = np.where(
            df[actual_col] != 0,
            100 * df['residuo'] / df[actual_col],
            np.nan,
        )
        return df

    def compute_m2_residuals(self, actual_col='metro_quadrado_real', pred_col='predicao_metro_quadrado') -> pd.DataFrame:
        """Calcula resíduos e erro percentual usando preço por metro quadrado."""
        self._ensure_columns([actual_col, pred_col])
        self.dados = self._compute_residuals(self.dados, actual_col, pred_col)
        return self.dados

    def summary_residuals(self, subset: pd.DataFrame | None = None) -> pd.DataFrame:
        df = self.dados if subset is None else subset.copy()
        if 'residuo' not in df.columns or 'residuo_pct' not in df.columns:
            raise ValueError('Resíduos ainda não foram calculados para esse DataFrame.')
        return df[['residuo', 'residuo_pct']].describe()

    def metrics(self, subset: pd.DataFrame | None = None, actual_col='metro_quadrado_real', pred_col='predicao_metro_quadrado') -> dict:
        df = self.dados if subset is None else subset.copy()
        self._ensure_columns([actual_col, pred_col])
        if 'residuo' not in df.columns or 'residuo_pct' not in df.columns:
            df = self._compute_residuals(df, actual_col, pred_col)

        y_true = df[actual_col]
        y_pred = df[pred_col]

        result = {
            'mae': mean_absolute_error(y_true, y_pred),
            'rmse': np.sqrt(mean_squared_error(y_true, y_pred)),
            'median_ae': median_absolute_error(y_true, y_pred),
            'r2': r2_score(y_true, y_pred),
            'explained_variance': explained_variance_score(y_true, y_pred),
        }

        nonzero = y_true != 0
        if nonzero.any():
            result['mape'] = np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100
        else:
            result['mape'] = np.nan

        baseline = np.full_like(y_true, y_true.mean(), dtype=float)
        result['baseline_mae'] = mean_absolute_error(y_true, baseline)
        return result

    def percent_within_error(self, limites=(5, 10, 20, 30, 50), subset: pd.DataFrame | None = None) -> dict:
        df = self.dados if subset is None else subset.copy()
        if 'residuo_pct' not in df.columns:
            raise ValueError('Resíduos percentuais não foram calculados.')
        results = {}
        for limite in limites:
            results[f'erro_abs_{limite}'] = (df['residuo_pct'].abs() <= limite).mean() * 100
        return results

    def plot_residuals(self, subset: pd.DataFrame | None = None, sample_frac=0.35):
        df = self.dados if subset is None else subset.copy()
        if 'residuo' not in df.columns or 'residuo_pct' not in df.columns:
            raise ValueError('Resíduos ainda não foram calculados para esse DataFrame.')

        sample = df.sample(frac=min(max(sample_frac, 0.0), 1.0), random_state=42)
        plt.figure(figsize=(18, 5))

        plt.subplot(1, 3, 1)
        sns.histplot(sample['residuo'], bins=40, kde=True, color='C0')
        plt.title('Histograma dos resíduos por m² (R$)')
        plt.xlabel('Resíduo por m² (R$)')
        plt.ylabel('Contagem')

        plt.subplot(1, 3, 2)
        sns.histplot(sample['residuo_pct'], bins=40, kde=True, color='C1')
        plt.title('Histograma dos resíduos percentuais (%)')
        plt.xlabel('Resíduo percentual (%)')
        plt.ylabel('Contagem')

        plt.subplot(1, 3, 3)
        sns.scatterplot(x='metro_quadrado_real', y='residuo', data=sample, alpha=0.5)
        plt.axhline(0, color='red', linestyle='--')
        plt.title('Resíduo vs Valor real por m²')
        plt.xlabel('Valor real por m² (R$)')
        plt.ylabel('Resíduo por m² (R$)')

        plt.tight_layout()
        plt.show()

    def plot_prediction_vs_actual(self, subset: pd.DataFrame | None = None, actual_col='metro_quadrado_real', pred_col='predicao_metro_quadrado'):
        df = self.dados if subset is None else subset.copy()
        self._ensure_columns([actual_col, pred_col])
        plt.figure(figsize=(10, 8))
        sns.scatterplot(x=df[actual_col], y=df[pred_col], alpha=0.4, s=20)
        plt.plot([df[actual_col].min(), df[actual_col].max()], [df[actual_col].min(), df[actual_col].max()], color='red', linestyle='--')
        plt.title('Valor real por m² vs Valor previsto por m²')
        plt.xlabel(f'Valor real por m² (R$)')
        plt.ylabel(f'Valor previsto por m² (R$)')
        plt.tight_layout()
        plt.show()

    def apartment_analysis(self) -> dict:
        self._ensure_columns(['tipo_imovel', 'metro_quadrado_real', 'predicao_metro_quadrado', 'bairro'])
        apartments = self.dados[self.dados['tipo_imovel'] == 'apartamento'].copy()
        if apartments.empty:
            raise ValueError('Não há apartamentos na base de dados.')

        apartments = apartments[apartments['metro_quadrado_real'].notna() & (apartments['metro_quadrado_real'] != 0)].copy()
        apartments = self._compute_residuals(apartments, 'metro_quadrado_real', 'predicao_metro_quadrado')

        metrics = self.metrics(apartments, actual_col='metro_quadrado_real', pred_col='predicao_metro_quadrado')
        percentiles = apartments['residuo_pct'].abs().dropna().quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict()
        within_errors = self.percent_within_error(subset=apartments)

        bairros = (
            apartments.groupby('bairro')
            .agg(
                mediana_residuo_pct=('residuo_pct', 'median'),
                mae=('residuo', lambda x: np.mean(np.abs(x))),
                contagem=('residuo_pct', 'size'),
            )
            .sort_values('mediana_residuo_pct')
        )

        top_errors = (
            apartments.sort_values('residuo_pct', ascending=False)
            .head(20)[['bairro', 'metragem', 'metro_quadrado_real', 'predicao_metro_quadrado', 'residuo_pct']]
        )

        return {
            'count': apartments.shape[0],
            'metrics': metrics,
            'percentiles_residuo_pct': percentiles,
            'within_error': within_errors,
            'bairros': bairros,
            'top_errors': top_errors,
        }
