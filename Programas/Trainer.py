import glob
import os
import re
import subprocess
import sys
import pandas as pd


def save_predictions_to_categorized_dataset(df_predictions, ticket_type: str):
    """
    Guarda/anexa las predicciones en el último archivo 'IncidentesCategorizados_v*.csv'
    o 'RequerimientosCategorizados_v*.csv' dentro de la carpeta 'Entrenamiento/Datos/'.
    
    ticket_type: 'incidentes' (o 'incidents') | 'requerimientos' (o 'requirements')
    """
    if df_predictions is None or df_predictions.empty:
        print("No hay predicciones para guardar en el conjunto de datos categorizado.")
        return

    ticket_type_lower = ticket_type.lower()
    if 'incid' in ticket_type_lower:
        base_dir = os.path.join("Incidentes", "Entrenamiento", "Datos")
        pattern_prefix = "IncidentesCategorizados_v"
        default_sep = ";"
        class_col_target = "Categoría"
    else:
        base_dir = os.path.join("Requerimientos", "Entrenamiento", "Datos")
        pattern_prefix = "RequerimientosCategorizados_v"
        default_sep = ";"
        class_col_target = "clasificacion"

    # Buscar el último archivo categorizado por versión (_v*.csv)
    target_file = None
    search_pattern = os.path.join(base_dir, f"{pattern_prefix}*.csv")
    files = glob.glob(search_pattern)

    if not files:
        # Búsqueda alternativa recursiva en caso de variaciones de ruta
        parent_dir = os.path.dirname(base_dir) if os.path.basename(base_dir) == "Datos" else base_dir
        files = glob.glob(os.path.join(parent_dir, "**", f"{pattern_prefix}*.csv"), recursive=True)

    if files:
        def extract_version(filepath):
            filename = os.path.basename(filepath)
            match = re.search(r"_v(\d+)\.csv$", filename, re.IGNORECASE)
            return int(match.group(1)) if match else 0

        files.sort(key=lambda f: (extract_version(f), os.path.getmtime(f)), reverse=True)
        target_file = files[0]

    if not target_file or not os.path.exists(target_file):
        print(f"Warning: No se encontró ningún archivo de conjunto de datos que coincida con '{pattern_prefix}*.csv' en {base_dir}.")
        return

    print(f"Saving predictions to latest categorized dataset: {target_file}")

    try:
        # Detectar delimitador y encoding del archivo de destino
        delimiter = default_sep
        encoding = 'latin-1'

        with open(target_file, 'r', encoding=encoding) as f:
            header_line = f.readline()
            if ';' in header_line:
                delimiter = ';'
            elif ',' in header_line:
                delimiter = ','

        # Leer primera fila para obtener los nombres exactos de columnas
        df_target_sample = pd.read_csv(target_file, sep=delimiter, nrows=1, encoding=encoding, dtype=str)
        target_columns = list(df_target_sample.columns)

        # Copiar dataframe de predicciones para alineación
        df_append = df_predictions.copy()

        # Asegurar asignaciones actualizadas
        if "predicted_assigned_to" in df_append.columns:
            df_append["assigned_to"] = df_append["predicted_assigned_to"]
        if "predicted_assignment_group" in df_append.columns:
            df_append["assignment_group"] = df_append["predicted_assignment_group"]

        # Mapear columna de clasificación/categoría
        if "Clasificación" in df_append.columns:
            matching_class_col = next((c for c in target_columns if c.lower() in ('categoría', 'categoria', 'clasificacion')), class_col_target)
            df_append[matching_class_col] = df_append["Clasificación"]

        # Mapear fecha de asignación si aplica para requerimientos
        if "opened_at" in df_append.columns and "fecha_asignacion" in target_columns:
            df_append["fecha_asignacion"] = df_append["opened_at"]

        # Limpiar BOM de nombres de columnas si existen
        target_columns_clean = [c.lstrip('\ufeff') for c in target_columns]

        # Crear dataframe alineado a target_columns
        aligned_df = pd.DataFrame()
        for orig_col, clean_col in zip(target_columns, target_columns_clean):
            if orig_col in df_append.columns:
                aligned_df[orig_col] = df_append[orig_col]
            elif clean_col in df_append.columns:
                aligned_df[orig_col] = df_append[clean_col]
            else:
                aligned_df[orig_col] = ""

        # Anexar filas al archivo categorizado
        aligned_df.to_csv(target_file, mode='a', index=False, header=False, sep=delimiter, encoding=encoding)
        print(f"Successfully appended {len(aligned_df)} predicted rows to {target_file}")

    except Exception as e:
        print(f"Error appending predictions to {target_file}: {e}")


def train_incident_models():
    """Entrena modelos supervisados y no supervisados para incidentes"""
    print("Training incident models...")
    
    original_cwd = os.getcwd()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Entrenar modelo supervisado
        supervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Incidentes", "Entrenamiento", "Supervisado"))
        print(f"Changing directory to: {supervised_dir}")
        os.chdir(supervised_dir)
        print("Training supervised incident model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureIncidents.py"], check=True)
        
        # Entrenar modelo no supervisado
        unsupervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Incidentes", "Entrenamiento", "No supervisado"))
        print(f"Changing directory to: {unsupervised_dir}")
        os.chdir(unsupervised_dir)
        print("Training unsupervised incident model...")
        subprocess.run([sys.executable, "UnsupervisedMultipleFeatureIncidents.py"], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"Error training incident models: {e}")
        raise
    finally:
        os.chdir(original_cwd)

def train_requirement_models():
    """Entrena modelos supervisados y no supervisados para requerimientos"""
    print("Training requirement models...")
    
    original_cwd = os.getcwd()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Entrenar modelo supervisado
        supervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Requerimientos", "Entrenamiento", "Supervisado"))
        print(f"Changing directory to: {supervised_dir}")
        os.chdir(supervised_dir)
        print("Training supervised requirement model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureRequirements.py"], check=True)
        
        # Entrenar modelo no supervisado
        unsupervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Requerimientos", "Entrenamiento", "No supervisado"))
        print(f"Changing directory to: {unsupervised_dir}")
        os.chdir(unsupervised_dir)
        print("Training unsupervised requirement model...")
        subprocess.run([sys.executable, "UnsupervisedMultipleFeatureRequirements.py"], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"Error training requirement models: {e}")
        raise
    finally:
        os.chdir(original_cwd)

def train_all_models():
    """Entrena todos los modelos ML"""
    print("Training all ML models...")
    try:
        train_incident_models()
        train_requirement_models()
        print("Model training completed successfully")
    except Exception as e:
        print(f"Model training failed: {e}")
        raise

if __name__ == "__main__":
    train_all_models()

