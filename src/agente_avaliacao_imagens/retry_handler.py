import asyncio
import logging
import random
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_com_backoff(
    func: Callable[..., Any],
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    **kwargs
) -> Any:
    """
    Executa função com retry exponencial + jitter.
    
    Args:
        func: Função async a executar
        max_attempts: Máximo de tentativas
        base_delay: Delay base em segundos (1s)
        max_delay: Delay máximo (60s)
    
    Returns:
        Resultado de func(*args, **kwargs)
    
    Raises:
        Exceção original após max_attempts esgotadas
    """
    last_exception = None
    
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt < max_attempts - 1:
                # Calcular delay: 2^attempt + jitter aleatório
                delay = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.1)  # ±10% jitter
                total_delay = delay + jitter
                
                logger.warning(
                    f"Tentativa {attempt + 1}/{max_attempts} falhou. "
                    f"Aguardando {total_delay:.2f}s antes de retry... Erro: {str(e)[:100]}"
                )
                await asyncio.sleep(total_delay)
            else:
                logger.error(
                    f"Todas {max_attempts} tentativas falharam. "
                    f"Erro final: {str(e)}"
                )
    
    raise last_exception
