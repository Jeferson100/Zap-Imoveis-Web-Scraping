"""Julgamento tipado (estilo Jev) da descrição das fotos, com Laya local.

Substitui o LLM generativo de `extrair_analise`: em vez de pedir um JSON em
texto livre e torcer para o parse, faz perguntas tipadas (`score` / `noul`) e
converte as respostas para `AnaliseImagens`.

Laya **não vê a imagem**: ele recebe o texto que `descrever_fotos` já produziu.
Roda em CPU, offline, sem API key. Modelo: `convaiinnovations/laya`.

Duas regras medidas no notebook (`react_agent_valiador.ipynb`):

1. `noul` precisa de `criteria` + `labels` explícitos. Sem eles o mesmo caso
   deu `aceitavel=0.044`; com eles, `0.758`.
2. `score` é **valor esperado** no intervalo `0..n_niveis-1`, não o nível
   escolhido. Normalizar por `(n_niveis - 1)` e comparar por faixa.

Uso:
    from agente_avaliacao_imagens.julgador_laya import julgar_descricao
    analise = julgar_descricao(descricao_das_fotos)  # -> AnaliseImagens
"""

import logging
import threading
from typing import Any, Dict

from .config import LAYA_MIN_ACEITAVEL, LAYA_PERFIL
from .schemas import AnaliseImagens

logger = logging.getLogger(__name__)

__all__ = [
    "PERGUNTAS_FOTOS",
    "LayaIndisponivel",
    "disponivel",
    "julgar_descricao",
    "detalhar_julgamento",
]

PERGUNTAS_FOTOS: Dict[str, Dict[str, Any]] = {
    "conservacao": {
        "type": "score",
        "instructions": (
            "Estado de conservacao do imovel descrito, considerando infiltracao, "
            "trincas e desgaste."
        ),
        "criteria": [
            "Precario, com dano grave.",
            "Desgastado, com patologias visiveis.",
            "Bom, com sinais leves de uso.",
            "Excelente, sem patologias.",
        ],
    },
    "acabamento": {
        "type": "score",
        "instructions": "Padrao dos acabamentos visiveis.",
        "criteria": ["Baixo padrao.", "Padrao medio.", "Alto padrao."],
    },
    "reforma": {
        "type": "score",
        "instructions": "Potencial de valorizacao com reforma.",
        "criteria": ["Nao vale reformar.", "Vale reforma parcial.", "Alto potencial."],
    },
    "confianca": {
        "type": "score",
        "instructions": "A descricao e clara e suficiente para avaliacao tecnica?",
        "criteria": ["Vaga ou parcial.", "Razoavel.", "Clara e completa."],
    },
    "aceitavel": {
        "type": "noul",
        "instructions": (
            "A descricao e de um comodo ou fachada real de imovel, "
            "e nao de um objeto, selfie ou texto vago?"
        ),
        "criteria": {
            "false": "Objeto, selfie, parede preta ou texto sem relacao com imovel.",
            "true": "Comodo ou fachada de imovel descrito com elementos construtivos.",
        },
        "labels": {"false": "NAO", "true": "SIM"},
    },
}

# Número de níveis de cada `score` (usado para normalizar 0..10).
_NIVEIS = {
    qid: (len(pergunta["criteria"]) if isinstance(pergunta["criteria"], list) else 2)
    for qid, pergunta in PERGUNTAS_FOTOS.items()
}

_ROUTER: Any = None
_ROUTER_LOCK = threading.Lock()


class LayaIndisponivel(RuntimeError):
    """O pacote `laya` não está instalado neste ambiente."""


def disponivel() -> bool:
    """True se `laya` importa **e** expõe `Router` (não carrega o modelo).

    Só importar não basta: o fork `laya-vision` instala um pacote `laya`
    com `load_vlm` (VLM) mas sem `Router` (julgamento de texto).
    """
    try:
        import laya
    except Exception:  # pragma: no cover - depende do ambiente
        return False
    return hasattr(laya, "Router")


