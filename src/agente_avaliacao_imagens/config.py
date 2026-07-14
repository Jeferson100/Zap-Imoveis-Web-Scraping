import os

MAX_TENTATIVAS = int(os.getenv("IMAGENS_MAX_TENTATIVAS", "2"))
TAMANHO_LOTE = int(os.getenv("IMAGENS_TAMANHO_LOTE", "5"))
TIMEOUT_DOWNLOAD = float(os.getenv("IMAGENS_TIMEOUT_DOWNLOAD", "15"))
MAX_BYTES_IMAGEM = int(os.getenv("IMAGENS_MAX_BYTES", str(10 * 1024 * 1024)))
MAX_CONCURRENT_LOTES = int(os.getenv("IMAGENS_MAX_CONCURRENT_LOTES", "3"))
MODEL_VISION = os.getenv("IMAGENS_MODEL_VISION", "mistralai/ministral-14b-instruct-2512")
MODEL_TEXTO = os.getenv("IMAGENS_MODEL_TEXTO", "deepseek-ai/deepseek-v4-pro")
