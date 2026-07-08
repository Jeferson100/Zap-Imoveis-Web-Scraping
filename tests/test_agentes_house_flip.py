from src.agentes_house_flip.schemas import AnaliseImagens, CategoriaConservacao


def test_analise_imagens_suporta_campos_de_conservacao():
    analise = AnaliseImagens(
        score_conservacao=7.5,
        score_acabamento=6.0,
        score_potencial_reforma=8.0,
        confianca_imagem=8.5,
        imagem_aceitavel=True,
        categorias_conservacao=[
            CategoriaConservacao(
                nome="pintura",
                score=7.0,
                severidade="BAIXA",
                evidencias=["Pintura sem manchas aparentes"],
                necessidade_reparo=False,
            )
        ],
        problemas_visiveis=[],
        pontos_fortes=["Boa iluminação"],
        observacoes="Imóvel com conservação regular.",
    )

    assert analise.confianca_imagem == 8.5
    assert analise.imagem_aceitavel is True
    assert analise.categorias_conservacao[0].nome == "pintura"
