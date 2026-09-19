"""
Código sincronizado automáticamente desde el cuaderno:
03_Entrenamiento_HNLP_MC_Incidentes.ipynb (Última mod: 2026-09-19 16:52:29)
"""
import os, sys, warnings
warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
# Asegurar importación de utilidades del pipeline
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from Programas.PipelineUtils import get_latest_training_dataset, clean_and_deidentify_text
# Compatibilidad con funciones nativas de Jupyter
try:
    from IPython.display import display
except ImportError:
    def display(*args, **kwargs):
        for a in args:
            print(a)

# ── Librería estándar ─────────────────────────────────────────────────────────
import os
import re
import unicodedata
import warnings
from collections import Counter

# ── Datos y visualización ─────────────────────────────────────────────────────
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import joblib

# ── Procesamiento de texto y NLP ──────────────────────────────────────────────
import nltk
from nltk.corpus import stopwords

# ── Scikit-learn: Preprocesamiento multicanal y Pipeline ──────────────────────
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder

# ── Scikit-learn: Modelos y Validación ───────────────────────────────────────
from sklearn.model_selection import GroupShuffleSplit
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    f1_score, precision_score, recall_score
)

# ── Imbalanced-learn ─────────────────────────────────────────────────────────
from imblearn.over_sampling import RandomOverSampler

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8-darkgrid')
sns.set(rc={'figure.figsize': (10, 6)})

explicit_data = os.environ.get('TRAINING_DATA_PATH', None)
ruta_csv = get_latest_training_dataset('incidentes', kind='preparados', explicit_path=explicit_data, verbose=True)
print(f"Cargando dataset preparado desde: {ruta_csv}")

df = pd.read_csv(ruta_csv, sep=';', encoding='latin-1')
print(f"Dimensiones: {df.shape[0]} filas x {df.shape[1]} columnas")
print(f"Tickets clasificados: {(df['Clasificación'] != 'sin_clasificar').sum()}")
print(f"Tickets sin clasificar: {(df['Clasificación'] == 'sin_clasificar').sum()}")
df.head(2)

# Importar función centralizada de desidentificación y normalización desde PipelineUtils
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), '..', '..', '..')))
from Programas.PipelineUtils import clean_and_deidentify_text

limpiar_cadena = clean_and_deidentify_text

# 1. Canal de Texto Libre
df['texto_sintoma'] = (df['short_description'].fillna('') + ' ' + df['description'].fillna('')).apply(limpiar_cadena)

# 2. Canal de Rol / Cargo
df['cargo_solicitante'] = df['u_affected_user.title'].fillna('desconocido').apply(limpiar_cadena)

# 3. Canal de Metadatos Categóricos Discretos
df['aplicacion'] = df['cmdb_ci_business_app'].fillna('DESCONOCIDO').astype(str)
df['empresa'] = df['u_affected_user.company'].fillna('DESCONOCIDO').astype(str)
df['subcategoria'] = df['u_subcategory_2'].fillna('DESCONOCIDO').astype(str)

# Separar conjunto clasificado y no clasificado
df_clasificados = df[df['Clasificación'] != 'sin_clasificar'].copy().reset_index(drop=True)
df_no_clasificados = df[df['Clasificación'] == 'sin_clasificar'].copy().reset_index(drop=True)

print(f"✓ Columnas procesadas para los 3 canales.")
print(f"✓ Total tickets clasificados: {len(df_clasificados)}")
print(f"✓ Total tickets sin clasificar: {len(df_no_clasificados)}")

# Definición de grupos basados en el texto crudo para aislar plantillas
grupos = df_clasificados['texto_unificado_raw'].astype(str).values
y_clasificados = df_clasificados['Clasificación'].astype(str).values

# Proteger clases con un solo grupo único (asignándolas a Train)
grupos_por_clase = df_clasificados.groupby('Clasificación')['texto_unificado_raw'].nunique()
clases_un_solo_grupo = grupos_por_clase[grupos_por_clase < 2].index.tolist()
indices = np.arange(len(df_clasificados))

if clases_un_solo_grupo:
    mask_un_grupo = df_clasificados['Clasificación'].isin(clases_un_solo_grupo).values
    idx_un_grupo = indices[mask_un_grupo]
    idx_multigrupo = indices[~mask_un_grupo]

    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_rel, test_rel = next(
        gss.split(df_clasificados.iloc[idx_multigrupo], y_clasificados[idx_multigrupo], groups=grupos[idx_multigrupo])
    )
    idx_train = np.concatenate([idx_multigrupo[train_rel], idx_un_grupo])
    idx_test = idx_multigrupo[test_rel]
