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
Desde la raíz del proyecto:
```bash
python Assigner_Incidents.py
python Assigner_Requirements.py
```

## Configuration

#### Shift Validation Rules
El sistema aplica las siguientes reglas de validación:
- **Operación TI**: Incidentes en categoría "Operación TI"
- **Batch**: Incidentes con subcategoría "Batch"  
- **Monitoreo**: Incidentes con tipo de contacto "Monitoreo"

Cualquier incidente que cumpla con ALGUNA de estas condiciones será asignado a "TURNO".

## Data Format

### Archivos de Entrada
- `Entrada/incidents.csv` - Datos de incidentes
- `Entrada/requirements.csv` - Datos de requerimientos

### Archivos de Salida
- `Salida/incidentes_con_asignacion_{timestamp}.csv`
- `Salida/requerimientos_con_asignacion_{timestamp}.csv`
- `Salida/resumen_asignaciones_{timestamp}.txt`

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
