# Implementation Plan: Otimização do Agente de Avaliação de Imagens

## Overview

Implementar os requisitos 1, 2, 4 e 6 do spec, modificando três arquivos:
`config.py` (novas env vars), `utils.py` (cliente compartilhado, cache, URL direta) e
`subgrafo_imagens.py` (skip do refletor quando `MAX_TENTATIVAS=0`).
Os requisitos 3 e 5 estão fora do escopo.

## Tasks

- [x] 1. Atualizar `config.py` com as novas variáveis de ambiente
  - Adicionar função `_parse_max_tentativas(raw: str) -> int` com validação de intervalo `[0, 10]` e log warning para valores inválidos, usando padrão `1`
  - Alterar `MAX_TENTATIVAS` para leitura via `_parse_max_tentativas`, com valor padrão `1` (antes era `"2"`)
  - Adicionar função `_parse_bool(raw: str | None, default: bool) -> bool` para leitura de booleanos de env vars
  - Adicionar `USAR_URL_DIRETA: bool = _parse_bool(os.getenv("IMAGENS_USAR_URL_DIRETA"), False)` com comentário inline indicando que requer suporte do modelo LLM_Visão a URLs externas
  - Adicionar `CACHE_DOWNLOADS: bool = _parse_bool(os.getenv("IMAGENS_CACHE_DOWNLOADS"), True)`
  - _Requirements: 1.1, 1.4, 1.5, 2.1, 6.1_

- [ ] 2. Refatorar `utils.py` — cliente compartilhado (Req 4)
  - Remover a criação de `httpx.AsyncClient` de dentro de `_com_semaforo`
  - Mover criação do `AsyncClient` para o início de `processar_todos_lotes`, antes do `asyncio.gather`
  - Envolver todo o processamento de lotes em `try/finally` com `await client.aclose()` no bloco `finally`
  - Alterar assinatura de `_processar_um_lote` para receber `client: httpx.AsyncClient` como parâmetro (já recebe — confirmar e manter)
  - Garantir que lotes que lançam exceção são capturados individualmente com log do índice e tipo, sem propagar para fechar o cliente prematuramente (via `return_exceptions=True` no `gather`)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 2.1 Escrever property test para cliente único e fechamento garantido
    - **Property 5: Exatamente um AsyncClient por invocação**
    - **Property 6: AsyncClient é fechado independentemente de falhas em lotes**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5, 4.6**
    - Usar `unittest.mock.patch` para contar instanciações de `AsyncClient`
    - Testar cenários com 0, 1, 3 lotes e com lotes que lançam exceção

- [ ] 3. Refatorar `utils.py` — cache de downloads em memória (Req 6)
  - Importar `CACHE_DOWNLOADS` e `USAR_URL_DIRETA` de `config.py`
  - Em `processar_todos_lotes`: criar `cache: dict[str, tuple[str, str]] | None = {} if CACHE_DOWNLOADS and not USAR_URL_DIRETA else None`
  - Alterar assinatura de `_baixar` para receber `cache: dict | None = None`
  - Em `_baixar`: antes do download, verificar `if cache is not None and url in cache: return cache[url]`
  - Em `_baixar`: após download bem-sucedido, inserir no cache com `if cache is not None: cache[url] = resultado`
  - Garantir que falhas de download não inserem no cache (o `return None` já antes do insert trata isso)
  - Garantir que o cache é passado para cada chamada de `_baixar` dentro de `_processar_um_lote` (alterar assinatura para receber `cache`)
  - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 3.1 Escrever property test para semântica do cache
    - **Property 7: Cache evita re-download de URL já baixada**
    - **Property 8: Cache não é criado quando URL_DIRETA está ativa**
    - **Property 9: Falha de download não contamina o cache**
    - **Validates: Requirements 6.3, 6.6, 6.7**
    - Mockar `httpx.AsyncClient.get` para rastrear chamadas por URL
    - Usar `hypothesis` com `@given(st.binary(min_size=1), st.text(min_size=1))`

