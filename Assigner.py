from Programas.CleaningData import limpiar_archivo_csv
from datetime import datetime
import glob
import os
import pandas as pd
import joblib

def predict_incident_assignments(df_incidentes, model_type='supervised'):
    """Predict assignments for incidents using trained models"""
    print(f"Predicting incident assignments using {model_type} model...")
    
    model_path = f"Incidentes/{model_type}_model"
    
    if model_type == 'supervised':
        try:
            # Load supervised model
            pipeline = joblib.load(f"{model_path}/assigned_to_tfidf_svm.joblib")
            label_encoder = joblib.load(f"{model_path}/label_encoder.joblib")
            
            # Prepare text features (same as in training)
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
            
            df_incidentes["text"] = df_incidentes.apply(build_text, axis=1)
            
            # Make predictions
            X = df_incidentes["text"].values
            predictions = pipeline.predict(X)
            predicted_assignees = label_encoder.inverse_transform(predictions)
            
            # Add predictions to dataframe
            df_incidentes["predicted_assigned_to"] = predicted_assignees
            
            # Apply shift validation rule
            df_incidentes = apply_shift_validation(df_incidentes)
            
            return df_incidentes
            
        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            return df_incidentes
    
    return df_incidentes

def apply_shift_validation(df_incidentes):
    """Apply shift validation rule for Operación TI + Batch and Monitoreo scenarios"""
    print("Applying shift validation rule...")
    
    # Create masks for different shift scenarios
    batch_category_mask = (
        df_incidentes.get("category", "").astype(str).str.strip() == "Operación TI"
    )
    
    batch_subcategory_mask = (
        df_incidentes.get("u_subcategory", "").astype(str).str.strip() == "Batch"
    )
    
    monitoreo_mask = (
        df_incidentes.get("contact_type", "").astype(str).str.strip() == "Monitoreo"
    )
    
    # Combine all masks with OR conditions (any of the criteria triggers TURNO assignment)
    shift_mask = batch_category_mask | batch_subcategory_mask | monitoreo_mask
    
    # Count how many incidents match each rule
    batch_category_count = batch_category_mask.sum()
    batch_subcategory_count = batch_subcategory_mask.sum()
    monitoreo_count = monitoreo_mask.sum()
    total_shift_count = shift_mask.sum()
    
    print(f"Found {batch_category_count} incidents matching Operación TI category")
    print(f"Found {batch_subcategory_count} incidents matching Batch subcategory")
    print(f"Found {monitoreo_count} incidents matching Monitoreo contact type")
    print(f"Total {total_shift_count} incidents assigned to TURNO")
    
    # Apply the shift rule
    df_incidentes.loc[shift_mask, "predicted_assigned_to"] = "TURNO"
    
    if total_shift_count > 0:
        print(f"Assigned {total_shift_count} incidents to TURNO based on shift validation rules")
    
    return df_incidentes

def predict_requirement_assignments(df_requerimientos, model_type='supervised'):
    """Predict assignments for requirements using trained models"""
    print(f"Predicting requirement assignments using {model_type} model...")
    
    model_path = f"Requerimientos/{model_type}_model"
    
    if model_type == 'supervised':
        try:
            # Load supervised model
            pipeline = joblib.load(f"{model_path}/assigned_to_tfidf_svm.joblib")
            label_encoder = joblib.load(f"{model_path}/label_encoder.joblib")
            
            # Prepare text features (same as in training)
            import re, unicodedata
            
            def normalize_text(s):
                if not isinstance(s, str): return ""
                s = s.strip().lower()
                s = unicodedata.normalize("NFKC", s)
                s = re.sub(r"\s+", " ", s)
                return s
            
            def build_text(row):
                parts = [
                    row.get("requested_for.title", ""),
                    row.get("requested_for.company", ""),
                    row.get("short_description", ""),
                    row.get("description", "")
                ]
                return normalize_text(" ".join([p for p in parts if isinstance(p, str)]))
            
            df_requerimientos["text"] = df_requerimientos.apply(build_text, axis=1)
            
            # Make predictions
            X = df_requerimientos["text"].values
            predictions = pipeline.predict(X)
            predicted_assignees = label_encoder.inverse_transform(predictions)
            
            # Add predictions to dataframe
            df_requerimientos["predicted_assigned_to"] = predicted_assignees
            
            return df_requerimientos
            
        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            return df_requerimientos
    
    return df_requerimientos

