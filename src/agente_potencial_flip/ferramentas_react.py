"""Ferramentas e middleware do agente ReAct (extraido de c0de6002).

As 5 ferramentas rodam na ordem do prompt; uma depende da outra.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.middleware import AgentMiddleware, HumanInTheLoopMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from agente_avaliacao_imagens.config import CLASSIFICADOR_POR_FOTO, CLASSIFICADOR_SAIDA_COMPLETA
from agente_avaliacao_imagens.julgador_classificador import julgar_fotos, julgar_fotos_detalhado
from agente_potencial_flip.modelo_llm import (
    criar_modelo_flip,
    criar_modelo_flip_com_fallbacks,
    modelos_fallback,
)
from agente_potencial_flip.schemas import AnalisePotencialFlip
from agente_potencial_flip.tools_flip import explicar_metricas, metricas_flip_tool, think_tool
from shared.serialization import converter_numpy
from agente_potencial_flip.trace_flip import ExigePensamento
from agente_validacao.subgrafo_validacao import subgrafo_validacao, SubgrafoValidacaoState
from agente_potencial_flip.comparaveis_proximos import (
    min_comparaveis_arv,
    usar_proximos_no_arv,
)
from agente_potencial_flip.loop_engineering import avaliar_graders

logger = logging.getLogger("agente_ci")

REPO = Path(__file__).resolve().parents[2]
ARQ_RUNS = REPO / "dados" / "agente_avaliacoes" / "runs.parquet"
ARQ_PROPOSTA = REPO / "dados" / "agente_avaliacoes" / "proposta_harness.md"

ESTADO_AGENTE = {}
SESSOES = {}
MODELO_AGENTE = os.environ.get("FLIP_MODEL_ID", "").strip() or criar_modelo_flip()
# MODELO_AGENTE precisa ser um ChatOpenAI puro: o `resolve_model` do deepagents
# nao aceita RunnableWithFallbacks — o fallback entra no AGENTE INTEIRO
# (criar_agente), nao no modelo.
print("modelo do agente:", MODELO_AGENTE if isinstance(MODELO_AGENTE, str)
      else type(MODELO_AGENTE).__name__)

# O deep agent sempre injeta TodoList/Filesystem/SubAgent. O subagente
# general-purpose traz a ferramenta `task`, que o modelo usava para re-delegar
# em loop e estourar a recursao (ver AGENTS.md). Desligamos APENAS ele; as
# ferramentas de filesystem sao obrigatorias no harness e ficam -- o prompt
# manda ignora-las.
_ID_MODELO = (MODELO_AGENTE if isinstance(MODELO_AGENTE, str)
              else (getattr(MODELO_AGENTE, "model_name", "")
                    or getattr(MODELO_AGENTE, "model", "")))
if _ID_MODELO:
    # `task` e o general-purpose saem (causa da recursao); as ferramentas de
    # filesystem/planjamento tambem saem — elas distraiam o modelo (ls 57x e
    # think_tool 66x sem registrar_decisao no smoke do deep agent).
    register_harness_profile(
        f"openai:{_ID_MODELO}",
        HarnessProfile(
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            excluded_tools=[
                "ls", "read_file", "write_file", "edit_file", "glob", "grep",
                "delete", "execute", "write_todos", "task",
            ],
        ),
    )
    logger.info("harness profile: general-purpose/task desligado para %s", _ID_MODELO)


# think_tool com schema corrigido para o deep agent: o proxima_acao do
# `tools_flip.EntradaPensamento` ainda lista `task:fotografo | task:dados`,
# que nao existem aqui e faziam o modelo repetir o think sem avancar.
class EntradaPensamento(BaseModel):
    pensamento: str = Field(
        description="Raciocinio em 1-3 frases: o que ja sei, o que falta, o que vou fazer."
    )
    proxima_acao: str = Field(
        description=(
            "classificar_fotos_tool | validar_dados_tool | calcular_metricas_tool "
            "| registrar_decisao"
        )
    )


@tool(args_schema=EntradaPensamento)
def think_tool(pensamento: str, proxima_acao: str) -> str:
    """Registre o raciocinio ANTES da proxima ferramenta e ANTES do veredito."""
    logger.info("THINK[%s] %s", proxima_acao, pensamento)
    return "registrado"


PROXIMO_PASSO = {
    "classificar_fotos_tool": "validar_dados_tool",
    "validar_dados_tool": "calcular_metricas_tool",
    "calcular_metricas_tool": "think_tool",
    "think_tool": "registrar_decisao",
}

def _marcar(nome: str, saida: dict) -> dict:
    """Acrescenta o proximo passo e, se a tool ja rodou, o aviso anti-laco."""
    chave = f"_n_{nome}"
    n = ESTADO_AGENTE.get(chave, 0) + 1
    ESTADO_AGENTE[chave] = n
    proximo = PROXIMO_PASSO.get(nome)
    if proximo:
        saida["proximo_passo"] = proximo
    if n > 1:
        saida["aviso"] = (
            f"{nome} ja rodou {n}x nesta sessao e o resultado e o mesmo. "
            f"NAO repita: chame {proximo} agora."
        )
    return saida


@tool
async def classificar_fotos_tool(
    fotos_urls: list[str] | None = None, refazer: bool = False
) -> str:
    """Classifica as fotos com o preditor ConvNeXt: ambiente (interna/externa) e conservacao (4 classes).

    Com IMAGENS_CLASSIFICADOR_POR_FOTO=true devolve tambem uma entrada por foto.
    Sem argumento, usa as fotos do anuncio em avaliacao. Repetir a chamada para
    o mesmo conjunto devolve cache ("fonte": "cache"): nunca reclassifica 30+
    fotos por engano. `refazer=True` forca nova predicao.
    """
    urls = list(fotos_urls or []) or list(
        (ESTADO_AGENTE.get("payload") or {}).get("fotos_urls") or []
    )
    if not urls:
        return json.dumps({"erro": "sem fotos no anuncio"}, ensure_ascii=False)

    reaproveita = (
        not refazer
        and ESTADO_AGENTE.get("imagem_resumo") is not None
        and tuple(urls) == ESTADO_AGENTE.get("imagem_urls")
    )
    if reaproveita:
        cache = dict(ESTADO_AGENTE["imagem_resumo"])
        cache["fonte"] = "cache"
        return json.dumps(_marcar("classificar_fotos_tool", cache), ensure_ascii=False)

    if not CLASSIFICADOR_POR_FOTO:
        imagem = await asyncio.to_thread(julgar_fotos, urls)
        ESTADO_AGENTE["imagem"] = imagem
        ESTADO_AGENTE["imagem_urls"] = tuple(urls)
        ESTADO_AGENTE["imagem_resumo"] = imagem.resumo()
        if CLASSIFICADOR_SAIDA_COMPLETA:
            return imagem.model_dump_json()
        saida = _marcar("classificar_fotos_tool", dict(imagem.resumo()))
        saida["fonte"] = "preditor"
        return json.dumps(saida, ensure_ascii=False)

    detalhe = await asyncio.to_thread(julgar_fotos_detalhado, urls)
    agregado = detalhe["agregado"]
    ESTADO_AGENTE["imagem"] = agregado
    ESTADO_AGENTE["imagem_por_foto"] = detalhe["por_foto"]
    ESTADO_AGENTE["imagem_urls"] = tuple(urls)
    ESTADO_AGENTE["imagem_resumo"] = agregado.resumo()
    bruto = {
        "por_foto": detalhe["por_foto"],
        "agregado": agregado.model_dump() if CLASSIFICADOR_SAIDA_COMPLETA else agregado.resumo(),
        "fonte": "preditor",
    }
    return json.dumps(_marcar("classificar_fotos_tool", bruto), ensure_ascii=False)


@tool
async def validar_dados_tool(
    dados_imovel_json: str = "", descricao_texto: str = "", refazer: bool = False
) -> str:
    """Confere os numeros do anuncio contra a descricao, usando o subgrafo de validacao.

    Sem argumentos, valida o imovel em avaliacao (payload atual). Repetir a
    chamada devolve cache ("fonte": "cache") em vez de gastar outra chamada de
    LLM; `refazer=True` forca nova validacao.
    """
    payload_atual = ESTADO_AGENTE.get("payload") or {}
    explicito = bool(str(dados_imovel_json).strip() or str(descricao_texto).strip())
    em_cache = ESTADO_AGENTE.get("validacao")
    if em_cache is not None and not refazer and not explicito:
        corpo = _marcar("validar_dados_tool", json.loads(em_cache.model_dump_json()))
        corpo["fonte"] = "cache"
        return json.dumps(corpo, ensure_ascii=False)
    if not str(dados_imovel_json).strip():
        dados_imovel_json = json.dumps(
            payload_atual.get("dados_imovel") or {}, ensure_ascii=False, default=str
        )
    if not descricao_texto:
        descricao_texto = str(payload_atual.get("descricao_texto") or "")
    try:
        dados = json.loads(dados_imovel_json)
    except (TypeError, ValueError) as exc:
        return json.dumps({"erro": f"JSON invalido em dados_imovel_json: {exc}"[:200]}, ensure_ascii=False)
    res = await subgrafo_validacao.ainvoke(SubgrafoValidacaoState(
        dados_imovel=dados,
        descricao_texto=descricao_texto or "",
        api_key=None,
        max_tentativas=0,
    ))
    validacao = res.get("analise")
    ESTADO_AGENTE["validacao"] = validacao
    if validacao is None:
        return json.dumps({"erro": "validacao indisponivel"}, ensure_ascii=False)
    corpo = _marcar("validar_dados_tool", json.loads(validacao.model_dump_json()))
    corpo["fonte"] = "validador"
    return json.dumps(corpo, ensure_ascii=False)


def _dados_para_metricas(payload, validacao):
    """Dados do imovel ajustados pela validacao. So metragem e valor_imovel.

    valor_predito/p50_bairro ficam intocados de proposito: se o LLM pudesse
    "corrigi-los", o ROI deixaria de ser deterministico e o G4 perderia o
    sentido (a regra de 15% passaria a depender da opiniao do modelo).
    """
    dados = dict((payload or {}).get("dados_imovel") or {})
    # O modelo nem sempre preenche os campos *_corrigido; quando ele so devolve
    # `dados_corrigidos`, as chaves de la sao a fonte da correcao.
    devolvidos = getattr(validacao, "dados_corrigidos", None) or {}
    campos = {
        "metragem": ("metragem_corrigida", "metragem"),
        "valor_imovel": ("valor_imovel_corrigido", "valor_imovel"),
    }
    corrigidos = {}
    for campo, (atributo, chave) in campos.items():
        valor = getattr(validacao, atributo, None)
        corrigidos[campo] = valor if valor is not None else devolvidos.get(chave)
    aplicadas = {}
    for campo, valor in corrigidos.items():
        try:
            novo = float(valor)
        except (TypeError, ValueError):
            continue
        if novo <= 0 or novo != novo:
            continue
        antigo = dados.get(campo)
        try:
            mudou = antigo is None or abs(float(antigo) - novo) > 0.01
        except (TypeError, ValueError):
            mudou = True
        if mudou:
            aplicadas[campo] = {"de": antigo, "para": novo}
        dados[campo] = novo
    return dados, aplicadas


@tool
def calcular_metricas_tool(dados_imovel_json: str = "", refazer: bool = False) -> str:
    """Calcula preco_por_m2, ARV, custo de reforma, lucro e ROI, com a memoria de calculo.

    Fonte unica dos numeros. Sem argumento, pega o imovel em avaliacao. Se
    validar_dados_tool ja rodou, usa metragem/valor corrigidos; se nao, calcula
    no bruto e marca `base_dados="bruto_sem_validacao"` (o G6 reprova).
    """
    validacao = ESTADO_AGENTE.get("validacao")
    payload = ESTADO_AGENTE.get("payload") or {}
    bruto = str(dados_imovel_json or "").strip()

    em_cache = ESTADO_AGENTE.get("metricas_tool")
    if em_cache is not None and not refazer and not bruto:
        saida = _marcar("calcular_metricas_tool", dict(em_cache))
        saida["fonte"] = "cache"
        return json.dumps(saida, ensure_ascii=False, default=str)
    if bruto:
        try:
            informado = json.loads(bruto)
        except (TypeError, ValueError) as exc:
            return json.dumps({"erro": f"JSON invalido: {exc}"[:200]}, ensure_ascii=False)
        if not isinstance(informado, dict):
            return json.dumps({"erro": "JSON invalido: esperado um objeto"}, ensure_ascii=False)
        # O JSON do modelo COMPLEMENTA o imovel em avaliacao; nao substitui.
        # Substituir apagava valor_predito/p50_bairro e o ARV caia para
        # `sem_ancora` (5 de 10 imoveis no CI).
        if validacao is not None:
            dados, aplicadas = _dados_para_metricas(payload, validacao)
            base = "validado" if aplicadas else "validado_sem_correcao"
        else:
            dados = dict(payload.get("dados_imovel") or {})
            aplicadas, base = {}, "bruto_sem_validacao"
        dados.update(informado)
        # Ancoras do anuncio nunca sao sobrescritas pelo modelo: o ROI precisa
        # continuar deterministico (mesma regra do _dados_para_metricas).
        originais = payload.get("dados_imovel") or {}
        for campo in ("valor_predito", "p50_bairro", "preco_por_m2"):
            if campo in originais:
                dados[campo] = originais[campo]
    elif validacao is not None:
        dados, aplicadas = _dados_para_metricas(payload, validacao)
        base = "validado" if aplicadas else "validado_sem_correcao"
    else:
        # Recusar fez o modelo desistir da etapa em 6 de 10 imoveis: ele recebia
        # o erro e respondia sem numero. Calcular sempre, e marcar a origem para
        # o grader julgar, da o mesmo sinal sem abrir espaco para desistencia.
        dados = dict(payload.get("dados_imovel") or {})
        aplicadas, base = {}, "bruto_sem_validacao"

    # Comparaveis proximos (mesma rua ou raio 300m): quando a publicacao traz rua
    # real e ha >= min_comparaveis_arv() vizinhos (default 5), usa p50_m2_proximos
    # no lugar do p50_bairro para o ARV refletir a microrregiao.
    comp = payload.get("comparaveis_proximos")
    p50_bairro_original = dados.get("p50_bairro")
    usou_proximos_no_arv = False
    if (
        isinstance(comp, dict)
        and usar_proximos_no_arv()
        and int(comp.get("n_comparaveis") or 0) >= min_comparaveis_arv()
        and float(comp.get("p50_m2_proximos") or 0) > 0
    ):
        dados = dict(dados)
        dados["p50_bairro"] = float(comp["p50_m2_proximos"])
        usou_proximos_no_arv = True

    detalhe = converter_numpy(explicar_metricas(dados))
    detalhe["base_dados"] = base
    detalhe["correcoes_aplicadas"] = aplicadas
    detalhe["fonte"] = "metricas"
    if isinstance(comp, dict):
        detalhe["comparaveis_proximos"] = converter_numpy({
            **comp,
            "usado_no_arv": usou_proximos_no_arv,
            "p50_bairro_original": p50_bairro_original,
        })
    detalhe["validacao"] = None if validacao is None else {
        "dados_consistentes": getattr(validacao, "dados_consistentes", None),
        "possui_erros": getattr(validacao, "possui_erros", None),
        "inconsistencias": list(getattr(validacao, "inconsistencias_encontradas", []) or []),
    }
    ESTADO_AGENTE["metricas_tool"] = detalhe
    return json.dumps(_marcar("calcular_metricas_tool", detalhe),
                      ensure_ascii=False, default=str)


@tool
def registrar_decisao(potencial_house_flip: str, score_potencial_flip: float, resumo: str) -> str:
    """Grava o veredito final. So executa depois da aprovacao humana (interrupt_on)."""
    registro = {
        "potencial_house_flip": str(potencial_house_flip),
        "score_potencial_flip": float(score_potencial_flip),
        "resumo": resumo,
    }
    ESTADO_AGENTE["decisao"] = registro
    # Devolve o registro em JSON: o runner reconstrói a decisão a partir do
    # histórico da thread, que é a fonte do que foi de fato aprovado/executado.
    return json.dumps({"registrado": registro}, ensure_ascii=False)


class VerificadorGraders(AgentMiddleware):
    """Loop 2 do artigo: grader deterministico anexado ao agente (after_agent).

    Com response_format, o veredito chega em structured_response, nao por tool.
    """

    async def aafter_agent(self, state, runtime):
        flip = None
        if isinstance(state, dict):
            flip = state.get("structured_response")
        flip = flip or ESTADO_AGENTE.get("flip")
        if flip is not None:
            ESTADO_AGENTE["flip"] = flip
        imagem = ESTADO_AGENTE.get("imagem")
        if imagem is None or flip is None:
            return None
        ESTADO_AGENTE["graders"] = avaliar_graders(
            imagem, flip, ESTADO_AGENTE.get("validacao"), ESTADO_AGENTE.get("metricas_tool")
        )
        return None


SYSTEM_FLIP_NB = """Voce e um investidor senior de Fix & Flip.
A mensagem traz apenas o anuncio (FOTOS_URLS, DADOS_IMOVEL_JSON, DESCRICAO).
Imagem, validacao e metricas vem das suas ferramentas, nesta ordem:
 ETAPA 1: classificar_fotos_tool (SEM argumentos). Preditor ConvNeXt: ambiente
          (interna/externa) e conservacao em 4 classes. Nao existe LLM de visao.
          Repetir a chamada devolve cache ("fonte": "cache"): chame UMA vez.
 ETAPA 2: validar_dados_tool (SEM argumentos). Confere os numeros do anuncio
          contra a descricao e devolve metragem/valor corrigidos.
 ETAPA 3: calcular_metricas_tool (SEM argumentos). Usa os dados VALIDADOS e
          devolve o resultado de cada operacao (formula, entradas, resultado).
 ETAPA 4: think_tool conciliando imagem + validacao + metricas.
 ETAPA 5: registrar_decisao com potencial_house_flip, score_potencial_flip e resumo.
          OBRIGATORIA: e a unica forma de gravar o veredito e pedir aprovacao
          humana. Nao responda o veredito estruturado antes dela.
