"""Loop engineering: graders G1–G7, fallback e condições de fim."""

from types import SimpleNamespace

from agente_potencial_flip.loop_engineering import (
    LIMITE_TENTATIVAS,
    REPETIDO,
    TIMEOUT,
    avaliar_graders,
    grader_narrativa,
    motivo_de_fim,
    veredito_fallback,
)
from agente_potencial_flip.schemas import AnalisePotencialFlip
from agente_potencial_flip.tools_flip import calcular_metricas_flip

DADOS = {
    "valor_imovel": 480000,
    "metragem": 100,
    "valor_predito": 688000,   # 6880/m2
    "p50_bairro": 4800,
}
METRICAS = calcular_metricas_flip(DADOS)


def analise(roi_pass=True, texto=None):
    if texto is None:
        roi = METRICAS["roi_conservador"]
        texto = (f"Média entre predição 6880/m² e bairro 4800/m², ARV 584000, "
                 f"ROI final {roi*100:.2f}%")
    return AnalisePotencialFlip(
        score_potencial_flip=9.0,
        potencial_house_flip="True" if roi_pass else "False",
        justificativa_potencial=texto,
        riscos=[], recomendacoes=[], observacoes="",
    )


def test_blend_e_grader_g5():
    # (6880 + 4800) / 2 * 100 = 584000  (o antigo max dava 688000)
    assert METRICAS["arv_estimado"] == 584000.0
    assert METRICAS["arv_fonte"] == "blend_mediana_predicao"
    assert METRICAS["valor_m2_blend"] == 5840.0
    res = avaliar_graders(None, analise(), None, METRICAS)
    assert res["passou"]["G5"], res["erros"]["G5"]


def test_fallback_imagem_nao_reprova_g1_g2():
    # Quando o classificador cai em fallback (sem pesos no CI), ambiente='desconhecido'
    # e conservacao=None/'indefinido'. G1 e G2 nao devem reprovar.
    img_fallback = SimpleNamespace(
        ambiente="desconhecido",
        classe_conservacao=None,
        confianca_ambiente=0.0,
        confianca_conservacao=0.0,
        score_conservacao=0.0,
        problemas_visiveis=["Pesos do classificador ausentes (fold*.pt); usando fallback"],
    )
    res = avaliar_graders(img_fallback, analise(), None, METRICAS)
    assert res["passou"]["G1"] is True
    assert res["passou"]["G2"] is True


def test_g3_reprova_justificativa_incompleta_e_incoerencia():
    # Justificativa curta ou de etapa intermediaria
    bad_analise = analise()
    bad_analise.justificativa_potencial = "Iniciando avaliação - etapa 1: classificar fotos"
    res = avaliar_graders(None, bad_analise, None, METRICAS)
    assert res["passou"]["G3"] is False
    assert any("etapa em andamento" in e for e in res["erros"]["G3"])

    # Incoerência: True mas score baixo (< 5.0)
    incoerente = analise()
    incoerente.score_potencial_flip = 2.3
    incoerente.potencial_house_flip = "True"
    res = avaliar_graders(None, incoerente, None, METRICAS)
    assert res["passou"]["G3"] is False
    assert any("potencial_house_flip=True mas score=2.3" in e for e in res["erros"]["G3"])


def test_g4_reprova_flip_sem_roi():
    Metricas = dict(METRICAS, passa_regra_15pct=False)
    res = avaliar_graders(None, analise(roi_pass=True), None, Metricas)
    assert res["passou"]["G4"] is False


def test_g7_narrativa():
    roi = METRICAS["roi_conservador"]
    assert grader_narrativa(analise(), METRICAS) == []
    erros = grader_narrativa(
        analise(texto="A ferramenta retornou métricas zeradas, ROI 0%"), METRICAS
    )
    assert any("G7" in e for e in erros)


def test_veredito_fallback():
    v = veredito_fallback(METRICAS, 2, LIMITE_TENTATIVAS)
    assert v.potencial_house_flip == ("True" if METRICAS["passa_regra_15pct"] else "False")
    assert "sintetizado" in v.justificativa_potencial


def test_motivo_fim():
    base = {"timeout_s": 180, "max_tentativas": 2}
    st = SimpleNamespace(
        analise=analise(), analise_anterior=None, tentativa=1, inicio=0.0,
    )
    assert motivo_de_fim(st, agora=10.0, limites=base) is None
    assert motivo_de_fim(st, agora=200.0, limites=base) == TIMEOUT
    st.analise_anterior = st.analise
    assert motivo_de_fim(st, agora=10.0, limites=base) == REPETIDO
    st.analise_anterior = None
    st.tentativa = 2
    assert motivo_de_fim(st, agora=10.0, limites=base) == LIMITE_TENTATIVAS
