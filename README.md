# Asignador - IT Incident and Requirement Assignment System

Sistema automatizado de asignación y categorización de incidentes y requerimientos de TI utilizando Machine Learning (Supervisado, Semisupervisado y No Supervisado) y automatización RPA (Robotic Process Automation) para ServiceNow.

## Overview

Este sistema utiliza modelos de Machine Learning avanzados para predecir la categoría de cada ticket y asignar automáticamente incidentes y requerimientos al personal adecuado basándose en su contenido textual, rol del solicitante, metadatos operacionales y balanceo de carga de trabajo. Además, incluye:

- **Arquitectura Híbrida Multicanal (HNLP-MC - Hybrid NLP Multi-Channel)**: Modelo semisupervisado de vanguardia que desacopla el texto libre, la semántica del cargo del solicitante y los metadatos institucionales/técnicos en canales de representación especializados procesados en paralelo mediante `ColumnTransformer`.
- **Pipeline de Entrenamiento Científico en 3 Módulos**: Flujo metodológico estandarizado para Incidentes y Requerimientos con auditoría de fuga de datos (*Zero Data Leakage* vía `GroupShuffleSplit`), análisis de relevancia estadística ($V$ de Cramér), resolución de ambigüedades por regla mayoritaria y benchmarking multimodelo.
- **Herramientas de RPA E2E (vía DOM DevTools y Coordenadas GUI)**: Interacción directa con ServiceNow en navegadores independientes para descarga, clasificación y actualización automatizada de tickets.
- **Sistema de Registro y Logging de Ejecución (`ExecutionLogger`)**: Captura sincronizada de salidas de consola y archivado estructurado por fecha.
- **Reporte Acumulativo de Auditoría (`reporte_detalle_asignaciones.csv`)**: Trazabilidad completa de asignaciones históricas, preservando el asignado previo original.
- **Balanceo de Carga y Gestión de Turnos (`LoadBalancer`)**: Distribución equilibrada de tickets y enrutamiento por turnos de guardia según `Turnos.csv`.

---

## Features

- **Machine Learning & Modelos Predictivos**:
  - **Arquitectura HNLP-MC (Híbrido Multi-Canal)**: Desacopla la señal textual de síntomas frente al rol del solicitante y metadatos categóricos discretos, superando a los modelos tradicionales de solo texto en precisión y generalización. Empaquetada en un `Pipeline` integral de Scikit-learn (`pipeline_HNLP_MC.joblib`) para inferencia directa en producción desde DataFrames crudos.
  - **Línea Base TF-IDF (Baseline)**: Modelos lineales y de ensamble entrenados sobre representaciones textuales unificadas (`ngram_range=(1, 2)` con 5.000 características).
  - **Selección Flexible de Arquitectura**: Los scripts de producción `Assigner_Incidents.py` y `Assigner_Requirements.py` soportan `architecture='hnlp_mc'` (por defecto) con opción de alternar a `architecture='tfidf'`.
  - **Modelos Supervisados**: Clasificación multiclase orientada a la asignación de responsable técnico (`assigned_to_tfidf_svm.joblib`, `modelo_Requerimientos.joblib`).
  - **Modelos No Supervisados**: Agrupamiento no supervisado (`Clustering / KMeans`) para descubrimiento de patrones emergentes.
  - **Inclusión de Metadatos de Predicción**: Inclusión transparente de `prediction_model_type` y `prediction_model_name` en los reportes de salida.
- **RPA E2E Orquestado**:
  - **Inyección DOM vía DevTools (`RPA_ServiceNow_DOM_E2E.py`)**: Inyección directa de JavaScript en la consola (Ctrl+Shift+J) combinada con PyAutoGUI para una asignación precisa e inmune a problemas de resolución de pantalla, zoom o adjuntos.
  - **Basado en Coordenadas de Pantalla (`RPA_ServiceNow_E2E.py`)**: Automatización clásica basada en clics y atajos en pantalla.
- **Navegador Independiente (Priorización Edge sobre Chrome)**:
  - Apertura automática de una ventana independiente de navegador (`--new-window`), evitando interferir con las ventanas de trabajo personales abiertas del usuario.
  - Prioridad de ejecutable: **Microsoft Edge** (`msedge.exe`) > **Google Chrome** (`chrome.exe`) > Navegador predeterminado del sistema.
