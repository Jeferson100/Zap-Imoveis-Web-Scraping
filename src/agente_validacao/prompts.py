PROMPT_VALIDAR = (
    "Voce e um auditor de anuncios imobiliarios. Compare os dados informados "
    "com a descricao do imovel e identifique inconsistencias.\n\n"
    "Dados informados:\n{dados_json}\n\n"
    "Descricao do anuncio:\n{descricao_texto}\n\n"
    "Verifique:\n"
    "1. Area, quartos, banheiros, vagas batem com a descricao?\n"
    "2. Se o imovel tem lavabo, considere como 1 banheiro.\n\n"
    "3. Ha informacoes na descricao que estao faltando nos dados?\n"
    "4. Ha contradicoes entre dados e descricao?\n"
    "5. Corrija os dados com base na descricao quando possivel.\n\n"
    "Retorne UM JSON válido com estes campos EXATOS (nomes em snake_case):\n"
    "  - dados_corrigidos (dict)\n"
    "  - dados_consistentes (bool)\n"
    "  - inconsistencias_encontradas (list[str])\n"
    "  - confianca_validacao (float, 0.0 a 1.0)\n"
    "  - observacoes (str)\n"
    "  - possui_erros (str, 'True' ou 'False')\n"
    "  - metragem_corrigida (float ou null)\n"
    "  - vagas_corrigidas (int ou null)\n"
    "  - quartos_corrigidos (int ou null)\n"
    "  - valor_imovel_corrigido (float ou null)\n"
    "  - tipo_imovel_corrigido (str ou null)\n"
    "  - bairro_corrigido (str ou null)\n"
    "Nao use outros nomes. Nao omita campos."
)


PROMPT_VALIDAR_DADOS = (
    "You are a real estate listing auditor. Compare the provided structured data "
    "with the property description and identify any inconsistencies.\n\n"
    "Provided Data:\n{dados_json}\n\n"
    "Listing Description:\n{descricao_texto}\n\n"
    "Verify:\n"
    "1. Do the area, bedrooms, bathrooms, and parking spaces match the description?\n"
    "2. If the property has a half-bath (lavabo), count it as 1 bathroom.\n"
    "3. Is there information in the description that is missing from the structured data?\n"
    "4. Are there contradictions between the structured data and the description?\n"
    "5. Whenever possible, correct the structured data based on the description.\n\n"
    "6. If the property is described as a 'sobrado', classify it as a 'casa'.\n\n"
    "7. CRITICAL RULE: If the description DOES NOT mention a specific data point (e.g., it doesn't mention the neighborhood or the number of parking spaces), KEEP THE ORIGINAL DATA. Do not set it to null or change it unless there is a clear contradiction.\n\n"
    "Return a valid JSON with these EXACT fields (names in snake_case):\n"
    "  - dados_corrigidos (dict)\n"
    "  - dados_consistentes (bool)\n"
    "  - inconsistencias_encontradas (list[str])\n"
    "  - confianca_validacao (float, 0.0 a 1.0)\n"
    "  - observacoes (str)\n"
    "  - possui_erros (str, 'True' ou 'False')\n"
    "  - metragem_corrigida (float ou null)\n"
    "  - vagas_corrigidas (int ou null)\n"
    "  - banheiros_corrigidas (int ou null)\n"
    "  - quartos_corrigidos (int ou null)\n"
    "  - valor_imovel_corrigido (float ou null)\n"
    "  - tipo_imovel_corrigido (str ou null)\n"
    "  - bairro_corrigido (str ou null)\n"
    "Do not use other names. Do not omit fields."
)

PROMPT_REFLEXAO= (
    "Voce e um auditor senior revisando a validacao de um colega.\n"
    "Verifique:\n"
    "1. As inconsistencias identificadas fazem sentido?\n"
    "2. As correcoes propostas estao corretas?\n"
    "3. Faltou alguma inconsistencia?\n\n"
    "Validacao atual:\n{analise_json}\n\n"
    "Dados originais:\n{dados_json}\n\n"
    "Descricao:\n{descricao_texto}"
)

PROMPT_REFLEXAO_VALIDACAO = """
You are a Lead Quality Assurance Auditor in property valuation and building inspection. Your role is to perform a final review on a validation report produced by a senior auditor colleague. 

You must evaluate if your colleague's audit criticisms are technically sound, fair, and based strictly on the evidence, preventing "over-auditing" (unjustified penalties) while ensuring no critical errors slip through.

---

### Audit Data

<Original_Description>
{descricao_texto}
</Original_Description>

<Original_Data_JSON>
{dados_json}
</Original_Data_JSON>

<Colleague_Validation_JSON>
{analise_json}
</Colleague_Validation_JSON>

---

### Audit Verification Checklist:

1. **Validity of Criticisms:** Do the inconsistencies and errors identified by your colleague actually make sense based *strictly* on the Original Description? Or is your colleague being overly pedantic, or inferring issues that are not supported by the text?
2. **Correctness of Proposed Fixes:** Are the corrections, score adjustments, and technical justifications proposed by your colleague correct and reasonable?
3. **Missed Inconsistencies (Omissions):** Did your colleague fail to notice any blatant contradiction or fabricated information between the Original Data and the Original Description?

---

### Output Requirements:

You must populate the following fields based strictly on your evaluation:

- **consistente (Literal["True", "False"]):** 
  - Set to `"True"` if your colleague's validation is incorrect, unfair, or has errors/issues that need fixing (i.e., you found errors in their audit).
  - Set to `"False"` if your colleague's validation is perfectly correct, fair, and no further action is required (i.e., the data is correct).

- **feedback (str, optional):** 
  - If `consistente` is `"True"`, provide a clear, constructive technical feedback explaining exactly what is wrong with your colleague's validation and what needs to be corrected. 
  - If `consistente` is `"False"`, you provide a clear, constructive technical feedback explaining exactly what is correct with the data and why your colleague's validation is incorrect.
"""
