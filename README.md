# Asignador - IT Incident and Requirement Assignment System

Sistema automatizado de asignación de incidentes y requerimientos de TI utilizando Machine Learning.

## Overview

Este sistema utiliza modelos de Machine Learning para asignar automáticamente incidentes y requerimientos al personal adecuado basándose en el contenido y características de cada caso.

## Features

- **Machine Learning Models**: Modelos supervisados y no supervisados para incidentes y requerimientos
- **Data Processing**: Limpieza y procesamiento automático de archivos CSV
- **Shift Validation**: Reglas especiales para escenarios de turno (Operación TI, Batch, Monitoreo)
- **Reports**: Generación automática de reportes y resúmenes

## Architecture

```
Asignador/
├── Assigner_Incidents.py       # Programa principal para incidentes
├── Assigner_Requirements.py    # Programa principal para requerimientos
├── Programas/
│   ├── CleaningData.py         # Funciones de limpieza de datos
│   ├── Trainer.py              # Entrenamiento de modelos (Supervisados y No supervisados)
│   ├── LoadBalancer.py         # Balanceador de carga de trabajo
│   ├── GroupWorkloadReport.py  # Generador de reportes de carga de grupos
│   └── GroupMapper.py          # Mapeador de grupos primarios
├── Incidentes/                 # Modelos y datos de incidentes
│   ├── Entrenamiento/          # Notebooks de EDA y datasets históricos
│   │   ├── Datos/
│   │   ├── Semisupervisado/    # Guarda modelos en semisupervised_model/ y CSV en Resultados/
│   │   ...
│   ├── supervised_model/       # Modelos supervisados para incidentes
│   ├── semisupervised_model/   # Modelos semisupervisados para incidentes
│   └── unsupervised_model/     # Modelos no supervisados (clusters) para incidentes
├── Requerimientos/             # Modelos y datos de requerimientos
│   ├── Entrenamiento/          # Notebooks de EDA y datasets históricos
│   │   ├── Datos/
│   │   ├── Semisupervisado/    # Guarda modelos en semisupervised_model/ y CSV en Resultados/
│   │   ...
│   ├── supervised_model/       # Modelos supervisados para requerimientos
│   ├── semisupervised_model/   # Modelos semisupervisados para requerimientos
│   └── unsupervised_model/     # Modelos no supervisados (clusters) para requerimientos
├── Entrada/                    # Archivos de entrada para procesamiento (incident.csv, requirements.csv)
└── Salida/                     # Reportes y CSVs finales de asignación generados
```

## Installation

### Prerequisites
- Python 3.7+
- pandas
- scikit-learn
- joblib
- requests (para API integration)
- nltk
- matplotlib (para graficar en notebooks)
- seaborn (para visualizaciones)
- imbalanced-learn (para RandomOverSampler)

### Setup
1. Clonar el repositorio
2. Instalar dependencias globales:
   ```bash
   pip install pandas scikit-learn joblib requests nltk matplotlib seaborn imbalanced-learn
   ```

## Usage

### Entrenar Modelos

Puedes entrenar los modelos supervisados y no supervisados (DBSCAN auto-clustering) ejecutando el master training script desde cualquier carpeta (raíz del proyecto o `Programas/`):
```bash
python Programas/Trainer.py
```
Este script actualizará de manera automática los modelos y archivos serializados dentro de las carpetas de modelos correspondientes (`supervised_model/` y `unsupervised_model/`).

Para los flujos semisupervisados, puedes ejecutar los notebooks interactivos en `Entrenamiento/Semisupervisado/`. Estos guardarán sus reportes de análisis en un subdirectorio local llamado `Resultados/` e implementarán los modelos resultantes directamente en la carpeta de producción `semisupervised_model/`.

### Ejecutar Asignación
Desde la raíz del proyecto, puedes ejecutar los modelos de asignación locales:
```bash
py Assigner_Incidents.py
py Assigner_Requirements.py
```

### Ejecutar RPA ServiceNow E2E Orchestrator
El orquestador RPA interactúa automáticamente con la interfaz web de ServiceNow usando control de mouse y teclado (PyAutoGUI) para descargar los tickets, procesarlos con los modelos de ML locales y subir las asignaciones.

Ejecución del orquestador:
```bash
py RPA_ServiceNow_E2E.py
```

El script ofrece las siguientes opciones:
1. **Run E2E RPA Pipeline**: Descarga los CSVs desde ServiceNow, ejecuta predicciones de ML y actualiza los tickets en la web.
2. **Run Models & Update**: Ejecuta predicciones de ML en los CSVs existentes en `Entrada/` y los sube a ServiceNow.
3. **Run Updates Only**: Sube a ServiceNow directamente usando los CSVs clasificados más recientes en `Salida/`.
4. **Setup Mode**: Calibra y guarda las coordenadas de pantalla para los campos de entrada y botones en ServiceNow.
5. **Daemon Mode**: Ejecuta el pipeline completo de forma cíclica según un intervalo de tiempo especificado.

