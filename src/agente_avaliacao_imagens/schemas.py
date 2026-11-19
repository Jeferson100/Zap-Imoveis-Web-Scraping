from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from .config import MAX_TENTATIVAS


def _coerce_str_list(v: Any) -> List[str]:
    """Aceita list[str] ou list[dict] (resposta mal-formatada de alguns LLMs)."""
    if not isinstance(v, list):
        return v
    result = []
    for item in v:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            # Tenta extrair o valor mais descritivo do dict
            for key in ("erro", "descricao", "description", "value", "text", "message"):
                if key in item:
                    result.append(str(item[key]))
                    break
            else:
                # Fallback: serializa o dict inteiro como string
                result.append(", ".join(f"{k}: {v}" for k, v in item.items()))
        else:
            result.append(str(item))
    return result


class AnaliseImagens(BaseModel):
    score_conservacao: float = Field(ge=0, le=10)
    score_acabamento: float = Field(ge=0, le=10)
    score_potencial_reforma: float = Field(ge=0, le=10)
    confianca_imagem: float = Field(ge=0, le=10)
    imagem_aceitavel: bool
    problemas_visiveis: List[str]
    pontos_fortes: List[str]
    observacoes: str
    # Saida do classificador de fotos (opcional: o LLM/Laya nao preenchem).
    ambiente: str = "desconhecido"
    confianca_ambiente: float = 0.0
    classe_conservacao: Optional[str] = None
    confianca_conservacao: float = 0.0
    # Conservacao separada por ambiente previsto das fotos (None quando nao ha
    # nenhuma foto daquele ambiente).
    score_conservacao_interna: Optional[float] = None
    classe_conservacao_interna: Optional[str] = None
    confianca_conservacao_interna: float = 0.0
    score_conservacao_externa: Optional[float] = None
    classe_conservacao_externa: Optional[str] = None
    confianca_conservacao_externa: float = 0.0
    fotos_por_ambiente: Dict[str, int] = {}

    def resumo(self) -> Dict[str, Any]:
        """Versao compacta para tools e prompts (5 chaves em vez de 19)."""

        def _grupo(nome: str) -> Optional[Dict[str, Any]]:
            nota = getattr(self, f"score_conservacao_{nome}")
            if nota is None:
                return None
            return {
                "nota": nota,
                "conservacao": getattr(self, f"classe_conservacao_{nome}"),
                "fotos": int(self.fotos_por_ambiente.get(nome, 0)),
            }

        return {
            "conservacao": self.classe_conservacao,
            "nota": self.score_conservacao,
            "confianca": self.confianca_conservacao,
            "interna": _grupo("interna"),
            "externa": _grupo("externa"),
        }

    @field_validator("ambiente", mode="after")
    @classmethod
    def _normaliza_ambiente(cls, v: str) -> str:
        return v if v in ("interna", "externa", "desconhecido") else "desconhecido"

    @field_validator("problemas_visiveis", "pontos_fortes", mode="before")
    @classmethod
    def _coerce_str_lists(cls, v: Any) -> List[str]:
        return _coerce_str_list(v)


class FeedbackImagens(BaseModel):
    consistente: bool
    feedback: Optional[str] = None
    inconsistencias: List[str] = []

    @field_validator("inconsistencias", mode="before")
    @classmethod
    def _coerce_inconsistencias(cls, v: Any) -> List[str]:
        return _coerce_str_list(v)


class SubgrafoImagensState(BaseModel):
    fotos_urls: List[str] = []
    descricao_foto: str = ""
    feedback: Optional[str] = None
    analise: Optional[AnaliseImagens] = None
    tentativa: int = 0
    max_tentativas: int = MAX_TENTATIVAS
    api_key: Optional[str] = None
