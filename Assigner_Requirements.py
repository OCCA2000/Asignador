from Programas.CleaningData import limpiar_archivo_csv, obtener_ruta_salida_fecha
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


def _construir_texto_final(row, min_tokens=4):
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

def calcular_fecha_resolucion(opened_at_str):
    try:
        fecha_asignacion = pd.to_datetime(opened_at_str, format='%d/%m/%Y %H:%M:%S')
    except Exception:
        return None

    fecha_base      = fecha_asignacion + relativedelta(months=1)
    dias_resta      = random.randint(0, 5)
    fecha_calculada = fecha_base - timedelta(days=dias_resta)

    if fecha_calculada.weekday() < 5:
        fecha_final = fecha_calculada.date()
    else:
        dias_a_viernes   = fecha_calculada.weekday() - 4
        dias_a_lunes     = 7 - fecha_calculada.weekday()
        viernes_anterior = fecha_calculada - timedelta(days=dias_a_viernes)
        lunes_siguiente  = fecha_calculada + timedelta(days=dias_a_lunes)
        fecha_min        = fecha_base - timedelta(days=5)

        if lunes_siguiente > fecha_base:
            fecha_final = viernes_anterior.date()
        elif viernes_anterior < fecha_min:
            fecha_final = lunes_siguiente.date()
        else:
            fecha_final = viernes_anterior.date()

    return fecha_asignacion.replace(
        year=fecha_final.year, month=fecha_final.month, day=fecha_final.day
    )


# ── Predicción ───────────────────────────────────────────────────────────────────

def predict_requirement_assignments(df_requerimientos, balancer):
    """Classify requirements and assign them using the trained supervisado model."""
    print("Predicting requirement assignments using supervisado model...")

    try:
        # Load model and vectorizer
        ruta_modelo     = "Requerimientos/supervised_model/modelo_Requerimientos.joblib"
        ruta_vectorizer = "Requerimientos/supervised_model/vectorizer_Requerimientos.joblib"

        if not os.path.exists(ruta_modelo) or not os.path.exists(ruta_vectorizer):
            print("Error: no se encontraron los archivos del modelo en Modelos/. Ejecuta Supervisado_Requerimientos.ipynb primero.")
            return df_requerimientos

        modelo     = joblib.load(ruta_modelo)
        vectorizer = joblib.load(ruta_vectorizer)
        print(f"Model:      {ruta_modelo}")
        print(f"Vectorizer: {ruta_vectorizer}")

        print("Normalizing text...")
        df_requerimientos['short_norm'] = df_requerimientos['short_description'].apply(_normalize_text_req)
        df_requerimientos['desc_norm'] = df_requerimientos['description'].apply(_normalize_text_req)

        df_requerimientos['short_core'] = df_requerimientos['short_norm'].apply(_strip_boilerplate)
        df_requerimientos['desc_core']  = df_requerimientos['desc_norm'].apply(_strip_boilerplate)

        df_requerimientos['texto_limpio'] = df_requerimientos.apply(_construir_texto_final, axis=1)

        sin_texto = (df_requerimientos['texto_limpio'] == '').sum()
        print(f"Tickets with valid text: {len(df_requerimientos) - sin_texto} / {len(df_requerimientos)}")

        # Predict
        X = vectorizer.transform(df_requerimientos['texto_limpio'])
        df_requerimientos['Clasificación'] = modelo.predict(X)

        # Tickets without text → 'revision'
        mask_sin_texto = df_requerimientos['texto_limpio'] == ''
        df_requerimientos.loc[mask_sin_texto, 'Clasificación'] = 'revision'

        print(f"\n{'='*55}")
        print(f"  MODELO: Supervisado")
        print(f"  Tickets procesados : {len(df_requerimientos)}")
        print(f"  Features TF-IDF    : {X.shape[1]}")
        print(f"{'='*55}")

        print("\n[Clasificación predicha por el modelo]\n")
        id_col = next((c for c in ['number', 'Number', 'id'] if c in df_requerimientos.columns), None)
        for _, row in df_requerimientos.iterrows():
            ticket_id = row[id_col] if id_col else "—"
            desc      = str(row.get('short_description', ''))[:60]
            clase     = row['Clasificación']
            print(f"  {ticket_id}  |  {clase:<40}  |  {desc}")

        print(f"\n[Distribución de clases predichas]")
        for clase, count in df_requerimientos['Clasificación'].value_counts().items():
            print(f"  {clase:<42} {count} ticket(s)")
        print()

        # Fecha de resolución (solo si opened_at está presente)
        if 'opened_at' in df_requerimientos.columns:
            random.seed(42)
            df_requerimientos['fecha_resolucion'] = df_requerimientos['opened_at'].apply(
                calcular_fecha_resolucion
            )
            print("[Fecha de resolución calculada a partir de opened_at]")

        # Workload balancing
        df_requerimientos = balancer.balance_assignment(df_requerimientos)

        if 'assigned_to' in df_requerimientos.columns:
            print(f"\n[Asignación final tras balanceo]")
            cols = [c for c in [id_col, 'Clasificación', 'assigned_to'] if c]
            print(df_requerimientos[cols].to_string(index=False))

        # Align column names for generate_assignment_reports / main()
        df_requerimientos['predicted_assigned_to']    = df_requerimientos['assigned_to']
        df_requerimientos['predicted_assignment_group'] = df_requerimientos['Clasificación']

        return df_requerimientos

    except Exception as e:
        print(f"Error in prediction: {e}")
        import traceback
        traceback.print_exc()
        return df_requerimientos