- [ ] 4. Refatorar `utils.py` — envio de URLs diretas ao LLM (Req 2)
  - Adicionar função `_montar_item_url_direta(url: str, idx: int) -> dict | None` que retorna `None` e loga warning se `url` for vazio, ou retorna `{"type": "image_url", "image_url": {"url": url}}`
  - Em `_processar_um_lote`: adicionar parâmetro `usar_url_direta: bool = False`
  - Em `_processar_um_lote`: quando `usar_url_direta=True`, montar `conteudo` usando `_montar_item_url_direta` sem realizar downloads; quando `False`, manter lógica atual com `_baixar`
  - Em `processar_todos_lotes`: passar `USAR_URL_DIRETA` para cada chamada de `_processar_um_lote`
  - Quando `USAR_URL_DIRETA=True`, não passar `cache` para `_processar_um_lote` (não há downloads a cachear — já tratado pelo `None` do cache)
  - _Requirements: 2.2, 2.3, 2.4, 2.5_

  - [ ]* 4.1 Escrever property test para payload com URL direta
    - **Property 3: Payload URL direta não contém base64**
    - **Property 4: URL vazia com URL_DIRETA é omitida do payload**
    - **Validates: Requirements 2.2, 2.4**
    - Usar `hypothesis` com `@given(st.lists(st.text(), min_size=1))`
    - Verificar que com `USAR_URL_DIRETA=True` nenhum `data:image/...;base64,` aparece no payload

- [ ] 5. Checkpoint — Garantir que `utils.py` está funcionando
  - Garantir que todos os testes passam, que não há regressões no comportamento de download base64 existente, e perguntar ao usuário se houver dúvidas.

- [ ] 6. Atualizar `subgrafo_imagens.py` — skip do refletor quando `MAX_TENTATIVAS=0` (Req 1)
  - Adicionar função `decidir_apos_extracao(state: SubgrafoImagensState) -> Literal["refletor_imagens", "__end__"]` que retorna `"__end__"` se `state.max_tentativas == 0`, caso contrário `"refletor_imagens"`; logar a decisão com nível `INFO`
  - Substituir o `builder.add_edge("extrair_analise", "refletor_imagens")` por `builder.add_conditional_edges("extrair_analise", decidir_apos_extracao, {"refletor_imagens": "refletor_imagens", "__end__": END})`
  - Remover o import não utilizado `RouterApiNvidia` de `roteador_llms.roteador_api_nvidia`
  - _Requirements: 1.2, 1.3, 1.6_

  - [ ]* 6.1 Escrever property test para roteamento do subgrafo
    - **Property 1: MAX_TENTATIVAS=0 nunca executa o refletor**
    - **Property 2: Limite de iterações do refletor é respeitado**
    - **Validates: Requirements 1.2, 1.3, 1.6**
    - Usar `hypothesis` com `@given(st.integers(min_value=0, max_value=3))`
    - Mockar `descrever_fotos`, `extrair_analise` e `refletor_imagens` para rastrear invocações
    - Para `max_tentativas=0`: contar invocações de `refletor_imagens` == 0
    - Para `max_tentativas=N >= 1`: contar invocações de `refletor_imagens` <= N

- [ ] 7. Atualizar `schemas.py` — valor padrão de `max_tentativas`
  - O campo `max_tentativas: int = MAX_TENTATIVAS` em `SubgrafoImagensState` já lê de `config.MAX_TENTATIVAS`. Verificar que, após a alteração em `config.py`, o valor padrão é `1` sem necessidade de mudança em `schemas.py`.
  - _Requirements: 1.1_

- [ ] 8. Checkpoint final — Garantir que todos os testes passam
  - Executar toda a suite de testes com `pytest` (ou `pytest --tb=short`)
  - Garantir que todos os testes passam, que não há regressões, e perguntar ao usuário se houver dúvidas.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1"] },
    { "wave": 2, "tasks": ["2", "3", "4"] },
    { "wave": 3, "tasks": ["5"] },
    { "wave": 4, "tasks": ["6", "7"] },
    { "wave": 5, "tasks": ["8"] }
  ]
}
```

## Notes

- Tarefas marcadas com `*` são opcionais e podem ser puladas para uma implementação mais rápida
- A ordem das tarefas importa: `config.py` (task 1) deve ser feito antes de `utils.py` (tasks 2–4) e `subgrafo_imagens.py` (task 6), pois ambos importam de `config`
- Os requisitos 3 e 5 estão fora do escopo e não devem ser implementados
- A lógica de `USAR_URL_DIRETA` e `CACHE_DOWNLOADS` interagem: quando `USAR_URL_DIRETA=True`, o cache deve ser `None` (sem criação nem consulta)
- O `AsyncClient` deve ser criado fora do semáforo em `processar_todos_lotes` para garantir que é único e compartilhado
