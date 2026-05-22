import os
import re
import unicodedata
import warnings
warnings.filterwarnings("ignore")


import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score

# --- Stopwords en español con NLTK ---
try:
    from nltk.corpus import stopwords
    stopwords_es = stopwords.words('spanish')
except LookupError:
    import nltk
    nltk.download('stopwords')
    from nltk.corpus import stopwords
    stopwords_es = stopwords.words('spanish')
except ImportError:
    stopwords_es = None
    print("No se pudo importar NLTK. Eliminará stopwords solo si NLTK está instalado.")

CSV_PATH = os.path.join("Data", "Categorizaciones_incidentes_depurado(Hoja1).csv")
OUTPUT_PATH = os.path.join("Data", "Categorizaciones_incidentes_clasificadas.csv")

# --- Utilidades de texto ---
def normalize_text(s):
    if not isinstance(s, str): return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s)
    return s

def build_text(row):
    parts = [
        row.get("short_description", ""),
        row.get("description", ""),
        row.get("u_subcategory_2", ""),
        row.get("category", "")
    ]
    return normalize_text(" ".join([str(p) for p in parts if isinstance(p, str)]))

# --- Carga de datos ---
df = pd.read_csv(CSV_PATH, sep=",", dtype=str, encoding="latin-1")


# --- Normalizar columna de clasificación ---
col_clasif = "Clasificaci\u00f3n" if "Clasificaci\u00f3n" in df.columns else "Clasificacion"
df[col_clasif] = df[col_clasif].fillna(0).replace("", 0)

# --- Inspección visual tras normalización ---
print("\nPrimeras filas tras normalizar columna de clasificación:")
print(df[[col_clasif, 'short_description', 'description', 'category', 'u_subcategory_2']].head(10))

# --- Separar datos etiquetados y no etiquetados ---
mask_labeled = (df[col_clasif] != "0") & (df[col_clasif] != 0)
df_labeled = df[mask_labeled].copy()
df_unlabeled = df[~mask_labeled].copy()


# --- Mostrar distribución de clases antes de filtrar ---
print(f"Tickets con clasificación conocida: {len(df_labeled)}")
print(f"Tickets sin clasificación: {len(df_unlabeled)}")
print("\nDistribución de clases antes de filtrar:")
print(df_labeled[col_clasif].value_counts())

# --- Filtrar clases con menos de 2 ejemplos ---
vc = df_labeled[col_clasif].value_counts()
clases_validas = vc[vc >= 2].index
df_labeled = df_labeled[df_labeled[col_clasif].isin(clases_validas)].copy()

# --- Preparar texto para el modelo ---
df_labeled["text"] = df_labeled.apply(build_text, axis=1)
df_unlabeled["text"] = df_unlabeled.apply(build_text, axis=1)

# --- Entrenamiento modelo supervisado ---
le = LabelEncoder()
y = le.fit_transform(df_labeled[col_clasif])
X_text = df_labeled["text"].values

vectorizer = TfidfVectorizer(max_features=3000, ngram_range=(1,2), stop_words=stopwords_es)
X = vectorizer.fit_transform(X_text)

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

clf = LogisticRegression(max_iter=200)
clf.fit(X_train, y_train)

# --- Evaluación ---
y_pred = clf.predict(X_test)
print("Accuracy en test:", accuracy_score(y_test, y_pred))
print(classification_report(y_test, y_pred, target_names=le.inverse_transform(np.unique(y_test))))

# --- Predecir para los no etiquetados ---
if len(df_unlabeled) > 0:
    X_unlabeled = vectorizer.transform(df_unlabeled["text"].values)
    y_unlabeled_pred = clf.predict(X_unlabeled)
    df_unlabeled[col_clasif] = le.inverse_transform(y_unlabeled_pred)
    print(f"Se predijeron {len(df_unlabeled)} clasificaciones para tickets sin etiqueta.")
else:
    print("No hay tickets sin clasificación para predecir.")

# --- Unir y guardar resultado ---
df_final = pd.concat([df_labeled, df_unlabeled], ignore_index=True)
df_final.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
print(f"Archivo guardado en: {OUTPUT_PATH}")
