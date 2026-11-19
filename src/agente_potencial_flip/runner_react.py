"""Executor do agente ReAct (extraido de c0de6003)."""

import hashlib
import json as _json
import logging
import os
import time

from agente_avaliacao_imagens.schemas import AnaliseImagens
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from agente_potencial_flip.ferramentas_react import (
    ESTADO_AGENTE, SESSOES, PROXIMO_PASSO, _marcar,
    classificar_fotos_tool, validar_dados_tool, calcular_metricas_tool,
    registrar_decisao, criar_agente,
)
from agente_potencial_flip.schemas_react import (
    AvaliacaoImovel, montar_saida, graders_sem_pecas,
)
from agente_potencial_flip.loop_engineering import avaliar_graders, grader_narrativa

logger = logging.getLogger("agente_ci")


def _pensamentos(messages):
    saida = []
    for m in messages or []:
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc.get("name") == "think_tool":
                args = tc.get("args", {}) or {}
                saida.append({
                    "proxima_acao": str(args.get("proxima_acao", "")),
                    "pensamento": str(args.get("pensamento", "")),
                })
    return saida


def _add_pensamentos(sessao, messages):
    """Com checkpointer o historico volta inteiro a cada ainvoke; sem dedupe duplica."""
    vistos = {(p["proxima_acao"], p["pensamento"]) for p in sessao["pensamentos"]}
    for p in _pensamentos(messages):
        chave = (p["proxima_acao"], p["pensamento"])
        if chave not in vistos:
            vistos.add(chave)
            sessao["pensamentos"].append(p)


def _mensagem(payload, feedback=None):
    """So o anuncio: imagem, validacao e metricas vem das ferramentas do agente."""
    msg = "Avalie este imovel para flip.\n" + (
        "FOTOS_URLS=" + _json.dumps(payload["fotos_urls"], ensure_ascii=False) + "\n"
        + "DADOS_IMOVEL_JSON=" + _json.dumps(payload["dados_imovel"], ensure_ascii=False, default=str) + "\n"
        + "DESCRICAO=" + payload["descricao_texto"][:1200]
    )
    if feedback:
        msg += "\nA tentativa anterior foi reprovada pelos graders: " + feedback + ". Refaca a decisao."
    return msg


def _reconstruir_da_thread(sessao, out):
    """Recupera da thread o veredito estruturado e a decisao aprovada.

    Imagem, validacao e metricas sao escritas pelas ferramentas em
    ESTADO_AGENTE (mesmo processo) e lidas de la.
    """
    flip = out.get("structured_response")
    if flip is not None:
        sessao["flip"] = flip

    for msg in out.get("messages", []) or []:
        if getattr(msg, "name", None) != "registrar_decisao":
            continue
        try:
            corpo = _json.loads(msg.content)
        except (TypeError, ValueError):
            continue
        if isinstance(corpo, dict) and corpo.get("registrado"):
            sessao["decisao"] = corpo["registrado"]

    # Ferramentas escrevem no estado compartilhado do processo.
    if ESTADO_AGENTE.get("imagem") is not None:
        sessao["imagem"] = ESTADO_AGENTE["imagem"]
    if ESTADO_AGENTE.get("validacao") is not None:
        sessao["validacao"] = ESTADO_AGENTE["validacao"]
    if ESTADO_AGENTE.get("metricas_tool") is not None:
        sessao["metricas_tool"] = ESTADO_AGENTE["metricas_tool"]
    if sessao.get("decisao") is None and ESTADO_AGENTE.get("decisao") is not None:
        sessao["decisao"] = ESTADO_AGENTE["decisao"]

    # Se o modelo nao chamou a tool de fotos, o preditor e deterministico: roda
    # aqui. Guarda as chaves de cache para a tool nao reclassificar as imagens.
    if sessao.get("imagem") is None:
        urls = (sessao.get("payload") or {}).get("fotos_urls") or []
        if urls:
            logger.warning("agente nao avaliou as fotos; usando o preditor direto")
            imagem = julgar_fotos(list(urls))
            sessao["imagem"] = imagem
            sessao["fallback_imagem"] = True
            ESTADO_AGENTE["imagem"] = imagem
            ESTADO_AGENTE["imagem_urls"] = tuple(urls)
            ESTADO_AGENTE["imagem_resumo"] = imagem.resumo()


