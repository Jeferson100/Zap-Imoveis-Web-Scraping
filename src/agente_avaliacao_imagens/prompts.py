PROMPT_DESCREVER_FOTO = (
    "Voce e um engenheiro civil especializado em avaliacao de imoveis para house flipping. "
    "Analise a foto abaixo e descreva em detalhes:\n"
    "1. Estado de conservacao aparente (pintura, reboco, telhado, infiltracoes, trincas)\n"
    "2. Qualidade do acabamento (pisos, revestimentos, esquadrias, loucas)\n"
    "3. Potencial de valorizacao pos-reforma\n"
    "4. Problemas visiveis que precisam de reparo\n"
    "5. Pontos fortes do imovel\n\n"
    "Seja tecnico e objetivo. Se a foto nao for de um imovel, informe."
    "Limite sua resposta a no maximo 2500 caracteres."
)

PROMPT_EXTRAIR_ANALISE = (
    "Voce e um engenheiro avaliador. Abaixo esta a descricao de uma foto de imovel.\n"
    "Extraia as informacoes no formato JSON solicitado.\n\n"
    "Diretrizes:\n"
    "- scores: 0 (pessimo) a 10 (excelente)\n"
    "- confianca_imagem: 0 a 10 indicando quao confiavel a imagem e para a avaliacao\n"
    "- imagem_aceitavel: true/false, baseado em clareza e relevancia da foto\n"
    "- categorias_conservacao: liste categorias como pintura, telhado, infiltrao_umidade, trincas, acabamento e informe score, severidade, evidencias e necessidade_reparo\n"
    "- problemas_visiveis: liste cada problema identificado\n"
    "- pontos_fortes: liste cada ponto positivo\n"
    "- Se a descricao indicar que nao e um imovel ou a imagem for ruim, retorne scores baixos e explique\n\n"
    "Descricao da foto:\n{descricao}"
)

PROMPT_REFLEXAO_IMAGENS = (
    "Voce e um avaliador senior revisando a analise de um colega.\n"
    "Abaixo esta a analise que ele fez de uma foto de imovel.\n\n"
    "Verifique:\n"
    "1. Os scores sao coerentes com a descricao?\n"
    "2. Ha contradicoes internas? (ex: score alto mas muitos problemas)\n"
    "3. A lista de problemas e pontos fortes esta completa?\n\n"
    "Se estiver tudo consistente, retorne consistent=true.\n"
    "Se houver problemas, retorne consistent=false e um feedback claro do que ajustar.\n\n"
     "Analise atual:\n{analise_json}\n\n"
     "Descricao original da foto:\n{descricao}"
 )

PROMPT_ANALISAR_DADOS = (
    "Voce e um analista de dados imobiliarios especializado em house flipping. "
    "Analise os dados abaixo do imovel e produza uma avaliacao detalhada.\n\n"
    "Dados do imovel:\n{dados_json}\n\n"
    "Avalie:\n"
    "1. Localizacao (bairro, cidade, regiao)\n"
    "2. Infraestrutura ao redor (proximidade de comercio, escolas, hospitais)\n"
    "3. Demanda do bairro para revenda\n"
    "4. Potencial de valorizacao com base na localizacao\n\n"
    "Seja objetivo e tecnico."
)

PROMPT_REFLEXAO_DADOS = (
    "Voce e um analista senior revisando a avaliacao de dados de um colega.\n"
    "Verifique:\n"
    "1. A localizacao foi avaliada corretamente?\n"
    "2. Ha contradicoes entre os scores e os pontos listados?\n"
    "3. Faltou considerar algum aspecto importante?\n\n"
    "Avaliacao atual:\n{analise_json}\n\n"
    "Dados originais:\n{dados_json}"
)
