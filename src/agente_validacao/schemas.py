from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal


class ValidacaoDados(BaseModel):
    dados_corrigidos: Dict[str, Any]
    dados_consistentes: bool
    inconsistencias_encontradas: List[str]
    confianca_validacao: float
    observacoes: str
    possui_erros: Literal["True", "False"] = Field(
        description="Indica se o modelo encontrou erros nos dados. 'True' se houver erros, 'False' se dados estao corretos."
    )
    metragem_corrigida: Optional[float] = None
    vagas_corrigidas: Optional[int] = None
    quartos_corrigidos: Optional[int] = None
    valor_imovel_corrigido: Optional[float] = None
    tipo_imovel_corrigido: Optional[str] = None
    bairro_corrigido: Optional[str] = None


class FeedbackValidacao(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
