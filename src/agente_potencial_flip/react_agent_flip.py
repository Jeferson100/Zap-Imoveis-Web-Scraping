"""ReAct flip isolado (sombra/canario): supervisor investidor + 2 subagentes.

Diferencas para `deep_agent_flip.py` (workflow oficial, intocado):
  1. Supervisor com teto+retry+fallback (`asyncio.wait_for` + 2 tentativas):
     `SocketTimeoutError` no no `model` vira fallback sombra, nunca crash.
  2. Matematica (ROI/ARV/regra 15%) em `tools_flip.calcular_metricas_flip`
     — o LLM so julga (principio hibrido).
  3. Delegacao com payload INLINE (subagentes sao stateless): fotos_urls e
     JSON vao na instrucao de cada `task()`, e cada subagente devolve
     relatorio autocontido.
  4. `write_todos` nas 3 etapas (TodoListMiddleware, default on).
  5. `name="flip-investidor"` + `thread_id` por imovel + checkpointer
     (resumable + time-travel debug).

Contrato de saida: dict `AnalisePotencialFlip` (igual ao workflow oficial),
para comparar com o parquet oficial na coluna sombra.
"""

import asyncio
import json
import logging
from typing import Any, Dict

from deepagents import create_deep_agent
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langgraph.checkpoint.memory import MemorySaver

from shared.serialization import converter_numpy

from .schemas import AnalisePotencialFlip
from .tools_flip import descrever_fotos_tool, metricas_flip_tool, validar_dados_tool

logger = logging.getLogger(__name__)

SUPERVISOR_MODEL = "moonshotai/kimi-k2-instruct"  # tools: True (tabela langchain-nvidia)
TEMPO_MAX_TENTATIVA_S = 300  # teto por tentativa (padrao roteador_langchain_nvidia)
TENTATIVAS = 2
PAUSA_ENTRE_TENTATIVAS_S = 5
MAX_FOTOS_MSG = 6
MAX_DESCRICAO_CHARS = 2000

SYSTEM_REACT_FLIP = """Voce e um investidor senior de Fix & Flip em loop ReAct
(Thought -> Action(tool ou task) -> Observation -> veredito). Avalie em
EXATAMENTE 3 etapas, nesta ordem — registre cada uma com write_todos antes:
ETAPA 1: delegue ao fotografo via task(), passando AS FOTOS_URLS INLINE na
  instrucao (o subagente e stateless e nao enxerga seu contexto).
ETAPA 2: delegue ao dados via task(), passando O JSON + DESCRICAO INLINE.
ETAPA 3: com os dois relatorios, de o veredito final.
Regras da decisao (metricas_flip_tool ja calculou tudo — nao recalcule):
1) SEMPRE chame metricas_flip_tool primeiro (via dados) ou use metricas_flip do contexto.
2) Sem fotos, PULE visao (avaliacao so numerica + descricao).
3) So valide dados se numero suspeito.
4) REGRA DE OURO 15% ROI: potencial_house_flip="True" SOMENTE se
   metricas_flip.passa_regra_15pct=true; sem dados suficientes responda "False".
   Nunca invente custo de reforma; assuma patologias ocultas.
Responda em portugues, SOMENTE no formato estruturado.
"""

fotos_subagent = {
    "name": "fotografo",
    "description": (
        "Descreve fotos do imovel: conservacao, acabamento, problemas "
        "visiveis, pontos fortes. Receba as URLs inline na instrucao e "
        "devolva relatorio autocontido. Use para a ETAPA 1."
    ),
    "system_prompt": (
        "Voce descreve fotos de imoveis. Chame descrever_fotos_tool com as "
        "URLs da instrucao e devolva relatorio autocontido: conservacao, "
        "acabamento, problemas_visiveis, pontos_fortes."
    ),
    "tools": [descrever_fotos_tool],
}

dados_subagent = {
    "name": "dados",
    "description": (
        "Confere os numeros do anuncio + metricas deterministicas de flip "
        "(ROI, ARV, descontos). Receba o JSON inline na instrucao e devolva "
        "resumo autocontido. Use para a ETAPA 2."
    ),
    "system_prompt": (
        "Voce organiza os dados do imovel. Chame metricas_flip_tool (sempre "
        "primeiro) e formatar/valide com o JSON da instrucao; devolva numeros "
        "+ metricas_flip (roi_conservador, passa_regra_15pct) + benchmarks."
    ),
    "tools": [metricas_flip_tool, validar_dados_tool],
}

agente_react_flip = create_deep_agent(
    name="flip-investidor",
    model=ChatNVIDIA(model=SUPERVISOR_MODEL),
    subagents=[fotos_subagent, dados_subagent],
    system_prompt=SYSTEM_REACT_FLIP,
    response_format=AnalisePotencialFlip,
    checkpointer=MemorySaver(),
)

FALLBACK_SOMBRA: Dict[str, Any] = {
    "score_potencial_flip": 0.0,
    "potencial_house_flip": "False",
    "justificativa_potencial": "",
    "riscos": ["Falha tecnica do agente ReAct (sombra)"],
    "recomendacoes": [],
    "observacoes": "Fallback sombra — workflow oficial continua valendo",
}


def montar_mensagem(estado: Dict[str, Any]) -> str:
    """Monta a mensagem com payload inline completo (subagentes stateless)."""
    return (
        "Avalie este imovel para flip.\n"
        f"DADOS_IMOVEL_JSON={json.dumps(converter_numpy(estado.get('dados_imovel', {})), ensure_ascii=False)}\n"
        f"DESCRICAO={str(estado.get('descricao_texto', ''))[:MAX_DESCRICAO_CHARS]}\n"
        f"FOTOS_URLS={json.dumps(list(estado.get('fotos_urls', []) or [])[:MAX_FOTOS_MSG])}"
    )


async def avaliar_imovel_react(estado: Dict[str, Any], thread_id: str = "flip-1") -> Dict[str, Any]:
    """Roda o ReAct p/ 1 imovel com teto+retry+fallback sombra.

    `estado`: dict no shape de EstadoGlobal. Retorna o veredito como dict
    (AnalisePotencialFlip). Nunca levanta por timeout: esgotadas as
    tentativas, retorna FALLBACK_SOMBRA.
    """
    mensagem = montar_mensagem(estado)
    config = {"configurable": {"thread_id": thread_id}}
    ultimo_erro: Exception | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            res = await asyncio.wait_for(
                agente_react_flip.ainvoke(
                    {"messages": [{"role": "user", "content": mensagem}]}, config=config
                ),
                timeout=TEMPO_MAX_TENTATIVA_S,
            )
            sr = res.get("structured_response") if isinstance(res, dict) else None
            if sr is None:
                raise RuntimeError("ReAct sem structured_response")
            return sr if isinstance(sr, dict) else sr.model_dump()
        except Exception as e:  # inclui asyncio.TimeoutError / SocketTimeoutError
            ultimo_erro = e
            logger.warning("ReAct flip tentativa %s/%s falhou: %s: %s",
                           tentativa, TENTATIVAS, type(e).__name__, e)
            if tentativa < TENTATIVAS:
                await asyncio.sleep(PAUSA_ENTRE_TENTATIVAS_S)
    logger.error("ReAct flip esgotou tentativas — fallback sombra.")
    out = dict(FALLBACK_SOMBRA)
    out["justificativa_potencial"] = f"Falha tecnica do ReAct (sombra): {ultimo_erro}"
    out["erro"] = str(ultimo_erro)
    return out