def resumo_tools(messages):
    """Pareia tool_calls com as ToolMessages e devolve [{tool, args, saida}].

    Cada chamada do modelo vira uma linha com a saida da ferramenta.
    """
    pendente, linhas = {}, []
    for m in messages or []:
        for tc in (getattr(m, "tool_calls", None) or []):
            pendente[tc.get("id")] = (tc.get("name"), tc.get("args"))
        if type(m).__name__ == "ToolMessage":
            nome, args = pendente.pop(
                getattr(m, "tool_call_id", None), (getattr(m, "name", None), None)
            )
            item = {"tool": nome, "args": args, "saida": str(m.content)[:1500]}
            if linhas and linhas[-1]["tool"] == item["tool"] and linhas[-1]["args"] == item["args"]:
                continue  # chamada repetida em sequencia: nao polui a trilha
            linhas.append(item)
    return linhas


MAX_CHAMADAS_TOOL = int(os.environ.get("FLIP_MAX_CHAMADAS_TOOL", "4"))


def _chamadas_por_tool(messages):
    """Conta chamadas por nome de ferramenta (protecao contra loop)."""
    contagem = {}
    for m in messages or []:
        for tc in (getattr(m, "tool_calls", None) or []):
            nome = str(tc.get("name") or "?")
            contagem[nome] = contagem.get(nome, 0) + 1
    return contagem


PROVEDOR_CAIU = ("429", "502", "503", "rate limit", "throttle", "timeout",
                 "maximum context", "connection", "unavailable")


async def _historico_do_checkpointer(sessao):
    """O historico real vive no checkpointer: e dele que se recupera a trilha.

    Sem isso, uma falha no meio do run devolvia o output anterior (vazio) e o
    log saia com `chamadas={}` mesmo depois de 45 passos de agente.
    """
    try:
        estado = await sessao["agente"].aget_state(sessao["cfg"])
        valores = dict(getattr(estado, "values", None) or {}) if estado else {}
        return valores.get("messages", []) or [], valores.get("structured_response")
    except Exception:  # noqa: BLE001 - recuperar nunca derruba a celula
        anterior = sessao.get("out") or {}
        return anterior.get("messages", []) or [], anterior.get("structured_response")