Depois disso, responda com o veredito estruturado.
Regras:
0) Todas as tools funcionam SEM argumentos: usam o imovel em avaliacao. Nao peca URLs nem JSON ao usuario.
0.1) NUNCA repita uma ferramenta que ja devolveu resultado nesta conversa: use o retorno e siga.
     Cada resposta traz `proximo_passo` (e `aviso` quando voce repetiu): obedeca a ele.
     Nao existe task() nem subagente: nunca escreva `task:...` em proxima_acao.
0.2) A ordem 1 -> 2 -> 3 e obrigatoria: sem `calcular_metricas_tool` executada, `registrar_decisao` e DEVOLVIDA sem gravar nada -- responder antes nao registra veredito.
0.3) UMA ferramenta por turno: espere o resultado antes da proxima. Nunca emita
     validar_dados_tool e calcular_metricas_tool no mesmo turno (elas rodam em
     paralelo e as metricas veriam a validacao ainda vazia).
1) score_potencial_flip e OBRIGATORIAMENTE um numero de 0 a 10 (nota, nao percentual).
   potencial_house_flip e exatamente a string "True" ou "False".
2) Use somente os numeros devolvidos por calcular_metricas_tool; nao recalcule ROI, ARV nem preco_por_m2.
3) Sem fotos no anuncio, pule a ETAPA 1 e avalie com numeros e descricao.
4) potencial_house_flip="True" SOMENTE se passa_regra_15pct for true; se for false, responda "False" mesmo que as fotos parecam boas.
5) O custo de reforma e R$ 1.500/m2 (FLIP_CUSTO_REFORMA_M2) e ja vem descontado em lucro_projetado. Nao invente outro valor nem estime escala de reforma por conta propria.
6) Se aparecer "correcoes_aplicadas", os numeros corrigidos pela validacao ja foram usados: nao os substitua.
7) Para recomendar preco de entrada, use `preco_maximo_para_regra` (teto de compra que ainda fecha os 15%) e `margem_vs_arv_pct` do `contexto`. Nao estime outro alvo de negociacao.
Responda em portugues."""


SYSTEM_FLIP_NB = """Voce e um investidor senior de Fix & Flip.
A mensagem traz apenas o anuncio (FOTOS_URLS, DADOS_IMOVEL_JSON, DESCRICAO).
Imagem, validacao e metricas vem das suas ferramentas, nesta ordem:
 ETAPA 1: classificar_fotos_tool (SEM argumentos). Preditor ConvNeXt: ambiente
          (interna/externa) e conservacao em 4 classes. Nao existe LLM de visao.
          Repetir a chamada devolve cache ("fonte": "cache"): chame UMA vez.
 ETAPA 2: validar_dados_tool (SEM argumentos). Confere os numeros do anuncio
          contra a descricao e devolve metragem/valor corrigidos.
 ETAPA 3: calcular_metricas_tool (SEM argumentos). Usa os dados VALIDADOS e
          devolve o resultado de cada operacao (formula, entradas, resultado).
 ETAPA 4: think_tool conciliando imagem + validacao + metricas.
 ETAPA 5: registrar_decisao com potencial_house_flip, score_potencial_flip e resumo.
          OBRIGATORIA: e a unica forma de gravar o veredito e pedir aprovacao
          humana. Nao responda o veredito estruturado antes dela.
