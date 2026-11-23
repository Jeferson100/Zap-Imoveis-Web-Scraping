"""Loop engineering do agente de flip no CI — determinístico, sem LLM.

Porta a mecânica do notebook (c0de5003/c0de6003) para o caminho que o GitHub
Action executa: graders G1–G7, orçamento de iterações, timeout, early-stop por
repetição, veredito sintetizado quando o loop se esgota e telemetria.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from agente_avaliacao_imagens import AMBIENTES, CLASSES_CONSERVACAO as LABELS

from .schemas import AnalisePotencialFlip
from .tools_flip import ROI_MINIMO, custo_reforma_m2

logger = logging.getLogger(__name__)

# Faixa de nota 0-10 esperada para cada desgaste previsto (limite superior exclusivo, exceto 10).
FAIXA_NOTA = {
    "bem conservado": (8.0, 10.0),
    "desgaste leve": (6.0, 8.0),
    "desgastado": (3.0, 6.0),
    "precário": (0.0, 3.0),
}
TOLERANCIA_G2 = float(os.environ.get("FLIP_TOLERANCIA_G2", "0.3"))

MAX_TENTATIVAS = int(os.environ.get("FLIP_MAX_TENTATIVAS", "2"))
LOOP_TIMEOUT_S = float(os.environ.get("FLIP_LOOP_TIMEOUT_S", "180"))
PARAR_SE_REPETE = os.environ.get("FLIP_LOOP_PARAR_SE_REPETE", "1") != "0"

CONCLUIDO = "concluido"
CONVERGIDO = "convergido"
LIMITE_TENTATIVAS = "limite_tentativas"
TIMEOUT = "timeout"
REPETIDO = "repetido"
SEM_ANALISE = "sem_analise"


def _num(valor, default: float = 0.0) -> float:
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return default
    return default if f != f or f in (float("inf"), float("-inf")) else f


def avaliar_graders(
    imagem, flip, validacao, metricas: Optional[dict] = None
) -> Dict[str, Any]:
    """G1–G6 portados do notebook. Nenhuma chamada de LLM."""
    erros: Dict[str, List[str]] = {
        "G1": [], "G2": [], "G3": [], "G4": [], "G5": [], "G6": []
    }

    # G1/G2: imagem válida e conservação coerente
    # Quando o classificador não tem pesos ou fotos (fallback), imagem traz
    # ambiente='desconhecido' e classe_conservacao=None/'indefinido'.
    # Nesses casos, G1 e G2 não devem travar o agente nem forçar retries inúteis.
    imagem_fallback = (
        imagem is None
        or getattr(imagem, "ambiente", None) == "desconhecido"
        or getattr(imagem, "classe_conservacao", None) in (None, "indefinido", "")
        or getattr(imagem, "problemas_visiveis", []) == ["Sem fotos para o classificador"]
    )

    if imagem is None:
        erros["G1"].append("analise de imagens ausente")
    elif not imagem_fallback:
        if getattr(imagem, "ambiente", None) not in AMBIENTES:
            erros["G1"].append(f"ambiente invalido: {imagem.ambiente}")
        if getattr(imagem, "classe_conservacao", None) not in LABELS:
            erros["G1"].append(f"conservacao invalida: {imagem.classe_conservacao}")
        for campo in ("confianca_ambiente", "confianca_conservacao"):
            v = _num(getattr(imagem, campo, None))
            if not 0 <= v <= 1:
                erros["G1"].append(f"{campo} fora de [0,1]: {v}")

        # G2: nota coerente com a conservação prevista
        classe = getattr(imagem, "classe_conservacao", None)
        if classe in FAIXA_NOTA:
            lo, hi = FAIXA_NOTA[classe]
            nota = _num(getattr(imagem, "score_conservacao", 0))
            if not (lo - TOLERANCIA_G2 <= nota and (nota < hi + TOLERANCIA_G2 or hi >= 10)):
                erros["G2"].append(
                    f"nota {nota} fora da faixa de '{classe}' "
                    f"[{lo}, {hi}) +/- {TOLERANCIA_G2}"
                )

    # G3: completude da validação e do flip, com checagem de coerência
    if validacao is None:
        erros["G3"].append("validacao ausente")
    if flip is None:
        erros["G3"].append("analise de flip ausente")
    else:
        pot = getattr(flip, "potencial_house_flip", None)
        if pot not in ("True", "False"):
            erros["G3"].append(
                f"potencial_house_flip invalido: {pot}"
            )
        just = str(getattr(flip, "justificativa_potencial", "") or "").strip()
        if not just or len(just) < 15:
            erros["G3"].append("justificativa vazia ou excessivamente curta")
        
        # Detectar se o modelo emitiu justificativa preliminar de etapa em andamento
        import re
        if re.search(r"(?i)^(iniciando|aguardando|chamando|etapa \d|vou |recalculando)", just):
            erros["G3"].append(f"justificativa de etapa em andamento (incompleta): '{just[:60]}...'")

        score = _num(getattr(flip, "score_potencial_flip", None))
        if not 0 <= score <= 10:
            erros["G3"].append(f"score fora de [0,10]: {score}")

        # Coerência entre potencial_house_flip e score
        if pot == "True" and score < 5.0:
            erros["G3"].append(f"incoerencia: potencial_house_flip=True mas score={score} (< 5.0)")
        if pot == "False" and score >= 7.0:
            erros["G3"].append(f"incoerencia: potencial_house_flip=False mas score={score} (>= 7.0)")

    # G4: a regra de 15% vem das métricas determinísticas, não do modelo
    if metricas is None:
        erros["G4"].append("metricas ausentes: veredito nao pode ser conferido")
    else:
        passa = bool(metricas.get("passa_regra_15pct"))
        roi = metricas.get("roi_conservador")
        if flip is not None and flip.potencial_house_flip == "True" and not passa:
            erros["G4"].append(
                f"aprovou flip com passa_regra_15pct=false (roi_conservador={roi})"
            )

    # G5: a conta da reforma tem que ser a regra vigente e entrar no lucro
    if metricas is None:
        erros["G5"].append("metricas ausentes: a conta da reforma nao pode ser conferida")
    else:
        metragem = _num(metricas.get("metragem_usada") or metricas.get("metragem"))
        reforma = _num(metricas.get("custo_reforma_estimado"))
        custo = _num(metricas.get("custo_reforma_por_m2")) or custo_reforma_m2()
        if not metragem:
            erros["G5"].append("metragem ausente: reforma nao pode ser conferida")
        else:
            if abs(reforma - custo * metragem) > 0.02:
                erros["G5"].append(
                    f"custo_reforma_estimado {reforma} != {custo}/m2 x {metragem}"
                )
            esperado = round(
                _num(metricas.get("arv_estimado")) * 0.90
                - _num(metricas.get("valor_imovel"))
                - reforma,
                2,
            )
            if abs(esperado - _num(metricas.get("lucro_projetado"))) > 0.02:
                erros["G5"].append(
                    f"lucro_projetado {metricas.get('lucro_projetado')} != {esperado} "
                    "(reforma nao descontada)"
                )
            arv = _num(metricas.get("arv_estimado"))
            if arv:
                teto = round((arv * 0.90 - reforma) / (1 + ROI_MINIMO), 2)
                if abs(teto - _num(metricas.get("preco_maximo_para_regra"))) > 0.02:
                    erros["G5"].append(
                        f"preco_maximo_para_regra "
                        f"{metricas.get('preco_maximo_para_regra')} != {teto}"
                    )

    # G6: as métricas têm que vir da base validada
    if metricas is None:
        erros["G6"].append("metricas ausentes: nao ha como provar a base validada")
    elif validacao is not None:
        base = metricas.get("base_dados")
        if base not in ("validado", "validado_sem_correcao"):
            erros["G6"].append(
                f"metricas nao usaram a base validada (base_dados={base!r})"
            )

    passou = {k: not v for k, v in erros.items()}
    return {"passou": passou, "erros": erros, "ok": all(passou.values())}


def _cita_numero(texto: str, valor: float) -> bool:
    """Aceita 0,3972 / 0.3972 / 39,72% / 39.7% / 39,7%."""
    v = float(valor or 0.0)
    opcoes = {
        f"{v:.4f}", f"{v:.4f}".replace(".", ","),
        f"{v*100:.1f}", f"{v*100:.1f}".replace(".", ","),
        f"{v*100:.2f}", f"{v*100:.2f}".replace(".", ","),
    }
    return any(o in texto for o in opcoes)


def grader_narrativa(analise, metricas: dict) -> List[str]:
    """G7: a justificativa tem que descrever a CONTA FINAL, não um retry anterior."""
    txt = str(getattr(analise, "justificativa_potencial", "") or "").lower()
    erros: List[str] = []
    if not any(p in txt for p in ("blend", "média", "media")):
        erros.append("G7: nao cita que o ARV e a MEDIA dos dois benchmarks")
    if not ("predi" in txt and "bairr" in txt):
        erros.append("G7: nao cita predicao E bairro")
    if not _cita_numero(txt, metricas.get("roi_conservador")):
        erros.append("G7: nao cita o ROI final calculado")
    return erros


def veredito_fallback(metricas: dict, tentativas: int, motivo: str) -> AnalisePotencialFlip:
    """Sintetiza o veredito quando o loop acaba sem narrativa válida.

    Mesma ideia do `garantir_etapas` do notebook: um número determinístico no
    lugar de um texto vazio ou de uma resposta presa em retry.
    """
    roi = _num(metricas.get("roi_conservador"))
    passa = bool(metricas.get("passa_regra_15pct"))
    arv = _num(metricas.get("arv_estimado"))
    teto = _num(metricas.get("preco_maximo_para_regra"))
    score = round(min(10.0, max(0.0, roi * 10)), 2)
    return AnalisePotencialFlip(
        score_potencial_flip=score,
        potencial_house_flip="True" if passa else "False",
        justificativa_potencial=(
            f"Veredito sintetizado pelo runner (loop encerrado: {motivo}, "
            f"{tentativas} tentativas). ARV blend {arv:,.0f}, ROI {roi:.2%}, "
            f"teto de compra {teto:,.0f}."
        ),
        riscos=["veredito sintetizado: sem justificativa valida do modelo"],
        recomendacoes=["revisar manualmente"],
        observacoes=f"motivo_fim={motivo}",
    )


def motivo_de_fim(
    state, *, agora: float, limites: Dict[str, Any]
) -> Optional[str]:
    """None = continua o loop; string = encerra com esse motivo."""
    if state.analise is None:
        return SEM_ANALISE
    if agora - _num(getattr(state, "inicio", agora), agora) > limites["timeout_s"]:
        return TIMEOUT
    if PARAR_SE_REPETE and getattr(state, "analise_anterior", None) is not None:
        if state.analise.model_dump_json() == state.analise_anterior.model_dump_json():
            return REPETIDO
    if getattr(state, "tentativa", 0) >= limites["max_tentativas"]:
        return LIMITE_TENTATIVAS
    return None
