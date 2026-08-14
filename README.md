# Asignador - IT Incident and Requirement Assignment System

Sistema automatizado de asignación de incidentes y requerimientos de TI utilizando Machine Learning y automatización RPA (Robotic Process Automation) para ServiceNow.

## Overview

Este sistema utiliza modelos de Machine Learning supervisados y no supervisados para asignar automáticamente incidentes y requerimientos al personal adecuado basándose en el contenido y características de cada caso. Además, incluye herramientas de RPA E2E para interactuar directamente con ServiceNow en navegadores independientes sin interferir con la sesión de trabajo activa del usuario.

## Features

- **Machine Learning Models**: Modelos supervisados, semisupervisados y no supervisados para incidentes y requerimientos.
- **RPA E2E Orquestado**:
  - **Inyección DOM vía DevTools (`RPA_ServiceNow_DOM_E2E.py`)**: Inyección directa de JavaScript en la consola (Ctrl+Shift+J) combinada con PyAutoGUI para una asignación precisa e inmune a problemas de resolución de pantalla, zoom o adjuntos.
  - **Basado en Coordenadas de Pantalla (`RPA_ServiceNow_E2E.py`)**: Automatización basada en clics y atajos en pantalla.
- **Navegador Independiente (Priorización Edge sobre Chrome)**:
  - Apertura automática de una ventana independiente de navegador (`--new-window`), evitando interferir con las ventanas de trabajo personales abiertas del usuario.
  - Prioridad de ejecutable: **Microsoft Edge** (`msedge.exe`) > **Google Chrome** (`chrome.exe`) > Navegador predeterminado del sistema.
- **Gestión de Pestañas y Modo Seguro DRY_RUN**:
  - Abre pestañas individuales por cada ticket a procesar.
  - **`DRY_RUN = True`**: Puebla y valida los campos pero mantiene las pestañas abiertas para revisión y guardado manual por parte del usuario.
  - **`DRY_RUN = False`**: Guarda la actualización y cierra automáticamente la pestaña (`Ctrl+W`).
  - No cierra la ventana del navegador ni pestañas con errores o procesos incompletos.
- **Ventana Emergente de Notificación Pre-Inicio**:
  - Alerta de 5 segundos mediante popup gráfico (`tkinter` topmost) antes de que el robot tome el control de la pantalla/teclado.
  - Configurable mediante la constante `SHOW_NOTIFICATION_POPUP = True` / `NOTIFICATION_COUNTDOWN_SECONDS = 5`.
  - Se muestra **una sola vez por ciclo de ejecución** para evitar interrupciones repetidas.
- **Data Processing**: Limpieza, normalización y procesamiento automático de datos.
- **Shift Validation**: Reglas automáticas para escenarios de turno (Operación TI, Batch, Monitoreo).
- **Reports**: Generación automática de reportes de carga de trabajo y resúmenes.

## Architecture

```
Asignador/
├── Assigner_Incidents.py       # Programa principal de asignación de incidentes
├── Assigner_Requirements.py    # Programa principal de asignación de requerimientos
├── RPA_ServiceNow_DOM_E2E.py   # Orquestador RPA E2E mediante inyección JavaScript DOM (Recomendado)
├── RPA_ServiceNow_E2E.py       # Orquestador RPA E2E mediante coordenadas de pantalla
├── Programas/
│   ├── CleaningData.py         # Funciones de limpieza de datos y nombrado según SO
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
└── Salida/                     # Reportes y CSVs finales de asignación generados
```

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
6. **Ejecución Completa Periódica**: Modo bucle daemon que repite la automatización según un intervalo en minutos.
7. **Salir**.

### 4. Ejecutar Orquestador RPA ServiceNow (Modo Coordenadas de Pantalla)
```bash
py RPA_ServiceNow_E2E.py
```

---

## Configuration & Feature Details

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
- 5 segundos antes de tomar el control del mouse/teclado, el sistema muestra una ventana centrada en pantalla siempre visible (`-topmost`) con un temporizador regresivo de 5 a 1 segundos para que el usuario pueda liberar el control de la pantalla.
- Se ejecuta **una sola vez por ciclo de ejecución** (evitando avisos duplicados en subfases).

### Modo DRY_RUN y Reglas de Pestañas
- Definido en el script mediante `DRY_RUN = True` (o `False`).
- **Pestañas e Iteraciones**:
  - **Sin `Ctrl+W`**: No se cierra ninguna pestaña individual durante el procesamiento de los tickets. Todas las pestañas creadas durante el ciclo permanecen abiertas.
  - `DRY_RUN = True`: Al finalizar la iteración completa, la ventana del navegador y todas sus pestañas abiertas **se mantienen abiertas** para permitir la inspección visual y guardado manual.
  - `DRY_RUN = False` (con `CLOSE_BROWSER_AT_END = True`): Al finalizar **toda la iteración del ciclo**, el sistema espera un tiempo personalizable (`CLOSE_BROWSER_WAIT_TIME = 10.0` segundos por defecto) y cierra la ventana independiente del navegador completa usando **`Alt+F4`**.

### Validaciones de Turno y Carga de Trabajo
El sistema aplica reglas automáticas para derivar incidentes específicos al personal en guardia/turno:
- **Operación TI**: Categoría "Operación TI".
- **Batch**: Subcategoría "Batch" o clasificado/predicho como "reportes batch" o "trickle feed".
- **Monitoreo**: Medio de contacto (`contact_type`) es "Monitoreo".

#### Cuadrante de Turnos (`Turnos.csv`)
Cuando un ticket es clasificado como de turno, el balanceador de carga (`Programas/LoadBalancer.py`) consulta `Especificaciones/Turnos.csv` para asignar automáticamente el ticket al usuario correspondiente según el horario:
- **Lunes a Viernes:**
  - `06:00:00` a `13:59:59` -> **Turno 1**
  - `14:00:00` a `21:59:59` -> **Turno 2**
  - `22:00:00` a `05:59:59` (del día siguiente) -> **Turno 3**
- **Sábado:**
  - `00:00:00` a `05:59:59` -> **Turno 3** (guardia del viernes)
  - `06:00:00` a `13:59:59` -> **Turno 4**
  - `14:00:00` a `23:59:59` -> **Stand-by**
- **Domingo:**
  - Todo el día -> **Stand-by**
- **Lunes temprano:**
  - `00:00:00` a `05:59:59` -> **Stand-by** (guardia del domingo)

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
- `Salida/resumen_asignaciones_{timestamp}.txt` - Resumen y estadísticas de distribución final de carga.

## License

Proyecto interno de automatización y asignación de TI.