*Nota: Se recomienda probar primero con el modo **DRY RUN** (opcional al arrancar) para validar visualmente los clics del robot sin guardar los cambios reales.*

## Configuration

#### Shift Validation Rules
El sistema aplica reglas automáticas para derivar incidentes específicos al personal de turno. Cualquier incidente que cumpla con alguna de las siguientes condiciones es clasificado como ticket de turno:
- **Operación TI**: Categoría "Operación TI"
- **Batch**: Subcategoría "Batch" o clasificado/predicho como "reportes batch" o "trickle feed"
- **Monitoreo**: Medio de contacto (contact_type) es "Monitoreo"

#### Shift Configuration (Turnos.csv)
Cuando un ticket es clasificado como de turno, el balanceador de carga (`Programas/LoadBalancer.py`) consulta el archivo `Entrada/Turnos.csv` para asignar automáticamente el ticket al usuario en turno específico, dependiendo de la fecha y hora de creación del ticket (`sys_created_on` o `opened_at`):

- **Lunes a Viernes:**
  - `06:00:00` a `13:59:59` -> **Turno 1**
  - `14:00:00` a `21:59:59` -> **Turno 2**
  - `22:00:00` a `05:59:59` (del día siguiente) -> **Turno 3**
- **Sábado:**
  - `00:00:00` a `05:59:59` -> **Turno 3** (perteneciente al viernes de guardia)
  - `06:00:00` a `13:59:59` -> **Turno 4**
  - `14:00:00` a `23:59:59` -> **Stand-by**
- **Domingo:**
  - Todo el día (`00:00:00` a `23:59:59`) -> **Stand-by**
- **Lunes temprano:**
  - `00:00:00` a `05:59:59` -> **Stand-by** (perteneciente al domingo de guardia)

Si el archivo `Entrada/Turnos.csv` no se encuentra o no contiene una coincidencia para el día y turno correspondiente, el ticket se asigna genéricamente a `"TURNO"`.

## Data Format

### Archivos de Entrada
- `Entrada/incident.csv` - Listado de incidentes activos descargados de ServiceNow
- `Entrada/sc_req_item.csv` - Listado de requerimientos activos descargados de ServiceNow
- `Entrada/Turnos.csv` - Cuadrante de turnos diario con columnas: `Fecha`, `Turno 1`, `Turno 2`, `Turno 3`, `Turno 4` y `Stand-by`
- `Entrada/Grupos - Incidentes(Grupos).csv` y `Entrada/Grupos - Requerimientos(Grupos).csv` - Configuración de miembros por cada macrogrupo
- `Entrada/Grupos - Usuarios.csv` - Listado general de usuarios de TI, sus usernames canónicos y estado de disponibilidad (`Estado = 1` para activo)

### Archivos de Configuración RPA
- `rpa_config_incidents.json` - Coordenadas de pantalla calibradas para actualizar Incidentes (2 campos)
- `rpa_config_requirements.json` - Coordenadas de pantalla calibradas para actualizar Requerimientos (5 campos)

### Archivos de Salida
- `Salida/incidentes_con_asignacion_{timestamp}.csv` - Incidentes con asignaciones y grupos mapeados
- `Salida/requerimientos_con_asignacion_{timestamp}.csv` - Requerimientos con asignaciones, estado actualizado e información de fecha de resolución (`fecha_resolucion`)
- `Salida/resumen_asignaciones_{timestamp}.txt` - Estadísticas y distribución final de carga

## Model Training

Los modelos se entrenan utilizando:
- **TF-IDF Vectorization**: Para procesamiento de texto
- **Linear SVM**: Para clasificación supervisada
- **Feature Engineering**: Combinación de múltiples campos de texto

## Error Handling

El sistema incluye manejo robusto de errores:
- Validación de archivos de entrada
- Timeout en llamadas a API (30 segundos)
- Rate limiting (0.1s entre requests)
- Logging detallado de errores

## Development

### Estructura del Código
- `Assigner_Incidents.py`: Workflow principal para incidentes
- `Assigner_Requirements.py`: Workflow principal para requerimientos
- `Trainer.py`: Entrenamiento y actualización de modelos
- `CleaningData.py`: Utilidades de procesamiento de datos

### Testing
Ejecutar tests individuales:
```bash
python -c "from Assigner_Incidents import load_and_clean_data; load_and_clean_data()"
```

## Contributing

1. Fork del repositorio
2. Crear feature branch
3. Realizar cambios
4. Ejecutar tests
5. Submit Pull Request

## License

Proyecto interno de asignación de TI.
