from Programas.CleaningData import clean_csv_file, get_output_path_date, get_windows_date_format, ExecutionLogger, generate_assignation_detail_report
from Programas.Trainer import save_predictions_to_categorized_dataset
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import glob
import os
import random
import re
import unicodedata
import pandas as pd
import joblib
from Programas.LoadBalancer import WorkloadBalancer

# ── Preprocessing pipeline (identical to Supervisado_Requerimientos.ipynb) ──────

def _build_stopwords():
    import nltk
    from nltk.corpus import stopwords as nltk_stopwords
    nltk.download('stopwords', quiet=True)

    def _norm(w):
        t = str(w).lower().strip()
        return unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('utf-8')

    return list(set(_norm(w) for w in (
        nltk_stopwords.words('spanish') + [
            'num', 'num_largo', 'fecha', 'fechas', 'email', 'url', 'largo',
            'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
            'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
            'dia', 'dias', 'mes', 'meses', 'semana', 'semanas', 'momento',
            'favor', 'apoyo', 'ayuda', 'gracias', 'gracia', 'estimado', 'estimada', 'estimados',
            'hola', 'buen', 'bueno', 'buena', 'atencion',
            'cordial', 'amable', 'esperar', 'adjuntar', 'agradecer', 'agradecere',
            'atento', 'comentario', 'colaboracion', 'gentil',
            'cristian', 'orellana', 'quevedo', 'california', 'parque', 'ecuador',
            'empalme', 'pichincha', 'sur', 'riobamba', 'paseo', 'rubianes', 'patricio',
            'quito', 'regional', 'carlos', 'jorge', 'maria', 'ana', 'juan', 'jose',
            'luis', 'paulin', 'diego', 'rodriguez', 'shopping', 'daule', 'manta',
            'cuenca', 'centro', 'san', 'christian', 'veronica', 'moreno',
            'cliente', 'cuenta', 'banco', 'bancs', 'bancslink', 'banclink',
            'tcs', 'sistema', 'aplicativo', 'aplicacion', 'servicio', 'usuario',
            'solicitud', 'requerimiento', 'incidente', 'ticket', 'caso',
            'proceso', 'procesamiento', 'transaccion', 'operacion',
            'informacion', 'datos', 'dato', 'registro', 'archivo',
            'numero', 'numeros', 'valor', 'valores',
            'revision', 'revisiones', 'documento', 'formato',
            'notificacion', 'correo', 'portal', 'modulo',
            'dichas', 'dicho', 'dichos', 'mismo', 'misma', 'mismos', 'mismas',
            'siguiente', 'siguientes', 'anteriores', 'correspondiente',
            'algun', 'alguna', 'algunos', 'algunas', 'alguno',
            'segun', 'dos', 'tres', 'ningun', 'ninguna',
            'nombre', 'parte', 'generacion', 'obtencion', 'muchas',
            'opcion', 'observacion',
            'bien', 'dar', 'ver', 'presenta', 'actualmente', 'prueba',
            'confirmacion', 'perteneciente', 'gerente', 'autorizacion',
            'mall', 'rio', 'telefono', 'detallar', 'contener', 'solo',
            'desear', 'jefe', 'amablemente', 'hacia', 'via',
            'proyecto', 'suficiente', 'mejora', 'adjunta', 'adjunto',
        ]
    )))

