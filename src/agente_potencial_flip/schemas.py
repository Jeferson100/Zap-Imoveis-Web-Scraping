from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal


class AnalisePotencialFlip(BaseModel):
    score_potencial_flip: float
    potencial_house_flip :Literal["True", "False"] = Field(
        description="If the imovel has auto potencial de reforma coloque True, se nao coloque False"
    )
    justificativa_potencial: str
    riscos: List[str]
    recomendacoes: List[str]
    observacoes: str


class FeedbackPotencialFlip(BaseModel):
    consistente: Literal["True", "False"] = Field(
        description="Indica se True se a analise do modelo anterior esta correta e false se nao"
    )
    feedback:  str
