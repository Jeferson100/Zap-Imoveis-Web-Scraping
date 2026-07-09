PROMPT_AVALIAR_POTENCIAL_FLIP = (
    "Voce e um investidor especializado em house flipping. "
    "Avalie se este imovel tem bom potencial para comprar, reformar e revender (house flip).\n\n"
    "--- DADOS DO IMOVEL (validados) ---\n"
    "{dados_imovel}\n\n"
    "--- ANALISE DAS FOTOS ---\n"
    "{analise_imagens}\n\n"
    "Avalie:\n"
    "1. Potencial de valorizacao apos reforma (estado atual vs pos-reforma)\n"
    "2. Localizacao vale o investimento? (bairro em valorizacao?)\n"
    "3. Custo estimado de reforma vs valor de revenda\n"
    "4. Riscos envolvidos (estruturais, documentacao, mercado)\n"
    "5. Prazo estimado para conclusao e revenda\n\n"
    "Seja conservador nas estimativas financeiras. "
    "Nao recomende house flip se o ROI projetado for menor que 15%."
)

PROMPT_REFLEXAO_POTENCIAL_FLIP = (
    "Voce e um investidor senior revisando a avaliacao de house flip de um colega.\n"
    "Verifique:\n"
    "1. O potencial house flip esta coerente com os dados e fotos?\n"
    "2. O custo de reforma estimado e realista para o estado do imovel?\n"
    "3. O ROI faz sentido com as demais estimativas?\n"
    "4. Ha riscos importantes ignorados?\n\n"
    "Avaliacao atual:\n{analise_json}\n\n"
    "Dados do imovel:\n{dados_imovel}\n\n"
    "Analise de imagens:\n{analise_imagens}\n\n"
    "Observacoes da validacao:\n{validacao_obs}"
)
