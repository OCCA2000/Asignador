from Programas.CleaningData import limpiar_archivo_csv, obtener_ruta_salida_fecha
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
            
            df_incidentes['predicted_assigned_to'] = df_incidentes['assigned_to']
            df_incidentes['predicted_assignment_group'] = df_incidentes['Clasificación']
            
            return df_incidentes
            
        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            return df_incidentes
    
    elif model_type == 'semisupervised':
        try:
            import re, unicodedata
            import nltk
            from nltk.corpus import stopwords as nltk_stopwords

            modelo = joblib.load(f"{model_path}/modelo_Logistic_Regression.joblib")
            vectorizer = joblib.load(f"{model_path}/vectorizer_tfidf.joblib")

            nltk.download('stopwords', quiet=True)
            spanish_stopwords = set(nltk_stopwords.words('spanish'))

            def limpiar_texto(texto):
                if pd.isnull(texto):
                    return ""
                texto = str(texto).lower()
                texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')
                texto = re.sub(r'[^a-zA-Z0-9\s]', ' ', texto)
                texto = re.sub(r'\b\d+\b', ' ', texto)
                texto = re.sub(r'\b[a-z]*\d+[a-z0-9]*\b', ' ', texto)
                texto = re.sub(r'\b\w{1,2}\b', ' ', texto)
                texto = re.sub(r'\s+', ' ', texto).strip()
                tokens = [t for t in texto.split() if t not in spanish_stopwords]
                return ' '.join(tokens)

            # Build texto_unificado with same columns used in training
            df_incidentes['texto_unificado'] = (
                df_incidentes['short_description'].fillna('') + ' ' +
                df_incidentes['description'].fillna('') + ' ' +
                df_incidentes['u_subcategory'].fillna('') + ' ' +
                df_incidentes['u_subcategory_2'].fillna('')
            )
            df_incidentes['texto_unificado'] = df_incidentes['texto_unificado'].apply(limpiar_texto)
            
            X = vectorizer.transform(df_incidentes['texto_unificado'])
            df_incidentes['Clasificación'] = modelo.predict(X)

            print(f"\n{'='*55}")
            print(f"  MODELO: Logistic Regression (semi-supervisado)")
            print(f"  Tickets procesados : {len(df_incidentes)}")
            print(f"  Features TF-IDF    : {X.shape[1]}")
            print(f"{'='*55}")
            print("\n[Clasificación predicha por el modelo]\n")
            id_col = next((c for c in ['number', 'Number', 'id'] if c in df_incidentes.columns), None)
            for _, row in df_incidentes.iterrows():
                ticket_id = row[id_col] if id_col else "—"
                desc = str(row.get('short_description', ''))[:60]
                clase = row['Clasificación']
                texto = str(row.get('texto_unificado', ''))[:50]
                print(f"  {ticket_id}  |  {clase:<30}  |  {desc}")
                print(f"  {'':^10}     texto: {texto}")
            print(f"\n[Distribución de clases predichas]")
            for clase, count in df_incidentes['Clasificación'].value_counts().items():
                print(f"  {clase:<35} {count} ticket(s)")

            df_incidentes = apply_shift_validation(df_incidentes)
            df_incidentes = balancer.balance_assignment(df_incidentes)

            if 'assigned_to' in df_incidentes.columns:
                print(f"\n[Asignación final tras balanceo]")
                cols = [c for c in [id_col, 'Clasificación', 'assigned_to'] if c]
                print(df_incidentes[cols].to_string(index=False))

            # Alinear nombres de columnas con los que espera generate_assignment_reports/main()
            df_incidentes['predicted_assigned_to'] = df_incidentes['assigned_to']
            df_incidentes['predicted_assignment_group'] = df_incidentes['Clasificación']

            return df_incidentes

        except Exception as e:
            print(f"Error in test_semisupervisado prediction: {e}")
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
    print(f"Total {total_shift_count} incidents matching metadata shift rules")
    
    return df_incidentes

def generate_assignment_reports(df_incidentes, timing, balancer=None):
    """Generate assignment reports and CSV output"""
    incident_output, _ = obtener_ruta_salida_fecha("incidentes_con_asignacion", base_dir="Salida", timing=timing, ext=".csv")
    summary_path, _ = obtener_ruta_salida_fecha("resumen_asignaciones_incidentes", base_dir="Salida", timing=timing, ext=".txt")
    
    # Save incident predictions
    if "predicted_assigned_to" in df_incidentes.columns:
        df_incidentes.to_csv(incident_output, sep=';', index=False, encoding='latin-1')
        print(f"Incident assignments saved to: {incident_output}")
    
    # Generate summary report
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
                display = balancer.display_name(person)
                status = "" if balancer.is_active(person) else " [INACTIVE]"
                f.write(f"{display.ljust(50)} {count} tickets{status}\n")
            f.write("\n")
    
    print(f"Summary report saved to: {summary_path}")

def load_and_clean_data():
    """Load and clean incident data files"""
    print("Loading and cleaning incident data files...")
    
    ruta_salida, timing = obtener_ruta_salida_fecha("incidentes", base_dir="Entrada")
    
    # Clean data files
    limpiar_archivo_csv(
        ruta_entrada="Entrada/incident.csv",
        ruta_salida=ruta_salida,
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )
    
    # Load cleaned data
    df_incidentes = pd.read_csv(ruta_salida, sep=';', dtype=str, engine='python',
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
    df_incidentes = predict_incident_assignments(df_incidentes, balancer, model_type='semisupervised')
    
    # Generate reports
    generate_assignment_reports(df_incidentes, timing, balancer)
    
    # Update original assigned file
    try:
        df_incidentes["assigned_to"] = df_incidentes["predicted_assigned_to"]
        df_incidentes["assignment_group"] = df_incidentes["predicted_assignment_group"]
        df_to_append = df_incidentes[original_columns]
        df_to_append.to_csv("Especificaciones/assigned_incidents.csv", mode='a', index=False, header=False, sep=',', encoding='utf-8')
        print("Successfully updated Especificaciones/assigned_incidents.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")
    
    print(f"Incident assignment process completed successfully at {timing}")

if __name__ == "__main__":
    main()
