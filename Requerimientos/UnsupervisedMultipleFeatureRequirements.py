import os
import re
import unicodedata
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer
from sklearn.cluster import DBSCAN

import joblib


# -----------------------------
# Configuration
# -----------------------------
CSV_PATH = "requerimientos_depurado.csv"
OUTPUT_DIR = "unsupervised_model"
RANDOM_STATE = 42

# DBSCAN parameters (key knobs)
EPS = 0.7          # neighborhood radius (tune this)
MIN_SAMPLES = 15   # minimum points to form a cluster


# -----------------------------
# Text normalization
# -----------------------------
def normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s


def build_text(row: pd.Series) -> str:
    parts = [
        row.get("requested_for.title",""),
        row.get("requested_for.company",""),
        row.get("short_description",""),
        row.get("description","")
    ]
    return normalize_text(" ".join(p for p in parts if isinstance(p, str)))


# -----------------------------
# Load data
# -----------------------------
df = pd.read_csv(
    CSV_PATH,
    sep=";",
    dtype=str,
    engine="python",
    on_bad_lines="skip",
    encoding="latin-1"
)

df["text"] = df.apply(build_text, axis=1)
df = df[df["text"].str.len() > 5].copy()
print(len(df))
texts = df["text"].values


# -----------------------------
# Feature engineering
# -----------------------------
word_tfidf = (
    "word",
    TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        min_df=3,
        max_features=150_000,
        sublinear_tf=True,
        strip_accents="unicode"
    )
)

char_tfidf = (
    "char",
    TfidfVectorizer(
        analyzer="char",
        ngram_range=(3, 5),
        min_df=3,
        max_features=100_000
    )
)

features = FeatureUnion([word_tfidf, char_tfidf])


# -----------------------------
# Auto‑cluster pipeline
# -----------------------------
pipeline = Pipeline([
    ("features", features),
    ("svd", TruncatedSVD(n_components=100, random_state=RANDOM_STATE)),
    ("norm", Normalizer(copy=False)),
    ("cluster", DBSCAN(
        eps=EPS,
        min_samples=MIN_SAMPLES,
        metric="euclidean",
        n_jobs=-1
    ))
])


# -----------------------------
# Fit model
# -----------------------------
cluster_ids = pipeline.fit_predict(texts)
df["cluster_id"] = cluster_ids


# -----------------------------
# Diagnostics
# -----------------------------
n_clusters = len(set(cluster_ids)) - (1 if -1 in cluster_ids else 0)
n_noise = np.sum(cluster_ids == -1)

print("\n✅ Auto‑clustering complete")
print("Detected clusters:", n_clusters)
print("Noise / outliers:", n_noise)

print("\nCluster sizes:")
print(df["cluster_id"].value_counts().sort_index())


# -----------------------------
# Save artifacts
# -----------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

joblib.dump(
    pipeline,
    f"{OUTPUT_DIR}/requirements_clustering_auto_pipeline.joblib"
)

df[["cluster_id", "text"]].to_csv(
    f"{OUTPUT_DIR}/clustered_requrirements_auto.csv",
    index=False,
    encoding="utf-8"
)