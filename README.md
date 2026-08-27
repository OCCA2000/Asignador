# Asignador - IT Incident and Requirement Assignment System

Sistema automatizado de asignación de incidentes y requerimientos de TI utilizando Machine Learning (Supervisado, Semisupervisado y No Supervisado) y automatización RPA (Robotic Process Automation) para ServiceNow.

## Overview

Este sistema utiliza modelos de Machine Learning avanzados para asignar automáticamente incidentes y requerimientos al personal adecuado basándose en el contenido, características y carga de trabajo de cada caso. Además, incluye:
- Herramientas de **RPA E2E (vía DOM DevTools y Coordenadas GUI)** para interactuar directamente con ServiceNow en navegadores independientes.
- **Sistema de Registro y Logging de Ejecución (`ExecutionLogger`)** que captura salidas de consola y archiva ejecuciones previas por fecha.
- **Reporte Acumulativo de Auditoría (`reporte_detalle_asignaciones.csv`)** para rastrear cada asignación realizada, preservando la asignación original.
- **Utilidades de Limpieza de CSVs y Corrección de Formatos** con autodetección de formato de fecha corta del sistema operativo.

---

## Features

- **Machine Learning Models**:
  - Modelos **Supervisados** (SVM / Random Forest / Naive Bayes).
  - Modelos **Semisupervisados** (Self-Training / Label Propagation).
  - Modelos **No Supervisados** (Clustering / KMeans / TF-IDF).
  - Inclusión de metadatos del modelo utilizado (`model_used`) y regla aplicada (`rule_applied`) en los reportes de salida.
- **RPA E2E Orquestado**:
  - **Inyección DOM vía DevTools (`RPA_ServiceNow_DOM_E2E.py`)**: Inyección directa de JavaScript en la consola (Ctrl+Shift+J) combinada con PyAutoGUI para una asignación precisa e inmune a problemas de resolución de pantalla, zoom o adjuntos.
  - **Basado en Coordenadas de Pantalla (`RPA_ServiceNow_E2E.py`)**: Automatización basada en clics y atajos en pantalla.
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
- **Limpieza de Datos y Formato de Fecha OS (`CleaningData.py`)**:
  - Corrección de registros CSV multilinea encerrados en comillas dobles (saltos de línea internos).
  - Detección automática del formato de fecha corta de Windows (`sShortDate` vía Registro de Windows).
- **Reporte Acumulativo de Asignaciones**:
  - Histórico persistente en `Salida/reporte_detalle_asignaciones.csv` con registro de asignación previa (`original_assigned_to`), asignada (`predicted_assigned_to`), fecha/hora y modelo/regla aplicada.
- **Validación de Turnos y Balanceo de Carga**:
  - Asignación automática por horarios de turno (`Turnos.csv`) para Operación TI, Batch y Monitoreo.

---

## Architecture

```
Asignador/
├── Assigner_Incidents.py       # Programa principal de asignación de incidentes
├── Assigner_Requirements.py    # Programa principal de asignación de requerimientos
├── RPA_ServiceNow_DOM_E2E.py   # Orquestador RPA E2E mediante inyección JavaScript DOM (Recomendado)
├── RPA_ServiceNow_E2E.py       # Orquestador RPA E2E mediante coordenadas de pantalla
├── Programas/
│   ├── CleaningData.py         # Utilidades de logging (ExecutionLogger), limpieza CSV y fecha OS
│   ├── Trainer.py              # Entrenamiento de modelos (Supervisados y No supervisados)
│   ├── LoadBalancer.py         # Balanceador de carga de trabajo y lógica de turnos
│   ├── GroupWorkloadReport.py  # Generador de reportes de carga de grupos
│   └── GroupMapper.py          # Mapeador de grupos primarios
├── Incidentes/                 # Modelos y datos de incidentes
│   ├── Entrenamiento/          # Notebooks de EDA y datasets históricos
│   ├── supervised_model/       # Modelos supervisados para incidentes
│   ├── semisupervised_model/   # Modelos semisupervisados para incidentes
│   └── unsupervised_model/     # Modelos no supervisados (clusters) para incidentes
├── Requerimientos/             # Modelos y datos de requerimientos
│   ├── Entrenamiento/          # Notebooks de EDA y datasets históricos
│   ├── supervised_model/       # Modelos supervisados para requerimientos
│   ├── semisupervised_model/   # Modelos semisupervisados para requerimientos
│   └── unsupervised_model/     # Modelos no supervisados (clusters) para requerimientos
├── Entrada/                    # Archivos de entrada (incident.csv, sc_req_item.csv e histórico por fecha)
├── Especificaciones/           # Parámetros (Grupos, Usuarios, Turnos, rpa_config_parameters.json)
└── Salida/                     # CSVs finales, reporte acumulativo (reporte_detalle_asignaciones.csv) y logs
```

---

## Installation

### Prerequisites
- Python 3.7+
- pandas
- scikit-learn
- joblib
- pyautogui
- pyperclip
- tkinter (incluido en Python en Windows)
- nltk
- matplotlib / seaborn (para visualización en notebooks)
- imbalanced-learn