- **Gestión de Pestañas y Modo Seguro DRY_RUN**:
  - Abre pestañas individuales por cada ticket a procesar.
  - **`DRY_RUN = True`**: Puebla y valida los campos pero mantiene las pestañas abiertas para revisión y guardado manual por parte del usuario.
  - **`DRY_RUN = False`**: Guarda la actualización y al finalizar el ciclo completo cierra la ventana independiente mediante `Alt+F4` (`CLOSE_BROWSER_AT_END = True`).
- **Ejecución Continua y Reintento (Modo Periódico y Daemon)**:
  - Bucle de automatización autónomo con intervalos personalizables (ej. cada 30 o 60 minutos).
  - Pausas reactivas a `Ctrl+C` en bloques de 5 segundos.
- **Sistema de Logging por Ejecución (`ExecutionLogger`)**:
  - Captura estándar de `stdout` y `stderr` hacia la consola y archivos `.log` fechados.
  - Archivamiento automático de ejecuciones y logs anteriores hacia carpetas `Salida/YYYY-MM-DD/`.
  - Soporte de entorno `DISABLE_EXECUTION_LOGGER=1` para evitar logs duplicados durante ejecuciones orquestadas.
- **Utilidades del Pipeline, Limpieza de Datos y Formato de Fecha OS (`PipelineUtils.py`)**:
  - Corrección de registros CSV multilínea encerrados en comillas dobles (saltos de línea internos).
  - Detección automática del formato de fecha corta de Windows (`sShortDate` vía Registro de Windows).
- **Reporte Acumulativo de Asignaciones**:
  - Histórico persistente en `Salida/reporte_detalle_asignaciones.csv` con registro de asignación previa (`original_assigned_to`), asignada (`predicted_assigned_to`), fecha/hora y modelo/regla aplicada.
- **Validación de Turnos y Balanceo de Carga**:
  - Asignación automática por horarios de turno (`Turnos.csv`) para Operación TI, Batch y Monitoreo.

---

## Architecture

```
Asignador/
├── Assigner_Incidents.py                   # Asignador de incidentes (Soporta HNLP-MC [default] y TF-IDF)
├── Assigner_Requirements.py                # Asignador de requerimientos (Soporta HNLP-MC [default] y TF-IDF)
├── RPA_ServiceNow_DOM_E2E.py               # Orquestador RPA E2E mediante inyección JavaScript DOM (Recomendado)
├── RPA_ServiceNow_E2E.py                   # Orquestador RPA E2E mediante coordenadas de pantalla
├── Programas/
│   ├── PipelineUtils.py                    # Logging (ExecutionLogger), utilidades de pipeline, limpieza CSV y fecha regional OS
│   ├── Trainer.py                          # Entrenamiento de modelos (Supervisados y No supervisados)
│   ├── LoadBalancer.py                     # Balanceador de carga de trabajo y lógica de turnos
│   ├── GroupWorkloadReport.py              # Generador de reportes de carga de grupos
│   └── GroupMapper.py                      # Mapeador de grupos primarios
├── Incidentes/                             # Modelos, notebooks y datos de incidentes
│   ├── Datos/                          # IncidentesCategorizados_v2.csv, Incidentes_Preparados.csv
│   ├── Entrenamiento/
│   │   └── Semisupervisado/
│   │       ├── 01_EDA_Categorizacion_Incidentes.ipynb     # Módulo 1: EDA, Cramér's V y dataset preparado
│   │       ├── 02_Entrenamiento_TFIDF_Incidentes.ipynb   # Módulo 2: Baseline TF-IDF (GroupSplit, ROS)
│   │       ├── 03_Entrenamiento_HNLP_MC_Incidentes.ipynb # Módulo 3: Arquitectura Multicanal HNLP-MC
│   │       └── Resultados/                 # CSVs de confusiones y pseudo-etiquetado
│   ├── semisupervised_model/
│   │   ├── pipeline_HNLP_MC.joblib         # Pipeline integral Scikit-learn HNLP-MC (Producción)
│   │   ├── modelo_Logistic_Regression.joblib # Modelo TF-IDF Baseline
│   │   └── vectorizer_tfidf.joblib         # Vectorizador TF-IDF unificado
│   ├── supervised_model/                   # Modelos supervisados para incidentes
│   └── unsupervised_model/                 # Modelos no supervisados (clusters) para incidentes
├── Requerimientos/                         # Modelos, notebooks y datos de requerimientos
│   ├── Datos/                          # RequerimientosCategorizados_v1.csv, Requerimientos_Preparados.csv
│   ├── Entrenamiento/
│   │   └── Semisupervisado/
│   │       ├── 01_EDA_Categorizacion_Requerimientos.ipynb     # Módulo 1: EDA, Cramér's V y dataset preparado
│   │       ├── 02_Entrenamiento_TFIDF_Requerimientos.ipynb   # Módulo 2: Baseline TF-IDF (GroupSplit, ROS)
│   │       ├── 03_Entrenamiento_HNLP_MC_Requerimientos.ipynb # Módulo 3: Arquitectura Multicanal HNLP-MC
│   │       └── Resultados/                 # CSVs de confusiones y pseudo-etiquetado
│   ├── semisupervised_model/
│   │   ├── pipeline_HNLP_MC.joblib         # Pipeline integral Scikit-learn HNLP-MC (Producción)
│   │   ├── modelo_Logistic_Regression.joblib # Modelo TF-IDF Baseline
│   │   └── vectorizer_tfidf.joblib         # Vectorizador TF-IDF unificado
│   ├── supervised_model/                   # Modelos supervisados para requerimientos
│   └── unsupervised_model/                 # Modelos no supervisados (clusters) para requerimientos
├── Entrada/                                # Archivos de entrada (incident.csv, sc_req_item.csv e histórico)
├── Especificaciones/                       # Parámetros (Grupos, Usuarios, Turnos, rpa_config_parameters.json)
└── Salida/                                 # CSVs finales, reporte acumulativo y logs de ejecución
```