else:
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_rel, test_rel = next(gss.split(df_clasificados, y_clasificados, groups=grupos))
    idx_train = indices[train_rel]
    idx_test = indices[test_rel]

# Crear DataFrames de Train y Test
df_train = df_clasificados.iloc[idx_train].copy().reset_index(drop=True)
df_test = df_clasificados.iloc[idx_test].copy().reset_index(drop=True)

y_train = df_train['Clasificación'].values
y_test = df_test['Clasificación'].values

print(f"✓ Train set: {len(df_train)} muestras ({len(df_train)/len(df_clasificados):.1%})")
print(f"✓ Test set:  {len(df_test)} muestras ({len(df_test)/len(df_clasificados):.1%})")
print(f"✓ Cero Data Leakage: Ningún grupo de texto se comparte entre Train y Test.")

# Definición de transformadores por canal
canal_texto = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
canal_cargo = TfidfVectorizer(max_features=150, ngram_range=(1, 1))
canal_metadatos = OneHotEncoder(handle_unknown='ignore', sparse_output=True)

# Ensamblar ColumnTransformer
preprocesador_hnlp = ColumnTransformer(
    transformers=[
        ('canal_1_texto', canal_texto, 'texto_sintoma'),
        ('canal_2_cargo', canal_cargo, 'cargo_solicitante'),
        ('canal_3_metadatos', canal_metadatos, ['aplicacion', 'empresa', 'subcategoria'])
    ],
    remainder='drop'
)

# Ajustar sobre train y transformar train y test
X_train_mc = preprocesador_hnlp.fit_transform(df_train)
X_test_mc = preprocesador_hnlp.transform(df_test)

print(f"✓ Matriz multicanal X_train shape: {X_train_mc.shape}")
print(f"✓ Matriz multicanal X_test shape:  {X_test_mc.shape}")
print(f"  -> Características Canal 1 (Texto): {preprocesador_hnlp.named_transformers_['canal_1_texto'].get_feature_names_out().shape[0]}")
print(f"  -> Características Canal 2 (Cargo): {preprocesador_hnlp.named_transformers_['canal_2_cargo'].get_feature_names_out().shape[0]}")
print(f"  -> Características Canal 3 (Metadatos OHE): {preprocesador_hnlp.named_transformers_['canal_3_metadatos'].get_feature_names_out().shape[0]}")

ros = RandomOverSampler(random_state=42)
X_train_res, y_train_res = ros.fit_resample(X_train_mc, y_train)

print(f"✓ Muestras Train antes de balanceo: {X_train_mc.shape[0]}")
print(f"✓ Muestras Train tras balanceo:     {X_train_res.shape[0]}")
print(f"✓ Clases igualadas a: {Counter(y_train_res).most_common(1)[0][1]} ejemplos por clase")

modelos_mc = {
    'Logistic Regression (HNLP-MC)': LogisticRegression(C=1.0, max_iter=3000, random_state=42, solver='lbfgs'),
    'Linear SVC (HNLP-MC)': LinearSVC(C=1.0, max_iter=3000, random_state=42),
    'Random Forest (HNLP-MC)': RandomForestClassifier(n_estimators=200, max_depth=None, random_state=42, n_jobs=-1)
}

resultados_mc = {}

for nombre, clf in modelos_mc.items():
    print(f"Entrenando {nombre}...")
    clf.fit(X_train_res, y_train_res)
    y_pred = clf.predict(X_test_mc)
    
    acc = accuracy_score(y_test, y_pred)
    f1_w = f1_score(y_test, y_pred, average='weighted', zero_division=0)
    f1_m = f1_score(y_test, y_pred, average='macro', zero_division=0)
    prec_w = precision_score(y_test, y_pred, average='weighted', zero_division=0)
    rec_w = recall_score(y_test, y_pred, average='weighted', zero_division=0)
    
    resultados_mc[nombre] = {
        'Modelo': clf,
        'Accuracy': acc,
        'F1-Weighted': f1_w,
        'F1-Macro': f1_m,
        'Precision-W': prec_w,
        'Recall-W': rec_w,
        'y_pred': y_pred
    }

df_metricas_mc = pd.DataFrame([
    {
        'Modelo': k,
        'Accuracy': v['Accuracy'],
        'F1-Weighted': v['F1-Weighted'],
        'F1-Macro': v['F1-Macro'],
        'Precision': v['Precision-W'],
        'Recall': v['Recall-W']
    }
    for k, v in resultados_mc.items()
]).sort_values(by='F1-Weighted', ascending=False).reset_index(drop=True)

