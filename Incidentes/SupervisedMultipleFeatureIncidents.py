import os, re, unicodedata, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC
from sklearn.metrics import classification_report, accuracy_score, f1_score
import joblib

CSV_PATH = "incidentes_depurado.csv"

def normalize_text(s: str) -> str:
    if not isinstance(s, str): return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s

def build_text(row):
    # mapea app primero para dar señal fuerte
    parts = [
        row.get("u_subcategory_2",""),
        row.get("cmdb_ci_business_app",""),
        row.get("short_description",""),
        row.get("u_affected_user.title",""),
        row.get("u_affected_user.department",""),
        row.get("u_affected_user.company",""),
        row.get("location.cmn_location_type",""),
        row.get("description","")
    ]
    return normalize_text(" ".join([p for p in parts if isinstance(p, str)]))

# --- Carga
df = pd.read_csv(CSV_PATH, sep=';', dtype=str, engine='python',
                 on_bad_lines='skip', encoding='latin-1')
need = [
        "u_subcategory_2",
        "cmdb_ci_business_app",
        "short_description",
        "u_affected_user.title",
        "u_affected_user.department",
        "u_affected_user.company",
        "location.cmn_location_type",
        "description",
        "assigned_to"]
for c in need:
    if c not in df.columns:
        raise ValueError(f"Falta columna: {c}")
        
df['cmdb_ci_business_app'] = df['cmdb_ci_business_app'].astype(str).fillna(df['cmdb_ci'])

df["text"] = df.apply(build_text, axis=1)
df["assigned_to"] = df["assigned_to"].fillna("DESCONOCIDO").str.strip()
df = df[(df["text"].str.len() > 3) & (df["assigned_to"].str.len() > 0)].copy()

# --- Reagrupar clases raras (umbral ajustable)
#freq = df["assigned_to"].value_counts()
#rare = set(freq[freq < 50].index)   # <-- prueba con 30/40/50
#df["assigned_to"] = df["assigned_to"].apply(lambda x: "OTROS" if x in rare else x)

X = df["text"].values
y = df["assigned_to"].values

le = LabelEncoder()
y_enc = le.fit_transform(y)

X_train, X_valid, y_train, y_valid = train_test_split(
    X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
)

# --- FeatureUnion: word TF-IDF + char TF-IDF
word_tfidf = ("word", TfidfVectorizer(
    analyzer="word",
    ngram_range=(1,2),
    min_df=3,
    max_features=150_000,
    sublinear_tf=True,
    strip_accents="unicode"
))
char_tfidf = ("char", TfidfVectorizer(
    analyzer="char",
    ngram_range=(3,5),
    min_df=3,
    max_features=100_000
))

features = FeatureUnion([word_tfidf, char_tfidf])

# --- Pipeline con opción LSA (comentada por defecto)
pipeline = Pipeline([
    ("feats", features),
    # ("svd", TruncatedSVD(n_components=300, random_state=42)),  # <-- activa si quieres LSA
    ("clf", LinearSVC(class_weight="balanced", random_state=42))
])

# --- Tuning simple de C (rápido). Si activas SVD, ajusta C algo mayor.
param_grid = {
    "clf__C": [0.5, 1.0, 2.0, 5.0]
}
gs = GridSearchCV(
    pipeline, param_grid=param_grid, scoring="f1_macro",
    cv=3, n_jobs=-1, verbose=1
)
gs.fit(X_train, y_train)

best = gs.best_estimator_
y_pred = best.predict(X_valid)

acc = accuracy_score(y_valid, y_pred)
f1_macro = f1_score(y_valid, y_pred, average="macro")
f1_micro = f1_score(y_valid, y_pred, average="micro")

print("Best params:", gs.best_params_)
print(f"Accuracy:  {acc:.4f}")
print(f"F1-macro:  {f1_macro:.4f}")
print(f"F1-micro:  {f1_micro:.4f}")
print("\nReporte de clasificación:")
print(classification_report(y_valid, y_pred, target_names=le.inverse_transform(np.unique(y_valid))))

os.makedirs("supervised_model", exist_ok=True)
joblib.dump(best, "supervised_model/assigned_to_tfidf_svm.joblib")
joblib.dump(le,   "supervised_model/label_encoder.joblib")
