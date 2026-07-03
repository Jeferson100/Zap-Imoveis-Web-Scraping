import logging
import pandas as pd
import numpy as np
import unidecode
import joblib
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF
from utils_topicos import STOPWORDS_TOTAL, RE_REMOVE

logger = logging.getLogger(__name__)


def treinar_modelo_topicos(train, test, save_path, n_topics=4, max_features=2000):
    logger.info("Treinando modelo de topicos com spaCy...")
    try:
        nlp = spacy.load("pt_core_news_lg")
    except OSError:
        from spacy.cli.download import download as spacy_download
        spacy_download("pt_core_news_lg")
        nlp = spacy.load("pt_core_news_lg")

    def _limpar_spacy(texto):
        if pd.isna(texto) or not texto:
            return ""
        return RE_REMOVE.sub(" ", unidecode.unidecode(str(texto)))

    # Train
    desc_bruta = train["descricao"].astype(str).apply(_limpar_spacy)
    lemmas = []
    for doc in nlp.pipe(desc_bruta, batch_size=256, n_process=1):
        tokens = [t.lemma_.lower() for t in doc
                  if len(t.text) > 2 and not t.is_digit
                  and t.text not in STOPWORDS_TOTAL]
        lemmas.append(" ".join(tokens))

    df_temp = train[["valor_imovel"]].copy()
    df_temp["desc_lemma"] = lemmas
    faixas = pd.qcut(df_temp["valor_imovel"], q=5, duplicates="drop")
    df_macro = df_temp.groupby(faixas, observed=False)["desc_lemma"]\
        .apply(lambda x: " ".join(x)).reset_index()

    n_macro = len(df_macro)
    vec = TfidfVectorizer(
        max_features=max_features, ngram_range=(1, 2),
        min_df=max(1, n_macro // 5),
        max_df=min(0.80, 1 - 1 / n_macro),
    )
    vec.fit(df_macro["desc_lemma"])

    X_vec = vec.transform(df_temp["desc_lemma"])
    nmf = NMF(n_components=n_topics, random_state=42, init="nndsvdar")
    W = nmf.fit_transform(X_vec)

    for i in range(n_topics):
        train[f"componente_{i}"] = W[:, i]

    # Test
    desc_test = test["descricao"].astype(str).apply(_limpar_spacy)
    lemmas_test = []
    for doc in nlp.pipe(desc_test, batch_size=256, n_process=1):
        tokens = [t.lemma_.lower() for t in doc
                  if len(t.text) > 2 and not t.is_digit
                  and t.text not in STOPWORDS_TOTAL]
        lemmas_test.append(" ".join(tokens))

    X_test = vec.transform(lemmas_test)
    W_test = nmf.transform(X_test)
    for i in range(n_topics):
        test[f"componente_{i}"] = W_test[:, i]

    modelo = {"vectorizer": vec, "nmf": nmf, "n_topics": n_topics}
    joblib.dump(modelo, save_path)
    logger.info("Modelo de topicos salvo: %s", save_path)

    vocab = vec.get_feature_names_out()
    for i, topic in enumerate(nmf.components_):
        top_idx = topic.argsort()[-15:][::-1]
        tokens = [f"{vocab[idx]} ({topic[idx]:.2f})" for idx in top_idx]
        logger.info("Componente %d: %s", i, ", ".join(tokens))

    return modelo
