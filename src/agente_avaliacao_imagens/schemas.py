from typing import List, Optional

from pydantic import BaseModel, Field

from .config import MAX_TENTATIVAS


class AnaliseImagens(BaseModel):
    score_conservacao: float = Field(ge=0, le=10)
    score_acabamento: float = Field(ge=0, le=10)
    score_potencial_reforma: float = Field(ge=0, le=10)
    confianca_imagem: float = Field(ge=0, le=10)
    imagem_aceitavel: bool
    problemas_visiveis: List[str]
    pontos_fortes: List[str]
    observacoes: str


class FeedbackImagens(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
    inconsistencias: List[str] = []


class SubgrafoImagensState(BaseModel):
    fotos_urls: List[str] = []
    descricao_foto: str = ""
    feedback: Optional[str] = None
    analise: Optional[AnaliseImagens] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None
