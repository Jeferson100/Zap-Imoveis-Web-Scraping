import re
import pandas as pd
import numpy as np
import unidecode
from nltk.corpus import stopwords
import nltk

nltk.download('stopwords', quiet=True)

TOPIC_COLS = ["componente_0", "componente_1", "componente_2", "componente_3"]

STOPWORDS_NLTK = set(stopwords.words("portuguese"))

STOPWORDS_IMOVEIS = {
    "imovel", "imoveis", "casa", "casas", "apartamento", "apartamentos",
    "quarto", "quartos", "banheiro", "banheiros", "suite", "suites",
    "vaga", "vagas", "garagem", "area", "areas", "cozinha", "sala",
    "condominio", "empreendimento", "empreendimentos", "imobiliaria",
    "corretor", "corretora", "contato", "visita", "joinville", "bairro",
    "venda", "telefone", "whatsapp", "anuncio", "voce", "ideal",
    "familia", "perfeito", "qualidade", "vida", "conforto", "amplo",
    "novo", "acesso", "facil", "morar", "regiao", "cidade", "bom",
    "valor", "sendo", "sao", "querer", "saber", "desejar", "tudo",
    "lugar", "tempo", "completo", "poder", "movel", "metro",
    "acabar", "diferencial", "maneira", "maior", "melhor", "menor",
    "unico", "usar", "fazer", "gosto", "gostar", "muito", "pouco",
    "demais", "ate", "cada", "mais", "menos", "entre", "sobre",
    "contra", "nesse", "nessa", "neste", "nesta", "nesse", "nessa",
    "aquele", "aquela", "aquilo", "mesmo", "proprio", "outro",
    "grande", "pequeno", "primeiro", "ultimo", "melhor", "pior",
    "maior", "menor", "bem", "mal", "ja", "ainda", "agora",
    "sempre", "nunca", "depois", "antes", "hoje", "ontem", "amanha",
}

STOPWORDS_TOTAL = STOPWORDS_NLTK | STOPWORDS_IMOVEIS

RE_REMOVE = re.compile(
    r"código\s+do\s+anúncio[\s:\d\-]+|código:\s*\d+|ref\.?:?\s*\d+|"
    r"ri[\-\s]*\d+|cr[ée]ci[\-\s]*\d+|"
    r"\b(creci|whatsapp|telefone|contato|celular)\b[\s\d\-\\(\\)]+|"
    r"\d{7,}|https?\://\S+|www\.\S+",
    re.IGNORECASE,
)


def limpar_descricao_rapida(texto):
    if pd.isna(texto) or not texto:
        return ""
    t = RE_REMOVE.sub(" ", str(texto))
    t = unidecode.unidecode(t)
    t = re.sub(r"\b\d+\b", " ", t)
    t = re.sub(r"[^a-zA-Z\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    tokens = [w for w in t.lower().split()
              if len(w) > 2 and w not in STOPWORDS_TOTAL]
    return " ".join(tokens)


def aplicar_topicos(df, topicos_data, col_descricao="descricao"):
    if topicos_data is None:
        for c in TOPIC_COLS:
            df[c] = 0.0
        return

    vec = topicos_data["vectorizer"]
    nmf = topicos_data["nmf"]
    n_topics = topicos_data.get("n_topics", 4)

    if col_descricao not in df.columns:
        for c in TOPIC_COLS:
            df[c] = 0.0
        return

    desc_limpa = df[col_descricao].astype(str).apply(limpar_descricao_rapida)
    X = vec.transform(desc_limpa)
    W = nmf.transform(X)

    for i in range(n_topics):
        df[f"componente_{i}"] = W[:, i]
    for i in range(n_topics, 4):
        df[f"componente_{i}"] = 0.0