_BOILERPLATE_PATTERNS = [
    r'\brequerimientos?\s+de\s+informacion\s+relacionados?\s+a\s+bancs?\s+y\s+bancslinks?\b',
    r'\batencion\s+solicitudes?\s+bancs?\s+y\s+bancslinks?\b',
    r'\bestimad[oa]s?\b', r'\bbuen[oa]s?\s+d[ii]as?\b',
    r'\bbuen[oa]s?\s+tardes?\b', r'\bbuen[oa]s?\s+noches?\b',
    r'\bbuen\s+d[ii]a\b',
    r'^\s*estimad[oa]s?\b', r'^\s*buen[oa]s?\s+d[ii]as\b',
    r'^\s*buen[oa]s?\s+tardes\b', r'^\s*buen[oa]s?\s+noches\b',
    r'\bespero\s+se\s+encuentren\s+bien\b',
    r'\bpor\s+favor\b', r'\bfavor\b', r'\bfavor\s+con\b',
    r'\bsu\s+gentil\s+ayuda\b', r'\bsu\s+ayuda\b',
    r'\bsu\s+gentil\s+apoyo\b', r'\bsu\s+apoyo\b',
    r'\bgentil\s+apoyo\b', r'\bfavor\s+su\s+ayuda\b',
    r'\bpor\s+favor\s+su\s+ayuda\s+con\b', r'\bpor\s+favor\s+su\s+apoyo\s+con\b',
    r'\bpor\s+favor\s+apoyar\b', r'\bpor\s+favor\s+ayudar\b',
    r'\bsu\s+gentil\s+apoyo\s+con\b', r'\bsu\s+ayuda\s+con\b',
    r'\bapoyo\s+con\b', r'\bayuda\s+con\b',
    r'\batenta?\s+a\s+sus\s+comentarios\b', r'\bquedo\s+atent[oa]\b',
    r'\bde\s+antemano\b', r'\bles\s+agradezco\b',
    r'\bagradezco\s+su\s+ayuda\b',
    r'\bcordial(?:es)?\s+saludos\b', r'\bsaludos?\s+cordiales?\b',
    r'\bsaludos?\b', r'\bgracias\b', r'\badjunto\b',
    r'\besperar\s+se\s+encontrar\s+bien\b', r'\badjuntar\b',
    r'\bquedar\s+atent[oa]\b', r'\bcordial(?:es)?\s+saludo[s]?\b',
    r'\bgracia[s]?\b', r'\ble[s]?\s+agradecer\b',
    r'\bagradecer\s+su\s+ayuda\b',
    r'\batento?\s+a\s+su[s]?\s+comentario[s]?\b',
]
_BOILERPLATE_REGEX = re.compile('|'.join(_BOILERPLATE_PATTERNS))
_PREFIX_REGEX = re.compile(
    r'^(con|con el|con la|con los|con las|para|sobre|del|de la|de los|de las)\s+'
)