def _router() -> Any:
    """Carrega o Router uma única vez (thread-safe) e reusa nas chamadas."""
    global _ROUTER
    if _ROUTER is None:
        with _ROUTER_LOCK:
            if _ROUTER is None:
                try:
                    from laya import Router
                except Exception as exc:  # pragma: no cover - depende do ambiente
                    raise LayaIndisponivel(f"falha ao importar laya: {exc}") from exc
                kwargs: Dict[str, Any] = {"preload": True}
                if LAYA_PERFIL:
                    kwargs["default"] = LAYA_PERFIL
                _ROUTER = Router(**kwargs)
    return _ROUTER


def _para_dez(score: float, n_niveis: int) -> float:
    """Normaliza o `score` do Laya (0..n_niveis-1) para a escala 0..10."""
    return round(max(0.0, min(1.0, float(score) / max(1, n_niveis - 1))) * 10.0, 1)


def _fallback(motivo: str) -> AnaliseImagens:
    return AnaliseImagens(
        score_conservacao=0,
        score_acabamento=0,
        score_potencial_reforma=0,
        confianca_imagem=0,
        imagem_aceitavel=False,
        problemas_visiveis=[motivo],
        pontos_fortes=[],
        observacoes=motivo,
    )


def julgar_descricao(descricao: str) -> AnaliseImagens:
    """Descrição textual -> `AnaliseImagens`, sem LLM generativo e sem levantar exceção.

    Levanta `LayaIndisponivel` apenas se o pacote não existir; falhas do modelo
    viram fallback com scores zerados.
    """
    texto = (descricao or "").strip()
    if not texto:
        return _fallback("Sem descricao")

    if not disponivel():
        raise LayaIndisponivel("pacote laya nao instalado")

    try:
        resposta = _router().predict(texto, PERGUNTAS_FOTOS)
        respostas = resposta["answers"]
    except Exception as exc:
        logger.exception("Falha no julgador Laya")
        return _fallback(f"Falha no julgador: {type(exc).__name__}: {str(exc)[:200]}")

    # Regra de negócio: descrição que não é de imóvel -> zeros.
    if float(respostas["aceitavel"]["noul"]) <= LAYA_MIN_ACEITAVEL:
        return _fallback("Laya: descricao nao parece ser de imovel")

    return AnaliseImagens(
        score_conservacao=_para_dez(
            respostas["conservacao"]["score"], _NIVEIS["conservacao"]
        ),
        score_acabamento=_para_dez(
            respostas["acabamento"]["score"], _NIVEIS["acabamento"]
        ),
        score_potencial_reforma=_para_dez(
            respostas["reforma"]["score"], _NIVEIS["reforma"]
        ),
        confianca_imagem=_para_dez(
            respostas["confianca"]["score"], _NIVEIS["confianca"]
        ),
        imagem_aceitavel=True,
        problemas_visiveis=[],
        pontos_fortes=[],
        observacoes=texto[:500],
    )


def detalhar_julgamento(descricao: str) -> Dict[str, Any]:
    """Respostas cruas do Laya (score, distribuição, confiança) para inspeção."""
    texto = (descricao or "").strip()
    if not texto:
        return {}

    resposta = _router().predict(texto, PERGUNTAS_FOTOS)
    saida: Dict[str, Any] = {}
    for qid, ans in resposta["answers"].items():
        if ans["type"] == "score":
            saida[qid] = {
                "tipo": "score",
                "score": round(float(ans["score"]), 3),
                "nota_0_10": _para_dez(ans["score"], _NIVEIS[qid]),
                "niveis": ans.get("legend"),
                "probabilidades": ans.get("probabilities"),
                "confianca": round(float(ans.get("confidence", 0.0)), 3),
            }
        else:
            saida[qid] = {
                "tipo": "noul",
                "p_verdadeiro": round(float(ans["noul"]), 3),
                "confianca": round(float(ans.get("confidence", 0.0)), 3),
            }
    saida["_routing"] = resposta.get("routing", {}).get("model")
    saida["_usage"] = resposta.get("usage")
    return saida