# ── Reportes ─────────────────────────────────────────────────────────────────────

def generate_assignment_reports(df_requerimientos, timing, balancer=None):
    """Generate output CSV and summary txt with assignment results."""
    print("Generating assignment reports...")

    output_path, _ = obtener_ruta_salida_fecha("requerimientos_con_asignacion", base_dir="Salida", timing=timing, ext=".csv")
    summary_path, _ = obtener_ruta_salida_fecha("resumen_asignaciones_requerimientos", base_dir="Salida", timing=timing, ext=".txt")

    if "predicted_assigned_to" in df_requerimientos.columns:
        cols_salida = [c for c in df_requerimientos.columns if not c.endswith('_norm')
                       and c not in ('short_core', 'desc_core', 'texto_limpio')]
        df_requerimientos[cols_salida].to_csv(output_path, sep=';', index=False, encoding='latin-1')
        print(f"Requirement assignments saved to: {output_path}")

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
                display = balancer.display_name(person)
                status = "" if balancer.is_active(person) else " [INACTIVE]"
                f.write(f"{display.ljust(50)} {count} tickets{status}\n")
            f.write("\n")

    print(f"Summary report saved to: {summary_path}")


# ── Carga de datos ────────────────────────────────────────────────────────────────

def load_and_clean_data():
    """Load and clean requirement data files."""
    print("Loading and cleaning requirement data files...")

    ruta_salida, timing = obtener_ruta_salida_fecha("requerimientos", base_dir="Entrada")

    limpiar_archivo_csv(
        ruta_entrada="Entrada/sc_req_item.csv",
        ruta_salida=ruta_salida,
        encoding="latin-1",
        replacement=" ",
        cambiar_separador=True,
        nuevo_separador=';'
    )

    df_requerimientos = pd.read_csv(
        ruta_salida,
        sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1'
    )

    print(f"Loaded {len(df_requerimientos)} requirements")

    original_columns = list(df_requerimientos.columns)

    return df_requerimientos, timing, original_columns


# ── Main ──────────────────────────────────────────────────────────────────────────

def main():
    """Main assignment workflow for requirements."""
    try:
        df_requerimientos, timing, original_columns = load_and_clean_data()
    except Exception as e:
        print(f"Error loading data: {e}. Please ensure Entrada/sc_req_item.csv exists.")
        return

    if df_requerimientos.empty:
        print("No requirements to process.")
        return

    balancer = WorkloadBalancer(
        grupos_path="Especificaciones/Grupos - Requerimientos(Grupos).csv",
        usuarios_path="Especificaciones/Grupos - Usuarios.csv",
    )

    print("Making assignment predictions for requirements...")
    df_requerimientos = predict_requirement_assignments(df_requerimientos, balancer)

    generate_assignment_reports(df_requerimientos, timing, balancer)

    try:
        df_requerimientos["assigned_to"]       = df_requerimientos["predicted_assigned_to"]
        df_requerimientos["assignment_group"]  = df_requerimientos["predicted_assignment_group"]
        df_to_append = df_requerimientos[original_columns]
        df_to_append.to_csv(
            "Especificaciones/assigned_requirements.csv",
            mode='a', index=False, header=False, sep=',', encoding='utf-8'
        )
        print("Successfully updated Especificaciones/assigned_requirements.csv")
    except Exception as e:
        print(f"Error updating assigned file: {e}")

    print(f"Requirement assignment process completed successfully at {timing}")


if __name__ == "__main__":
    main()
