from Programas.CleaningData import clean_csv_file, get_output_path_date, ExecutionLogger, generate_assignation_detail_report
from Programas.Trainer import save_predictions_to_categorized_dataset
from datetime import datetime
import glob
import os
import pandas as pd
import joblib
from Programas.LoadBalancer import WorkloadBalancer

def predict_incident_assignments(df_incidents, balancer, model_type='supervised'):
    """Predice asignaciones de incidentes utilizando modelos entrenados"""
    print(f"Predicting incident assignments using {model_type} model...")
    
    model_path = f"Incidentes/{model_type}_model"
    
    if model_type == 'supervised':
        try:
            # Cargar modelo supervisado
            pipeline = joblib.load(f"{model_path}/assigned_to_tfidf_svm.joblib")
            label_encoder = joblib.load(f"{model_path}/label_encoder.joblib")
            
            # Preparar características de texto (igual que en entrenamiento)
            import re, unicodedata
            
            def normalize_text(s):
                if not isinstance(s, str): return ""
                s = s.strip().lower()
                s = unicodedata.normalize("NFKC", s)
                s = re.sub(r"\s+", " ", s)
                return s
            
            def build_text(row):
                parts = [
                    row.get("u_subcategory_2", ""),
                    row.get("cmdb_ci_business_app", ""),
                    row.get("short_description", ""),
                    row.get("u_affected_user.title", ""),
                    row.get("u_affected_user.department", ""),
                    row.get("u_affected_user.company", ""),
                    row.get("location.cmn_location_type", ""),
                    row.get("description", "")
                ]
                return normalize_text(" ".join([p for p in parts if isinstance(p, str)]))
            
            df_incidents["text"] = df_incidents.apply(build_text, axis=1)
            
            # Realizar predicciones
            X = df_incidents["text"].values
            predictions = pipeline.predict(X)
            predicted_assignees = label_encoder.inverse_transform(predictions)
            
            # Agregar predicciones al dataframe
            df_incidents["predicted_assigned_to"] = predicted_assignees
            df_incidents["prediction_model_type"] = "supervised"
            df_incidents["prediction_model_name"] = "assigned_to_tfidf_svm.joblib"
            
            # Aplicar regla de validación de turnos
            df_incidents = apply_shift_validation(df_incidents)
            
            # Agregar predicción de grupo y balancear carga
            df_incidents = balancer.balance_assignment(df_incidents, assigned_col="predicted_assigned_to")
            
            df_incidents['predicted_assignment_group'] = df_incidents['Clasificación']
            
            return df_incidents
            
        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            return df_incidents
    
    elif model_type == 'semisupervised':
        try:
            import re, unicodedata
            import nltk
            from nltk.corpus import stopwords as nltk_stopwords
 
            model = joblib.load(f"{model_path}/modelo_Logistic_Regression.joblib")
            vectorizer = joblib.load(f"{model_path}/vectorizer_tfidf.joblib")
 
            nltk.download('stopwords', quiet=True)
            spanish_stopwords = set(nltk_stopwords.words('spanish'))
 
            def clean_text(text):
                if pd.isnull(text):
                    return ""
                text = str(text).lower()
                text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
                text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
                text = re.sub(r'\b\d+\b', ' ', text)
                text = re.sub(r'\b[a-z]*\d+[a-z0-9]*\b', ' ', text)
                text = re.sub(r'\b\w{1,2}\b', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                tokens = [t for t in text.split() if t not in spanish_stopwords]
                return ' '.join(tokens)
 
            # Construir texto_unificado con las mismas columnas usadas en entrenamiento
            df_incidents['texto_unificado'] = (
                df_incidents['short_description'].fillna('') + ' ' +
                df_incidents['description'].fillna('') + ' ' +
                df_incidents['u_subcategory'].fillna('') + ' ' +
                df_incidents['u_subcategory_2'].fillna('')
            )
            df_incidents['texto_unificado'] = df_incidents['texto_unificado'].apply(clean_text)
            
            X = vectorizer.transform(df_incidents['texto_unificado'])
            df_incidents['Clasificación'] = model.predict(X)
            df_incidents["prediction_model_type"] = "semisupervised"
            df_incidents["prediction_model_name"] = "modelo_Logistic_Regression.joblib"
 
            print(f"\n{'='*55}")
            print(f"  MODELO: Logistic Regression (semi-supervisado)")
            print(f"  Tickets procesados : {len(df_incidents)}")
            print(f"  Features TF-IDF    : {X.shape[1]}")
            print(f"{'='*55}")
            print("\n[Clasificación predicha por el modelo]\n")
            id_col = next((c for c in ['number', 'Number', 'id'] if c in df_incidents.columns), None)
            for _, row in df_incidents.iterrows():
                ticket_id = row[id_col] if id_col else "—"
                desc = str(row.get('short_description', ''))[:60]
                predicted_class = row['Clasificación']
                text = str(row.get('texto_unificado', ''))[:50]
                print(f"  {ticket_id}  |  {predicted_class:<30}  |  {desc}")
                print(f"  {'':^10}     texto: {text}")
            print(f"\n[Distribución de clases predichas]")
            for predicted_class, count in df_incidents['Clasificación'].value_counts().items():
                print(f"  {predicted_class:<35} {count} ticket(s)")
 
            df_incidents = apply_shift_validation(df_incidents)
            df_incidents = balancer.balance_assignment(df_incidents, assigned_col="predicted_assigned_to")
 
            if 'predicted_assigned_to' in df_incidents.columns:
                print(f"\n[Asignación final tras balanceo]")
                cols = [c for c in [id_col, 'Clasificación', 'predicted_assigned_to'] if c]
                print(df_incidents[cols].to_string(index=False))
 
            # Alinear nombres de columnas con los que espera generate_assignment_reports/main()
            df_incidents['predicted_assignment_group'] = df_incidents['Clasificación']
 
            return df_incidents

        except Exception as e:
            print(f"Error in test_semisupervisado prediction: {e}")
            return df_incidents

    return df_incidents

def apply_shift_validation(df_incidents):
    """Aplica reglas de validación de turnos para escenarios de Operación TI + Batch y Monitoreo"""
    print("Applying shift validation rule...")
    
    # Crear máscaras para diferentes escenarios de turno
    batch_category_mask = (
        df_incidents.get("category", "").astype(str).str.strip() == "Operación TI"
    )
    
    batch_subcategory_mask = (
        df_incidents.get("u_subcategory", "").astype(str).str.strip() == "Batch"
    )
    
    monitoreo_mask = (
        df_incidents.get("contact_type", "").astype(str).str.strip() == "Monitoreo"
    )
    
    # Combinar todas las máscaras con condiciones OR (cualquier criterio activa asignación por TURNO)
    shift_mask = batch_category_mask | batch_subcategory_mask | monitoreo_mask
    
    # Contar cuántos incidentes coinciden con cada regla
    batch_category_count = batch_category_mask.sum()
    batch_subcategory_count = batch_subcategory_mask.sum()
    monitoreo_count = monitoreo_mask.sum()
    total_shift_count = shift_mask.sum()
    
    print(f"Found {batch_category_count} incidents matching Operación TI category")
    print(f"Found {batch_subcategory_count} incidents matching Batch subcategory")
    print(f"Found {monitoreo_count} incidents matching Monitoreo contact type")
    print(f"Total {total_shift_count} incidents matching metadata shift rules")
    
    return df_incidents

def generate_assignment_reports(df_incidents, timing, balancer=None):
    """Genera reportes de asignación y salida CSV"""
    incident_output, _ = get_output_path_date("incidentes_con_asignacion", base_dir="Salida", timing=timing, ext=".csv")
    summary_path, _ = get_output_path_date("resumen_asignaciones_incidentes", base_dir="Salida", timing=timing, ext=".txt")
    
    # Guardar predicciones de incidentes
    if "predicted_assigned_to" in df_incidents.columns:
        df_incidents.to_csv(incident_output, sep=';', index=False, encoding='latin-1')
        print(f"Incident assignments saved to: {incident_output}")
    
    # Generar reporte acumulativo consolidado
    try:
        generate_assignation_detail_report(df_incidents, "Incidente", timing)
    except Exception as e:
        print(f"Error generando reporte acumulativo de asignaciones: {e}")

    # Generar reporte de resumen
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Incident Assignment Summary - {timing}\n")
        f.write("=" * 50 + "\n\n")
        
        if "predicted_assigned_to" in df_incidents.columns:
            f.write(f"Incidents processed: {len(df_incidents)}\n")
            f.write(f"Unique assignees predicted: {df_incidents['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_incidents['predicted_assigned_to'].value_counts().head().to_string())
            f.write("\n\n")
            
        if balancer and hasattr(balancer, 'workload') and balancer.workload:
            f.write("Total Workload Distribution (All active tickets):\n")
            f.write("-" * 50 + "\n")
            sorted_workload = sorted(balancer.workload.items(), key=lambda item: item[1], reverse=True)
            for person, count in sorted_workload:
                display = balancer.display_name(person)
                status = "" if balancer.is_active(person) else " [INACTIVE]"
                f.write(f"{display.ljust(50)} {count} tickets{status}\n")
            f.write("\n")
    
    print(f"Summary report saved to: {summary_path}")

def load_and_clean_data():
    """Carga y limpia archivos de datos de incidentes"""
    print("Loading and cleaning incident data files...")
    
    output_path, timing = get_output_path_date("incidentes", base_dir="Entrada")
    
    # Limpiar archivos de datos
    clean_csv_file(
        input_path="Entrada/incident.csv",
        output_path=output_path,
        encoding="latin-1",
        replacement=" ",
        change_separator=True,
        new_separator=';'
    )
    
    # Cargar datos limpios
    df_incidents = pd.read_csv(output_path, sep=';', dtype=str, engine='python',
                     on_bad_lines='skip', encoding='latin-1')
    
    original_columns = list(df_incidents.columns)
    
    # Preservar el valor asignado previo original antes de predecir
    if 'assigned_to' in df_incidents.columns:
        df_incidents['original_assigned_to'] = df_incidents['assigned_to']
    
    print(f"Loaded {len(df_incidents)} incidents")
    
    return df_incidents, timing, original_columns

def main():
    """Flujo principal de asignación para incidentes"""
    # Cargar y limpiar datos
    try:
        df_incidents, timing, original_columns = load_and_clean_data()
    except Exception as e:
        print(f"Error loading data: {e}. Please ensure Entrada/incident.csv exists.")
        return
        
    balancer = WorkloadBalancer()
    
    # Realizar predicciones (usando modelos entrenados)
    print("Making assignment predictions for incidents...")
    df_incidents = predict_incident_assignments(df_incidents, balancer, model_type='semisupervised')
    
    # Generar reportes
    generate_assignment_reports(df_incidents, timing, balancer)
    
    # Actualizar archivo original de asignaciones
    try:
        import csv
        df_incidents["assigned_to"] = df_incidents["predicted_assigned_to"]
        df_incidents["assignment_group"] = df_incidents["predicted_assignment_group"]
        df_to_append = df_incidents[original_columns]
        df_to_append.to_csv("Especificaciones/assigned_incidents.csv", mode='a', index=False, header=False, sep=',', encoding='utf-8', quoting=csv.QUOTE_ALL)
        print("Successfully updated Especificaciones/assigned_incidents.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")
    
    # Guardar predicciones en el último conjunto de datos categorizado para entrenamiento futuro
    try:
        save_predictions_to_categorized_dataset(df_incidents, ticket_type="incidentes")
    except Exception as e:
        print(f"Error saving to categorized dataset: {e}")

    print(f"Incident assignment process completed successfully at {timing}")

if __name__ == "__main__":
    import os, sys
    if hasattr(sys.stdout, 'log_file') or os.environ.get("DISABLE_EXECUTION_LOGGER") == "1":
        main()
    else:
        with ExecutionLogger("Salida", prefix="ejecucion_incidents"):
            main()