def generate_assignment_reports(df_incidentes, df_requerimientos, timing):
    """Generate output files with assignment predictions"""
    print("Generating assignment reports...")
    
    # Create output directory
    os.makedirs("Salida", exist_ok=True)
    
    # Save incident predictions
    if "predicted_assigned_to" in df_incidentes.columns:
        incident_output = f"Salida/incidentes_con_asignacion_{timing}.csv"
        df_incidentes.to_csv(incident_output, sep=';', index=False, encoding='latin-1')
        print(f"Incident assignments saved to: {incident_output}")
    
    # Save requirement predictions
    if "predicted_assigned_to" in df_requerimientos.columns:
        requirement_output = f"Salida/requerimientos_con_asignacion_{timing}.csv"
        df_requerimientos.to_csv(requirement_output, sep=';', index=False, encoding='latin-1')
        print(f"Requirement assignments saved to: {requirement_output}")
    
    # Generate summary report
    summary_path = f"Salida/resumen_asignaciones_{timing}.txt"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Assignment Summary - {timing}\n")
        f.write("=" * 50 + "\n\n")
        
        if "predicted_assigned_to" in df_incidentes.columns:
            f.write(f"Incidents processed: {len(df_incidentes)}\n")
            f.write(f"Unique assignees predicted: {df_incidentes['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_incidentes['predicted_assigned_to'].value_counts().head().to_string())
            f.write("\n\n")
        
        if "predicted_assigned_to" in df_requerimientos.columns:
            f.write(f"Requirements processed: {len(df_requerimientos)}\n")
            f.write(f"Unique assignees predicted: {df_requerimientos['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_requerimientos['predicted_assigned_to'].value_counts().head().to_string())
    
    print(f"Summary report saved to: {summary_path}")

def load_and_clean_data():
    """Load and clean incident and requirement data files"""
    print("Loading and cleaning data files...")
    
    # Clean old processed files
    for file in glob.glob("Entrada/requerimientos*"):
        print("Eliminando", file)
        os.remove(file)
    
    for file in glob.glob("Entrada/incidentes*"):
        print("Eliminando", file)
        os.remove(file)

    timing = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    # Clean data files
    limpiar_archivo_csv(
        ruta_entrada="Entrada/requirements.csv",
        ruta_salida=f"Entrada/requerimientos_{timing}.csv",
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )
    
    limpiar_archivo_csv(
        ruta_entrada="Entrada/incidents.csv",
        ruta_salida=f"Entrada/incidentes_{timing}.csv",
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )
    
    # Load cleaned data
    df_requerimientos = pd.read_csv(f"Entrada/requerimientos_{timing}.csv", sep=';', dtype=str, engine='python',
                     on_bad_lines='skip', encoding='latin-1')
    
    df_incidentes = pd.read_csv(f"Entrada/incidentes_{timing}.csv", sep=';', dtype=str, engine='python',
                     on_bad_lines='skip', encoding='latin-1')
    
    print(f"Loaded {len(df_requerimientos)} requirements and {len(df_incidentes)} incidents")
    
    return df_requerimientos, df_incidentes, timing

def main():
    """Main assignment workflow"""
    # Load and clean data
    df_requerimientos, df_incidentes, timing = load_and_clean_data()
    
    # Make predictions (using existing trained models)
    print("Making assignment predictions...")
    df_incidentes = predict_incident_assignments(df_incidentes, model_type='supervised')
    df_requerimientos = predict_requirement_assignments(df_requerimientos, model_type='supervised')
    
    # Generate reports
    generate_assignment_reports(df_incidentes, df_requerimientos, timing)
    
    print(f"Assignment process completed successfully at {timing}")

if __name__ == "__main__":
    main()