import logging
import os

logger = logging.getLogger(__name__)


def _parse_max_tentativas(raw: str) -> int:
    try:
        val = int(raw)
        if val < 0 or val > 10:
            raise ValueError(f"fora do intervalo [0, 10]: {val}")
        return val
    except (ValueError, TypeError) as e:
        logger.warning("IMAGENS_MAX_TENTATIVAS inválido (%s), usando padrão 1. Erro: %s", raw, e)
        return 1


def _parse_bool(raw: str | None, default: bool) -> bool:
    return raw.strip().lower() in ("1", "true", "yes") if raw else default


MAX_TENTATIVAS = _parse_max_tentativas(os.getenv("IMAGENS_MAX_TENTATIVAS", "0"))
TAMANHO_LOTE = int(os.getenv("IMAGENS_TAMANHO_LOTE", "5"))
TIMEOUT_DOWNLOAD = float(os.getenv("IMAGENS_TIMEOUT_DOWNLOAD", "15"))
TIMEOUT_LLM = float(os.getenv("IMAGENS_TIMEOUT_LLM", "30"))
MAX_BYTES_IMAGEM = int(os.getenv("IMAGENS_MAX_BYTES", str(10 * 1024 * 1024)))
MAX_CONCURRENT_LOTES = int(os.getenv("IMAGENS_MAX_CONCURRENT_LOTES", "8"))
# Modelos de visão/texto: seleção dinâmica via catálogo
# (src/roteador_llms/selecao_modelos.py). Sem defaults manuais aqui.
USAR_URL_DIRETA: bool = _parse_bool(os.getenv("IMAGENS_USAR_URL_DIRETA"), True)  # =true requer suporte do modelo LLM_Visão a URLs externas
CACHE_DOWNLOADS: bool = _parse_bool(os.getenv("IMAGENS_CACHE_DOWNLOADS"), True)

# Julgamento da descrição: "classificador" (ConvNeXt, ambiente + desgaste, sem LLM),
# "laya" (perguntas tipadas) ou "llm" (JSON gerado por LLM). Na falta dos pesos,
# o grafo cai automaticamente para "llm".
JULGADOR = os.getenv("IMAGENS_JULGADOR", "classificador").strip().lower()
# Probabilidade mínima do `noul aceitavel` para considerar a descrição válida.
LAYA_MIN_ACEITAVEL = float(os.getenv("IMAGENS_LAYA_MIN_ACEITAVEL", "0.5"))
# Perfil do Router: "" = roteamento automático; ou english/multilingual/typed-decisions.
LAYA_PERFIL = os.getenv("IMAGENS_LAYA_PERFIL", "").strip()

# Classificador de fotos (ConvNeXt treinado no repo). Usado quando
# IMAGENS_JULGADOR=classificador.
CLASSIFICADOR_DIR = os.getenv("IMAGENS_CLASSIFICADOR_DIR", "").strip()
CLASSIFICADOR_FOLDS = os.getenv("IMAGENS_CLASSIFICADOR_FOLDS", "all").strip().lower()
CLASSIFICADOR_TTA: bool = _parse_bool(os.getenv("IMAGENS_CLASSIFICADOR_TTA"), True)
# 0 (padrao) = todas as fotos do anuncio; >0 limita a quantidade.
CLASSIFICADOR_MAX_FOTOS = int(os.getenv("IMAGENS_CLASSIFICADOR_MAX_FOTOS", "0"))
# True = a tool devolve o dump completo (19 campos) em vez do resumo (5 chaves).
CLASSIFICADOR_SAIDA_COMPLETA: bool = _parse_bool(os.getenv("IMAGENS_SAIDA_COMPLETA"), False)
# True = a tool devolve uma entrada por foto (alem do agregado do anuncio).
CLASSIFICADOR_POR_FOTO: bool = _parse_bool(os.getenv("IMAGENS_CLASSIFICADOR_POR_FOTO"), False)
