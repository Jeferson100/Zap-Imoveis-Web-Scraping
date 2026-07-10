import asyncio
import importlib
import os
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.agente_avaliacao_imagens.schemas import AnaliseImagens, CategoriaConservacao
from src.agente_avaliacao_imagens.subgrafos.subgrafo_imagens import SubgrafoImagensState

subgrafo_imagens_module = importlib.import_module(
    "src.agente_avaliacao_imagens.subgrafos.subgrafo_imagens"
)


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


def test_descrever_fotos_usa_url_direto(monkeypatch):
    captured = {}

    async def fake_enviar_vision(router_vision, content, model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"):
        captured["content"] = content
        return "descrição"

    monkeypatch.setattr(subgrafo_imagens_module, "_enviar_vision", fake_enviar_vision)

    state = SubgrafoImagensState(
        fotos_urls=[
            "https://www.chavesnamao.com.br/imn/1200x0800/N/75/imoveis/154808/41822648/sc-joinville-atiradores-rua-alberto-kroehne-apartamento-a-venda-3-quartos-69e93b5d-1.jpg"
        ],
        usar_url_direto=True,
    )

    result = asyncio.run(subgrafo_imagens_module.descrever_fotos(state))

    assert result["descricoes"] == ["descrição"]
    assert captured["content"][1]["type"] == "image_url"
    assert captured["content"][1]["image_url"]["url"] == state.fotos_urls[0]
