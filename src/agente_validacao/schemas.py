from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class ValidacaoDados(BaseModel):
    dados_corrigidos: Dict[str, Any]
    dados_consistentes: bool
    inconsistencias_encontradas: List[str]
    confianca_validacao: float
    observacoes: str


class FeedbackValidacao(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
