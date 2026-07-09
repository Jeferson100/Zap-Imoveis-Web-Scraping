from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class AnalisePotencialFlip(BaseModel):
    score_house_flip: float
    potencial_house_flip: str  # BAIXO / MEDIO / ALTO / ALTISSIMO
    justificativa_potencial: str
    custo_reforma_estimado: float
    valor_estimado_pos_reforma: float
    roi_estimado: float
    prazo_estimado_meses: Optional[int] = None
    riscos: List[str]
    recomendacoes: List[str]
    observacoes: str


class FeedbackPotencialFlip(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
