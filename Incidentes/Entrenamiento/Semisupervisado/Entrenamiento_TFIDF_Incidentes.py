"""
Código sincronizado automáticamente desde el cuaderno:
02_Entrenamiento_TFIDF_Incidentes.ipynb (Última mod: 2026-09-04 00:05:57)
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

# ── Procesamiento de texto ────────────────────────────────────────────────────
import nltk
from nltk.corpus import stopwords

# ── Estadística y matrices dispersas ─────────────────────────────────────────
from scipy.stats import f_oneway
from scipy.sparse import vstack

# ── Scikit-learn: features y preprocesamiento ────────────────────────────────
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer

# ── Scikit-learn: modelos ─────────────────────────────────────────────────────
from sklearn.linear_model import LogisticRegression
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import LinearSVC
from sklearn.ensemble import RandomForestClassifier

# ── Scikit-learn: selección de modelos y métricas ────────────────────────────
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    f1_score, precision_score, recall_score
)

# ── Imbalanced-learn ─────────────────────────────────────────────────────────
from imblearn.over_sampling import RandomOverSampler

warnings.filterwarnings('ignore')

# ── Configuración de gráficos ─────────────────────────────────────────────────
plt.style.use('seaborn-v0_8-darkgrid')
sns.set(rc={'figure.figsize': (10, 6)})

# Ruta del archivo curado exportado por el EDA
explicit_data = os.environ.get('TRAINING_DATA_PATH', None)
ruta_csv = get_latest_training_dataset('incidentes', kind='preparados', explicit_path=explicit_data, verbose=True)
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
# Las stopwords ya fueron eliminadas en limpiar_texto → no se repasan aquí
vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
# Vectorizar datos clasificados
X_clasificados = vectorizer.fit_transform(df_clasificados['texto_unificado'])
y_clasificados = df_clasificados['Clasificación'].values
# Vectorizar datos sin clasificar (usando el MISMO vectorizer)
X_no_clasificados = vectorizer.transform(df_no_clasificados['texto_unificado'])
print("Distribución original de clases:", Counter(y_clasificados))
print(f"Matriz X_clasificados shape: {X_clasificados.shape}")
print(f"Vectorizer features: {vectorizer.get_feature_names_out().shape[0]}")
# ===== PASO 2: PARTICIÓN POR GRUPOS (GroupShuffleSplit) =====
# Se agrupan los tickets por su 'texto_unificado_raw' para garantizar que ningún
# texto idéntico o plantilla compartida aparezca simultáneamente en Train y Test.
# Esto previene el Data Leakage y evalúa la capacidad de generalización real sin destruir datos.

from sklearn.model_selection import GroupShuffleSplit

# Asegurar tipos homogéneos de etiquetas
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
# Se usa RandomOverSampler en lugar de SMOTE porque:
#   - SMOTE interpola entre vecinos → genera vectores TF-IDF promedio sin sentido lingüístico
#   - RandomOverSampler duplica tickets reales → mantiene la semántica del texto original
#   - Para datos de texto dispersos (sparse), ROS es la opción más adecuada

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
# Se evalúa con StratifiedKFold sobre X_train_balanced — X_test NO se toca aquí.
# Cada fold actúa como validación interna; el test set queda reservado para evaluación final.

k_range = range(1, 16)
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
f1_scores = []

for k in k_range:
    knn = KNeighborsClassifier(n_neighbors=k, metric='cosine')
    fold_f1 = []
    for train_idx, val_idx in cv.split(X_train_balanced, y_train_balanced):
        X_fold_train, y_fold_train = X_train_balanced[train_idx], y_train_balanced[train_idx]
        X_fold_val,   y_fold_val   = X_train_balanced[val_idx],   y_train_balanced[val_idx]
        knn.fit(X_fold_train, y_fold_train)
        y_fold_pred = knn.predict(X_fold_val)
        fold_f1.append(f1_score(y_fold_val, y_fold_pred, average='weighted', zero_division=0))
    f1_scores.append(np.mean(fold_f1))

k_optimo_idx = np.argmax(f1_scores)
k_optimo = list(k_range)[k_optimo_idx]

plt.figure(figsize=(10, 5))
plt.plot(k_range, f1_scores, marker='o', linewidth=2, markersize=8)
plt.axvline(x=k_optimo, color='red', linestyle='--', label=f'k óptimo = {k_optimo}')
plt.title('Búsqueda de k Óptimo: F1 medio CV (5 folds) — solo train set')
plt.xlabel('Número de vecinos (k)')
plt.ylabel('F1-Score Ponderado (media CV)')
plt.xticks(k_range)
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.close()

print(f"\n✓ k óptimo encontrado: {k_optimo}")
print(f"  F1-Score medio CV (train): {max(f1_scores):.4f}")
print(f"  X_test no fue utilizado en este paso.")

# ===== PASO 5: ENTRENAMIENTO FINAL CON k ÓPTIMO =====
# Entrenar SOLO con datos balanceados de TRAIN
knn_final = KNeighborsClassifier(n_neighbors=k_optimo, metric='cosine')
knn_final.fit(X_train_balanced, y_train_balanced)

print(f"✓ Modelo KNN entrenado con k={k_optimo}")
print(f"  Datos de entrenamiento: {X_train_balanced.shape[0]} muestras")

# Clasificar los tickets no clasificados
y_pred_no_clasificados = knn_final.predict(X_no_clasificados)
df_no_clasificados['Clasificación_predicha'] = y_pred_no_clasificados

print(f"\n✓ Clasificados {df_no_clasificados.shape[0]} tickets sin clasificar")
print('\nEjemplos de tickets no clasificados y su predicción:')
display(df_no_clasificados[['texto_unificado', 'Clasificación_predicha']].head(10))
# ===== PASO 6: EVALUACIÓN EN TEST SET (sin data leakage) =====
# Predecir en TEST SET (datos que el modelo NUNCA vio)
y_pred_test = knn_final.predict(X_test)

# Calcular métricas robustas
accuracy = accuracy_score(y_test, y_pred_test)
precision_weighted = precision_score(y_test, y_pred_test, average='weighted', zero_division=0)
recall_weighted = recall_score(y_test, y_pred_test, average='weighted', zero_division=0)
f1_weighted = f1_score(y_test, y_pred_test, average='weighted', zero_division=0)

print("\n" + "="*60)
print("EVALUACIÓN EN TEST SET (Datos nuevos)")
print("="*60)
print(f"Accuracy:              {accuracy:.4f}")
print(f"Precision (ponderado): {precision_weighted:.4f}")
print(f"Recall (ponderado):    {recall_weighted:.4f}")
print(f"F1-Score (ponderado):  {f1_weighted:.4f}")

print("="*60)
print("REPORTE DE CLASIFICACIÓN (Por clase):")
print(classification_report(y_test, y_pred_test, zero_division=0))

# Visualizar matriz de confusión normalizada
labels = sorted(list(set(list(y_test) + list(y_pred_test))))
cm = confusion_matrix(y_test, y_pred_test)
cm_norm = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]

plt.figure(figsize=(14, 12))
sns.heatmap(cm_norm, annot=True, fmt='.2%', cmap='Blues',
            xticklabels=labels, yticklabels=labels, cbar_kws={'label': 'Proporción'})
plt.xlabel('Predicción')
plt.ylabel('Etiqueta Real')
plt.title('Matriz de Confusión Normalizada (Test Set) - Proporciones por fila')
plt.tight_layout()
plt.close()

rf_model = RandomForestClassifier(n_estimators=200, max_depth=None, random_state=42, n_jobs=-1)
rf_model.fit(X_train_balanced, y_train_balanced)

print("✓ Random Forest entrenado  (n_estimators=200)")

lr_model = LogisticRegression(C=1.0, max_iter=3000, random_state=42, solver='lbfgs')
lr_model.fit(X_train_balanced, y_train_balanced)

print("✓ Logistic Regression entrenada  (C=1.0)")


# ── Combinar los tres modelos y evaluar en test set ────────────────────────
modelos = {
    'KNN':                 knn_final,
    'Random Forest':       rf_model,
    'Logistic Regression': lr_model,
}

resultados = []
predicciones_modelos = {}
for nombre, modelo in modelos.items():
    y_pred_m = modelo.predict(X_test)
    predicciones_modelos[nombre] = y_pred_m
    resultados.append({
        'Modelo':    nombre,
        'Accuracy':  accuracy_score(y_test, y_pred_m),
        'F1-Score':  f1_score(y_test, y_pred_m, average='weighted', zero_division=0),
        'Precision': precision_score(y_test, y_pred_m, average='weighted', zero_division=0),
        'Recall':    recall_score(y_test, y_pred_m, average='weighted', zero_division=0)
    })

df_resultados = pd.DataFrame(resultados).set_index('Modelo')

print("=== Métricas comparativas (conjunto de prueba) ===\n")
print(df_resultados.round(4).to_string())

mejor = df_resultados['F1-Score'].idxmax()
print(f"\n► Mejor clasificador por F1-Score (weighted): {mejor}  "
      f"({df_resultados.loc[mejor, 'F1-Score']:.4f})")

metricas = ['Accuracy', 'F1-Score', 'Precision', 'Recall']
x = np.arange(len(metricas))
n_modelos = len(df_resultados)
ancho = 0.18
colores = ['#4C72B0', '#DD8452', '#55A868', '#C44E52']

fig, ax = plt.subplots(figsize=(12, 5))
for i, (nombre, row) in enumerate(df_resultados.iterrows()):
    valores = [row[m] for m in metricas]
    barras = ax.bar(x + i * ancho, valores, ancho, label=nombre, color=colores[i], alpha=0.88)
    for barra, val in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2,
                barra.get_height() + 0.008,
                f'{val:.3f}', ha='center', va='bottom', fontsize=7.5)

offset_centro = (n_modelos - 1) * ancho / 2
ax.set_xticks(x + offset_centro)
ax.set_xticklabels(metricas, fontsize=11)
ax.set_ylim(0, 1.15)
ax.set_ylabel('Score', fontsize=11)
ax.set_title('Comparativa de Clasificadores — conjunto de prueba', fontsize=13, fontweight='bold')
ax.legend(loc='upper right', fontsize=10)
ax.grid(axis='y', linestyle='--', alpha=0.5)
plt.tight_layout()
plt.close()

labels = sorted(list(set(list(y_test))))
fig, axes = plt.subplots(1, 3, figsize=(36, 11))

for ax, (nombre, y_pred_m) in zip(axes, predicciones_modelos.items()):
    cm = confusion_matrix(y_test, y_pred_m, labels=labels)
    cm_norm = cm.astype('float') / cm.sum(axis=1, keepdims=True)
    sns.heatmap(
        cm_norm, annot=True, fmt='.2%', cmap='Blues',
        xticklabels=labels, yticklabels=labels,
        cbar_kws={'label': 'Proporción'}, ax=ax
    )
    ax.set_xlabel('Predicción', fontsize=11)
    ax.set_ylabel('Etiqueta Real', fontsize=11)
    ax.set_title(f'Matriz de Confusión Normalizada\n{nombre}', fontsize=13, fontweight='bold')
    ax.tick_params(axis='x', rotation=45)
    ax.tick_params(axis='y', rotation=0)

plt.tight_layout()
plt.close()

# ── Análisis detallado de errores — Logistic Regression ────────────────────

# Predecir en test set con Logistic Regression
y_pred_lr = lr_model.predict(X_test)

# Identificar muestras mal clasificadas
indices_errores = np.where(y_test != y_pred_lr)[0]
df_errores = df_test_base.iloc[indices_errores].copy()
df_errores['y_predicho'] = y_pred_lr[indices_errores]
df_errores['es_error'] = True

print(f"Total de errores en test set: {len(df_errores)} de {len(y_test)}")
print(f"Tasa de error: {len(df_errores) / len(y_test) * 100:.2f}%")
print(f"Accuracy: {1 - len(df_errores) / len(y_test):.4f}\n")

# Matriz de confusión de errores
print("Top 15 confusiones más frecuentes:")
confusiones = df_errores.groupby(['y_real', 'y_predicho']).size().reset_index(name='count')
confusiones = confusiones.sort_values('count', ascending=False).head(15)
print(confusiones.to_string(index=False))

# Mostrar ejemplos de errores por tipo
print("\n" + "="*80)
print("EJEMPLOS DE ERRORES (primeras 10 muestras mal clasificadas):")
print("="*80)

cols_error = [c for c in ['number', 'short_description', 'texto_unificado', 'y_real', 'y_predicho'] 
              if c in df_errores.columns]
with pd.option_context('display.max_colwidth', 100, 'display.max_rows', None):
    display(df_errores[cols_error].head(10))

# Gráfico: clases más confundidas
fig, ax = plt.subplots(figsize=(12, 6))
confusiones_top = confusiones.head(10)
barras = ax.barh(range(len(confusiones_top)), confusiones_top['count'], color='coral', alpha=0.8)
ax.set_yticks(range(len(confusiones_top)))
labels_y = [f"{row['y_real']} → {row['y_predicho']}" 
            for _, row in confusiones_top.iterrows()]
ax.set_yticklabels(labels_y)
ax.set_xlabel('Número de errores', fontsize=11)
ax.set_title('Top 10 Confusiones — Logistic Regression', fontsize=13, fontweight='bold')
ax.invert_yaxis()
for barra, val in zip(barras, confusiones_top['count']):
    ax.text(val + 0.1, barra.get_y() + barra.get_height()/2, str(int(val)), 
            va='center', fontsize=10)
plt.tight_layout()
plt.close()
# Tickets que presentan confusión (errores de clasificación en test)
# Usa df_errores generado en la celda de análisis de errores.

if 'df_errores' not in globals():
    raise ValueError("No existe 'df_errores'. Ejecuta primero la celda de análisis de errores.")

# Crear identificador de ticket si no existe la columna 'number'
if 'number' not in df_errores.columns:
    df_errores = df_errores.copy()
    df_errores['number'] = df_errores.index.astype(str)

print(f"Total de tickets con confusión: {len(df_errores)}")

# 1) Resumen por tipo de confusión (real -> predicho) con IDs de tickets
resumen_confusiones_tickets = (
    df_errores.groupby(['y_real', 'y_predicho'], as_index=False)
    .agg(
        total_tickets=('number', 'count'),
        tickets=('number', lambda x: ', '.join(x.astype(str).head(30)))
    )
    .sort_values('total_tickets', ascending=False)
)

print("\nTop confusiones con tickets asociados:")
display(resumen_confusiones_tickets)

# Exportar a CSV el resumen y/o detalle de tickets con confusión

fecha_hoy = pd.Timestamp.today().strftime("%Y-%m-%d")
carpeta_output = 'Resultados'
os.makedirs(carpeta_output, exist_ok=True)

# 1) Resumen de confusiones (si existe)
resumen_confusiones = globals().get('resumen_confusiones_tickets')
if resumen_confusiones is not None:
    ruta_resumen = os.path.join(carpeta_output, f"resumen_confusiones_tickets_{fecha_hoy}.csv")
    resumen_confusiones.to_csv(ruta_resumen, index=False, encoding='utf-8-sig')
    print(f"✓ Resumen exportado: {ruta_resumen} ({len(resumen_confusiones)} filas)")

# 2) Detalle de tickets confundidos (si existe)
tickets_conf = globals().get('tickets_confundidos')
if tickets_conf is not None:
    ruta_detalle = os.path.join(carpeta_output, f"tickets_confundidos_{fecha_hoy}.csv")
    tickets_conf.to_csv(ruta_detalle, index=False, encoding='utf-8-sig')
    print(f"✓ Detalle exportado: {ruta_detalle} ({len(tickets_conf)} filas)")
elif 'df_errores' in globals():
    cols_detalle = [c for c in ['number', 'short_description', 'texto_unificado', 'y_real', 'y_predicho'] if c in df_errores.columns]
    detalle_tmp = df_errores[cols_detalle].sort_values(['y_real', 'y_predicho', 'number']).reset_index(drop=True)
    ruta_detalle = os.path.join(carpeta_output, f"tickets_confundidos_{fecha_hoy}.csv")
    detalle_tmp.to_csv(ruta_detalle, index=False, encoding='utf-8-sig')
    print(f"✓ Detalle exportado (desde df_errores): {ruta_detalle} ({len(detalle_tmp)} filas)")

# ── Usar el mejor clasificador para predecir tickets no clasificados ──────────
mejor_modelo = modelos[mejor]
y_pred_final = mejor_modelo.predict(X_no_clasificados)

# ── Obtener confianza de la predicción ────────────────────────────────────────
# NOTA: LinearSVC no tiene predict_proba → se usa decision_function + softmax,
#       pero esos valores NO son probabilidades calibradas (son distancias al hiperplano).
#       Por eso se usa un umbral más bajo (0.10) cuando el modelo es LinearSVC.
if hasattr(mejor_modelo, 'predict_proba'):
    proba_matrix = mejor_modelo.predict_proba(X_no_clasificados)
    confianza = proba_matrix.max(axis=1)
    umbral_revision = 0.40
    tipo_confianza = 'probabilidad calibrada'
else:
    # Softmax sobre decision_function — no es probabilidad real, solo aproximación relativa
    scores = mejor_modelo.decision_function(X_no_clasificados)
    exp_scores = np.exp(scores - scores.max(axis=1, keepdims=True))
    proba_matrix = exp_scores / exp_scores.sum(axis=1, keepdims=True)
    confianza = proba_matrix.max(axis=1)
    umbral_revision = 0.10   # umbral ajustado para scores softmax de LinearSVC
    tipo_confianza = 'softmax(decision_function) — no calibrada'

# ── Construir DataFrame resultado ─────────────────────────────────────────────
cols_visibles = [c for c in ['number', 'short_description', 'description',
                              'u_subcategory', 'u_subcategory_2', 'texto_unificado',
                              'Clasificación']
                 if c in df_no_clasificados.columns]

df_resultado = df_no_clasificados[cols_visibles].copy()
df_resultado['Clasificación_predicha'] = y_pred_final
df_resultado['Confianza'] = np.round(confianza, 4)
df_resultado['Requiere_revision'] = confianza < umbral_revision
df_resultado['Modelo_usado'] = mejor

print(f"Modelo usado: {mejor}  |  Tipo de confianza: {tipo_confianza}")
print(f"Umbral de revisión aplicado: {umbral_revision}")
print(f"\nTotal de tickets clasificados: {len(df_resultado)}")
print(f"\nDistribución de predicciones:")
print(df_resultado['Clasificación_predicha'].value_counts().to_string())
print(f"\nTickets con baja confianza (< {umbral_revision}): {df_resultado['Requiere_revision'].sum()} "
      f"({df_resultado['Requiere_revision'].mean():.1%} del total)")

from datetime import datetime

# Carpeta output/ al mismo nivel que Data/ (un nivel arriba de Analisis/)
fecha_hoy = datetime.now().strftime("%Y-%m-%d")
nombre_modelo_csv = mejor.replace(" ", "_")
nombre_archivo = f"tickets_clasificados_{nombre_modelo_csv}_{fecha_hoy}.csv"

carpeta_output = 'Resultados'
os.makedirs(carpeta_output, exist_ok=True)

ruta_salida = os.path.normpath(os.path.join(carpeta_output, nombre_archivo))
df_resultado.to_csv(ruta_salida, index=False, encoding='utf-8-sig', sep=';')

print(f"✓ CSV exportado: {ruta_salida}")
print(f"  Filas: {len(df_resultado)}  |  Columnas: {list(df_resultado.columns)}")
print(f"\n  Alta confianza (≥ {umbral_revision}): {(~df_resultado['Requiere_revision']).sum()} tickets")
print(f"  Requiere revisión  (< {umbral_revision}): {df_resultado['Requiere_revision'].sum()} tickets")

# ── Histograma de confianza ───────────────────────────────────────────────────
plt.figure(figsize=(8, 4))
plt.hist(df_resultado['Confianza'], bins=20, color='steelblue', edgecolor='white', alpha=0.85)
plt.axvline(umbral_revision, color='red', linestyle='--', linewidth=1.5,
            label=f'Umbral revisión ({umbral_revision})')
plt.xlabel('Confianza de la predicción')
plt.ylabel('Número de tickets')
plt.title(f'Distribución de confianza — {mejor}')
plt.legend()
plt.tight_layout()
plt.close()

# ── Combinar tickets clasificados originales + tickets reclasificados ──────────

# 1. DataFrame de tickets clasificados (originales, sin cambios)
df_clasificados_final = df_clasificados[['number', 'short_description', 'description',
                                          'u_subcategory', 'u_subcategory_2', 
                                          'texto_unificado', 'Clasificación']].copy()
df_clasificados_final['Fuente'] = 'Original_Clasificado'
df_clasificados_final['Confianza'] = 1.0

# 2. DataFrame de tickets reclasificados (que eran sin_clasificar)
df_reclasificados = df_no_clasificados[['number', 'short_description', 'description',
                                         'u_subcategory', 'u_subcategory_2',
                                         'texto_unificado']].copy()
df_reclasificados['Clasificación'] = y_pred_final
df_reclasificados['Fuente'] = 'Reclasificado_IA'
df_reclasificados['Confianza'] = confianza

# 3. Combinar ambos DataFrames
df_completo = pd.concat([df_clasificados_final, df_reclasificados], 
                         ignore_index=True, sort=False)

# 4. Ordenar por número de ticket
df_completo = df_completo.sort_values('number').reset_index(drop=True)

# 5. Exportar CSV completo
fecha_hoy = datetime.now().strftime("%Y-%m-%d")
nombre_archivo_completo = f"tickets_clasificados_completo_{mejor.replace(' ', '_')}_{fecha_hoy}.csv"
carpeta_output = 'Resultados'
os.makedirs(carpeta_output, exist_ok=True)

ruta_salida_completa = os.path.normpath(os.path.join(carpeta_output, nombre_archivo_completo))
df_completo.to_csv(ruta_salida_completa, index=False, encoding='utf-8-sig')

print(f"✓ CSV COMPLETO exportado: {ruta_salida_completa}")
print(f"  Total de tickets: {len(df_completo)}")
print(f"  - Clasificados originales: {len(df_clasificados_final)}")
print(f"  - Reclasificados (sin_clasificar → IA): {len(df_reclasificados)}")
print(f"\nDistribución final de clasificaciones:") 
print(df_completo['Clasificación'].value_counts().to_string())
print(f"\nColumnas del CSV: {list(df_completo.columns)}")
# ── Persistencia del modelo y vectorizer ─────────────────────────────────────
# Se guardan juntos en la carpeta 'modelo/' para garantizar que la
# transformación TF-IDF sea idéntica al momento de inferencia futura.
nombre_modelo = mejor.replace(' ', '_')

carpeta_modelo = os.path.normpath(os.path.join(os.getcwd(), '..', '..', 'semisupervised_model'))
os.makedirs(carpeta_modelo, exist_ok=True)

ruta_modelo     = os.path.join(carpeta_modelo, f'modelo_{nombre_modelo}.joblib')
ruta_vectorizer = os.path.join(carpeta_modelo, 'vectorizer_tfidf.joblib')

joblib.dump(mejor_modelo, ruta_modelo)
joblib.dump(vectorizer,   ruta_vectorizer)

print(f"✓ Modelo guardado:     {ruta_modelo}")
print(f"✓ Vectorizer guardado: {ruta_vectorizer}")
print()
print("Para cargar y usar en otro script:")
print(f"  modelo     = joblib.load('modelo/modelo_{nombre_modelo}.joblib')")
print(f"  vectorizer = joblib.load('modelo/vectorizer_tfidf.joblib')")
print(f"  X_nuevo    = vectorizer.transform(textos_nuevos)")
print(f"  prediccion = modelo.predict(X_nuevo)")

