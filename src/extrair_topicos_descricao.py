import re
import logging
import argparse
import warnings
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import joblib
import spacy
import unidecode
from nltk.corpus import stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import NMF

logger = logging.getLogger(__name__)

STOPWORDS_NLTK = set(stopwords.words("portuguese"))

STOPWORDS_IMOVEIS = {
    "apartamento", "apartamentos", "imovel", "imoveis", "casa", "casas",
    "sobrado", "sobrados", "geminado", "geminados", "quarto", "quartos",
    "suite", "suites", "dormitorio", "dormitorios", "banheiro", "banheiros",
    "vaga", "vagas", "garagem", "garagens", "area", "areas", "cozinha",
    "sala", "lavanderia", "condominio", "empreendimento", "empreendimentos",
    "imobiliaria", "corretor", "corretora", "visita", "agende", "consulte",
    "contato", "joinville", "bairro", "venda", "informacao", "telefone",
    "whatsapp", "site", "anuncio", "contar", "proximo", "imobiliarios",
    "solicite", "valores", "consulta", "dia", "praticidade", "ambiente",
    "voce", "ideal", "familia", "perfeito", "qualidade", "vida", "conforto",
    "proporcionar", "momento", "amplo", "perca", "nao", "alem", "sob",
    "00", "000", "aprox", "br", "acesso", "facil", "buscar", "morar",
    "regiao", "cidade", "escola", "bom", "garantir", "metro", "fundo",
    "completo", "novo", "poder", "movel", "empresa", "estadual", "work",
    "gptw", "abmi", "reloca", "cliente", "carteira", "conquistamos", "great",
    "selo", "rede", "nacional", "tradicao", "credibilidade", "inovacao",
    "setor", "imobiliario", "comprar", "alugar", "canal", "atendimento",
    "humano", "digital", "iso", "fazemos", "parte", "possibilitar",
    "escolher", "caminho", "relacionar", "place", "modelo", "gestao",
    "fundada", "grande", "oferecer", "desejar", "venha", "conosco",
    "informacoes", "equipe", "saber", "querer", "video", "pra", "falar",
    "encante", "valido", "estoque", "vigente", "alteracao", "disponibilidade",
    "acordo", "direto", "atestar", "integrar", "colocar", "trabalhar",
    "experiencia", "lar", "esperar", "lugar", "apaixonar", "lindo",
    "ofertas", "oferta", "facilitar", "tempo", "tabela", "chave",
    "unidade", "durar", "enquanto", "valor", "sofrer", "aceitar",
    "aceita", "pagamento", "vista", "situado", "possuir", "jantar",
    "seguranca", "tudo", "medicao", "conter", "sendo", "sao",
    "joao", "costa", "furlanetto", "creci", "kolben", "marcio",
    "sonhos", "concretizados", "click", "link", "evjnttb",
    "personalizada", "oportunidade", "financia", "ampliacoes",
    "ampliacao", "diferenciais", "experiencias", "totvs", "anita",
    "america", "localizada", "rack", "gem", "codigo", "demi", "gloria",
}

STOPWORDS_TOTAL = STOPWORDS_NLTK | STOPWORDS_IMOVEIS

RE_REMOVE = re.compile(
    r"código\s+do\s+anúncio[\s:\d\-]+|código:\s*\d+|ref\.?:?\s*\d+|"
    r"ri[\-\s]*\d+|cr[ée]ci[\-\s]*\d+|"
    r"\b(creci|whatsapp|telefone|contato|celular)\b[\s\d\-\\(\\)]+|"
    r"\d{7,}|https?\://\S+|www\.\S+",
    re.IGNORECASE,
)


def limpar_descricoes_spacy(textos, nlp, batch_size=256):
    lemmas = []
    for doc in nlp.pipe(textos, batch_size=batch_size, n_process=1):
        tokens = []
        for token in doc:
            t = token.lemma_.lower()
            t = unidecode.unidecode(t)
            if len(t) > 2 and not t.isdigit() and t not in STOPWORDS_TOTAL:
                tokens.append(t)
        lemmas.append(" ".join(tokens))
    return lemmas