def _normalize_text_req(texto):
    if pd.isna(texto):
        return ''
    t = str(texto).strip().lower()
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('utf-8', errors='ignore')
    t = re.sub(r'(https?://\S+|www\.\S+)', ' url ', t)
    t = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', ' email ', t)
    t = re.sub(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', ' fecha ', t)
    t = re.sub(r'\b\d{7,}\b', ' num_largo ', t)
    t = re.sub(r'\b\d+\b', ' num ', t)
    t = re.sub(r'[_\-=/\\|()[\]{},;:]+', ' ', t)
    t = re.sub(r'[^\w\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    t = re.sub(r'(.)\1{3,}', ' ', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _strip_boilerplate(texto):
    if pd.isna(texto):
        return ''
    t = str(texto)
    for _ in range(6):
        t_new = _BOILERPLATE_REGEX.sub(' ', t)
        t_new = re.sub(r'\s+', ' ', t_new).strip()
        if t_new == t:
            break
        t = t_new
    for _ in range(4):
        t_new = _PREFIX_REGEX.sub('', t).strip()
        if t_new == t:
            break
        t = t_new
    return re.sub(r'\s+', ' ', t).strip()


def _build_final_text(row, min_tokens=4):
    d = row['desc_core']  if pd.notna(row.get('desc_core'))  else ''
    s = row['short_core'] if pd.notna(row.get('short_core')) else ''
    d_ok = len(str(d).strip().split()) >= min_tokens
    s_ok = len(str(s).strip().split()) >= min_tokens
    if d_ok and s_ok:
        return (d + ' ' + s).strip()
    if d_ok:
        return d.strip()
    if s_ok:
        return s.strip()
    return ''


# ── Fecha de resolución ──────────────────────────────────────────────────────────

def calculate_resolution_date(opened_at_str):
    win_fmt = get_windows_date_format()
    try:
        assignment_date = pd.to_datetime(opened_at_str, format=f"{win_fmt} %H:%M:%S", errors='coerce')
        if pd.isna(assignment_date):
            assignment_date = pd.to_datetime(opened_at_str, format=win_fmt, errors='coerce')
        if pd.isna(assignment_date):
            assignment_date = pd.to_datetime(opened_at_str, format='%d/%m/%Y %H:%M:%S', errors='coerce')
        if pd.isna(assignment_date):
            assignment_date = pd.to_datetime(opened_at_str, errors='coerce')
        if pd.isna(assignment_date):
            return None
    except Exception:
        return None

    base_date        = assignment_date + relativedelta(months=1)
    days_subtract    = random.randint(0, 5)
    calculated_date  = base_date - timedelta(days=days_subtract)

    if calculated_date.weekday() < 5:
        final_date = calculated_date.date()
    else:
        days_to_friday   = calculated_date.weekday() - 4
        days_to_monday   = 7 - calculated_date.weekday()
        previous_friday  = calculated_date - timedelta(days=days_to_friday)
        next_monday      = calculated_date + timedelta(days=days_to_monday)
        min_date         = base_date - timedelta(days=5)

        if next_monday > base_date:
            final_date = previous_friday.date()
        elif previous_friday < min_date:
            final_date = next_monday.date()
        else:
            final_date = previous_friday.date()

    return assignment_date.replace(
        year=final_date.year, month=final_date.month, day=final_date.day
    ).strftime(f"{win_fmt} %H:%M:%S")


# ── Predicción y asignación ──────────────────────────────────────────────────────

def predict_requirement_assignments(df_requirements, balancer, model_type='supervised'):
    """Clasifica requerimientos y los asigna utilizando modelos entrenados."""
    print(f"Predicting requirement assignments using {model_type} model...")

    model_path = f"Requerimientos/{model_type}_model"

    if model_type == 'supervised':
        try:
            # Cargar modelo supervisado y vectorizer
            model_file      = f"{model_path}/modelo_Requerimientos.joblib"
            vectorizer_file = f"{model_path}/vectorizer_Requerimientos.joblib"

            if not os.path.exists(model_file) or not os.path.exists(vectorizer_file):
                print(f"Error: no se encontraron los archivos del modelo en {model_path}. Ejecuta Supervisado_Requerimientos.ipynb primero.")
                return df_requirements

            model      = joblib.load(model_file)
            vectorizer = joblib.load(vectorizer_file)
            print(f"Model:      {model_file}")
            print(f"Vectorizer: {vectorizer_file}")

            print("Normalizing text...")
            df_requirements['short_norm'] = df_requirements['short_description'].apply(_normalize_text_req)
            df_requirements['desc_norm'] = df_requirements['description'].apply(_normalize_text_req)

            df_requirements['short_core'] = df_requirements['short_norm'].apply(_strip_boilerplate)
            df_requirements['desc_core']  = df_requirements['desc_norm'].apply(_strip_boilerplate)

            df_requirements['texto_limpio'] = df_requirements.apply(_build_final_text, axis=1)

            empty_text_count = (df_requirements['texto_limpio'] == '').sum()
            print(f"Tickets with valid text: {len(df_requirements) - empty_text_count} / {len(df_requirements)}")

            # Predicción
            X = vectorizer.transform(df_requirements['texto_limpio'])
            df_requirements['Clasificación'] = model.predict(X)

            # Tickets sin texto -> 'revision'
            empty_text_mask = df_requirements['texto_limpio'] == ''
            df_requirements.loc[empty_text_mask, 'Clasificación'] = 'revision'

            print(f"\n{'='*55}")
            print(f"  MODELO: Supervisado")
            print(f"  Tickets procesados : {len(df_requirements)}")
            print(f"  Features TF-IDF    : {X.shape[1]}")
            print(f"{'='*55}")

            print("\n[Clasificación predicha por el modelo]\n")
            id_col = next((c for c in ['number', 'Number', 'id'] if c in df_requirements.columns), None)
            for _, row in df_requirements.iterrows():
                ticket_id       = row[id_col] if id_col else "—"
                desc            = str(row.get('short_description', ''))[:60]
                predicted_class = row['Clasificación']
                print(f"  {ticket_id}  |  {predicted_class:<40}  |  {desc}")

            print(f"\n[Distribución de clases predichas]")
            for predicted_class, count in df_requirements['Clasificación'].value_counts().items():
                print(f"  {predicted_class:<42} {count} ticket(s)")
            print()

            # Fecha de resolución (solo si opened_at está presente)
            if 'opened_at' in df_requirements.columns:
                random.seed(42)
                df_requirements['fecha_resolucion'] = df_requirements['opened_at'].apply(
                    calculate_resolution_date
                )
                print("[Fecha de resolución calculada a partir de opened_at]")

            # Balanceo de carga
            df_requirements = balancer.balance_assignment(df_requirements, assigned_col="predicted_assigned_to")

            if 'predicted_assigned_to' in df_requirements.columns:
                print(f"\n[Asignación final tras balanceo]")
                cols = [c for c in [id_col, 'Clasificación', 'predicted_assigned_to'] if c]
                print(df_requirements[cols].to_string(index=False))

            # Alinear nombres de columnas para generate_assignment_reports / main()
            df_requirements['predicted_assignment_group'] = df_requirements['Clasificación']

            return df_requirements

        except Exception as e:
            print(f"Error in supervised prediction: {e}")
            import traceback
            traceback.print_exc()
            return df_requirements

    elif model_type == 'semisupervised':
        try:
            import re, unicodedata
            import nltk
            from nltk.corpus import stopwords as nltk_stopwords

            model_file      = f"{model_path}/modelo_Logistic_Regression.joblib"
            vectorizer_file = f"{model_path}/vectorizer_tfidf.joblib"

            if not os.path.exists(model_file) or not os.path.exists(vectorizer_file):
                print(f"Error: no se encontraron los archivos del modelo en {model_path}.")
                return df_requirements

            model      = joblib.load(model_file)
            vectorizer = joblib.load(vectorizer_file)
            print(f"Model:      {model_file}")
            print(f"Vectorizer: {vectorizer_file}")

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

            # Construir texto_unificado con las columnas correspondientes
            df_requirements['texto_unificado'] = (
                df_requirements['short_description'].fillna('') + ' ' +
                df_requirements['description'].fillna('')
            )
            df_requirements['texto_unificado'] = df_requirements['texto_unificado'].apply(clean_text)

            X = vectorizer.transform(df_requirements['texto_unificado'])
            df_requirements['Clasificación'] = model.predict(X)

            print(f"\n{'='*55}")
            print(f"  MODELO: Logistic Regression (semi-supervisado)")
            print(f"  Tickets procesados : {len(df_requirements)}")
            print(f"  Features TF-IDF    : {X.shape[1]}")
            print(f"{'='*55}")

            print("\n[Clasificación predicha por el modelo]\n")
            id_col = next((c for c in ['number', 'Number', 'id'] if c in df_requirements.columns), None)
            for _, row in df_requirements.iterrows():
                ticket_id = row[id_col] if id_col else "—"
                desc = str(row.get('short_description', ''))[:60]
                predicted_class = row['Clasificación']
                text = str(row.get('texto_unificado', ''))[:50]
                print(f"  {ticket_id}  |  {predicted_class:<40}  |  {desc}")
                print(f"  {'':^10}     texto: {text}")

            print(f"\n[Distribución de clases predichas]")
            for predicted_class, count in df_requirements['Clasificación'].value_counts().items():
                print(f"  {predicted_class:<42} {count} ticket(s)")
            print()

            # Fecha de resolución (solo si opened_at está presente)
            if 'opened_at' in df_requirements.columns:
                random.seed(42)
                df_requirements['fecha_resolucion'] = df_requirements['opened_at'].apply(
                    calculate_resolution_date
                )
                print("[Fecha de resolución calculada a partir de opened_at]")

            # Balanceo de carga
            df_requirements = balancer.balance_assignment(df_requirements, assigned_col="predicted_assigned_to")

            if 'predicted_assigned_to' in df_requirements.columns:
                print(f"\n[Asignación final tras balanceo]")
                cols = [c for c in [id_col, 'Clasificación', 'predicted_assigned_to'] if c]
                print(df_requirements[cols].to_string(index=False))

            # Alinear nombres de columnas para generate_assignment_reports / main()
            df_requirements['predicted_assignment_group'] = df_requirements['Clasificación']

            return df_requirements

        except Exception as e:
            print(f"Error in semisupervised prediction: {e}")
            import traceback
            traceback.print_exc()
            return df_requirements


# ── Reportes ─────────────────────────────────────────────────────────────────────

def generate_assignment_reports(df_requirements, timing, balancer=None):
    """Genera CSV de salida y reporte resumen txt con los resultados de asignación."""
    print("Generating assignment reports...")

    output_path, _ = get_output_path_date("requerimientos_con_asignacion", base_dir="Salida", timing=timing, ext=".csv")
    summary_path, _ = get_output_path_date("resumen_asignaciones_requerimientos", base_dir="Salida", timing=timing, ext=".txt")

    if "predicted_assigned_to" in df_requirements.columns:
        output_cols = [c for c in df_requirements.columns if not c.endswith('_norm')
                       and c not in ('short_core', 'desc_core', 'texto_limpio', 'original_assigned_to')]
        df_requirements[output_cols].to_csv(output_path, sep=';', index=False, encoding='latin-1')
        print(f"Requirement assignments saved to: {output_path}")

    # Generar reporte acumulativo consolidado
    try:
        generate_assignation_detail_report(df_requirements, "Requerimiento", timing)
    except Exception as e:
        print(f"Error generando reporte acumulativo de asignaciones: {e}")

    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"Requirement Assignment Summary - {timing}\n")
        f.write("=" * 50 + "\n\n")

        if "predicted_assigned_to" in df_requirements.columns:
            f.write(f"Requirements processed: {len(df_requirements)}\n")
            f.write(f"Unique assignees predicted: {df_requirements['predicted_assigned_to'].nunique()}\n")
            f.write("\nTop 5 predicted assignees:\n")
            f.write(df_requirements['predicted_assigned_to'].value_counts().head().to_string())
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


# ── Carga de datos ────────────────────────────────────────────────────────────────

def load_and_clean_data():
    """Carga y limpia archivos de datos de requerimientos."""
    print("Loading and cleaning requirement data files...")

    output_path, timing = get_output_path_date("requerimientos", base_dir="Entrada")

    clean_csv_file(
        input_path="Entrada/sc_req_item.csv",
        output_path=output_path,
        encoding="latin-1",
        replacement=" ",
        change_separator=True,
        new_separator=';'
    )

    df_requirements = pd.read_csv(
        output_path,
        sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1'
    )

    # Preservar el valor asignado previo original antes de predecir
    if 'assigned_to' in df_requirements.columns:
        df_requirements['original_assigned_to'] = df_requirements['assigned_to']

    print(f"Loaded {len(df_requirements)} requirements")

    original_columns = list(df_requirements.columns)

    return df_requirements, timing, original_columns


# ── Main ──────────────────────────────────────────────────────────────────────────

def main():
    """Flujo de trabajo principal de asignación para requerimientos."""
    try:
        df_requirements, timing, original_columns = load_and_clean_data()
    except Exception as e:
        print(f"Error loading data: {e}. Please ensure Entrada/sc_req_item.csv exists.")
        return

    balancer = WorkloadBalancer(
        groups_path="Especificaciones/Grupos - Requerimientos(Grupos).csv",
        users_path="Especificaciones/Grupos - Usuarios.csv",
    )

    print("Making assignment predictions for requirements...")
    df_requirements = predict_requirement_assignments(df_requirements, balancer, model_type='semisupervised')

    generate_assignment_reports(df_requirements, timing, balancer)

    try:
        df_requirements["assigned_to"]       = df_requirements["predicted_assigned_to"]
        df_requirements["assignment_group"]  = df_requirements["predicted_assignment_group"]
        df_to_append = df_requirements[original_columns]
        df_to_append.to_csv(
            "Especificaciones/assigned_requirements.csv",
            mode='a', index=False, header=False, sep=',', encoding='utf-8'
        )
        print("Successfully updated Especificaciones/assigned_requirements.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")

    # Guardar predicciones en el último conjunto de datos categorizado para entrenamiento futuro
    try:
        save_predictions_to_categorized_dataset(df_requirements, ticket_type="requerimientos")
    except Exception as e:
        print(f"Error saving to categorized dataset: {e}")

    print(f"Requirement assignment process completed successfully at {timing}")


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, 'log_file'):
        main()
    else:
        with ExecutionLogger("Salida", prefix="ejecucion_requirements"):
            main()