Depois disso, responda com o veredito estruturado.
Regras:
0) Todas as tools funcionam SEM argumentos: usam o imovel em avaliacao. Nao peca URLs nem JSON ao usuario.
0.1) NUNCA repita uma ferramenta que ja devolveu resultado nesta conversa: use o retorno e siga.
     Cada resposta traz `proximo_passo` (e `aviso` quando voce repetiu): obedeca a ele.
     Nao existe task() nem subagente: nunca escreva `task:...` em proxima_acao.
0.2) A ordem 1 -> 2 -> 3 e obrigatoria: sem `calcular_metricas_tool` executada, `registrar_decisao` e DEVOLVIDA sem gravar nada -- responder antes nao registra veredito.
0.3) UMA ferramenta por turno: espere o resultado antes da proxima. Nunca emita
     validar_dados_tool e calcular_metricas_tool no mesmo turno (elas rodam em
     paralelo e as metricas veriam a validacao ainda vazia).
1) score_potencial_flip e OBRIGATORIAMENTE um numero de 0 a 10 (nota, nao percentual).
   potencial_house_flip e exatamente a string "True" ou "False".
2) Use somente os numeros devolvidos por calcular_metricas_tool; nao recalcule ROI, ARV nem preco_por_m2.
3) Sem fotos no anuncio, pule a ETAPA 1 e avalie com numeros e descricao.
4) potencial_house_flip="True" SOMENTE se passa_regra_15pct for true; se for false, responda "False" mesmo que as fotos parecam boas.
5) O custo de reforma e R$ 1.500/m2 (FLIP_CUSTO_REFORMA_M2) e ja vem descontado em lucro_projetado. Nao invente outro valor nem estime escala de reforma por conta propria.
6) Se aparecer "correcoes_aplicadas", os numeros corrigidos pela validacao ja foram usados: nao os substitua.
7) Para recomendar preco de entrada, use `preco_maximo_para_regra` (teto de compra que ainda fecha os 15%) e `margem_vs_arv_pct` do `contexto`. Nao estime outro alvo de negociacao.
Responda em portugues."""


class MenuEnxuto(AgentMiddleware):
    """Tira do menu so a ferramenta que JA rodou; as pendentes continuam livres.

    O corta-circuito anterior removia TODAS as ferramentas ao atingir N
    ToolMessages. Como think_tool conta no total, o modelo que pensava antes de
    cada etapa chegava ao teto com calcular_metricas_tool ainda pendente e era
    forcado a responder sem conta -- o remedio virava a doenca. Retirar apenas o
    que ja foi feito corta a repeticao (que cairia no cache de qualquer jeito)
    sem fechar o caminho das pedras.
    """


SYSTEM_FLIP_NB += (
    "\n8) Este e um deep agent: podem aparecer ferramentas de filesystem "
    "(ls, read_file, write_file, edit_file, glob, grep, delete, execute) e de "
    "planejamento. IGNORE-AS: nao fazem parte da avaliacao. Use SOMENTE as 5 "
    "ferramentas do flip, na ordem 1 a 5. Nunca delegue, nunca crie tarefas, "
    "nunca escreva arquivos."
    "\n9) Se `calcular_metricas_tool` devolver `comparaveis_proximos` (imovel com "
    "rua informada), cite na justificativa e nos riscos a origem (`mesma_rua` ou "
    "`raio_300m`), a quantidade `n_comparaveis` e a mediana `p50_m2_proximos` "
    "comparada ao preco/m2 do imovel. Quando `usado_no_arv=true`, deixe explicito "
    "que o ARV usou os comparaveis proximos no lugar da mediana do bairro."
)


class MenuEnxuto(AgentMiddleware):
    """Tira do menu so a ferramenta que JA rodou; as pendentes continuam livres.

    O corta-circuito anterior removia TODAS as ferramentas ao atingir N
    ToolMessages. Como think_tool conta no total, o modelo que pensava antes de
    cada etapa chegava ao teto com calcular_metricas_tool ainda pendente e era
    forcado a responder sem conta -- o remedio virava a doenca. Retirar apenas o
    que ja foi feito corta a repeticao (que cairia no cache de qualquer jeito)
    sem fechar o caminho das pedras.
    """

    FEITO = {"classificar_fotos_tool": "imagem",
             "validar_dados_tool": "validacao",
             "calcular_metricas_tool": "metricas_tool"}

    async def awrap_model_call(self, request, handler):
        ferramentas = list(request.tools or [])
        if not ferramentas:
            return await handler(request)
        feitas = {nome for nome, chave in self.FEITO.items()
                  if ESTADO_AGENTE.get(chave) is not None}
        if not feitas:
            return await handler(request)
        restantes = [t for t in ferramentas
                     if getattr(t, "name", None) not in feitas]
        if len(restantes) != len(ferramentas):
            logger.info("menu enxuto: %s ja rodaram, saem do menu", sorted(feitas))
            request = request.override(tools=restantes)
        return await handler(request)


class ExigeAnaliseCompleta(AgentMiddleware):
    """Barra registrar_decisao ate a conta de flip existir.

    Em 6 de 10 imoveis o modelo respondeu `potencial_house_flip=True` sem nunca
    chamar calcular_metricas_tool, e o texto do prompt nao segurou. Aqui a
    chamada devolve uma ToolMessage dizendo exatamente o que falta. Como a tool
    de metricas nao recusa mais, obedecer custa uma chamada -- nao vira laco.
    """

    FALTAS = (("metricas_tool", "calcular_metricas_tool"),
              ("validacao", "validar_dados_tool"))

    async def awrap_tool_call(self, request, handler):
        nome = str((request.tool_call or {}).get("name") or "")
        if nome != "registrar_decisao":
            return await handler(request)

        faltando = [rotulo for chave, rotulo in self.FALTAS
                    if ESTADO_AGENTE.get(chave) is None]
        if faltando:
            return ToolMessage(
                content=(
                    "NAO REGISTRADO: faltam " + " e ".join(faltando) + ". Chame "
                    + " e ".join(faltando) + " sem argumentos e repita "
                    "registrar_decisao. Veredito sem conta nao e avaliado."
                ),
                tool_call_id=(request.tool_call or {}).get("id"),
                name=nome,
            )
        return await handler(request)


def _middlewares():
    base = [
        ExigeAnaliseCompleta(),
        MenuEnxuto(),
        ExigePensamento(vigiadas=("registrar_decisao",)),
        VerificadorGraders(),
        HumanInTheLoopMiddleware(interrupt_on={"registrar_decisao": True}),
    ]
    return base






def _deep_agent(modelo):
    """Deep agent com o subagente general-purpose desligado (sem tool `task`).

    O harness injeta TodoList/Filesystem/SubAgent; o perfil registrado no topo
    remove o general-purpose (a tool `task` era a causa da recursao). As
    ferramentas de filesystem sao obrigatorias e o prompt manda ignora-las.
    """
    return create_deep_agent(
        model=modelo,
        tools=[classificar_fotos_tool, validar_dados_tool,
               calcular_metricas_tool, think_tool, registrar_decisao],
        middleware=_middlewares(),
        system_prompt=SYSTEM_FLIP_NB,
        response_format=AnalisePotencialFlip,
        # HITL ja vem em _middlewares() (HumanInTheLoopMiddleware do notebook):
        # nao passar interrupt_on aqui para nao duplicar o mesmo interrupt.
        checkpointer=MemorySaver(),
    )


def criar_agente():
    """Deep agent principal + fallback por MODELO no agente inteiro.

    O `resolve_model` do deepagents so aceita BaseChatModel ou string, entao
    nao da para usar `with_fallbacks` no modelo. A cadeia entra nos GRAFOS
    compilados: se o provedor do principal cair (429/502/timeout), o imovel
    e reavaliado do zero com o proximo modelo da lista.
    """
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    principal = _deep_agent(MODELO_AGENTE)
    fallbacks = [_deep_agent(criar_modelo_flip(model=m)) for m in modelos_fallback()]
    if not fallbacks:
        return principal
    logger.warning("agente principal: %s | fallbacks (imovel inteiro): %s",
                   getattr(MODELO_AGENTE, "model_name", "?"), ",".join(modelos_fallback()))
    return principal.with_fallbacks(
        fallbacks,
        exceptions_to_handle=(APIStatusError, APITimeoutError, APIConnectionError),
    )
