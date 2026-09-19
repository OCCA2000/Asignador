"""
Código sincronizado automáticamente desde el cuaderno:
02_Entrenamiento_TFIDF_Requerimientos.ipynb (Última mod: 2026-09-19 13:11:02)
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

# ── Datos y visualización ───────────────────────────────────────────────────
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import joblib

# ── Procesamiento de texto ────────────────────────────────────────────────
import nltk
from nltk.corpus import stopwords

# ── Estadística y matrices dispersas ───────────────────────────────────────
from scipy.stats import f_oneway
from scipy.sparse import vstack

# ── Scikit-learn: features y preprocesamiento ──────────────────────────────
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

# ── Scikit-learn: modelos ─────────────────────────────────────────────
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier

# ── Scikit-learn: selección de modelos y métricas ────────────────────────
from sklearn.model_selection import train_test_split, StratifiedKFold, GroupShuffleSplit
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    f1_score, precision_score, recall_score
)

# ── Imbalanced-learn ─────────────────────────────────────────────
from imblearn.over_sampling import RandomOverSampler

warnings.filterwarnings('ignore')

# ── Configuración de gráficos ──────────────────────────────────────────
plt.style.use('seaborn-v0_8-darkgrid')
sns.set(rc={'figure.figsize': (10, 6)})

# Ruta del archivo curado exportado por el EDA
explicit_data = os.environ.get('TRAINING_DATA_PATH', None)
ruta_csv = get_latest_training_dataset('requerimientos', kind='preparados', explicit_path=explicit_data, verbose=True)
print(f"Cargando dataset preparado desde: {ruta_csv}")

df = pd.read_csv(ruta_csv, sep=';', encoding='latin-1')
print(f"Dimensiones totales: {df.shape[0]} filas x {df.shape[1]} columnas")
print(f"Tickets clasificados: {(df['Clasificación'] != 'sin_clasificar').sum()}")
print(f"Tickets sin clasificar: {(df['Clasificación'] == 'sin_clasificar').sum()}")
df.head(3)

# Separar tickets clasificados y no clasificados
df_clasificados = df[df['Clasificación'] != 'sin_clasificar'].copy()
df_no_clasificados = df[df['Clasificación'] == 'sin_clasificar'].copy()
print(f"Tickets clasificados: {df_clasificados.shape[0]}")
print(f"Tickets sin clasificar: {df_no_clasificados.shape[0]}")

# ===== PASO 1: VECTORIZACIÓN ÚNICA Y CONSISTENTE =====
vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
# Vectorizar datos clasificados
X_clasificados = vectorizer.fit_transform(df_clasificados['texto_unificado'])
y_clasificados = df_clasificados['Clasificación'].values
# Vectorizar datos sin clasificar (usando el MISMO vectorizer)
X_no_clasificados = vectorizer.transform(df_no_clasificados['texto_unificado'])
print("Distribución original de clases:", Counter(y_clasificados))
print(f"Matriz X_clasificados shape: {X_clasificados.shape}")
print(f"Vectorizer features: {vectorizer.get_feature_names_out().shape[0]}")

# ===== PASO 2: PARTICIPACIÓN POR GRUPOS (GroupShuffleSplit) =====
y_clasificados_str = np.array(y_clasificados, dtype=str)
grupos = df_clasificados['texto_unificado_raw'].astype(str).values

# Clases con un solo grupo único van directo a Train para asegurar que el modelo las conozca
grupos_por_clase = df_clasificados.groupby('Clasificación')['texto_unificado_raw'].nunique()
clases_un_solo_grupo = grupos_por_clase[grupos_por_clase < 2].index.tolist()

indices = np.arange(len(df_clasificados))

if clases_un_solo_grupo:
    print(f"  Clases con 1 solo grupo único (van directo a Train): {clases_un_solo_grupo}")
    mask_un_grupo = df_clasificados['Clasificación'].isin(clases_un_solo_grupo).values
    idx_un_grupo = indices[mask_un_grupo]
    idx_multigrupo = indices[~mask_un_grupo]

    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_rel, test_rel = next(
        gss.split(
            X_clasificados[idx_multigrupo],
            y_clasificados_str[idx_multigrupo],
            groups=grupos[idx_multigrupo]
        )
    )
    idx_train = np.concatenate([idx_multigrupo[train_rel], idx_un_grupo])
    idx_test = idx_multigrupo[test_rel]
else:
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_rel, test_rel = next(
        gss.split(
            X_clasificados,
            y_clasificados_str,
            groups=grupos
        )
    )
    idx_train = indices[train_rel]
    idx_test = indices[test_rel]

# Generar matrices y etiquetas de Train y Test
X_train, y_train = X_clasificados[idx_train], y_clasificados_str[idx_train]
X_test, y_test = X_clasificados[idx_test], y_clasificados_str[idx_test]

# Reconstruir DataFrame base del test set para auditoría posterior
df_test_base = df_clasificados.iloc[idx_test].copy().reset_index(drop=True)
df_test_base['y_real'] = y_test

# Verificación estricta de cero fuga de datos
overlap_grupos = set(grupos[idx_train]).intersection(set(grupos[idx_test]))
assert len(overlap_grupos) == 0, f"¡Alerta! Hay {len(overlap_grupos)} grupos compartidos."

print(f"✓ Train set: {X_train.shape[0]} muestras ({X_train.shape[0] / len(df_clasificados):.1%})")
print(f"✓ Test set:  {X_test.shape[0]} muestras ({X_test.shape[0] / len(df_clasificados):.1%})")
print(f"✓ Total grupos únicos Train: {len(set(grupos[idx_train]))} | Test: {len(set(grupos[idx_test]))}")
print(f"✓ Overlap de textos entre Train y Test: {len(overlap_grupos)} (Data Leakage = 0)")
print(f"✓ df_test_base: {df_test_base.shape[0]} filas listas para evaluación")

# ===== PASO 3: OVERSAMPLING SOLO EN TRAIN =====
ros = RandomOverSampler(random_state=42)
X_train_balanced, y_train_balanced = ros.fit_resample(X_train, y_train)

conteo_antes  = Counter(y_train)
conteo_despues = Counter(y_train_balanced)

print(f"✓ Balanceo con RandomOverSampler")
print(f"  Muestras antes:   {X_train.shape[0]}")
print(f"  Muestras después: {X_train_balanced.shape[0]}")
print(f"\nDistribución después del balanceo ({len(conteo_despues)} clases, todas igualadas):")
print(conteo_despues)

# ===== PASO 4: BÚSQUEDA DE k ÓPTIMO CON CROSS-VALIDATION =====
k_range = range(1, 16)
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
f1_scores = []

for k in k_range:
    knn_cv = KNeighborsClassifier(n_neighbors=k)
    fold_scores = []
    for train_idx, val_idx in cv.split(X_train_balanced, y_train_balanced):
        knn_cv.fit(X_train_balanced[train_idx], y_train_balanced[train_idx])
        val_pred = knn_cv.predict(X_train_balanced[val_idx])
        fold_scores.append(f1_score(y_train_balanced[val_idx], val_pred, average='weighted', zero_division=0))
    f1_scores.append(np.mean(fold_scores))

mejor_k = k_range[np.argmax(f1_scores)]
print(f"✓ k óptimo seleccionado: {mejor_k} (F1-score CV = {max(f1_scores):.4f})")

plt.figure(figsize=(9, 4))
plt.plot(k_range, f1_scores, marker='o', color='royalblue')
plt.axvline(mejor_k, color='red', linestyle='--', label=f'k óptimo = {mejor_k}')
plt.xlabel('Número de Vecinos (k)')
plt.ylabel('F1-Score Ponderado (CV 5-fold)')
plt.title('Método del Codo para KNN sobre Requerimientos')
plt.legend()
plt.tight_layout()
plt.close()

# ===== PASO 5: ENTRENAMIENTO DE CLASIFICADORES =====
modelos = {
    f'KNN (k={mejor_k})': KNeighborsClassifier(n_neighbors=mejor_k),
    'Logistic Regression': LogisticRegression(C=1.0, max_iter=3000, random_state=42, solver='lbfgs'),
    'Linear SVC': LinearSVC(C=1.0, max_iter=3000, random_state=42),
    'Random Forest': RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)
}

predicciones_modelos = {}
metricas_modelos = {}

for nombre, clf in modelos.items():
    print(f"Entrenando {nombre}...")
    clf.fit(X_train_balanced, y_train_balanced)
    y_pred = clf.predict(X_test)
    predicciones_modelos[nombre] = y_pred
    
    metricas_modelos[nombre] = {
        'Accuracy': accuracy_score(y_test, y_pred),
        'F1-Weighted': f1_score(y_test, y_pred, average='weighted', zero_division=0),
        'F1-Macro': f1_score(y_test, y_pred, average='macro', zero_division=0),
        'Precision': precision_score(y_test, y_pred, average='weighted', zero_division=0),
        'Recall': recall_score(y_test, y_pred, average='weighted', zero_division=0)
    }

df_resultados = pd.DataFrame(metricas_modelos).T.sort_values(by='F1-Weighted', ascending=False)
print("\n" + "="*85)
print("DESEMPEÑO EN TEST SET — MODELOS DE LÍNEA BASE TF-IDF")
print("="*85)
print(df_resultados.to_string())

# Gráfico comparativo de modelos
metricas = ['Accuracy', 'F1-Weighted', 'F1-Macro', 'Precision', 'Recall']
n_modelos = len(df_resultados)
ancho = 0.18
x = np.arange(len(metricas))
colores = ['#4C72B0', '#DD8452', '#55A868', '#C44E52']

fig, ax = plt.subplots(figsize=(12, 5))
for i, (nombre, row) in enumerate(df_resultados.iterrows()):
    valores = [row[m] for m in metricas]
    barras = ax.bar(x + i * ancho, valores, ancho, label=nombre, color=colores[i % len(colores)], alpha=0.88)
    for barra, val in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2,
                barra.get_height() + 0.008,
                f'{val:.3f}', ha='center', va='bottom', fontsize=7.5)

offset_centro = (n_modelos - 1) * ancho / 2
ax.set_xticks(x + offset_centro)
ax.set_xticklabels(metricas, fontsize=11)
ax.set_ylim(0, 1.15)
ax.set_ylabel('Score', fontsize=11)
ax.set_title('Comparativa de Clasificadores — Conjunto de Prueba (Requerimientos)', fontsize=13, fontweight='bold')
ax.legend(loc='upper right', fontsize=10)
ax.grid(axis='y', linestyle='--', alpha=0.5)
plt.tight_layout()
plt.close()

# Usar el modelo con mejor F1-Weighted
mejor = df_resultados.index[0]
mejor_modelo = modelos[mejor]
print(f'[MEJOR CLASIFICADOR]: {mejor}')

y_pred_mejor = predicciones_modelos[mejor]
indices_errores = np.where(y_test != y_pred_mejor)[0]
df_errores = df_test_base.iloc[indices_errores].copy()
df_errores['y_predicho'] = y_pred_mejor[indices_errores]
df_errores['es_error'] = True

print(f"Total de errores en test set: {len(df_errores)} de {len(y_test)}")
print(f"Tasa de error: {len(df_errores) / len(y_test) * 100:.2f}%")
print(f"Accuracy: {1 - len(df_errores) / len(y_test):.4f}\n")

confusiones = df_errores.groupby(['y_real', 'y_predicho']).size().reset_index(name='count')
confusiones = confusiones.sort_values('count', ascending=False).head(15)
print("Top 15 confusiones más frecuentes:")
print(confusiones.to_string(index=False))

# 1) Resumen por tipo de confusión (real -> predicho) con IDs de tickets
if 'number' not in df_errores.columns:
    df_errores['number'] = df_errores.index.astype(str)

resumen_confusiones_tickets = (
    df_errores.groupby(['y_real', 'y_predicho'], as_index=False)
    .agg(
        total_tickets=('number', 'count'),
        tickets=('number', lambda x: ', '.join(x.astype(str).head(30)))
    )
    .sort_values('total_tickets', ascending=False)
)

print("\nTop confusiones con tickets asociados:")
display(resumen_confusiones_tickets.head(15))

# Exportar a CSV el resumen y detalle de tickets con confusión
fecha_hoy = pd.Timestamp.today().strftime("%Y-%m-%d")
carpeta_output = 'Resultados'
os.makedirs(carpeta_output, exist_ok=True)

ruta_resumen = os.path.join(carpeta_output, f"resumen_confusiones_tickets_{fecha_hoy}.csv")
resumen_confusiones_tickets.to_csv(ruta_resumen, index=False, encoding='utf-8-sig')
print(f"✓ Resumen exportado: {ruta_resumen} ({len(resumen_confusiones_tickets)} filas)")

cols_detalle = [c for c in ['number', 'short_description', 'texto_unificado', 'y_real', 'y_predicho'] if c in df_errores.columns]
detalle_tmp = df_errores[cols_detalle].sort_values(['y_real', 'y_predicho', 'number']).reset_index(drop=True)
ruta_detalle = os.path.join(carpeta_output, f"tickets_confundidos_{fecha_hoy}.csv")
detalle_tmp.to_csv(ruta_detalle, index=False, encoding='utf-8-sig')
print(f"✓ Detalle exportado: {ruta_detalle} ({len(detalle_tmp)} filas)")

# Predicción sobre tickets no clasificados
y_pred_final = mejor_modelo.predict(X_no_clasificados)

if hasattr(mejor_modelo, 'predict_proba'):
    proba_matrix = mejor_modelo.predict_proba(X_no_clasificados)
    confianza = proba_matrix.max(axis=1)
    umbral_revision = 0.40
    tipo_confianza = 'probabilidad calibrada'
else:
    scores = mejor_modelo.decision_function(X_no_clasificados)
    exp_scores = np.exp(scores - scores.max(axis=1, keepdims=True))
    proba_matrix = exp_scores / exp_scores.sum(axis=1, keepdims=True)
    confianza = proba_matrix.max(axis=1)
    umbral_revision = 0.10
    tipo_confianza = 'softmax(decision_function)'

cols_visibles = [c for c in ['number', 'short_description', 'description', 'requested_for.title', 'requested_for.company', 'texto_unificado', 'Clasificación'] if c in df_no_clasificados.columns]
df_resultado = df_no_clasificados[cols_visibles].copy()
df_resultado['Clasificación_predicha'] = y_pred_final
df_resultado['Confianza'] = np.round(confianza, 4)
df_resultado['Requiere_revision'] = confianza < umbral_revision
df_resultado['Modelo_usado'] = mejor

print(f"Modelo usado: {mejor}  |  Tipo de confianza: {tipo_confianza}")
print(f"Umbral de revisión aplicado: {umbral_revision}")
print(f"Total de requerimientos sin clasificar predichos: {len(df_resultado)}")
print(f"Tickets con baja confianza (< {umbral_revision}): {df_resultado['Requiere_revision'].sum()} ({df_resultado['Requiere_revision'].mean():.1%})")

# Exportar tickets clasificados
nombre_modelo_csv = mejor.replace(" ", "_")
nombre_archivo = f"tickets_clasificados_{nombre_modelo_csv}_{fecha_hoy}.csv"
ruta_salida_pred = os.path.join(carpeta_output, nombre_archivo)
df_resultado.to_csv(ruta_salida_pred, index=False, encoding='utf-8-sig', sep=';')
print(f"✓ CSV de predicciones exportado: {ruta_salida_pred}")

# Combinar clasificados originales + reclasificados
df_clasificados_final = df_clasificados[cols_visibles].copy()
df_clasificados_final['Fuente'] = 'Original_Clasificado'
df_clasificados_final['Confianza'] = 1.0

df_reclasificados = df_no_clasificados[cols_visibles].copy()
df_reclasificados['Clasificación'] = y_pred_final
df_reclasificados['Fuente'] = 'Reclasificado_IA'
df_reclasificados['Confianza'] = confianza

df_completo = pd.concat([df_clasificados_final, df_reclasificados], ignore_index=True, sort=False)
df_completo = df_completo.sort_values('number').reset_index(drop=True)

nombre_archivo_completo = f"tickets_clasificados_completo_{nombre_modelo_csv}_{fecha_hoy}.csv"
ruta_salida_completa = os.path.join(carpeta_output, nombre_archivo_completo)
df_completo.to_csv(ruta_salida_completa, index=False, encoding='utf-8-sig', sep=';')
print(f"✓ CSV COMPLETO exportado: {ruta_salida_completa}")
print(f"  Total registros combinados: {len(df_completo)}")

# Persistencia del modelo y vectorizer
carpeta_modelo = os.path.normpath(os.path.join(os.getcwd(), '..', '..', 'semisupervised_model'))
os.makedirs(carpeta_modelo, exist_ok=True)

# Guardamos Logistic Regression como modelo estándar del RPA
lr_clf = modelos.get('Logistic Regression', mejor_modelo)
ruta_modelo = os.path.join(carpeta_modelo, 'modelo_Logistic_Regression.joblib')
ruta_vectorizer = os.path.join(carpeta_modelo, 'vectorizer_tfidf.joblib')

joblib.dump(lr_clf, ruta_modelo)
joblib.dump(vectorizer, ruta_vectorizer)

print(f"✓ Modelo guardado:     {ruta_modelo}")
print(f"✓ Vectorizer guardado: {ruta_vectorizer}")

