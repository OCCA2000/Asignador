"""
Orquestador Central de Entrenamiento de Modelos de Machine Learning
Sistema Asignador de Tickets (Incidentes y Requerimientos) — ServiceNow

Permite ejecutar de forma unificada o granular los 8 modelos del sistema:
- Incidentes: Supervisado (SVM), No supervisado (DBSCAN), Semisupervisado (TF-IDF Baseline y HNLP-MC)
- Requerimientos: Supervisado (SVM), No supervisado (DBSCAN), Semisupervisado (TF-IDF Baseline y HNLP-MC)

Características clave:
- Sincronización automática de cambios de cuadernos Jupyter (.ipynb) hacia scripts (.py) por marca de tiempo (mtime).
- Resolución dinámica de datasets de entrenamiento priorizando la fecha de modificación (getmtime).
- Soporte para sobreescritura de dataset mediante parámetro CLI --data-path.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
import pandas as pd

script_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.normpath(os.path.join(script_dir, ".."))
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

try:
    from Programas.PipelineUtils import ExecutionLogger, get_latest_training_dataset
except ImportError:
    ExecutionLogger = None
    get_latest_training_dataset = None


# Mapeo de Cuadernos Jupyter (.ipynb) a Scripts Python (.py)
NOTEBOOK_SCRIPT_MAPPINGS = [
    (
        os.path.join("Incidentes", "Entrenamiento", "Semisupervisado", "02_Entrenamiento_TFIDF_Incidentes.ipynb"),
        os.path.join("Incidentes", "Entrenamiento", "Semisupervisado", "Entrenamiento_TFIDF_Incidentes.py")
    ),
    (
        os.path.join("Incidentes", "Entrenamiento", "Semisupervisado", "03_Entrenamiento_HNLP_MC_Incidentes.ipynb"),
        os.path.join("Incidentes", "Entrenamiento", "Semisupervisado", "Entrenamiento_HNLP_MC_Incidentes.py")
    ),
    (
        os.path.join("Requerimientos", "Entrenamiento", "Semisupervisado", "02_Entrenamiento_TFIDF_Requerimientos.ipynb"),
        os.path.join("Requerimientos", "Entrenamiento", "Semisupervisado", "Entrenamiento_TFIDF_Requerimientos.py")
    ),
    (
        os.path.join("Requerimientos", "Entrenamiento", "Semisupervisado", "03_Entrenamiento_HNLP_MC_Requerimientos.ipynb"),
        os.path.join("Requerimientos", "Entrenamiento", "Semisupervisado", "Entrenamiento_HNLP_MC_Requerimientos.py")
    ),
]


def sync_notebook_to_script(notebook_rel_path: str, script_rel_path: str, force: bool = False) -> bool:
    """
    Sincroniza automáticamente los cambios realizados en un cuaderno Jupyter (.ipynb)
    hacia su script Python (.py) correspondiente.

    Se activa si mtime(.ipynb) > mtime(.py) o si force=True.
    - Neutraliza comandos mágicos de Jupyter (%matplotlib, !pip, etc.).
    - Neutraliza llamadas gráficas bloqueantes (plt.show() -> plt.close()).
    - Inyecta resolución dinámica de datasets basada en la fecha de modificación más reciente.
    """
    nb_full = os.path.normpath(os.path.join(workspace_root, notebook_rel_path))
    sc_full = os.path.normpath(os.path.join(workspace_root, script_rel_path))

    if not os.path.exists(nb_full):
        return False

    nb_mtime = os.path.getmtime(nb_full)
    sc_exists = os.path.exists(sc_full)
    sc_mtime = os.path.getmtime(sc_full) if sc_exists else 0

    if not force and sc_exists and nb_mtime <= sc_mtime:
        return False

    nb_name = os.path.basename(nb_full)
    sc_name = os.path.basename(sc_full)
    nb_dt = datetime.fromtimestamp(nb_mtime).strftime('%Y-%m-%d %H:%M:%S')
    print(f">> [Sync] Cuaderno '{nb_name}' modificado ({nb_dt}). Sincronizando hacia '{sc_name}'...")

    try:
        with open(nb_full, 'r', encoding='utf-8') as f:
            nb = json.load(f)

        is_incidents = 'incid' in sc_name.lower() or 'incid' in nb_name.lower()
        domain = 'incidentes' if is_incidents else 'requerimientos'

        header = [
            f'"""\nCódigo sincronizado automáticamente desde el cuaderno:\n{nb_name} (Última mod: {nb_dt})\n"""\n',
            'import os, sys, warnings\n',
            'warnings.filterwarnings("ignore")\n',
            'if hasattr(sys.stdout, "reconfigure"):\n',
            '    sys.stdout.reconfigure(encoding="utf-8")\n',
            'if hasattr(sys.stderr, "reconfigure"):\n',
            '    sys.stderr.reconfigure(encoding="utf-8")\n',
            '# Asegurar importación de utilidades del pipeline\n',
            'sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))\n',
            'from Programas.PipelineUtils import get_latest_training_dataset, clean_and_deidentify_text\n',
            '# Compatibilidad con funciones nativas de Jupyter\n',
            'try:\n',
            '    from IPython.display import display\n',
            'except ImportError:\n',
            '    def display(*args, **kwargs):\n',
            '        for a in args:\n',
            '            print(a)\n\n'
        ]

        code_lines = header.copy()

        for cell in nb.get('cells', []):
            if cell.get('cell_type') != 'code':
                continue
            for line in cell.get('source', []):
                l_strip = line.strip()
                # 1. Neutralizar comandos mágicos de Jupyter
                if l_strip.startswith(('%', '!')):
                    code_lines.append(f"# [Jupyter magic] {line}")
                # 2. Neutralizar plt.show() bloqueante
                elif 'plt.show()' in line:
                    code_lines.append(line.replace('plt.show()', 'plt.close()'))
                # 3. Dinamizar la lectura de dataset si hay ruta_csv fija en el notebook
                elif re.match(r'^\s*ruta_csv\s*=\s*', line) and 'pd.read_csv' not in line:
                    code_lines.append(
                        f"explicit_data = os.environ.get('TRAINING_DATA_PATH', None)\n"
                        f"ruta_csv = get_latest_training_dataset('{domain}', kind='preparados', explicit_path=explicit_data, verbose=True)\n"
                    )
                else:
                    code_lines.append(line)
            code_lines.append('\n')

        content = ''.join(code_lines)
        with open(sc_full, 'w', encoding='utf-8') as f:
            f.write(content)

        # Ajustar timestamp del script para que sea coherente con el notebook
        target_time = max(nb_mtime + 2, time.time())
        os.utime(sc_full, (target_time, target_time))
        print(f">> [Sync] Sincronización exitosa: {sc_name} actualizado y listo para entrenar.\n")
        return True

    except Exception as e:
        print(f">> [Sync Warning] No se pudo sincronizar {nb_name} -> {sc_name}: {e}")
        return False


def sync_all_notebooks(force: bool = False, ticket_type: str = 'all'):
    """Sincroniza todos los cuadernos relevantes antes del entrenamiento."""
    tt_lower = ticket_type.lower()
    for nb_rel, sc_rel in NOTEBOOK_SCRIPT_MAPPINGS:
        if tt_lower != 'all':
            is_inc = 'incid' in nb_rel.lower()
            if tt_lower in ('incidentes', 'incidents') and not is_inc:
                continue
            if tt_lower in ('requerimientos', 'requirements') and is_inc:
                continue
        sync_notebook_to_script(nb_rel, sc_rel, force=force)


def save_predictions_to_categorized_dataset(df_predictions, ticket_type: str):
    """
    Guarda/anexa las predicciones en el último archivo 'IncidentesCategorizados_v*.csv'
    o 'RequerimientosCategorizados_v*.csv' dentro de la carpeta 'Entrenamiento/Datos/'.
    
    Prioriza la fecha de modificación (getmtime) como discriminante principal.
    """
    if df_predictions is None or df_predictions.empty:
        print("No hay predicciones para guardar en el conjunto de datos categorizado.")
        return

    ticket_type_lower = ticket_type.lower()
    if 'incid' in ticket_type_lower:
        base_dir = os.path.join(workspace_root, "Incidentes", "Entrenamiento", "Datos")
        pattern_prefix = "IncidentesCategorizados_v"
        default_sep = ";"
        class_col_target = "Categoría"
    else:
        base_dir = os.path.join(workspace_root, "Requerimientos", "Entrenamiento", "Datos")
        pattern_prefix = "RequerimientosCategorizados_v"
        default_sep = ";"
        class_col_target = "clasificacion"

    target_file = None
    search_pattern = os.path.join(base_dir, f"{pattern_prefix}*.csv")
    files = glob.glob(search_pattern)

    if not files:
        parent_dir = os.path.dirname(base_dir) if os.path.basename(base_dir) == "Datos" else base_dir
        files = glob.glob(os.path.join(parent_dir, "**", f"{pattern_prefix}*.csv"), recursive=True)

    if files:
        def extract_version(filepath):
            filename = os.path.basename(filepath)
            match = re.search(r"_v(\d+)\.csv$", filename, re.IGNORECASE)
            return int(match.group(1)) if match else 0

        # Priorizar fecha de modificación (getmtime) y luego versión
        files.sort(key=lambda f: (os.path.getmtime(f), extract_version(f)), reverse=True)
        target_file = files[0]

    if not target_file or not os.path.exists(target_file):
        print(f"Warning: No se encontró ningún archivo que coincida con '{pattern_prefix}*.csv' en {base_dir}.")
        return

    mtime_str = datetime.fromtimestamp(os.path.getmtime(target_file)).strftime('%Y-%m-%d %H:%M:%S')
    print(f"Saving predictions to latest categorized dataset: {os.path.basename(target_file)} [mtime: {mtime_str}]")

    try:
        delimiter = default_sep
        encoding = 'latin-1'

        with open(target_file, 'r', encoding=encoding) as f:
            header_line = f.readline()
            if ';' in header_line:
                delimiter = ';'
            elif ',' in header_line:
                delimiter = ','

        df_target_sample = pd.read_csv(target_file, sep=delimiter, nrows=1, encoding=encoding, dtype=str)
        target_columns = list(df_target_sample.columns)
        df_append = df_predictions.copy()

        if "predicted_assigned_to" in df_append.columns:
            df_append["assigned_to"] = df_append["predicted_assigned_to"]
        if "predicted_assignment_group" in df_append.columns:
            df_append["assignment_group"] = df_append["predicted_assignment_group"]

        if "Clasificación" in df_append.columns:
            matching_class_col = next((c for c in target_columns if c.lower() in ('categoría', 'categoria', 'clasificacion')), class_col_target)
            df_append[matching_class_col] = df_append["Clasificación"]

        if "opened_at" in df_append.columns and "fecha_asignacion" in target_columns:
            df_append["fecha_asignacion"] = df_append["opened_at"]

        target_columns_clean = [c.lstrip('\ufeff') for c in target_columns]
        aligned_df = pd.DataFrame()
        for orig_col, clean_col in zip(target_columns, target_columns_clean):
            if orig_col in df_append.columns:
                aligned_df[orig_col] = df_append[orig_col]
            elif clean_col in df_append.columns:
                aligned_df[orig_col] = df_append[clean_col]
            else:
                aligned_df[orig_col] = ""

        aligned_df.to_csv(target_file, mode='a', index=False, header=False, sep=delimiter, encoding=encoding)
        print(f"Successfully appended {len(aligned_df)} predicted rows to {target_file}")

    except Exception as e:
        print(f"Error appending predictions to {target_file}: {e}")


def _run_script(script_dir_path: str, script_name: str, desc: str, data_path: str = None):
    """Ejecuta un script de entrenamiento en su directorio objetivo de forma aislada."""
    full_path = os.path.normpath(os.path.join(script_dir_path, script_name))
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Script no encontrado: {full_path}")

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    if data_path:
        env['TRAINING_DATA_PATH'] = os.path.normpath(data_path)

    print(f"\n>> [{desc}] Iniciando: {script_name}...")
    t0 = time.time()
    result = subprocess.run([sys.executable, script_name], cwd=script_dir_path, env=env, check=True)
    elapsed = time.time() - t0
    print(f">> [{desc}] Finalizado con éxito en {elapsed:.1f}s.\n")
    return result


def train_incident_models(paradigms=None, architecture: str = 'all', data_path: str = None, force_sync: bool = False):
    """
    Entrena modelos para Incidentes según los paradigmas indicados.
    """
    if paradigms is None or 'all' in paradigms:
        paradigms = ['supervised', 'unsupervised', 'semisupervised']
    elif isinstance(paradigms, str):
        paradigms = [paradigms]

    print("\n" + "="*70)
    print("  INICIANDO ENTRENAMIENTO DE MODELOS DE INCIDENTES")
    print("="*70)

    # Auto-sincronización si el notebook fue editado
    if 'semisupervised' in paradigms:
        sync_all_notebooks(force=force_sync, ticket_type='incidentes')

    # 1. Supervisado
    if 'supervised' in paradigms:
        sup_dir = os.path.normpath(os.path.join(workspace_root, "Incidentes", "Entrenamiento", "Supervisado"))
        _run_script(sup_dir, "SupervisedMultipleFeatureIncidents.py", "Incidentes - Supervisado (LinearSVC)", data_path=data_path)

    # 2. No supervisado
    if 'unsupervised' in paradigms:
        unsup_dir = os.path.normpath(os.path.join(workspace_root, "Incidentes", "Entrenamiento", "No supervisado"))
        _run_script(unsup_dir, "UnsupervisedMultipleFeatureIncidents.py", "Incidentes - No Supervisado (DBSCAN)", data_path=data_path)

    # 3. Semisupervisado
    if 'semisupervised' in paradigms:
        semi_dir = os.path.normpath(os.path.join(workspace_root, "Incidentes", "Entrenamiento", "Semisupervisado"))
        if architecture in ('all', 'tfidf'):
            _run_script(semi_dir, "Entrenamiento_TFIDF_Incidentes.py", "Incidentes - Semisupervisado (TF-IDF Baseline)", data_path=data_path)
        if architecture in ('all', 'hnlp_mc'):
            _run_script(semi_dir, "Entrenamiento_HNLP_MC_Incidentes.py", "Incidentes - Semisupervisado (HNLP-MC Híbrido)", data_path=data_path)


def train_requirement_models(paradigms=None, architecture: str = 'all', data_path: str = None, force_sync: bool = False):
    """
    Entrena modelos para Requerimientos según los paradigmas indicados.
    """
    if paradigms is None or 'all' in paradigms:
        paradigms = ['supervised', 'unsupervised', 'semisupervised']
    elif isinstance(paradigms, str):
        paradigms = [paradigms]

    print("\n" + "="*70)
    print("  INICIANDO ENTRENAMIENTO DE MODELOS DE REQUERIMIENTOS")
    print("="*70)

    # Auto-sincronización si el notebook fue editado
    if 'semisupervised' in paradigms:
        sync_all_notebooks(force=force_sync, ticket_type='requerimientos')

    # 1. Supervisado
    if 'supervised' in paradigms:
        sup_dir = os.path.normpath(os.path.join(workspace_root, "Requerimientos", "Entrenamiento", "Supervisado"))
        _run_script(sup_dir, "SupervisedMultipleFeatureRequirements.py", "Requerimientos - Supervisado (LinearSVC)", data_path=data_path)

    # 2. No supervisado
    if 'unsupervised' in paradigms:
        unsup_dir = os.path.normpath(os.path.join(workspace_root, "Requerimientos", "Entrenamiento", "No supervisado"))
        _run_script(unsup_dir, "UnsupervisedMultipleFeatureRequirements.py", "Requerimientos - No Supervisado (DBSCAN)", data_path=data_path)

    # 3. Semisupervisado
    if 'semisupervised' in paradigms:
        semi_dir = os.path.normpath(os.path.join(workspace_root, "Requerimientos", "Entrenamiento", "Semisupervisado"))
        if architecture in ('all', 'tfidf'):
            _run_script(semi_dir, "Entrenamiento_TFIDF_Requerimientos.py", "Requerimientos - Semisupervisado (TF-IDF Baseline)", data_path=data_path)
        if architecture in ('all', 'hnlp_mc'):
            _run_script(semi_dir, "Entrenamiento_HNLP_MC_Requerimientos.py", "Requerimientos - Semisupervisado (HNLP-MC Híbrido)", data_path=data_path)


def train_all_models(architecture: str = 'all', data_path: str = None, force_sync: bool = False):
    """Entrena todos los modelos del sistema (Incidentes y Requerimientos, 8 modelos)."""
    print("\n" + "#"*70)
    print("  EJECUCIÓN INTEGRAL: ENTRENAMIENTO DE TODOS LOS MODELOS ML")
    print("#"*70)
    t_start = time.time()
    try:
        train_incident_models(paradigms=['supervised', 'unsupervised', 'semisupervised'], architecture=architecture, data_path=data_path, force_sync=force_sync)
        train_requirement_models(paradigms=['supervised', 'unsupervised', 'semisupervised'], architecture=architecture, data_path=data_path, force_sync=force_sync)
        total_time = time.time() - t_start
        print("\n" + "#"*70)
        print(f"  ENTRENAMIENTO COMPLETO FINALIZADO CON ÉXITO en {total_time:.1f}s")
        print("#"*70 + "\n")
    except Exception as e:
        print(f"\n[ERROR] Falló el entrenamiento integral de modelos: {e}", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Orquestador Central de Entrenamiento ML — Asignador ServiceNow",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '-t', '--ticket-type',
        choices=['all', 'incidentes', 'requerimientos', 'incidents', 'requirements'],
        default='all',
        help="Tipo de tickets a entrenar (por defecto: 'all')"
    )
    parser.add_argument(
        '-p', '--paradigm',
        choices=['all', 'supervised', 'unsupervised', 'semisupervised'],
        default='all',
        help="Paradigma de aprendizaje a entrenar (por defecto: 'all')"
    )
    parser.add_argument(
        '-a', '--architecture',
        choices=['all', 'tfidf', 'hnlp_mc'],
        default='all',
        help="Arquitectura específica para semisupervisado: 'tfidf', 'hnlp_mc', o 'all' (por defecto: 'all')"
    )
    parser.add_argument(
        '-d', '--data-path',
        default=None,
        help="Ruta específica a un archivo de dataset (ignora resolución automática por fecha de modificación)"
    )
    parser.add_argument(
        '--sync-notebooks',
        dest='sync_notebooks',
        action='store_true',
        help="Fuerza la sincronización de todos los cuadernos .ipynb hacia scripts .py"
    )
    parser.add_argument(
        '--all',
        dest='run_all',
        action='store_true',
        help="Fuerza el entrenamiento de los 8 modelos del sistema"
    )
    parser.add_argument(
        '--no-log',
        dest='no_log',
        action='store_true',
        help="Desactiva el registro en archivo de log dentro de Salida/"
    )

    args = parser.parse_args()

    ticket_type = 'all' if args.run_all else args.ticket_type.lower()
    paradigm = 'all' if args.run_all else args.paradigm.lower()
    architecture = 'all' if args.run_all else args.architecture.lower()
    force_sync = args.sync_notebooks
    data_path = args.data_path

    # Si se solicitó sincronización explícita única
    if force_sync and not args.run_all and paradigm == 'all' and ticket_type == 'all' and len(sys.argv) == 2:
        sync_all_notebooks(force=True)
        print("Sincronización manual de todos los cuadernos completada.")
        return

    def _execute():
        paradigms_list = ['supervised', 'unsupervised', 'semisupervised'] if paradigm == 'all' else [paradigm]

        if ticket_type in ('all',):
            train_all_models(architecture=architecture, data_path=data_path, force_sync=force_sync)
        elif ticket_type in ('incidentes', 'incidents'):
            train_incident_models(paradigms=paradigms_list, architecture=architecture, data_path=data_path, force_sync=force_sync)
        elif ticket_type in ('requerimientos', 'requirements'):
            train_requirement_models(paradigms=paradigms_list, architecture=architecture, data_path=data_path, force_sync=force_sync)

    if ExecutionLogger and not args.no_log:
        salida_dir = os.path.join(workspace_root, "Salida")
        with ExecutionLogger(base_dir=salida_dir, prefix="entrenamiento", archive_logs=True):
            _execute()
    else:
        _execute()


if __name__ == "__main__":
    main()
