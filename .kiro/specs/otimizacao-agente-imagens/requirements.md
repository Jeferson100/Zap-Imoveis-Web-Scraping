# Requirements Document

## Introduction

O módulo `src/agente_avaliacao_imagens` é um subgrafo LangGraph que avalia fotos de imóveis usando LLMs. O fluxo atual percorre três nós (descrever_fotos → extrair_analise → refletor_imagens) e pode repetir o ciclo completo até `MAX_TENTATIVAS=3` vezes. Para cada imóvel, o módulo baixa todas as imagens, converte-as para base64 e as envia ao LLM em lotes controlados por semáforo.

Este spec define os requisitos para otimizar o módulo, reduzindo latência, custo de tokens e consumo de rede sem degradar a qualidade das análises produzidas.

---

## Glossary

- **Agente**: O módulo `src/agente_avaliacao_imagens` como um todo.
- **Subgrafo**: O grafo LangGraph compilado em `subgrafo_imagens.py`.
- **Nó**: Um dos três estágios do Subgrafo (`descrever_fotos`, `extrair_analise`, `refletor_imagens`).
- **Lote**: Subconjunto de URLs de imagens processadas em uma única chamada ao LLM de visão.
- **Reflexão**: Ciclo de auditoria executado pelo nó `refletor_imagens` que pode provocar nova iteração.
- **LLM_Visão**: Modelo multimodal responsável por descrever as fotos (nó `descrever_fotos`).
- **LLM_Texto**: Modelo de texto responsável por extrair e auditar a análise (nós `extrair_analise` e `refletor_imagens`).
- **LLM_Estruturado**: Modelo de texto de baixo custo usado exclusivamente para estruturar texto em JSON (nó `extrair_analise`).
- **HttpClient**: Instância de `httpx.AsyncClient` usada para download de imagens.
- **CacheDownload**: Mapeamento em memória de URL → `(mime, base64)` válido durante o processamento de um imóvel.
- **URL_Direta**: URL original da imagem enviada diretamente ao LLM sem conversão para base64.
- **Config**: Arquivo `config.py` que lê variáveis de ambiente para todas as configurações do Agente.

---

## Requirements

### Requirement 1: Loop de Reflexão Configurável

**User Story:** Como operador do pipeline, eu quero controlar o número máximo de iterações do loop de reflexão via variável de ambiente, para que eu possa reduzir o tempo de processamento ajustando `IMAGENS_MAX_TENTATIVAS` sem alterar código.

#### Acceptance Criteria

1. THE Config SHALL expor a variável de ambiente `IMAGENS_MAX_TENTATIVAS` com valor padrão `1`.
2. IF `IMAGENS_MAX_TENTATIVAS` é definida com valor `0`, THEN THE Subgrafo SHALL executar somente os nós `descrever_fotos` e `extrair_analise`, sem executar o nó `refletor_imagens` nenhuma vez durante a execução.
3. IF `IMAGENS_MAX_TENTATIVAS` é definida com valor maior ou igual a `1`, THEN THE Subgrafo SHALL executar o nó `refletor_imagens` exatamente `IMAGENS_MAX_TENTATIVAS` vezes como limite máximo por execução completa.
4. THE Config SHALL aceitar valores inteiros entre `0` e `10` inclusive para `IMAGENS_MAX_TENTATIVAS`.
5. IF `IMAGENS_MAX_TENTATIVAS` contiver um valor não inteiro ou negativo, THEN THE Config SHALL registrar um aviso de log e usar o valor padrão `1`.
6. WHEN o número de iterações do loop atingir o valor configurado em `IMAGENS_MAX_TENTATIVAS`, THE Subgrafo SHALL encerrar o loop e retornar o resultado atual sem iniciar nova iteração.

---

### Requirement 2: Envio de URLs Diretas ao LLM de Visão

**User Story:** Como desenvolvedor, eu quero que o Agente envie URLs originais das imagens ao LLM_Visão quando o modelo suportar esse modo, para que o tempo de download e o consumo de memória sejam eliminados nesses casos.

#### Acceptance Criteria

1. THE Config SHALL expor a variável de ambiente `IMAGENS_USAR_URL_DIRETA` com valor padrão `false`.
2. IF `IMAGENS_USAR_URL_DIRETA` é `true`, THEN THE Agente SHALL montar o payload do lote usando `{"type": "image_url", "image_url": {"url": "<url_original>"}}` sem realizar download nem conversão para base64.
3. IF `IMAGENS_USAR_URL_DIRETA` é `false`, THEN THE Agente SHALL manter o comportamento atual de download e conversão para base64.
4. IF `IMAGENS_USAR_URL_DIRETA` é `true` e uma URL individual for vazia ou nula, THEN THE Agente SHALL omitir a entrada do payload e registrar um aviso de log identificando a posição do item inválido.
5. IF `IMAGENS_USAR_URL_DIRETA` é `true` e a chamada ao LLM retornar indicação de falha de acesso a uma URL, THEN THE Agente SHALL registrar um aviso de log contendo a URL e o motivo do erro reportado.
6. THE Config SHALL documentar em comentário inline que `IMAGENS_USAR_URL_DIRETA=true` requer que o modelo LLM_Visão suporte acesso a URLs externas.

---

### Requirement 3: Modelo Dedicado de Baixo Custo para Extração Estruturada