async def _invocar(sessao, entrada):
    """`ainvoke` com rede de seguranca: nenhuma falha derruba a celula.

    Recursao (laco de ferramentas) e erro do provedor encerram a etapa e viram
    motivo nos graders - o pior caso e um veredito incompleto, nao um traceback.
    """
    try:
        return await sessao["agente"].ainvoke(entrada, config=sessao["cfg"])
    except GraphRecursionError:
        logger.warning("limite de recursao atingido; encerrando a etapa")
        sessao["recursao_atingida"] = True
    except Exception as exc:  # noqa: BLE001 - HTTP 400/429/timeout nao podem matar a celula
        logger.warning("chamada do agente falhou: %s: %s", type(exc).__name__, str(exc)[:300])
        sessao["erro_etapa"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    msgs, flip = await _historico_do_checkpointer(sessao)
    return {"messages": msgs, "structured_response": flip}


async def _resolver_interrupts(sessao, out):
    """Retoma ate acabar as pausas, ou para quando quem decide e o humano."""
    while out.get("__interrupt__"):
        req = out["__interrupt__"][0]
        sessao["solicitacoes"].append(getattr(req, "value", req))
        if sessao["decisao_humana"] is None:
            return out, True
        out = await _invocar(
            sessao, Command(resume={"decisions": [{"type": sessao["decisao_humana"]}]})
        )
    return out, False


def _saida(sessao, graders):
    saida = montar_saida(
        sessao.get("imagem") or julgar_fotos([]),
        sessao.get("flip"),
        sessao.get("validacao"),
        graders,
        len(sessao["historico"]),
        sessao["historico"],
    )
    if sessao.get("imagem") is not None:
        saida.graders["imagem_resumo"] = sessao["imagem"].resumo()
    saida.graders["tools"] = sessao.get("tools", [])
    saida.graders["pensamentos"] = sessao["pensamentos"]
    saida.graders["decisao"] = sessao.get("decisao")
    saida.graders["solicitacoes_aprovacao"] = sessao["solicitacoes"]
    saida.graders["decisao_humana"] = sessao["decisao_humana"]
    saida.graders["resumo_agente"] = sessao.get("ultima_msg", "")
    saida.graders["chamadas_por_tool"] = sessao.get("chamadas")
    saida.graders["limite_chamadas"] = sessao.get("limite_chamadas")
    saida.graders["erro_etapa"] = sessao.get("erro_etapa")
    saida.graders["provedor_caiu"] = sessao.get("provedor_caiu")
    saida.graders["validou"] = sessao.get("validacao") is not None
    saida.graders["classificou"] = sessao.get("imagem") is not None
    saida.graders["etapas_runner"] = sessao.get("recuperadas") or []
    saida.graders["quem_analisou"] = "runner" if sessao.get("recuperadas") else "agente"
    saida.graders["metricas_tool"] = sessao.get("metricas_tool")
    saida.graders["metricas_base"] = (sessao.get("metricas_tool") or {}).get("base_dados")
    return saida


def _span_ferramenta(nome, saida, t0, origem):
    """Marca no LangSmith a etapa que o runner executou FORA do grafo.

    O que roda dentro do grafo (turno do modelo, ToolNode) ja e traceado pelo
    LANGCHAIN_TRACING_V2. `garantir_etapas` roda no runner, entao sem isto a
    recuperacao ficaria invisivel na arvore.
    """
    try:
        from langsmith.run_helpers import trace as ls_trace

        corpo = str(saida)
        imovel = str((ESTADO_AGENTE.get("payload") or {}).get("_id", "?"))
        with ls_trace(f"runner:{nome}", run_type="tool",
                      inputs={"origem": origem, "imovel": imovel},
                      project_name=os.environ.get("LANGCHAIN_PROJECT")) as run:
            run.end(outputs={
                "duracao_ms": round((time.perf_counter() - t0) * 1000, 1),
                "cache": '"fonte": "cache"' in corpo,
                "recusada": corpo.lstrip().startswith('{"erro"'),
                "saida": corpo[:4000],
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("span de %s no LangSmith falhou: %s", nome, exc)


async def garantir_etapas(sessao):
    """Roda de fora o que o agente pulou.

    Medido no lote: o modelo ou percorre as 5 etapas (~245 s) ou responde em
    ~25 s depois de UMA chamada, sem validar e sem calcular. Pedir de novo nao
    conserta -- ele repete o atalho com o proprio veredito na thread. As etapas
    sao deterministicas de conta (a visao e o ConvNeXt, nao o LLM), entao o
    runner as executa e o veredito e pedido de novo COM os numeros na mensagem.
    """
    recuperadas = []
    quem_antes = ESTADO_AGENTE.get("_quem")
    ESTADO_AGENTE["_quem"] = "runner"
    try:
        # Sem fotos na lista, a ferramenta nunca preenche `imagem` e a
        # recuperacao a chamaria de novo a cada passada.
        tem_fotos = bool((sessao.get("payload") or {}).get("fotos_urls"))
        if ESTADO_AGENTE.get("imagem") is None and tem_fotos:
            t0 = time.perf_counter()
            saida = await classificar_fotos_tool.ainvoke({})
            _span_ferramenta("classificar_fotos_tool", saida, t0, "runner")
            recuperadas.append("classificar_fotos_tool")

        if ESTADO_AGENTE.get("validacao") is None:
            t0 = time.perf_counter()
            saida = await validar_dados_tool.ainvoke({})
            _span_ferramenta("validar_dados_tool", saida, t0, "runner")
            recuperadas.append("validar_dados_tool")

        if ESTADO_AGENTE.get("metricas_tool") is None:
            t0 = time.perf_counter()
            saida = calcular_metricas_tool.invoke({})
            _span_ferramenta("calcular_metricas_tool", saida, t0, "runner")
            recuperadas.append("calcular_metricas_tool")
    finally:
        if quem_antes is None:
            ESTADO_AGENTE.pop("_quem", None)
        else:
            ESTADO_AGENTE["_quem"] = quem_antes

    if recuperadas:
        sessao["imagem"] = sessao.get("imagem") or ESTADO_AGENTE.get("imagem")
        sessao["validacao"] = sessao.get("validacao") or ESTADO_AGENTE.get("validacao")
        sessao["metricas_tool"] = ESTADO_AGENTE.get("metricas_tool")
        sessao["recuperadas"] = recuperadas
        logger.warning("etapas puladas pelo agente, rodadas pelo runner: %s", recuperadas)
    return recuperadas


def _mensagem_com_conta(sessao):
    """Repedido do veredito com os numeros NA mensagem.

    Insistir com texto nao mudava nada: o modelo tinha acabado de responder sem
    conta e a thread dele nao tinha numero algum para reler.
    """
    payload = sessao["payload"]
    conta = {k: v for k, v in (sessao.get("metricas_tool") or {}).items()
             if k not in ("operacoes", "validacao")}
    msg = "Reavalie ESTE imovel e chame registrar_decisao com o veredito.\n"
    msg += "METRICAS_JSON=" + _json.dumps(conta, ensure_ascii=False, default=str) + "\n"
    if sessao.get("imagem") is not None:
        msg += "IMAGEM_JSON=" + _json.dumps(sessao["imagem"].resumo(), ensure_ascii=False) + "\n"
    val = sessao.get("validacao")
    if val is not None:
        msg += "VALIDACAO_JSON=" + _json.dumps({
            "dados_consistentes": getattr(val, "dados_consistentes", None),
            "possui_erros": getattr(val, "possui_erros", None),
            "inconsistencias": list(getattr(val, "inconsistencias_encontradas", []) or []),
        }, ensure_ascii=False, default=str) + "\n"
    msg += ("potencial_house_flip depende de passa_regra_15pct desses numeros; use "
            "preco_maximo_para_regra como alvo de negociacao. Nao chame "
            "classificar_fotos_tool, validar_dados_tool nem calcular_metricas_tool.\n")
    msg += ("FOTOS_URLS=" + _json.dumps(payload["fotos_urls"], ensure_ascii=False) + "\n"
            + "DADOS_IMOVEL_JSON="
            + _json.dumps(payload["dados_imovel"], ensure_ascii=False, default=str) + "\n"
            + "DESCRICAO=" + payload["descricao_texto"][:1200])
    return msg


async def _processar(sessao, out, max_tentativas=1):
    for tentativa in range(1, max_tentativas + 2):
        out, pausado = await _resolver_interrupts(sessao, out)
        if pausado:
            sessao["out"] = out
            return {"estado": "aguardando_humano", "sessao": sessao}

        msgs = out.get("messages", [])
        _add_pensamentos(sessao, msgs)
        sessao["tools"] = resumo_tools(msgs)
        sessao["ultima_msg"] = str(msgs[-1].content) if msgs else ""

        _reconstruir_da_thread(sessao, out)

        chamadas = _chamadas_por_tool(msgs)
        sessao["chamadas"] = chamadas
        estourou = bool(sessao.get("recursao_atingida"))
        repetiu = {n: c for n, c in chamadas.items() if c >= MAX_CHAMADAS_TOOL}
        if repetiu:
            # Informativo: a repeticao cai no cache da ferramenta, entao nao
            # justifica cancelar o retry dos graders.
            sessao["limite_chamadas"] = repetiu
            logger.info("ferramentas repetidas (cache): %s", repetiu)

        # Veredito sem conta nao e veredito: roda o que faltou e pede de novo,
        # agora com os numeros na mensagem. Uma vez por sessao.
        sem_conta = (ESTADO_AGENTE.get("metricas_tool") is None
                     or ESTADO_AGENTE.get("validacao") is None)
        # Recursao atingida NAO e motivo para pular a recuperacao: e justamente o
        # caso do modelo que girou em classificar_fotos_tool ate o teto sem nunca
        # calcular (medido em 3 de 10 do lote). Cada ainvoke tem orçamento novo de
        # passos, entao a conta ainda pode ser feita e o veredito pedido.
        # So nao se tenta quando o provedor respondeu erro: ai seria queimar chamada.
        if (sem_conta and not sessao.get("recuperou_etapas")
                and not sessao.get("erro_etapa")):
            sessao["recuperou_etapas"] = True
            await garantir_etapas(sessao)
            sessao["flip"] = None                # veredito sem base nao vale
            ESTADO_AGENTE.pop("flip", None)      # senao a thread recupera o antigo
            sessao["decisao"] = None
            out = await _invocar(
                sessao,
                {"messages": [{"role": "user", "content": _mensagem_com_conta(sessao)}]},
            )
            out, pausado = await _resolver_interrupts(sessao, out)
            if pausado:
                sessao["out"] = out
                return {"estado": "aguardando_humano", "sessao": sessao}
            _reconstruir_da_thread(sessao, out)
            msgs = out.get("messages", []) or msgs
            sessao["tools"] = resumo_tools(msgs)
            if msgs:
                sessao["ultima_msg"] = str(msgs[-1].content)
            if sessao.get("flip") is None:
                graders = graders_sem_pecas(sessao)
                sessao["historico"].append({"tentativa": tentativa, "ok": False,
                                            "erros": graders["erros"]})
                return {"estado": "concluido", "sessao": sessao,
                        "saida": _saida(sessao, graders)}

        # O modelo costuma emitir o veredito estruturado sem chamar
        # registrar_decisao. Pedir de novo custava um turno e o modelo reiniciava
        # a sequencia de ferramentas (laco). A decisao sai do proprio veredito.
        if sessao.get("decisao") is None and sessao.get("flip") is not None:
            flip = sessao["flip"]
            decisao = {
                "potencial_house_flip": str(flip.potencial_house_flip),
                "score_potencial_flip": float(flip.score_potencial_flip),
                "resumo": str(flip.justificativa_potencial)[:300],
                "origem": "veredito_estruturado",
            }
            sessao["decisao"] = decisao
            ESTADO_AGENTE["decisao"] = decisao
            logger.info("decisao sintetizada do veredito estruturado")

        if (sessao.get("imagem") is None or sessao.get("flip") is None
                or sessao.get("metricas_tool") is None or sessao.get("validacao") is None):
            graders = graders_sem_pecas(sessao)
        else:
            graders = avaliar_graders(
                sessao["imagem"], sessao["flip"], sessao.get("validacao"),
                ESTADO_AGENTE.get("metricas_tool"),
            )
        sessao["historico"].append({"tentativa": tentativa, "ok": graders["ok"], "erros": graders["erros"]})
        # So completa do global o que a thread nao forneceu (nao sobrescreve).
        sessao["imagem"] = sessao.get("imagem") or ESTADO_AGENTE.get("imagem")
        sessao["flip"] = sessao.get("flip") or ESTADO_AGENTE.get("flip")
        sessao["validacao"] = sessao.get("validacao") or ESTADO_AGENTE.get("validacao")
        caiu = any(m in (sessao.get("erro_etapa") or "").lower() for m in PROVEDOR_CAIU)
        if caiu:
            sessao["provedor_caiu"] = sessao["erro_etapa"]
        # Retry nao conserta provedor indisponivel: so gasta chamada e polui o
        # historico com um veredito tardio.
        if estourou and not graders["ok"]:
            logger.warning("estouro de recursao sem veredito valido: %s", chamadas)
        if graders["ok"] or tentativa > max_tentativas or estourou or caiu:
            return {"estado": "concluido", "sessao": sessao, "saida": _saida(sessao, graders)}

        faltam = []
        if sessao.get("validacao") is None:
            faltam.append("validar_dados_tool")
        if ESTADO_AGENTE.get("metricas_tool") is None:
            faltam.append("calcular_metricas_tool")
        if faltam:
            # O texto do grader mostrava o erro e o modelo respondia igual. Aqui a
            # instruicao nomeia a ferramenta que falta e veta as ja feitas.
            feedback = ("Voce respondeu sem rodar " + " e ".join(faltam) + ". Chame "
                        + " e ".join(faltam) + " SEM argumentos agora, e so depois "
                        "chame registrar_decisao. Nao repita classificar_fotos_tool "
                        "nem think_tool.")
        else:
            feedback = (
                "OS GRADERS AUTOMATICOS reprovaram o veredito anterior; nao foi rejeicao humana. "
                + "; ".join(e for lista in graders["erros"].values() for e in lista)
            )
        out = await _invocar(
            sessao,
            {"messages": [{"role": "user", "content": _mensagem(sessao["payload"], feedback)}]},
        )
    return {"estado": "concluido", "sessao": sessao, "saida": _saida(sessao, graders)}


def _cfg_trace(payload, thread_id):
    """Config do ainvoke com o que identifica a trace no LangSmith.

    Sem isto a raiz aparece como `LangGraph`, com `tags=[]` e so um `thread_id`
    com hash: dois imoveis do lote podem cair no mesmo id e nao ha como saber
    qual arvore e de qual anuncio. `tags` e `metadata` viram filtro na UI.
    """
    imovel = str((payload or {}).get("_id") or "solto")
    dados = (payload or {}).get("dados_imovel") or {}
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": int(os.environ.get("FLIP_RECURSION_LIMIT", "45")),
        "run_name": imovel,
        "tags": [f"imovel:{imovel}",
                 f"lote:{os.environ.get('FLIP_LOTE_TAG', 'atiradores')}",
                 "flip"],
        "metadata": {
            "imovel": imovel,
            "thread_id": thread_id,
            "bairro": str(dados.get("bairro") or ""),
            "tipo_imovel": str(dados.get("tipo_imovel") or ""),
            "preco_por_m2": dados.get("preco_por_m2"),
            "metragem": dados.get("metragem"),
            "valor_imovel": dados.get("valor_imovel"),
        },
    }


async def iniciar_avaliacao(payload, thread_id, decisao_humana=None, max_tentativas=1):
    """decisao_humana=None pausa para aprovacao; "approve"/"edit"/"reject" decide sozinho."""
    ESTADO_AGENTE.clear()
    ESTADO_AGENTE["payload"] = payload
    sessao = {
        "thread_id": thread_id,
        "payload": payload,
        "agente": criar_agente(),
        # Teto de turnos: o modelo repete ferramentas e cada turno entra no
        # historico. 60 permitia ~30 chamadas e estourava 131k tokens de contexto.
        "cfg": _cfg_trace(payload, thread_id),
        "decisao_humana": decisao_humana,
        "historico": [], "pensamentos": [], "solicitacoes": [], "tools": [],
    }
    SESSOES[thread_id] = sessao

    # Imagem, validacao e metricas NAO sao pre-calculadas: as ferramentas do
    # agente fazem isso na ordem certa (e as metricas usam os dados validados).
    out = await _invocar(
        sessao,
        {"messages": [{"role": "user", "content": _mensagem(payload)}]},
    )
    sessao["out"] = out
    return await _processar(sessao, out, max_tentativas)


async def retomar_avaliacao(thread_id, decisao="approve", max_tentativas=1):
    sessao = SESSOES[thread_id]
    sessao["decisao_humana"] = decisao
    out = await _invocar(sessao, Command(resume={"decisions": [{"type": decisao}]}))
    sessao["out"] = out
    return await _processar(sessao, out, max_tentativas)


async def avaliar_imovel_agente(payload, max_tentativas=1) -> "AvaliacaoImovel":
    """Atalho sem pausa humana (usado nos lotes e no teste de 3 imoveis)."""
    # O hash sozinho colide entre imoveis parecidos; o _id do lote na frente
    # garante thread e trace distintas por anuncio.
    _marca = str(payload.get("_id") or "")
    thread = (f"auto-{_marca}-" if _marca else "auto-") + hashlib.sha1(
        _json.dumps(payload["dados_imovel"], sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:10]
    r = await iniciar_avaliacao(payload, thread, decisao_humana="approve",
                                max_tentativas=max_tentativas)
    if "saida" not in r:
        s = r["sessao"]
        g = {"passou": {"G1": False, "G2": False, "G3": False,
                         "G4": False, "G5": False, "G6": False}, "ok": False,
             "erros": {"G1": [], "G2": [], "G3": ["nao concluido"],
                       "G4": [], "G5": [], "G6": []}}
        return montar_saida(s.get("imagem") or julgar_fotos([]), s.get("flip"), s.get("validacao"),
                            g, len(s["historico"]), s["historico"])
    return r["saida"]