---

## Metodología de Modelado Semisupervisado (HNLP-MC)

El proyecto implementa un marco metodológico estandarizado y reproducible en tres etapas modulares:

### 1. Módulo 1: Análisis Exploratorio, Auditoría y Preparación de Datos (`01_EDA`)
- **Normalización del Target**: Unificación ortográfica, remoción de acentos (NFKD), homogenización de singular/plural y mapeo de tickets sin categorizar (`revision` o `pendiente` $\rightarrow$ `sin_clasificar`). Depuración de clases con $< 3$ muestras.
- **Auditoría de Fuga de Información (*Data Leakage*)**: Aislamiento estricto de variables generadas durante o después de la gestión del ticket (`state`, `assigned_to`, `fecha_asignacion`, `close_notes`, `resolved_at`, etc.).
- **Evaluación de Relevancia Estadística ($V$ de Cramér corregido)**: Medición del poder discriminante de cada variable categórica vs la variable objetivo, descartando campos cuasi-constantes ($\ge 95\%$ dominancia).
- **Resolución de Ambigüedades Humanas**: Detección de tickets idénticos categorizados erróneamente con etiquetas distintas por analistas humanos; resolución por regla de mayoría (`.idxmax()`) preservando el 100% del volumen de datos.
- **Salida**: Generación de datasets curados estandarizados (`Incidentes_Preparados.csv`, `Requerimientos_Preparados.csv`).

### 2. Módulo 2: Modelo de Línea Base TF-IDF (`02_Entrenamiento_TFIDF`)
- **Partición por Grupos (`GroupShuffleSplit`)**: Agrupación estricta por texto crudo (`texto_unificado_raw`) con 20% en test. Garantiza **Data Leakage = 0** asegurando que ninguna plantilla o texto repetido esté simultáneamente en entrenamiento y prueba.
- **Balanceo en Entrenamiento (`RandomOverSampler`)**: Sobremuestreo aplicado exclusivamente sobre el conjunto de entrenamiento para equilibrar clases minoritarias sin distorsionar la distribución natural del test set.
- **Benchmarking de Clasificadores**: Comparativa rigurosa entre KNN (con optimización de $k$ por validación cruzada interna), Logistic Regression, Linear SVC y Random Forest.
- **Diagnóstico de Errores y Pseudo-Etiquetado**: Matrices de confusión normalizadas, extracción de los 15 pares de confusión más frecuentes e inferencia con umbrales de confianza sobre tickets `sin_clasificar`.

### 3. Módulo 3: Arquitectura Híbrida Multicanal (`03_Entrenamiento_HNLP_MC`)
Desacopla la información en tres canales en paralelo fusionados mediante `ColumnTransformer`:

| Canal | Descripción | Transformador | Variables en Incidentes | Variables en Requerimientos |
| :--- | :--- | :--- | :--- | :--- |
| **Canal 1** | Texto Libre del Ticket (NLP Principal) | `TfidfVectorizer(max_features=5000, ngram_range=(1, 2))` | `short_description` + `description` | `short_description` + `description` |
| **Canal 2** | Semántica del Rol del Solicitante | `TfidfVectorizer(max_features=150, ngram_range=(1, 1))` | `u_affected_user.title` | `requested_for.title` (Cramér's V = 0.4017) |
| **Canal 3** | Metadatos Categóricos Discretos | `OneHotEncoder(handle_unknown='ignore')` | `cmdb_ci_business_app`, `u_affected_user.company`, `u_subcategory_2` | `requested_for.company` (Cramér's V = 0.2374) |

- **Desempeño Científico**: La arquitectura HNLP-MC superó a la línea base TF-IDF en todas las familias de clasificadores (alcanzando **87.83% de Accuracy** y **87.68% de F1-Weighted** con Linear SVC en Requerimientos, una mejora de **+2.02%** sobre el modelo de solo texto).
- **Persistencia**: Empaquetado en un `Pipeline` integral Scikit-learn (`pipeline_HNLP_MC.joblib`) listo para inferencia directa en producción.

---

## Installation

### Prerequisites
- Python 3.8+ (en Windows invocado mediante `py`)
- pandas
- numpy
- scipy
- scikit-learn
- imbalanced-learn
- nltk
- joblib
- matplotlib / seaborn (para visualización en notebooks)
- pyautogui / pyperclip (para RPA)

### Setup
1. Clonar el repositorio.
2. Asegurar que el entorno virtual local esté activo y ejecutar:
   ```bash
   pip install pandas numpy scipy scikit-learn imbalanced-learn nltk joblib matplotlib seaborn pyautogui pyperclip
   ```

---

## Usage

### 1. Ejecutar Asignación con Modelos ML Locales (Producción RPA)
Los programas principales ejecutan por defecto la arquitectura **HNLP-MC** sobre los tickets entrantes en `Entrada/`:

```bash
# Procesar incidentes (Entrada/incident.csv -> Salida/)
py Assigner_Incidents.py

# Procesar requerimientos (Entrada/sc_req_item.csv -> Salida/)
py Assigner_Requirements.py
```

Ambos scripts soportan selección de arquitectura en `predict_*_assignments`:
```python
# Arquitectura por defecto (Híbrido Multi-Canal):
predict_incident_assignments(df, balancer, model_type='semisupervised', architecture='hnlp_mc')
predict_requirement_assignments(df, balancer, model_type='semisupervised', architecture='hnlp_mc')

# Alternativa histórica (Línea Base TF-IDF):
predict_incident_assignments(df, balancer, model_type='semisupervised', architecture='tfidf')
predict_requirement_assignments(df, balancer, model_type='semisupervised', architecture='tfidf')
```

### 2. Re-entrenar Modelos Semisupervisados (Jupyter Notebooks)
Para reproducir o actualizar el entrenamiento sobre nuevos datos históricos:
1. **Paso 1**: Ejecutar `01_EDA_Categorizacion_*.ipynb` para auditar datos y generar el dataset preparado `*_Preparados.csv`.
2. **Paso 2**: Ejecutar `02_Entrenamiento_TFIDF_*.ipynb` para evaluar la línea base TF-IDF y generar diagnósticos de confusión.
3. **Paso 3**: Ejecutar `03_Entrenamiento_HNLP_MC_*.ipynb` para entrenar la arquitectura multicanal y actualizar el artefacto `pipeline_HNLP_MC.joblib`.

### 3. Entrenar Modelos Supervisados Tradicionales
Para actualizar los clasificadores supervisados (`supervised_model/`) y clusters no supervisados:
```bash
py Programas/Trainer.py
```

### 4. Ejecutar Orquestador RPA ServiceNow (Modo DOM DevTools - Recomendado)
Automatización completa E2E descargando listas, ejecutando modelos de ML e inyectando campos vía la consola DevTools del navegador:
```bash
py RPA_ServiceNow_DOM_E2E.py
```

#### Menú de Opciones:
1. **Solo INCIDENTES**: Ejecutar Predicciones y Actualizar DOM.
2. **Solo INCIDENTES**: Solo Actualizar DOM (usando la última predicción en `Salida/`).
3. **Solo REQUERIMIENTOS**: Ejecutar Predicciones y Actualizar DOM.
4. **Solo REQUERIMIENTOS**: Solo Actualizar DOM (usando la última predicción en `Salida/`).
5. **Ejecución Completa**: Procesa Incidentes y Requerimientos de inicio a fin.
6. **Ejecución Completa Periódica**: Modo bucle daemon que repite la automatización según un intervalo en minutos (ej. 30 min).
7. **Salir**.

### 5. Ejecutar Orquestador RPA ServiceNow (Modo Coordenadas de Pantalla)
```bash
py RPA_ServiceNow_E2E.py
```

---

## Configuration & Feature Details

### Sistema de Logging y Registro (`ExecutionLogger`)
- Implementado en `Programas/PipelineUtils.py`.
- Genera automáticamente un archivo `.log` con marca de tiempo en `Salida/` (ej. `ejecucion_incidents_2026-09-19_13-00-00.log`).
- Mantiene duplicación de stream (`TeeStream`) para reflejar la salida simultáneamente en la consola y en el archivo log.
- En ejecuciones orquestadas, la variable `DISABLE_EXECUTION_LOGGER=1` evita la creación de logs fragmentados en los subprocesos.

### Reporte Acumulativo de Detalle de Asignaciones
- Archivo centralizado: `Salida/reporte_detalle_asignaciones.csv`.
- Registra de forma acumulativa cada ticket procesado:
  - `ticket_id`: Número de incidente (INC) o requerimiento (RITM).
  - `ticket_type`: Categoría ('incidentes' o 'requerimientos').
  - `short_description`: Descripción corta del ticket.
  - `original_assigned_to`: Usuario asignado previamente antes del proceso.
  - `predicted_assigned_to`: Usuario asignado por el sistema.
  - `rule_applied`: Regla de negocio aplicada (ej. 'Turno Monitoreo', 'Model Prediction', 'Load Balancer').
  - `model_used`: Nombre o tipo del modelo de ML utilizado (`pipeline_HNLP_MC.joblib`, `semisupervised_hnlp_mc`, etc.).
  - `assigned_at`: Fecha y hora de procesamiento.

### Validaciones de Turno y Carga de Trabajo
Aplica reglas automáticas para derivar incidentes específicos al personal en guardia/turno según `Especificaciones/Turnos.csv`:
- **Operación TI**: Categoría "Operación TI".
- **Batch**: Subcategoría "Batch" o clasificado/predicho como "reportes batch" o "trickle feed".
- **Monitoreo**: Medio de contacto (`contact_type`) es "Monitoreo".

---

## Data Format

### Archivos de Entrada (`Entrada/`)
- `Entrada/incident.csv` - Listado de incidentes activos descargados de ServiceNow.
- `Entrada/sc_req_item.csv` - Listado de requerimientos activos descargados de ServiceNow.
- `Entrada/YYYY-MM-DD/` - Histórico diario de archivos descargados.

### Archivos de Parámetros y Configuración (`Especificaciones/`)
- `Especificaciones/Grupos - Usuarios.csv` - Mapeo de nombres de usuario, usernames canónicos y ServiceNow IDs.
- `Especificaciones/Grupos - Requerimientos(Grupos).csv` - Configuración de grupos para requerimientos.
- `Especificaciones/Turnos.csv` - Cuadrante diario de turnos del equipo.
- `Especificaciones/rpa_config_parameters.json` - URLs de descarga y Sys IDs de configuración (ej. CMDB Bancs).
- `Especificaciones/rpa_config_incidents.json` y `rpa_config_requirements.json` - Coordenadas para modo GUI tradicional.

### Archivos de Salida (`Salida/`)
- `Salida/incidentes_con_asignacion_{timestamp}.csv` - Incidentes clasificados con asignaciones y sys_id.
- `Salida/requerimientos_con_asignacion_{timestamp}.csv` - Requerimientos clasificados con estado 'En proceso', fecha prevista de resolución e información de CMDB.
- `Salida/reporte_detalle_asignaciones.csv` - Reporte acumulativo histórico de detalles de asignación.
- `Salida/resumen_asignaciones_{timestamp}.txt` - Resumen y estadísticas de distribución final de carga.
- `Salida/ejecucion_{prefix}_{timestamp}.log` - Logs detallados por cada ciclo de ejecución.

---

## License

Proyecto Integrador - Maestría en Inteligencia Artificial Aplicada.
Sistema interno de automatización, clasificación y asignación inteligente de TI.
