from Programas.CleaningData import limpiar_archivo_csv
from datetime import datetime
import glob
import os
import pandas as pd
import joblib
from Programas.LoadBalancer import WorkloadBalancer

def predict_incident_assignments(df_incidentes, balancer, model_type='supervised'):
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
            
            # Add group prediction and load balance
            df_incidentes = balancer.balance_assignment(df_incidentes)
            
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

def generate_assignment_reports(df_incidentes, timing, balancer=None):
    """Generate output files with assignment predictions"""
    print("Generating assignment reports...")
    
    # Create output directory
    os.makedirs("Salida", exist_ok=True)
    
    # Save incident predictions
    if "predicted_assigned_to" in df_incidentes.columns:
        incident_output = f"Salida/incidentes_con_asignacion_{timing}.csv"
        df_incidentes.to_csv(incident_output, sep=';', index=False, encoding='latin-1')
        print(f"Incident assignments saved to: {incident_output}")
    
    # Generate summary report
    summary_path = f"Salida/resumen_asignaciones_incidentes_{timing}.txt"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Incident Assignment Summary - {timing}\n")
        f.write("=" * 50 + "\n\n")
        
        if "predicted_assigned_to" in df_incidentes.columns:
            f.write(f"Incidents processed: {len(df_incidentes)}\n")
            f.write(f"Unique assignees predicted: {df_incidentes['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_incidentes['predicted_assigned_to'].value_counts().head().to_string())
            f.write("\n\n")
            
        if balancer and hasattr(balancer, 'workload') and balancer.workload:
            f.write("Total Workload Distribution (All active tickets):\n")
            f.write("-" * 50 + "\n")
            sorted_workload = sorted(balancer.workload.items(), key=lambda item: item[1], reverse=True)
            for person, count in sorted_workload:
                f.write(f"{person.ljust(40)} {count} tickets\n")
            f.write("\n")
    
    print(f"Summary report saved to: {summary_path}")

def load_and_clean_data():
    """Load and clean incident data files"""
    print("Loading and cleaning incident data files...")
    
    # Clean old processed files
    for file in glob.glob("Entrada/incidentes*"):
        print("Eliminando", file)
        os.remove(file)

    timing = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    # Clean data files
    limpiar_archivo_csv(
        ruta_entrada="Entrada/incident.csv",
        ruta_salida=f"Entrada/incidentes_{timing}.csv",
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )
    
    # Load cleaned data
    df_incidentes = pd.read_csv(f"Entrada/incidentes_{timing}.csv", sep=';', dtype=str, engine='python',
                     on_bad_lines='skip', encoding='latin-1')
    
    print(f"Loaded {len(df_incidentes)} incidents")
    
    original_columns = list(df_incidentes.columns)
    
    return df_incidentes, timing, original_columns

def main():
    """Main assignment workflow for incidents"""
    # Load and clean data
    try:
        df_incidentes, timing, original_columns = load_and_clean_data()
    except Exception as e:
        print(f"Error loading data: {e}. Please ensure Entrada/incident.csv exists.")
        return
        
    balancer = WorkloadBalancer()
    
    # Make predictions (using existing trained models)
    print("Making assignment predictions for incidents...")
    df_incidentes = predict_incident_assignments(df_incidentes, balancer, model_type='supervised')
    
    # Generate reports
    generate_assignment_reports(df_incidentes, timing, balancer)
    
    # Update original assigned file
    try:
        df_incidentes["assigned_to"] = df_incidentes["predicted_assigned_to"]
        df_incidentes["assignment_group"] = df_incidentes["predicted_assignment_group"]
        df_to_append = df_incidentes[original_columns]
        df_to_append.to_csv("Entrada/assigned_incidents.csv", mode='a', index=False, header=False, sep=',', encoding='utf-8')
        print("Successfully updated Entrada/assigned_incidents.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")
    
    print(f"Incident assignment process completed successfully at {timing}")

if __name__ == "__main__":
    main()
