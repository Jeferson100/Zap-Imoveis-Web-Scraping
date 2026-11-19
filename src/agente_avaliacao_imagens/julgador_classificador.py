"""Julgamento das fotos com o classificador ConvNeXt treinado no repositório.

Duas cabeças, na mesma imagem:

- **conservação**: 4 classes ordinais (`bem conservado` → `precário`), convertidas
  para a nota 0–10 de `AnaliseImagens` pelo valor esperado das probabilidades.
- **ambiente**: `interna` ou `externa`.

Os pesos ficam em `dados/modelo_fotos/<tarefa>/fold*.pt` (5 folds por tarefa).
O padrão é fazer ensemble de todos os folds; `IMAGENS_CLASSIFICADOR_FOLDS=5` usa
apenas o fold 5.

Uso:
    from agente_avaliacao_imagens.julgador_classificador import julgar_fotos
    analise = julgar_fotos(["https://.../foto.webp"])  # -> AnaliseImagens
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .config import (
    CLASSIFICADOR_DIR,
    CLASSIFICADOR_FOLDS,
    CLASSIFICADOR_MAX_FOTOS,
    CLASSIFICADOR_TTA,
)
from .schemas import AnaliseImagens

logger = logging.getLogger(__name__)

__all__ = [
    "LABELS",
    "AMBIENTES",
    "ClassificadorIndisponivel",
    "disponivel",
    "julgar_foto",
    "julgar_fotos",
    "julgar_fotos_detalhado",
    "montar_analise",
]

LABELS = ["bem conservado", "desgaste leve", "desgastado", "precário"]
AMBIENTES = ["interna", "externa"]
# Nota 0–10 ancorada nas classes ordinais (bem conservado = 10, precário = 0).
NOTA_POR_CLASSE = np.array([10.0, 6.7, 3.3, 0.0], dtype=np.float32)

REPO = Path(__file__).resolve().parent.parent.parent
PASTA_PADRAO = REPO / "dados" / "modelo_fotos"

_MODELOS: Optional[Dict[str, List[Tuple[Any, dict]]]] = None
_LOCK = threading.Lock()


class ClassificadorIndisponivel(RuntimeError):
    """Checkpoints do classificador ausentes ou dependências não instaladas."""


def _pasta() -> Path:
    return Path(CLASSIFICADOR_DIR) if CLASSIFICADOR_DIR else PASTA_PADRAO


def _folds(tarefa: str) -> List[Path]:
    arquivos = sorted((_pasta() / tarefa).glob("fold*.pt"))
    if CLASSIFICADOR_FOLDS != "all":
        alvo = f"fold{CLASSIFICADOR_FOLDS}.pt"
        arquivos = [a for a in arquivos if a.name == alvo]
    return arquivos


def disponivel() -> bool:
    """True se há checkpoints das duas tarefas (não carrega os pesos)."""
    return bool(_folds("conservacao")) and bool(_folds("ambiente"))


def _carregar() -> Dict[str, List[Tuple[Any, dict]]]:
    """Carrega os folds uma vez (thread-safe) e reusa nas chamadas."""
    global _MODELOS
    if _MODELOS is None:
        with _LOCK:
            if _MODELOS is None:
                try:
                    from classificador_fotos import carregar_checkpoint
                except Exception as exc:  # pragma: no cover - ambiente
                    raise ClassificadorIndisponivel(f"import de classificador_fotos: {exc}") from exc
                # Falha rapido: sem folds, `_prever_tarefa` devolveria nan 0-d e
                # o `np.dot` com NOTA_POR_CLASSE estourava em float() (CI sem os
                # pesos, que sao gitignored).
                faltando = [t for t in ("conservacao", "ambiente") if not _folds(t)]
                if faltando:
                    raise ClassificadorIndisponivel(
                        "pesos fold*.pt ausentes para: " + ", ".join(faltando)
                    )
                _MODELOS = {
                    tarefa: [carregar_checkpoint(p) for p in _folds(tarefa)]
                    for tarefa in ("conservacao", "ambiente")
                }
    return _MODELOS


def _prever_tarefa(tarefa: str, caminho: Path) -> np.ndarray:
    """Probabilidades médias dos folds para uma tarefa e uma imagem."""
    from classificador_fotos import prever_caminhos

    modelos = _carregar()[tarefa]
    if not modelos:
        raise ClassificadorIndisponivel(f"sem checkpoints para a tarefa '{tarefa}'")
    probs = []
    for modelo, ck in modelos:
        size = int(ck.get("img", 192))
        p = prever_caminhos(modelo, ck["base"], [caminho], size=size, tta=CLASSIFICADOR_TTA)
        probs.append(p[0])
    return np.mean(probs, axis=0)


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


def montar_analise(
    probs_conservacao: np.ndarray,
    probs_ambiente: np.ndarray,
    extra: Optional[Dict[str, Any]] = None,
    fotos_por_ambiente: Optional[Dict[str, int]] = None,
) -> AnaliseImagens:
    """Converte as duas distribuições de probabilidade para `AnaliseImagens`.

    `extra` permite preencher os campos por ambiente (interna/externa) sem
    duplicar a montagem. Separado da inferência para ser testável sem torch.
    """
    pc = np.asarray(probs_conservacao, dtype=float).ravel()
    pa = np.asarray(probs_ambiente, dtype=float).ravel()
    if pc.shape != (4,) or pa.shape != (2,):
        raise ValueError(f"esperado probs (4,) e (2,), veio {pc.shape} e {pa.shape}")

    idx = int(np.argmax(pc))
    nota = float(np.dot(pc, NOTA_POR_CLASSE))
    # Proxy documentado: o classificador só prevê conservação. Acabamento usa a
    # mesma nota; potencial de reforma é o complemento (pior estado -> mais ganho).
    dados: Dict[str, Any] = dict(
        score_conservacao=round(nota, 1),
        score_acabamento=round(nota, 1),
        score_potencial_reforma=round(10.0 - nota, 1),
        confianca_imagem=round(float(np.max(pc)) * 10.0, 1),
        imagem_aceitavel=True,
        problemas_visiveis=[],
        pontos_fortes=[],
        observacoes=(
            "classificador convnext-tiny-224 (ensemble de folds); "
            f"acabamento e potencial de reforma sao proxies da conservacao"
        ),
        ambiente=AMBIENTES[int(np.argmax(pa))],
        confianca_ambiente=round(float(np.max(pa)), 3),
        classe_conservacao=LABELS[idx],
        confianca_conservacao=round(float(np.max(pc)), 3),
    )
    if extra:
        dados.update(extra)
    if fotos_por_ambiente:
        dados["fotos_por_ambiente"] = dict(fotos_por_ambiente)
    return AnaliseImagens(**dados)


def julgar_foto(url_ou_caminho: str) -> AnaliseImagens:
    """Avalia uma foto (URL ou path local) com o classificador."""
    if not disponivel():
        raise ClassificadorIndisponivel("checkpoints do classificador ausentes")

    try:
        from classificador_fotos import baixar
    except Exception as exc:  # pragma: no cover - ambiente
        raise ClassificadorIndisponivel(f"import de classificador_fotos: {exc}") from exc

    try:
        caminho = Path(url_ou_caminho)
        if not caminho.is_file():
            caminho = Path(baixar(url_ou_caminho))
        pc = _prever_tarefa("conservacao", caminho)
        pa = _prever_tarefa("ambiente", caminho)
        return _agregar([pc], [pa])
    except Exception as exc:
        logger.exception("Falha no classificador de fotos")
        return _fallback(f"Falha no classificador: {type(exc).__name__}: {str(exc)[:200]}")


def _carregar_foto(url: str) -> Path:
    from classificador_fotos import baixar

    caminho = Path(url)
    return caminho if caminho.is_file() else Path(baixar(url))


def limite_fotos() -> int:
    """Limite efetivo de fotos (0 = todas), lido do ambiente a cada chamada.

    Ler a cada chamada evita o problema de kernel/processo que importou o modulo
    antes da variavel ser definida.
    """
    bruto = os.getenv("IMAGENS_CLASSIFICADOR_MAX_FOTOS")
    if bruto is None or str(bruto).strip() == "":
        return CLASSIFICADOR_MAX_FOTOS
    try:
        return int(str(bruto).strip())
    except (TypeError, ValueError):
        logger.warning("IMAGENS_CLASSIFICADOR_MAX_FOTOS invalido (%r); usando %s",
                       bruto, CLASSIFICADOR_MAX_FOTOS)
        return CLASSIFICADOR_MAX_FOTOS


def _limitar(urls: Sequence[str]) -> List[str]:
    """Filtra vazios e aplica `IMAGENS_CLASSIFICADOR_MAX_FOTOS` (0 = todas)."""
    limpos = [u for u in (urls or []) if u]
    limite = limite_fotos()
    if limite and limite > 0:
        return limpos[:limite]
    if len(limpos) > 20:
        logger.info(
            "classificador: %d fotos no anuncio (sem limite); o custo cresce por foto",
            len(limpos),
        )
    return limpos


def _grupos_por_ambiente(
    pcs: Sequence[np.ndarray], pas: Sequence[np.ndarray]
) -> Dict[str, List[np.ndarray]]:
    """Separa os vetores de conservação pelo ambiente previsto de cada foto."""
    grupos: Dict[str, List[np.ndarray]] = {nome: [] for nome in AMBIENTES}
    for pc, pa in zip(pcs, pas):
        grupos[AMBIENTES[int(np.argmax(pa))]].append(pc)
    return grupos


def _resumo_grupo(lista_pc: Sequence[np.ndarray]) -> Tuple[float, str, float]:
    """(nota, classe, confiança) para um conjunto de fotos do mesmo ambiente."""
    pc = np.asarray(np.mean(list(lista_pc), axis=0), dtype=float).ravel()
    if pc.shape != (4,):
        raise ValueError(f"esperado probs (4,) no grupo, veio {pc.shape}")
    return (
        round(float(np.dot(pc, NOTA_POR_CLASSE)), 1),
        LABELS[int(np.argmax(pc))],
        round(float(np.max(pc)), 3),
    )


def _agregar(pcs: Sequence[np.ndarray], pas: Sequence[np.ndarray]) -> AnaliseImagens:
    """Conservação pela média das distribuições; ambiente por voto majoritário.

    Também devolve a conservação separada por ambiente previsto das fotos.
    """
    pc = np.mean(list(pcs), axis=0)
    votos = [int(np.argmax(pa)) for pa in pas]
    contagem = {v: votos.count(v) for v in votos}
    maior = max(contagem.values())
    vencedor = next(v for v in votos if contagem[v] == maior)  # empate -> primeira foto
    pa = np.mean([p for p, v in zip(pas, votos) if v == vencedor], axis=0)

    grupos = _grupos_por_ambiente(pcs, pas)
    extra: Dict[str, Any] = {}
    for nome, lista in grupos.items():
        if not lista:
            continue
        try:
            nota, classe, conf = _resumo_grupo(lista)
        except ValueError as exc:
            logger.warning("classificador: grupo %s ignorado (%s)", nome, exc)
            continue
        extra[f"score_conservacao_{nome}"] = nota
        extra[f"classe_conservacao_{nome}"] = classe
        extra[f"confianca_conservacao_{nome}"] = conf

    return montar_analise(
        pc,
        pa,
        extra=extra,
        fotos_por_ambiente={nome: len(lista) for nome, lista in grupos.items()},
    )


def julgar_fotos(urls: Sequence[str]) -> AnaliseImagens:
    """Avalia até `IMAGENS_CLASSIFICADOR_MAX_FOTOS` fotos e devolve uma análise única.

    Conservação: média das distribuições. Ambiente: voto majoritário.
    """
    urls = _limitar(urls)
    if not urls:
        return _fallback("Sem fotos para o classificador")

    if not disponivel():
        # CI sem os pesos (dados/modelo_fotos e gitignored): sem esta guarda o
        # `_prever_tarefa` devolvia nan 0-d e o dot/float estourava TypeError.
        return _fallback("Pesos do classificador ausentes (fold*.pt); usando fallback")

    if len(urls) == 1:
        return julgar_foto(urls[0])

    pcs, pas = [], []
    for url in urls:
        try:
            caminho = _carregar_foto(url)
            pcs.append(_prever_tarefa("conservacao", caminho))
            pas.append(_prever_tarefa("ambiente", caminho))
        except Exception as exc:
            logger.warning("classificador: falha em %s (%s)", url, exc)

    if not pcs:
        return _fallback("Falha no classificador em todas as fotos")
    return _agregar(pcs, pas)


def julgar_fotos_detalhado(urls: Sequence[str]) -> Dict[str, Any]:
    """Avalia foto a foto e devolve `{"por_foto": [...], "agregado": AnaliseImagens}`.

    `por_foto` traz uma entrada por imagem (ambiente, conservacao, confiancas e nota)
    ou `{"url": ..., "erro": ...}` quando o download/inferência falha. `agregado`
    mantém a análise única do anúncio, usada pelos graders.
    """
    urls = _limitar(urls)
    if not urls:
        return {"por_foto": [], "agregado": _fallback("Sem fotos para o classificador")}

    if not disponivel():
        motivo = "Pesos do classificador ausentes (fold*.pt); usando fallback"
        return {"por_foto": [], "agregado": _fallback(motivo)}

    por_foto: List[Dict[str, Any]] = []
    pcs, pas = [], []
    for url in urls:
        try:
            caminho = _carregar_foto(url)
            pc = _prever_tarefa("conservacao", caminho)
            pa = _prever_tarefa("ambiente", caminho)
            analise = montar_analise(pc, pa)
        except Exception as exc:
            logger.warning("classificador: falha em %s (%s)", url, exc)
            por_foto.append({"url": url, "erro": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue

        pcs.append(pc)
        pas.append(pa)
        por_foto.append({
            "url": url,
            "ambiente": analise.ambiente,
            "confianca_ambiente": analise.confianca_ambiente,
            "conservacao": analise.classe_conservacao,
            "confianca_conservacao": analise.confianca_conservacao,
            "nota": analise.score_conservacao,
        })

    if not pcs:
        return {"por_foto": por_foto, "agregado": _fallback("Falha no classificador em todas as fotos")}

    return {"por_foto": por_foto, "agregado": _agregar(pcs, pas)}