print("\n" + "="*85)
print("DESEMPEÑO EN TEST SET — ARQUITECTURA HNLP-MC")
print("="*85)
print(df_metricas_mc.to_string(index=False))

# Visualización comparativa de métricas
fig, ax = plt.subplots(figsize=(10, 5))
df_plot = df_metricas_mc.melt(id_vars='Modelo', value_vars=['Accuracy', 'F1-Weighted', 'F1-Macro', 'Precision', 'Recall'], var_name='Métrica', value_name='Score')
sns.barplot(data=df_plot, x='Métrica', y='Score', hue='Modelo', palette='Set2', ax=ax)
ax.set_title("Comparativa de Clasificadores en Arquitectura HNLP-MC (Test Set)", fontsize=12, fontweight='bold')
ax.set_ylim(0, 1.05)
for p in ax.patches:
    if p.get_height() > 0:
        ax.annotate(f"{p.get_height():.2f}", (p.get_x() + p.get_width() / 2., p.get_height() / 2), ha='center', va='center', fontsize=9, color='white', fontweight='bold', rotation=90)
plt.tight_layout()
plt.close()

# Identificar mejor modelo
mejor_nombre_mc = df_metricas_mc.iloc[0]['Modelo']
mejor_modelo_mc = resultados_mc[mejor_nombre_mc]['Modelo']
y_pred_mejor = resultados_mc[mejor_nombre_mc]['y_pred']
print(f"\n🏆 Mejor modelo HNLP-MC seleccionado: {mejor_nombre_mc}")
print(f"   F1-Weighted: {resultados_mc[mejor_nombre_mc]['F1-Weighted']:.4f} | F1-Macro: {resultados_mc[mejor_nombre_mc]['F1-Macro']:.4f}")

# Matriz de Confusión del mejor modelo HNLP-MC
labels_mc = sorted(list(set(y_test)))
cm = confusion_matrix(y_test, y_pred_mejor, labels=labels_mc, normalize='true')

plt.figure(figsize=(14, 10))
sns.heatmap(cm, annot=False, cmap='Blues', xticklabels=labels_mc, yticklabels=labels_mc)
plt.title(f"Matriz de Confusión Normalizada — {mejor_nombre_mc}", fontsize=12, fontweight='bold')
plt.xlabel("Predicción")
plt.ylabel("Real")
plt.xticks(rotation=90)
plt.tight_layout()
plt.close()

# Transformar datos sin clasificar con el preprocesador multicanal ajustado
X_no_clasificados_mc = preprocesador_hnlp.transform(df_no_clasificados)

# Predicción de categorías
predicciones_no_clasificados = mejor_modelo_mc.predict(X_no_clasificados_mc)

# Probabilidades o confianza (si el modelo lo soporta)
if hasattr(mejor_modelo_mc, 'predict_proba'):
    probas = mejor_modelo_mc.predict_proba(X_no_clasificados_mc)
    confianzas = probas.max(axis=1)
else:
    decision = mejor_modelo_mc.decision_function(X_no_clasificados_mc)
    confianzas = decision.max(axis=1)

df_no_clasificados_pred = df_no_clasificados.copy()
df_no_clasificados_pred['Clasificación_Sugerida'] = predicciones_no_clasificados
df_no_clasificados_pred['Confianza_Modelo'] = np.round(confianzas, 4)

print(f"✓ {len(df_no_clasificados_pred)} tickets sin clasificar han sido predichos con {mejor_nombre_mc}.")
print("\nTop 10 categorías asignadas:")
print(df_no_clasificados_pred['Clasificación_Sugerida'].value_counts().head(10))

# Construir Pipeline integral End-to-End
pipeline_hnlp_mc = Pipeline([
    ('preprocesador', preprocesador_hnlp),
    ('clasificador', mejor_modelo_mc)
])

carpeta_modelo = os.path.normpath(os.path.join(os.getcwd(), '..', '..', 'semisupervised_model'))
os.makedirs(carpeta_modelo, exist_ok=True)

ruta_pipeline = os.path.join(carpeta_modelo, 'pipeline_HNLP_MC.joblib')
joblib.dump(pipeline_hnlp_mc, ruta_pipeline)

print(f"✓ Pipeline HNLP-MC guardado exitosamente:")
print(f"  Ruta: {ruta_pipeline}")
print()
print("Para utilizar en Assigner_Incidents.py o RPA ServiceNow:")
print("  pipeline = joblib.load('semisupervised_model/pipeline_HNLP_MC.joblib')")
print("  predicciones = pipeline.predict(df_incidentes_nuevos)")