### Setup
1. Clonar el repositorio.
2. Instalar dependencias requeridas en el entorno Python:
   ```bash
   pip install pandas scikit-learn joblib pyautogui pyperclip nltk matplotlib seaborn imbalanced-learn
   ```

---

## Usage

### 1. Entrenar Modelos
Puedes entrenar los modelos supervisados y no supervisados ejecutando el script máster de entrenamiento:
```bash
py Programas/Trainer.py
```
Este script actualizará de manera automática los modelos serializados en `supervised_model/` y `unsupervised_model/`.

### 2. Ejecutar Asignación de Modelos ML Locales
Para procesar los datos de entrada sin interactuar con el navegador web:
```bash
py Assigner_Incidents.py
py Assigner_Requirements.py
```

### 3. Ejecutar Orquestador RPA ServiceNow (Modo DOM DevTools - Recomendado)
El script `RPA_ServiceNow_DOM_E2E.py` permite la automatización completa E2E descargando listas, ejecutando modelos de ML e inyectando campos vía la consola DevTools del navegador.

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

### 4. Ejecutar Orquestador RPA ServiceNow (Modo Coordenadas de Pantalla)
```bash
py RPA_ServiceNow_E2E.py
```

---

## Configuration & Feature Details

### Sistema de Logging y Registro (`ExecutionLogger`)
- Implementado en `Programas/CleaningData.py`.
- Genera automáticamente un archivo `.log` con marca de tiempo en `Salida/` (ej. `ejecucion_dom_periodica_2026-08-27_17-00-00.log`).
- Mantiene duplicación de stream (`TeeStream`) para reflejar la salida simultáneamente en la consola y en el archivo log.
- En ejecuciones orquestadas, la variable `DISABLE_EXECUTION_LOGGER=1` evita la creación de logs fragmentados en los subprocesos de predicción.

### Reporte Acumulativo de Detalle de Asignaciones
- Archivo centralizado: `Salida/reporte_detalle_asignaciones.csv`.
- Registra de forma acumulativa cada ticket procesado con las siguientes columnas:
  - `ticket_id`: Número de incidente (INC) o requerimiento (RITM).
  - `ticket_type`: Categoría ('incidentes' o 'requerimientos').
  - `short_description`: Descripción corta del ticket.
  - `original_assigned_to`: Usuario asignado previamente antes del proceso.
  - `predicted_assigned_to`: Usuario asignado por el sistema.
  - `rule_applied`: Regla de negocio aplicada (ej. 'Turno Monitoreo', 'Model Prediction', 'Load Balancer').
  - `model_used`: Nombre o tipo del modelo de ML utilizado.
  - `assigned_at`: Fecha y hora de procesamiento.

### Limpieza de Datos y Formato de Fecha OS (`CleaningData.py`)
- **Archivamiento Automático**: `archive_previous_files()` mueve archivos `.csv`, `.txt` y `.log` anteriores de la raíz de `Salida/` o `Entrada/` hacia subcarpetas organizadas por fecha (`Salida/YYYY-MM-DD/`).
- **Corrección CSV**: Elimina saltos de línea internos en campos de texto delimitados por comillas (`fix_newlines_inside_quotes`) y estandariza separadores (`replace_commas_outside_quotes`).
- **Formato de Fecha de Windows**: La función `get_windows_date_format()` lee la clave de registro `Control Panel\International\sShortDate` de Windows para adaptar dinámicamente las conversiones `strftime` al formato regional del sistema operativo.

### Navegador Independiente y Priorización Edge
- Al iniciar el flujo de descarga o actualización de tickets, el sistema busca ejecutables instalados en el sistema:
  1. **Microsoft Edge** (`msedge.exe`)
  2. **Google Chrome** (`chrome.exe`)
  3. Navegador predeterminado del sistema.
- Lanza una **nueva ventana de navegador independiente** con el flag `--new-window`, asegurando que no se reutilice ni interrumpa la sesión o pestañas personales abiertas del usuario.

### Ventana Emergente de Notificación Pre-Inicio
- Definida por las constantes:
  - `SHOW_NOTIFICATION_POPUP = True`
  - `NOTIFICATION_COUNTDOWN_SECONDS = 5`
- 5 segundos antes de tomar el control del mouse/teclado, el sistema muestra una ventana centrada en pantalla siempre visible (`-topmost`) con un temporizador regresivo para alertar al usuario.
- Se ejecuta **una sola vez por ciclo de ejecución**.

### Modo DRY_RUN y Reglas de Pestañas
- Definido en el script mediante `DRY_RUN = True` (o `False`).
- `DRY_RUN = True`: Mantiene las pestañas abiertas para revisión y guardado manual.
- `DRY_RUN = False` (con `CLOSE_BROWSER_AT_END = True`): Al finalizar toda la iteración del ciclo, el sistema espera un tiempo personalizable (`CLOSE_BROWSER_WAIT_TIME = 10.0` s) y cierra la ventana independiente del navegador completa usando **`Alt+F4`**.

### Validaciones de Turno y Carga de Trabajo
El sistema aplica reglas automáticas para derivar incidentes específicos al personal en guardia/turno según `Especificaciones/Turnos.csv`:
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
- `Especificaciones/Turnos.csv` - Cuadrante diario de turnos.
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

Proyecto interno de automatización y asignación de TI.
