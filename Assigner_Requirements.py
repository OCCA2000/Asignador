from Programas.CleaningData import limpiar_archivo_csv
from datetime import datetime
import glob
import os
import pandas as pd
import joblib
from Programas.LoadBalancer import WorkloadBalancer

def predict_requirement_assignments(df_requerimientos, balancer, model_type='supervised'):
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
            
            # Add group prediction and load balance
            df_requerimientos = balancer.balance_assignment(df_requerimientos)
            
            return df_requerimientos
            
        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            return df_requerimientos
    
    return df_requerimientos

def generate_assignment_reports(df_requerimientos, timing, balancer=None):
    """Generate output files with assignment predictions"""
    print("Generating assignment reports...")
    
    # Create output directory
    os.makedirs("Salida", exist_ok=True)
    
    # Save requirement predictions
    if "predicted_assigned_to" in df_requerimientos.columns:
        requirement_output = f"Salida/requerimientos_con_asignacion_{timing}.csv"
        df_requerimientos.to_csv(requirement_output, sep=';', index=False, encoding='latin-1')
        print(f"Requirement assignments saved to: {requirement_output}")
    
    # Generate summary report
    summary_path = f"Salida/resumen_asignaciones_requerimientos_{timing}.txt"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Requirement Assignment Summary - {timing}\n")
        f.write("=" * 50 + "\n\n")
        
        if "predicted_assigned_to" in df_requerimientos.columns:
            f.write(f"Requirements processed: {len(df_requerimientos)}\n")
            f.write(f"Unique assignees predicted: {df_requerimientos['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_requerimientos['predicted_assigned_to'].value_counts().head().to_string())
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
    """Load and clean requirement data files"""
    print("Loading and cleaning requirement data files...")
    
    # Clean old processed files
    for file in glob.glob("Entrada/requerimientos*"):
        print("Eliminando", file)
        os.remove(file)

    timing = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    # Clean data files
    limpiar_archivo_csv(
        ruta_entrada="Entrada/sc_req_item.csv",
        ruta_salida=f"Entrada/requerimientos_{timing}.csv",
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )
    
    # Load cleaned data
    df_requerimientos = pd.read_csv(f"Entrada/requerimientos_{timing}.csv", sep=';', dtype=str, engine='python',
                     on_bad_lines='skip', encoding='latin-1')
    
    print(f"Loaded {len(df_requerimientos)} requirements")
    
    original_columns = list(df_requerimientos.columns)
    
    return df_requerimientos, timing, original_columns

def main():
    """Main requirement assignment workflow"""
    # Load and clean data
    try:
        df_requerimientos, timing, original_columns = load_and_clean_data()
    except Exception as e:
        print(f"Error loading data: {e}. Please ensure Entrada/sc_req_item.csv exists.")
        return
        
    if df_requerimientos.empty:
        print("No requirements to process.")
        return
    
    balancer = WorkloadBalancer()
    
    # Make predictions (using existing trained models)
    print("Making assignment predictions for requirements...")
    df_requerimientos = predict_requirement_assignments(df_requerimientos, balancer, model_type='supervised')
    
    # Generate reports
    generate_assignment_reports(df_requerimientos, timing, balancer)
    
    # Update original assigned file
    try:
        df_requerimientos["assigned_to"] = df_requerimientos["predicted_assigned_to"]
        df_requerimientos["assignment_group"] = df_requerimientos["predicted_assignment_group"]
        df_to_append = df_requerimientos[original_columns]
        df_to_append.to_csv("Entrada/assigned_requirements.csv", mode='a', index=False, header=False, sep=',', encoding='utf-8')
        print("Successfully updated Entrada/assigned_requirements.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")
    
    print(f"Requirement assignment process completed successfully at {timing}")

if __name__ == "__main__":
    main()
