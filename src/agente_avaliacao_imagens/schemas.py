from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class CategoriaConservacao(BaseModel):
    nome: str
    score: float
    severidade: str
    evidencias: List[str]
    necessidade_reparo: bool


class AnaliseImagens(BaseModel):
    score_conservacao: float
    score_acabamento: float
    score_potencial_reforma: float
    confianca_imagem: float
    imagem_aceitavel: bool
    categorias_conservacao: List[CategoriaConservacao]
    problemas_visiveis: List[str]
    pontos_fortes: List[str]
    observacoes: str


class FeedbackImagens(BaseModel):
    consistente: bool
    feedback: Optional[str] = None


class AnaliseDados(BaseModel):
    endereco_formatado: str
    bairro: str
    cidade: str
    area_estimada: Optional[float] = None
    quartos_estimados: Optional[int] = None
    banheiros_estimados: Optional[int] = None
    score_localizacao: float
    score_infraestrutura: float
    demanda_bairro: float
    pontos_positivos: List[str]
    pontos_negativos: List[str]
    observacoes: str


class FeedbackDados(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
