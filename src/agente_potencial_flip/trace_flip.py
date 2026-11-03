"""Trilha auditavel do agente flip: Thought -> Action -> Observation.

Por que callback e nao streaming: a tool `task` roda o subagente com
`subagent.ainvoke(...)` (deepagents/middleware/subagents.py), entao o interior
de `fotografo`/`dados` e uma run separada — `astream(subgraphs=True)` mostra o
supervisor, nao os subagentes. Callbacks sao propagados para a run filha.

Uso:
    trilha = TrilhaFlip()
    saida = await avaliar_imovel_react(estado, thread_id="flip-1",
                                       callbacks=[trilha])
    for ev in trilha.resumo():
        print(ev)

Custo: zero chamadas extras de LLM. O `raciocinio` so vem preenchido se o
provider expuser CoT (`additional_kwargs["reasoning"]`/`["reasoning_content"]`,
caso do gpt-oss no OpenRouter); caso contrario a trilha mostra o `texto` que o
modelo escreveu junto do tool_call.
"""

import logging
from typing import Any, Dict, List

from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage

logger = logging.getLogger(__name__)

MAX_TRECHO = 800


def _curto(valor: Any, limite: int = MAX_TRECHO) -> str:
    return " ".join(str(valor or "").split())[:limite]


def _origem(kwargs: Dict[str, Any]) -> str:
    """Melhor rotulo disponivel para 'quem falou' (subagente vs supervisor)."""
    meta = kwargs.get("metadata") or {}
    for chave in ("lc_agent_name", "langgraph_node", "lc_namespace"):
        valor = meta.get(chave)
        if isinstance(valor, str) and valor:
            return valor
        if isinstance(valor, (list, tuple)) and valor:
            return "/".join(str(v) for v in valor[-2:])
    tags = kwargs.get("tags") or []
    marcas = [t for t in tags if isinstance(t, str) and ("subagent" in t or "agent" in t)]
    return marcas[-1] if marcas else ""


class TrilhaFlip(BaseCallbackHandler):
    """Coletor em memoria de thought/action/observation (para notebook e log)."""

    def __init__(self, limite: int = MAX_TRECHO) -> None:
        self.limite = limite
        self.eventos: List[Dict[str, Any]] = []
        self.erros: List[str] = []

    # Thought: o modelo respondeu (content = raciocinio; tool_calls = acao).
    def on_chat_model_end(self, response: Any, **kwargs: Any) -> None:
        try:
            geracao = (getattr(response, "generations", None) or [[None]])[0][0]
            msg = getattr(geracao, "message", None)
            if msg is None:
                return
            ak = getattr(msg, "additional_kwargs", None) or {}
            self.eventos.append({
                "tipo": "thought",
                "origem": _origem(kwargs),
                "texto": _curto(getattr(msg, "content", ""), self.limite),
                "raciocinio": _curto(
                    ak.get("reasoning_content") or ak.get("reasoning") or "", self.limite
                ),
                "acoes": [
                    {"tool": tc.get("name"), "args": tc.get("args")}
                    for tc in (getattr(msg, "tool_calls", None) or [])
                ],
            })
        except Exception as e:  # trilha nunca derruba a avaliacao
            self.erros.append(f"on_chat_model_end: {e}")

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> None:
        try:
            self.eventos.append({
                "tipo": "action",
                "origem": _origem(kwargs),
                "tool": (serialized or {}).get("name"),
                "input": _curto(input_str, self.limite),
            })
        except Exception as e:
            self.erros.append(f"on_tool_start: {e}")

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        try:
            self.eventos.append({
                "tipo": "observation",
                "origem": _origem(kwargs),
                "saida": _curto(getattr(output, "content", output), self.limite),
            })
        except Exception as e:
            self.erros.append(f"on_tool_end: {e}")

    def resumo(self) -> List[Dict[str, Any]]:
        return list(self.eventos)

    def pensamentos(self) -> List[Dict[str, str]]:
        """So os `think_tool` chamados (pensamento + proxima_acao)."""
        out = []
        for ev in self.eventos:
            if ev["tipo"] != "thought":
                continue
            for acao in ev.get("acoes") or []:
                if acao.get("tool") == "think_tool":
                    args = acao.get("args") or {}
                    out.append({
                        "proxima_acao": str(args.get("proxima_acao", "")),
                        "pensamento": str(args.get("pensamento", "")),
                    })
        return out


def _pensou_antes(messages: List[Any]) -> bool:
    """True se houve tool_call de think_tool no turno atual (antes daqui)."""
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage):
            nomes = [tc.get("name") for tc in (msg.tool_calls or [])]
            if "think_tool" in nomes:
                return True
        elif isinstance(msg, ToolMessage):
            continue
        else:
            return False  # chegou no HumanMessage = turno novo
    return False


class ExigePensamento(AgentMiddleware):
    """Gate opcional: task/veredito sem think_tool antes devolve erro ao modelo.

    Nao bloqueia silenciosamente: devolve uma ToolMessage explicando, e o
    modelo repete a chamada. Custa um round-trip por violacao — por isso o
    default vigia apenas `task`.
    """

    def __init__(self, vigiadas: tuple[str, ...] = ("task",)) -> None:
        super().__init__()
        self.vigiadas = set(vigiadas)

    async def awrap_tool_call(self, request, handler):
        nome = (request.tool_call or {}).get("name")
        if nome in self.vigiadas and not _pensou_antes(
            (request.state or {}).get("messages", [])
        ):
            return ToolMessage(
                content=(
                    "Pare: chame think_tool (pensamento + proxima_acao) e depois "
                    "repita esta chamada."
                ),
                tool_call_id=(request.tool_call or {}).get("id"),
                name=nome,
            )
        return await handler(request)