**User Story:** Como operador do pipeline, eu quero que o nó `extrair_analise` use um modelo mais leve e barato, pois essa etapa apenas converte texto em JSON sem precisar de capacidade de visão ou raciocínio avançado.

#### Acceptance Criteria

1. THE Config SHALL expor a variável de ambiente `IMAGENS_MODEL_ESTRUTURADO` com valor padrão `"stepfun-ai/step-3.5-flash"`.
2. THE Nó `extrair_analise` SHALL usar o modelo configurado em `IMAGENS_MODEL_ESTRUTURADO` como valor do parâmetro `model_llm` ao instanciar o LlmRouter, em vez de usar `MODEL_TEXTO`.
3. IF `IMAGENS_MODEL_ESTRUTURADO` estiver definida com um valor não vazio, THEN THE Nó `extrair_analise` SHALL posicionar esse modelo como primeiro item da lista `api_nvidia_models` passada ao LlmRouter.
4. IF `IMAGENS_MODEL_ESTRUTURADO` estiver vazia ou ausente, THEN THE Config SHALL registrar um aviso de log e usar o valor padrão `"stepfun-ai/step-3.5-flash"`.
5. IF o nó `extrair_analise` falhar com todos os modelos da lista `api_nvidia_models`, THEN THE Nó `extrair_analise` SHALL retornar o `AnaliseImagens` de fallback com `imagem_aceitavel=false` e registrar no log o nome do último modelo tentado e a exceção capturada.

---

### Requirement 4: Reutilização do HttpClient entre Lotes

**User Story:** Como desenvolvedor, eu quero que um único `httpx.AsyncClient` seja criado e compartilhado entre todos os lotes de um mesmo processamento, para que connection pooling reduza a latência de downloads paralelos.

#### Acceptance Criteria

1. THE Agente SHALL instanciar exatamente um `httpx.AsyncClient` por invocação da função `processar_todos_lotes`.
2. THE Agente SHALL passar o mesmo `HttpClient` para todos os lotes processados dentro de uma única chamada a `processar_todos_lotes`.
3. WHEN todos os lotes tiverem sido concluídos ou falhado dentro da mesma invocação de `processar_todos_lotes`, THE Agente SHALL fechar o `HttpClient`.
4. IF um lote individual lançar uma exceção, THEN THE Agente SHALL registrar no log o índice do lote e o tipo da exceção.
5. IF um lote individual lançar uma exceção, THEN THE Agente SHALL continuar o processamento dos demais lotes sem fechar o `HttpClient` prematuramente.
6. IF uma exceção não tratada propagar-se para fora do contexto de gerenciamento do `HttpClient`, THEN THE Agente SHALL garantir o fechamento do cliente antes de relançar a exceção.

---

### Requirement 5: Concorrência de Lotes Configurável

**User Story:** Como operador do pipeline, eu quero controlar o número máximo de lotes processados simultaneamente via variável de ambiente, para que eu possa ajustar a concorrência conforme os limites de rate da API.

#### Acceptance Criteria

1. THE Config SHALL expor a variável de ambiente `IMAGENS_MAX_CONCURRENT_LOTES` com valor padrão `5`.
2. WHEN o Agente for inicializado, THE Agente SHALL ler `IMAGENS_MAX_CONCURRENT_LOTES` e aplicar o valor lido ao semáforo de concorrência antes de processar qualquer lote.
3. THE Config SHALL aceitar valores inteiros entre `1` e `20` inclusive para `IMAGENS_MAX_CONCURRENT_LOTES`.
4. IF `IMAGENS_MAX_CONCURRENT_LOTES` contiver um valor fora do intervalo `[1, 20]` ou não conversível para inteiro, THEN THE Config SHALL registrar um aviso de log descrevendo o valor inválido recebido e usar o valor padrão `5`.

---

### Requirement 6: Cache de Downloads por Imóvel

**User Story:** Como operador do pipeline, eu quero que imagens já baixadas sejam reutilizadas dentro do mesmo ciclo de processamento de um imóvel, para que reavaliações causadas pelo loop de reflexão não baixem as mesmas URLs repetidamente.

#### Acceptance Criteria

1. THE Config SHALL expor a variável de ambiente `IMAGENS_CACHE_DOWNLOADS` com valor padrão `true`.
2. WHEN `processar_todos_lotes` for invocada com `IMAGENS_CACHE_DOWNLOADS=true`, THE Agente SHALL inicializar um `CacheDownload` vazio mapeando URL → `(mime, base64)` para uso exclusivo durante aquela invocação.
3. IF `IMAGENS_CACHE_DOWNLOADS` é `true` e uma URL já está presente no `CacheDownload`, THEN THE Agente SHALL retornar o valor cacheado sem realizar nova requisição HTTP.
4. IF `IMAGENS_CACHE_DOWNLOADS` é `false`, THEN THE Agente SHALL realizar o download de cada URL a cada solicitação, sem consultar cache.
5. WHEN a invocação de `processar_todos_lotes` for concluída, THE Agente SHALL descartar o `CacheDownload`, não persistindo entre execuções distintas de imóveis.
6. IF `IMAGENS_USAR_URL_DIRETA` é `true`, THEN THE Agente SHALL não criar nem consultar o `CacheDownload`, pois não há download a cachear.
7. IF o download de uma URL falhar, THEN THE Agente SHALL não inserir a entrada no `CacheDownload`, garantindo que a próxima solicitação da mesma URL tente novamente via HTTP.