def extrair_topicos(
    cidade="joinville",
    mes_ref=None,
    pasta_dados=None,
    n_topics=4,
    max_features=2000,
):
    pasta_dados = Path(pasta_dados or Path(__file__).resolve().parent.parent / "dados" / cidade)

    if mes_ref is None:
        arquivos = sorted(pasta_dados.glob(f"{cidade}_imoveis_limpo_*.parquet"))
        if not arquivos:
            raise FileNotFoundError(f"Nenhum parquet encontrado em {pasta_dados}")
        mes_ref = arquivos[-1].stem.split("_")[-1]
        logger.info("Usando mes: %s", mes_ref)

    caminho = pasta_dados / f"{cidade}_imoveis_limpo_{mes_ref}.parquet"
    logger.info("Carregando: %s", caminho.name)
    df = pd.read_parquet(caminho)

    df_tipo = df[df["tipo_imovel"].isin(["apartamento", "casa"])].copy()
    df_tipo = df_tipo.dropna(subset=["descricao"])
    logger.info("Registros com descricao: %d", len(df_tipo))

    logger.info("Carregando spacy pt_core_news_lg...")
    nlp = spacy.load("pt_core_news_lg")

    descricoes = df_tipo["descricao"].astype(str)
    descricoes = descricoes.apply(lambda t: RE_REMOVE.sub(" ", t))

    logger.info("Limpando descricoes com spacy...")
    desc_limpas = limpar_descricoes_spacy(descricoes, nlp)
    df_tipo["descricao_limpa"] = desc_limpas

    logger.info("Agrupando por faixa de preco...")
    faixas = pd.qcut(df_tipo["valor_imovel"], q=5, duplicates="drop")
    df_treino = (
        df_tipo.groupby(faixas, observed=False)["descricao_limpa"]
        .apply(lambda x: " ".join(str(v) for v in x))
        .reset_index()
    )

    n_macro = len(df_treino)
    logger.info("Macro-documentos: %d", n_macro)

    vec = TfidfVectorizer(
        max_features=max_features,
        ngram_range=(1, 2),
        min_df=max(1, n_macro // 5),
        max_df=min(0.80, 1 - 1 / n_macro),
    )
    logger.info("Fitting TfidfVectorizer...")
    vec.fit(df_treino["descricao_limpa"])
    n_vocab = len(vec.get_feature_names_out())
    logger.info("Vocabulario: %d termos", n_vocab)

    X = vec.transform(df_tipo["descricao_limpa"])
    logger.info("Shape TF-IDF: %s", X.shape)

    nmf = NMF(n_components=n_topics, random_state=42, init="nndsvdar")
    W = nmf.fit_transform(X)

    vocab = vec.get_feature_names_out()
    for i, topic in enumerate(nmf.components_):
        top_idx = topic.argsort()[-15:][::-1]
        tokens = [f"{vocab[idx]} ({topic[idx]:.2f})" for idx in top_idx]
        logger.info("Componente %d: %s", i, ", ".join(tokens))

    for i in range(n_topics):
        df_tipo[f"componente_{i}"] = W[:, i]

    saida_pkl = pasta_dados / f"{cidade}_topicos_descricao_{mes_ref}.pkl"
    modelos = {"vectorizer": vec, "nmf": nmf, "n_topics": n_topics}
    joblib.dump(modelos, saida_pkl)
    logger.info("Modelos salvos: %s", saida_pkl.name)

    corr = df_tipo[[f"componente_{i}" for i in range(n_topics)] + ["valor_imovel"]].corr()
    logger.info("Correlacao com valor_imovel:\n%s",
                corr["valor_imovel"].drop("valor_imovel").sort_values(key=abs, ascending=False))

    logger.info("Concluido!")
    return modelos


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser()
    parser.add_argument("--cidade", default="joinville")
    parser.add_argument("--mes", default=None)
    parser.add_argument("--n_topics", type=int, default=4)
    parser.add_argument("--max_features", type=int, default=2000)
    args = parser.parse_args()

    extrair_topicos(
        cidade=args.cidade,
        mes_ref=args.mes,
        n_topics=args.n_topics,
        max_features=args.max_features,
    )
