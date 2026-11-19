"""Schema do veredito ReAct (extraido de c0de5003)."""

import os
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class AvaliacaoImovel(BaseModel):
    # Mesmo formato de AnalisePotencialFlip
    score_potencial_flip: float
    potencial_house_flip: Literal["True", "False"]
    justificativa_potencial: str
    riscos: List[str]
    recomendacoes: List[str]
    observacoes: str
    # Imagem (preditor)
    ambiente_fotos: str
    confianca_ambiente: float
    conservacao_fotos: str
    confianca_conservacao: float
    nota_conservacao: float
    # Validacao dos dados
    dados_consistentes: bool
    inconsistencias: List[str]
    possui_erros: Literal["True", "False"]
    # Loop 2
    aprovado_graders: bool
    tentativas: int
    graders: Dict[str, Any]


# Faixa de nota 0-10 esperada para cada desgaste previsto (limite superior exclusivo, exceto 10).
FAIXA_NOTA = {
    "bem conservado": (8.0, 10.0),
    "desgaste leve": (6.0, 8.0),
    "desgastado": (3.0, 6.0),
    "precário": (0.0, 3.0),
}

# Tolerancia de borda do G2. A nota e a media ponderada das 4 classes e a classe
# e o argmax: 5.9 em "desgaste leve" [6.0, 8.0) e o argmax vizinho, nao o agente
# inventando numero. Sem tolerancia o G2 reprova por arredondamento de faixa.
TOLERANCIA_G2 = float(os.environ.get("FLIP_TOLERANCIA_G2", "0.3"))


FAIXA_NOTA = {
    "bem conservado": (8.0, 10.0),
    "desgaste leve": (6.0, 8.0),
    "desgastado": (3.0, 6.0),
    "precário": (0.0, 3.0),
}


def _num(valor, default: float = 0.0) -> float:
    """float seguro para os graders: None/str invalida/NaN/inf -> default."""
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return default
    return default if f != f or f in (float("inf"), float("-inf")) else f


def graders_sem_pecas(sessao) -> Dict[str, Any]:
    """Graders de um run incompleto: cada ausencia no seu proprio grader.

    O bloco antigo acusava "sem saida do preditor" sempre que faltasse
    qualquer peca, inclusive com a imagem presente - o Loop 4 aprendia a causa
    errada da falha.
    """
    erros = {"G1": [], "G2": [], "G3": [], "G4": [], "G5": [], "G6": []}
    if sessao.get("imagem") is None:
        erros["G1"].append("classificar_fotos_tool nao rodou (nem o fallback deterministico)")
    if sessao.get("validacao") is None:
        erros["G6"].append("validar_dados_tool nao foi chamada")
    if sessao.get("metricas_tool") is None:
        erros["G4"].append("calcular_metricas_tool nao foi chamada: veredito nao conferido")
        erros["G5"].append("sem metricas: custo de reforma nao conferido")
    if sessao.get("flip") is None:
        erros["G3"].append("sem veredito estruturado")
    motivo = sessao.get("erro_etapa") or sessao.get("provedor_caiu")
    if motivo:
        erros["G3"].append(f"etapa interrompida pelo provedor: {motivo[:160]}")
    passou = {k: not v for k, v in erros.items()}
    return {"passou": passou, "erros": erros, "ok": all(passou.values())}


def montar_saida(imagem, flip, validacao, graders, tentativas, historico) -> AvaliacaoImovel:
    return AvaliacaoImovel(
        score_potencial_flip=round(min(10.0, max(0.0, float(flip.score_potencial_flip))), 2) if flip else 0.0,
        potencial_house_flip=flip.potencial_house_flip if flip else "False",
        justificativa_potencial=flip.justificativa_potencial if flip else "flip indisponivel",
        riscos=list(flip.riscos) if flip else [],
        recomendacoes=list(flip.recomendacoes) if flip else [],
        observacoes=flip.observacoes if flip else "",
        ambiente_fotos=imagem.ambiente,
        confianca_ambiente=imagem.confianca_ambiente,
        conservacao_fotos=imagem.classe_conservacao or "indefinido",
        confianca_conservacao=imagem.confianca_conservacao,
        nota_conservacao=imagem.score_conservacao,
        dados_consistentes=bool(getattr(validacao, "dados_consistentes", False)),
        inconsistencias=list(getattr(validacao, "inconsistencias_encontradas", []) or []),
        possui_erros=getattr(validacao, "possui_erros", "False") or "False",
        aprovado_graders=graders["ok"],
        tentativas=tentativas,
        graders={"passou": graders["passou"], "historico": historico},
    )

