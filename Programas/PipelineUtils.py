import glob
import os
import re
import shutil
import sys
import traceback
import time
import unicodedata
from datetime import datetime
import pandas as pd

# Cache global de stopwords para optimizar rendimiento
_SPANISH_STOPWORDS = None

# Mapeo ordenado de secuencias de mojibake y corrupción de codificación UTF-8 / Latin-1 / cp1252
MOJIBAKE_REPLACEMENTS = [
    # 1. Triple-encoded / Multi-layer mojibake
    ('Ã\x83Â¡', 'á'), ('Ã\x83Â©', 'é'), ('Ã\x83Â\xad', 'í'), ('Ã\x83Â­', 'í'), ('Ã\x83Â¬', 'í'),
    ('Ã\x83Â³', 'ó'), ('Ã\x83Âº', 'ú'), ('Ã\x83Â±', 'ñ'),
    ('Ã\x83Â\x81', 'Á'), ('Ã\x83Â‰', 'É'), ('Ã\x83Â\x8d', 'Í'), ('Ã\x83Â“', 'Ó'),
    ('Ã\x83Âš', 'Ú'), ('Ã\x83Â\x91', 'Ñ'),
    ('ÃƒÂ¡', 'á'), ('ÃƒÂ©', 'é'), ('ÃƒÂ\xad', 'í'), ('ÃƒÂ³', 'ó'), ('ÃƒÂº', 'ú'), ('ÃƒÂ±', 'ñ'),
    ('ÃƒÂ', 'Á'), ('ÃƒÂ‰', 'É'), ('ÃƒÂ“', 'Ó'), ('ÃƒÂš', 'Ú'), ('ÃƒÂ‘', 'Ñ'),
    ('Ã‚Â¿', '¿'), ('Ã‚Â¡', '¡'),

    # 2. Mayúsculas UTF-8 en cp1252 / secuencias de bytes crudos (deben ejecutarse antes de caracteres individuales)
    ('Ã\x81', 'Á'), ('Ã\x89', 'É'), ('Ã\x8d', 'Í'), ('Ã\x91', 'Ñ'), ('Ã\x92', 'Ó'), ('Ã\x93', 'Ó'),
    ('Ã\x9a', 'Ú'), ('Ã\x9c', 'Ü'),
    ('Ã‘', 'Ñ'), ('Ã“', 'Ó'), ('Ã‰', 'É'), ('Ãš', 'Ú'), ('Ãœ', 'Ü'),

    # 3. Minúsculas UTF-8 en Latin-1 / cp1252
    ('Ã¡', 'á'), ('Ã©', 'é'), ('Ã­', 'í'), ('Ã\xad', 'í'), ('Ã³', 'ó'), ('Ãº', 'ú'), ('Ã±', 'ñ'),
    ('Ã¼', 'ü'),
    ('Ã ', 'Á'), ('Ã ', 'Í'),

    # 4. Signos de puntuación y símbolos comunes
    ('Â¿', '¿'), ('Â¡', '¡'), ('Â°', '°'), ('Âº', 'º'), ('Âª', 'ª'),
    ('Â\x91', "'"), ('Â\x92', "'"), ('Â\x93', '"'), ('Â\x94', '"'), ('Â\x96', '-'), ('Â\x97', '-'),
    ('â€“', '–'), ('â€”', '—'), ('â€˜', "‘"), ('â€™', "’"), ('â€œ', '“'), ('â€\x9d', '”'), ('â€', '"'),
    ('â€¢', '•'), ('â€¦', '…'),
    ('Â\xa0', ' '), ('\xa0', ' '), ('Â ', ' '),

    # 5. Comillas y guiones aislados cp1252 (después de resolver pares con Ã)
    ('\x91', "'"), ('\x92', "'"), ('\x93', '"'), ('\x94', '"'), ('\x96', '-'), ('\x97', '-'),

    # 6. Marcadores BOM (Byte Order Mark) y mojibake UTF-8 decodificado como Latin-1
    ('ï»¿', ''), ('\ufeff', '')
]


def clean_encoding_text(text: str) -> str:
    """
    Corrige y normaliza secuencias corruptas de codificación (mojibake UTF-8 / Latin-1 / Windows-1252).
    Es completamente idempotente: si el texto ya está limpio en UTF-8 correcto,
    lo devuelve intacto sin alteración alguna.
    """
    if text is None or pd.isna(text):
        return ""

    t = str(text)
    if not t:
        return ""

    # 1. Bypass rápido si el texto no contiene secuencias de mojibake ni caracteres sospechosos
    has_mojibake = any(c in t for c in (
        'Ã', 'Â', 'â', 'ã', 'ƒ', '\x81', '\x83', '\x89', '\x8d', '\x91', '\x92',
        '\x93', '\x94', '\x96', '\x97', '\x9a', '\x9c', '\xa0', '\xad', 'ï', '\ufeff'
    ))
    if not has_mojibake:
        return t

    # 2. Aplicar reemplazos ordenados para secuencias específicas y triples
    for bad, good in MOJIBAKE_REPLACEMENTS:
        if bad in t:
            t = t.replace(bad, good)

    # 3. Si aún quedan secuencias candidatas, intentar decodificación utf-8 de bloques
    if any(c in t for c in ('Ã', 'Â', 'â')):
        try:
            candidate = t.encode('latin-1').decode('utf-8')
            t = candidate
        except (UnicodeEncodeError, UnicodeDecodeError):
            def _sub_chunk(m):
                chunk = m.group(0)
                try:
                    return chunk.encode('latin-1').decode('utf-8')
                except Exception:
                    return chunk
            t = re.sub(r'[\xc2\xc3][\x80-\xbf]', _sub_chunk, t)

    # 4. Limpieza residual de caracteres de control cp1252 o Â huérfana
    t = re.sub(r'Â(?=[\s\.,;:\-_/\(\)])', '', t)
    t = re.sub(r'[\x80-\x9f]', '', t)

    return t


def clean_dataframe_encodings(df: pd.DataFrame, columns: list = None) -> tuple:
    """
    Recorre las columnas de texto de un DataFrame y aplica clean_encoding_text.
    Calcula cuántos registros fueron modificados.

    Retorna: (df_limpio, total_modificaciones)
    Si total_modificaciones == 0, significa que el dataset ya estaba limpio.
    """
    if df is None or df.empty:
        return df, 0

    df_clean = df.copy()
    # Sanitizar nombres de columnas eliminando posibles marcas BOM, comillas y espacios residuales
    df_clean.columns = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)) for c in df_clean.columns]
    if columns is None:
        columns = list(df_clean.select_dtypes(include=['object', 'string']).columns)

    total_changes = 0
    for col in columns:
        if col not in df_clean.columns:
            continue
        original_col = df_clean[col].astype(str)
        cleaned_col = df_clean[col].apply(clean_encoding_text)
        diff_mask = (original_col != cleaned_col) & df_clean[col].notna()
        changes = int(diff_mask.sum())
        if changes > 0:
            df_clean[col] = cleaned_col
            total_changes += changes

    return df_clean, total_changes


def detect_csv_separator(filepath: str, default: str = ';') -> str:
    """Detecta si el archivo utiliza coma (',') o punto y coma (';') como separador."""
    try:
        with open(filepath, 'r', encoding='latin-1', errors='ignore') as f:
            first_line = f.readline()
        count_semi = first_line.count(';')
        count_comma = first_line.count(',')
        if count_semi > count_comma:
            return ';'
        elif count_comma > 0:
            return ','
    except Exception:
        pass
    return default


def clean_dataset_encodings(file_path: str, output_path: str = None, sep: str = None,
                            text_columns: list = None, in_place: bool = False,
                            verbose: bool = True) -> pd.DataFrame:
    """
    Carga un archivo CSV de entrenamiento o inferencia, detecta su codificación y separador de origen,
    corrige mojibake y secuencias UTF-8 dañadas de forma idempotente.

    - Si el dataset ya está limpio, NO altera el archivo original y devuelve el DataFrame tal cual.
    - Si detecta datos corruptos y (in_place=True o output_path especificado), guarda la versión
      corregida en codificación 'utf-8-sig'.

    Retorna el DataFrame limpio.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No se encontró el archivo de dataset: {file_path}")

    if sep is None:
        sep = detect_csv_separator(file_path)

    encodings_to_try = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    df = None
    for enc in encodings_to_try:
        try:
            df = pd.read_csv(file_path, sep=sep, encoding=enc, dtype=str, on_bad_lines='skip', engine='python')
            break
        except Exception:
            continue

    if df is None:
        raise ValueError(f"No fue posible leer el archivo {file_path} con las codificaciones habituales.")

    df_clean, total_changes = clean_dataframe_encodings(df, columns=text_columns)
    target_save_path = output_path if output_path else (file_path if in_place else None)

    if total_changes == 0:
        if verbose:
            print(f"[PipelineUtils] Dataset ya verificado y limpio (0 modificaciones en {os.path.basename(file_path)}).")
    else:
        if verbose:
            print(f"[PipelineUtils] Se limpiaron {total_changes} registros con mojibake/UTF-8 corrupto en {os.path.basename(file_path)}.")
        if target_save_path:
            import csv
            try:
                df_clean.to_csv(target_save_path, sep=sep, index=False, encoding='latin-1', quoting=csv.QUOTE_MINIMAL)
            except UnicodeEncodeError:
                df_clean.to_csv(target_save_path, sep=sep, index=False, encoding='utf-8', quoting=csv.QUOTE_MINIMAL)
            if verbose:
                print(f"[PipelineUtils] Archivo guardado correctamente en: {target_save_path}")

    return df_clean


def clean_all_input_csv_files(directories: list = None, verbose: bool = True) -> dict:
    """
    Escanea y limpia todos los archivos CSV en las carpetas de entrada y configuración del sistema.
    Corrige problemas de codificación y sobrescribe los archivos dañados con UTF-8 corregido.
    Si el archivo ya está limpio, no lo modifica.

    Directorios predeterminados:
      - 'Entrada'
      - 'Requerimientos/Entrenamiento/Datos'
      - 'Incidentes/Entrenamiento/Datos'
      - 'Especificaciones'

    Retorna un diccionario: {ruta_archivo: cantidad_de_cambios}
    """
    if directories is None:
        directories = [
            "Entrada",
            os.path.join("Requerimientos", "Entrenamiento", "Datos"),
            os.path.join("Incidentes", "Entrenamiento", "Datos"),
            "Especificaciones"
        ]

    results = {}
    if verbose:
        print("\n" + "="*60)
        print("  SANEAMIENTO Y CORRECCIÓN DE ARCHIVOS CSV DE ENTRADA")
        print("="*60)

    total_files = 0
    total_cleaned = 0

    for d in directories:
        if not os.path.exists(d):
            continue

        csv_files = glob.glob(os.path.join(d, "*.csv"))
        for csv_f in csv_files:
            total_files += 1
            try:
                sep = detect_csv_separator(csv_f)
                encodings_to_try = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
                df = None
                for enc in encodings_to_try:
                    try:
                        df = pd.read_csv(csv_f, sep=sep, encoding=enc, dtype=str, on_bad_lines='skip', engine='python')
                        break
                    except Exception:
                        continue

                if df is None:
                    continue

                df_clean, changes = clean_dataframe_encodings(df)
                results[csv_f] = changes

                if changes > 0:
                    import csv
                    try:
                        df_clean.to_csv(csv_f, sep=sep, index=False, encoding='latin-1', quoting=csv.QUOTE_MINIMAL)
                    except UnicodeEncodeError:
                        df_clean.to_csv(csv_f, sep=sep, index=False, encoding='utf-8', quoting=csv.QUOTE_MINIMAL)
                    total_cleaned += 1
                    if verbose:
                        print(f"  [CORREGIDO] {csv_f} -> {changes} valores corregidos.")
                else:
                    if verbose:
                        print(f"  [OK / LIMPIO] {csv_f}")

            except Exception as e:
                if verbose:
                    print(f"  [ERROR] No se pudo procesar {csv_f}: {e}")

    if verbose:
        print("="*60)
        print(f"Resumen: {total_files} archivos inspeccionados, {total_cleaned} corregidos.")
        print("="*60 + "\n")

    return results



def get_spanish_stopwords() -> set:
    """Obtiene y cachea las stopwords en español de NLTK."""
    global _SPANISH_STOPWORDS
    if _SPANISH_STOPWORDS is None:
        try:
            import nltk
            from nltk.corpus import stopwords as nltk_stopwords
            nltk.download('stopwords', quiet=True)
            _SPANISH_STOPWORDS = set(nltk_stopwords.words('spanish'))
        except Exception:
            _SPANISH_STOPWORDS = set()
    return _SPANISH_STOPWORDS


def clean_and_deidentify_text(text, remove_stopwords: bool = True) -> str:
    r"""
    Desidentificación y Normalización de Características Operacionales (Single Source of Truth):
    0. Corrige previamente cualquier mojibake o daño de codificación UTF-8/Latin-1.
    1. Normaliza acentos y caracteres especiales (NFKD a ASCII).
    2. Enmascara PII directo (URLs -> 'url', emails -> 'email', fechas -> 'fecha', números largos -> 'num_largo').
    3. Remueve caracteres no alfanuméricos.
    4. Remueve tokens numéricos puros (\b\d+\b) y códigos alfanuméricos con dígitos.
    5. Remueve tokens residuales de 1 a 2 caracteres.
    6. Opcionalmente filtra stopwords en español.
    """
    if text is None or pd.isna(text):
        return ""

    # Paso 0: Sanitización de codificación y corrección de mojibake previa
    t = clean_encoding_text(str(text)).lower()
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode('utf-8', errors='ignore')

    # Desidentificación y normalización de PII
    t = re.sub(r'(https?://\S+|www\.\S+)', ' url ', t)
    t = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', ' email ', t)
    t = re.sub(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', ' fecha ', t)
    t = re.sub(r'\b\d{7,}\b', ' num_largo ', t)

    # Remoción de signos y ruido residual
    t = re.sub(r'[^a-zA-Z0-9\s]', ' ', t)
    t = re.sub(r'\b\d+\b', ' ', t)
    t = re.sub(r'\b[a-z]*\d+[a-z0-9]*\b', ' ', t)
    t = re.sub(r'\b\w{1,2}\b', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()

    if remove_stopwords:
        sw = get_spanish_stopwords()
        tokens = [token for token in t.split() if token not in sw]
        return ' '.join(tokens)

    return t


def fix_newlines_inside_quotes(text: str, replacement: str = " ") -> str:
    """
    Reemplaza saltos de línea (\n y \r) solo cuando ocurren dentro de comillas dobles.
    - Mantiene el resto del contenido intacto.
    - Respeta comillas escapadas CSV: "" dentro de un campo.
    - replacement: qué poner donde había saltos dentro de comillas (por defecto un espacio).
    """
    result = []
    in_quotes = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == '"':
            # Si estamos en un campo con comillas y vemos '""', es una comilla escapada literal.
            if in_quotes and i + 1 < n and text[i + 1] == '"':
                result.append('""')
                i += 2
                continue
            # Entrar/salir de comillas
            in_quotes = not in_quotes
            result.append('"')
            i += 1
            continue

        # Si estamos dentro de comillas y aparece salto(s) de línea, reemplazar por 'replacement'
        if in_quotes and ch in ('\n', '\r'):
            # Manejar CRLF como unidad
            if ch == '\r' and i + 1 < n and text[i + 1] == '\n':
                i += 2
            else:
                i += 1
            result.append(replacement)
            continue

        # Caso normal
        result.append(ch)
        i += 1

    return ''.join(result)


def replace_commas_outside_quotes(text: str, to_separator: str = ';') -> str:
    """
    Reemplaza comas ',' por 'to_separator' SOLO cuando están fuera de comillas dobles.
    Respeta comillas escapadas CSV: "" dentro de un campo.
    """
    result = []
    in_quotes = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch == '"':
            # Manejar comillas escapadas dentro de comillas
            if in_quotes and i + 1 < n and text[i + 1] == '"':
                result.append('""')
                i += 2
                continue
            in_quotes = not in_quotes
            result.append('"')
            i += 1
            continue

        if not in_quotes and ch == ',':
            result.append(to_separator)
            i += 1
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


def archive_previous_files(base_dir: str, pattern: str, exclude_files: list = None):
    """
    Mueve los archivos que coincidan con 'pattern' en la raíz de 'base_dir' hacia subcarpetas de fecha 'base_dir/YYYY-MM-DD/'.
    """
    if not os.path.exists(base_dir):
        return

    if exclude_files is None:
        exclude_files = ["reporte_detalle_asignaciones.csv"]
    elif "reporte_detalle_asignaciones.csv" not in exclude_files:
        exclude_files.append("reporte_detalle_asignaciones.csv")

    active_log_path = None
    if hasattr(sys.stdout, 'log_file') and getattr(sys.stdout, 'log_file', None):
        try:
            active_log_path = os.path.abspath(sys.stdout.log_file.name)
        except Exception:
            pass

    search_path = os.path.join(base_dir, pattern)
    target_files = [f for f in glob.glob(search_path) if os.path.isfile(f)]
    for filepath in target_files:
        filename = os.path.basename(filepath)
        if filename in exclude_files:
            continue
        if active_log_path and os.path.abspath(filepath) == active_log_path:
            continue  # Omitir el archivo de log actualmente en uso
        mtime = os.path.getmtime(filepath)
        date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
        target_dir = os.path.join(base_dir, date_str)
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, filename)
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(os.path.join(target_dir, f"{base}_{counter}{ext}")):
                counter += 1
            dest_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
        try:
            shutil.move(filepath, dest_path)
            print(f"Archived previous execution: {filename} -> {date_str}/")
        except Exception as e:
            print(f"Could not archive {filepath}: {e}")


def get_output_path_date(prefix: str, base_dir: str = "Entrada", timing: str = None, ext: str = ".csv", archive_previous: bool = True) -> tuple:
    """
    Archiva archivos previos coincidentes en la raíz de base_dir hacia base_dir/YYYY-MM-DD/,
    luego devuelve la nueva ruta directamente en la raíz de base_dir y la cadena de tiempo.
    """
    now = datetime.now()
    if timing is None:
        timing = now.strftime('%Y-%m-%d_%H-%M-%S')

    if not ext.startswith("."):
        ext = "." + ext

    os.makedirs(base_dir, exist_ok=True)

    if archive_previous:
        archive_previous_files(base_dir, f"{prefix}_*{ext}")

    output_path = os.path.join(base_dir, f"{prefix}_{timing}{ext}")
    return output_path, timing


def delete_unprocessed_input_files(base_dir: str = "Entrada", filenames: list = None) -> list:
    """
    Elimina directamente de base_dir los archivos residuales de entrada sin procesar
    (por defecto 'incident.csv' y 'sc_req_item.csv') antes de una nueva descarga,
    evitando que ejecuciones posteriores utilicen entradas previas obsoletas si la descarga falla.
    Devuelve la lista de archivos eliminados.
    """
    if filenames is None:
        filenames = ["incident.csv", "sc_req_item.csv"]

    deleted = []
    for filename in filenames:
        filepath = os.path.join(base_dir, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                deleted.append(filepath)
                print(f"[LIMPIEZA] Archivo de entrada residual eliminado preventivamente: {filepath}")
            except Exception as e:
                print(f"[ADVERTENCIA] No se pudo eliminar archivo residual {filepath}: {e}")
    return deleted


def check_file_freshness(filepath: str, min_mtime: float = None, max_age_seconds: float = None, tolerance_seconds: float = 15.0) -> tuple:
    """
    Verifica si un archivo existe y fue modificado recientemente.

    Parámetros:
      - filepath: Ruta absoluta o relativa al archivo.
      - min_mtime: Timestamp mínimo admisible (ej. inicio del ciclo de descarga).
      - max_age_seconds: Antigüedad máxima permitida en segundos desde el momento actual.
      - tolerance_seconds: Margen de tolerancia para desfasajes de reloj o búferes de escritura.

    Devuelve:
      - (True, "Mensaje de éxito") si el archivo es reciente.
      - (False, "Razón del fallo") si el archivo no existe o es demasiado antiguo.
    """
    if not os.path.exists(filepath):
        return False, f"El archivo '{filepath}' no existe."

    try:
        file_mtime = os.path.getmtime(filepath)
    except Exception as e:
        return False, f"No se pudo consultar timestamp de '{filepath}': {e}"

    file_time_str = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')

    # 1. Comprobar contra min_mtime si fue especificado
    if min_mtime is not None:
        effective_min = min_mtime - tolerance_seconds
        if file_mtime < effective_min:
            min_time_str = datetime.fromtimestamp(min_mtime).strftime('%Y-%m-%d %H:%M:%S')
            return False, (
                f"El archivo '{filepath}' es antiguo (timestamp: {file_time_str} < mínimo esperado: {min_time_str}). "
                f"Se infiere que la descarga falló o se reutilizó un archivo previo."
            )

    # 2. Comprobar contra max_age_seconds si fue especificado
    if max_age_seconds is not None and max_age_seconds > 0:
        age_seconds = time.time() - file_mtime
        if age_seconds > (max_age_seconds + tolerance_seconds):
            return False, (
                f"El archivo '{filepath}' supera la antigüedad máxima permitida "
                f"({int(age_seconds)}s > {int(max_age_seconds)}s, última modificación: {file_time_str}). "
                f"Se infiere que no fue descargado en esta ejecución."
            )

    return True, f"Archivo reciente y válido (timestamp: {file_time_str})."


def clean_csv_file(input_path: str, output_path: str, encoding: str = "utf-8",
                   replacement: str = " ", change_separator: bool = True,
                   new_separator: str = ';'):
    """
    Lee un archivo completo (CSV o texto), corrige saltos de línea dentro de comillas dobles,
    sanea problemas de codificación/mojibake y opcionalmente cambia los separadores de coma a 'new_separator' fuera de comillas.
    Escribe el resultado en output_path.
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    content = None
    if encoding and encoding.lower() in ('utf-8-sig', 'utf-8'):
        encodings_to_try = [encoding, 'utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    elif encoding:
        encodings_to_try = ['utf-8-sig', encoding, 'utf-8', 'latin-1', 'cp1252']
    else:
        encodings_to_try = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    seen = set()
    encs = [x for x in encodings_to_try if not (x in seen or seen.add(x))]

    for enc in encs:
        try:
            with open(input_path, 'r', encoding=enc, newline='') as f:
                content = f.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        raise ValueError(f"No fue posible leer {input_path} con las codificaciones especificadas.")

    # 0) Descartar BOM inicial si quedó residual
    if content.startswith('\ufeff'):
        content = content[1:]
    elif content.startswith('ï»¿'):
        content = content[3:]

    # 1) Corregir saltos de línea dentro de comillas
    cleaned = fix_newlines_inside_quotes(content, replacement=replacement)

    # 2) Cambiar separador fuera de comillas
    if change_separator:
        cleaned = replace_commas_outside_quotes(cleaned, to_separator=new_separator)

    # 3) Saneamiento de secuencias de codificación mojibake
    cleaned = clean_encoding_text(cleaned)

    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        f.write(cleaned)



def clean_csv_text(text: str, replacement: str = " ", change_separator: bool = True,
                   new_separator: str = ';') -> str:
    """Procesa una cadena de texto en memoria."""
    cleaned = fix_newlines_inside_quotes(text, replacement=replacement)
    if change_separator:
        cleaned = replace_commas_outside_quotes(cleaned, to_separator=new_separator)
    return cleaned


def get_windows_date_format() -> str:
    """
    Obtiene el formato de fecha corta configurado en el sistema Windows (sShortDate)
    y lo traduce a un formato compatible con datetime de Python (por ejemplo, '%Y-%m-%d').
    Si no está en Windows o falla, retorna '%Y-%m-%d' por defecto.
    """
    import platform
    default_format = '%Y-%m-%d'
    if platform.system() != 'Windows':
        return default_format

    try:
        import winreg
        key_path = r"Control Panel\International"
        value_name = "sShortDate"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            if val:
                fmt = str(val)
                # Convertir formato de registro a formato de python strftime
                # Reemplazar año
                if 'yyyy' in fmt:
                    fmt = fmt.replace('yyyy', '%Y')
                elif 'yy' in fmt:
                    fmt = fmt.replace('yy', '%y')
                
                # Reemplazar mes
                if 'MM' in fmt:
                    fmt = fmt.replace('MM', '%m')
                else:
                    fmt = fmt.replace('M', '%m')
                
                # Reemplazar día
                if 'dd' in fmt:
                    fmt = fmt.replace('dd', '%d')
                else:
                    fmt = fmt.replace('d', '%d')
                
                fmt = fmt.strip("'\"")
                return fmt
    except Exception as e:
        print(f"Warning: could not get Windows short date format: {e}")

    return default_format


class TeeStream:
    """Duplica las salidas de un stream (sys.stdout/sys.stderr) hacia el stream original y un archivo de log."""
    def __init__(self, original_stream, log_file):
        self.original_stream = original_stream
        self.log_file = log_file

    def write(self, message):
        if self.original_stream:
            try:
                self.original_stream.write(message)
            except Exception:
                pass
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.write(message)
                self.log_file.flush()
            except Exception:
                pass

    def flush(self):
        if self.original_stream:
            try:
                self.original_stream.flush()
            except Exception:
                pass
        if self.log_file and not self.log_file.closed:
            try:
                self.log_file.flush()
            except Exception:
                pass

    def isatty(self):
        return getattr(self.original_stream, 'isatty', lambda: False)()


class ExecutionLogger:
    """
    Gestor de logs por ejecución.
    Archiva logs previos en base_dir hacia base_dir/YYYY-MM-DD/, abre un nuevo archivo de log
    con marca de tiempo y captura stdout y stderr.
    """
    def __init__(self, base_dir: str = "Salida", prefix: str = "ejecucion", archive_logs: bool = True):
        self.base_dir = base_dir
        self.prefix = prefix
        self.archive_logs = archive_logs
        self.log_file = None
        self.log_path = None
        self._orig_stdout = None
        self._orig_stderr = None

    def start(self):
        if self.archive_logs:
            archive_previous_files(self.base_dir, "*.log")
        
        now = datetime.now()
        timing = now.strftime('%Y-%m-%d_%H-%M-%S')
        os.makedirs(self.base_dir, exist_ok=True)
        self.log_path = os.path.join(self.base_dir, f"{self.prefix}_{timing}.log")
        
        self.log_file = open(self.log_path, 'a', encoding='utf-8')
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        
        sys.stdout = TeeStream(self._orig_stdout, self.log_file)
        sys.stderr = TeeStream(self._orig_stderr, self.log_file)
        
        print(f"=== INICIO DE EJECUCIÓN [{now.strftime('%Y-%m-%d %H:%M:%S')}] ===")
        print(f"Archivo de log en: {self.log_path}\n")
        return self.log_path

    def stop(self):
        if self._orig_stdout:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n=== FIN DE EJECUCIÓN [{now_str}] ===")
            sys.stdout = self._orig_stdout
            sys.stderr = self._orig_stderr
            self._orig_stdout = None
            self._orig_stderr = None
        if self.log_file and not self.log_file.closed:
            self.log_file.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            print("\n[EXCEPCIÓN NO CONTROLADA CAPTURADA EN LOG]", file=sys.stderr)
            traceback.print_exception(exc_type, exc_val, exc_tb, file=sys.stderr)
        self.stop()
        return False


def generate_assignation_detail_report(df: pd.DataFrame, ticket_type: str, timing: str = None, base_dir: str = "Salida") -> str:
    """
    Genera o anexa registros al reporte acumulativo final 'Salida/reporte_detalle_asignaciones.csv'.
    Mantiene 7 columnas exactas:
    Ticket identification;Ticket type;Assignation timestamp;Description;Predicted group;Previous person assigned;Person assigned;Predicted end date
    """
    if df is None or len(df) == 0:
        return ""

    os.makedirs(base_dir, exist_ok=True)
    report_path = os.path.join(base_dir, "reporte_detalle_asignaciones.csv")

    win_fmt = get_windows_date_format()
    dt_fmt = f"{win_fmt} %H:%M:%S"
    now_str = datetime.now().strftime(dt_fmt)

    # 1. Ticket identification
    num_col = next((c for c in ['number', 'Number', 'id', 'ticket_id'] if c in df.columns), None)
    if not num_col:
        print(f"Advertencia: No se encontró columna de identificación de ticket en df de {ticket_type}.")
        return ""

    # 2. Description
    desc_series = pd.Series([""] * len(df))
    for desc_col in ['description', 'Description', 'short_description', 'Short description', 'u_description', 'desc_core', 'texto_limpio']:
        if desc_col in df.columns:
            desc_series = df[desc_col]
            break

    # 3. Predicted group
    predicted_group_series = df.get('predicted_assignment_group', df.get('assignment_group', df.get('Clasificación', pd.Series([""] * len(df)))))

    # 4. Previous person assigned
    if 'original_assigned_to' in df.columns:
        prev_assigned_series = df['original_assigned_to']
    elif 'assigned_to' in df.columns and 'predicted_assigned_to' in df.columns:
        prev_assigned_series = df['assigned_to']
    else:
        prev_assigned_series = df.get('assigned_to', pd.Series([""] * len(df)))

    # 5. Person assigned
    person_assigned_series = df.get('predicted_assigned_to', df.get('assigned_to', pd.Series([""] * len(df))))

    # 6. Predicted end date
    end_date_series = pd.Series([""] * len(df))
    for col_candidate in ['u_fecha_limite', 'fecha_resolucion', 'due_date', 'predicted_end_date']:
        if col_candidate in df.columns:
            end_date_series = df[col_candidate]
            break

    def clean_empty(val):
        if pd.isna(val) or val is None:
            return ""
        s = str(val).strip()
        if s.lower() in ('nan', 'none', 'null'):
            return ""
        return s

    def clean_text_field(val):
        s = clean_empty(val)
        if not s:
            return ""
        # Reemplazar saltos de línea y tabulaciones para preservar formato CSV limpio
        s = s.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
        return ' '.join(s.split())

    def format_date_val(val):
        clean_val = clean_empty(val)
        if not clean_val:
            return ""
        formats_to_try = (
            dt_fmt,
            win_fmt,
            '%Y-%m-%d %H:%M:%S',
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d',
            '%d/%m/%Y'
        )
        for fmt in formats_to_try:
            try:
                dt = datetime.strptime(clean_val, fmt)
                return dt.strftime(dt_fmt)
            except ValueError:
                continue
        return clean_val

    report_df = pd.DataFrame()
    report_df['Ticket identification'] = df[num_col].apply(clean_empty)
    report_df['Ticket type'] = ticket_type
    report_df['Assignation timestamp'] = now_str
    report_df['Description'] = desc_series.apply(clean_text_field)
    report_df['Predicted group'] = predicted_group_series.apply(clean_empty)
    report_df['Previous person assigned'] = prev_assigned_series.apply(clean_empty)
    report_df['Person assigned'] = person_assigned_series.apply(clean_empty)
    report_df['Predicted end date'] = end_date_series.apply(format_date_val)
    report_df['Model type'] = df.get('prediction_model_type', pd.Series([""] * len(df))).apply(clean_empty)
    report_df['Model name'] = df.get('prediction_model_name', pd.Series([""] * len(df))).apply(clean_empty)

    # Verificar si el archivo ya existe y tiene contenido
    file_exists = os.path.exists(report_path) and os.path.getsize(report_path) > 0

    report_df.to_csv(report_path, mode='a', sep=';', index=False, header=not file_exists, encoding='utf-8-sig')
    print(f"Reporte detallado acumulativo actualizado en: {report_path}")
    return report_path


def get_retry_dataframe_from_assignment_report(ticket_ids: list, ticket_type: str = None, base_dir: str = "Salida") -> pd.DataFrame:
    """
    Busca los ticket_ids en 'Salida/reporte_detalle_asignaciones.csv' (tomando el registro
    más reciente para cada uno) y construye un DataFrame estandarizado con las columnas:
    ['number', 'predicted_assigned_to', 'fecha_resolucion', 'predicted_assignment_group', 'original_assigned_to', 'Ticket type']
    listo para ser procesado por las funciones de actualización RPA.
    """
    if not ticket_ids:
        return pd.DataFrame()

    report_path = os.path.join(base_dir, "reporte_detalle_asignaciones.csv")
    if not os.path.exists(report_path):
        print(f"[VERIFICACIÓN] No se encontró el reporte histórico '{report_path}'.")
        return pd.DataFrame()

    df_rep = None
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            df_rep = pd.read_csv(report_path, sep=';', encoding=enc, dtype=str)
            break
        except Exception:
            continue
    if df_rep is None:
        try:
            df_rep = pd.read_csv(report_path, sep=';', encoding='latin-1', dtype=str)
        except Exception as e:
            print(f"[VERIFICACIÓN] Error al leer '{report_path}': {e}")
            return pd.DataFrame()

    # Normalizar columnas
    df_rep.columns = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df_rep.columns]

    num_col = next((c for c in ['Ticket identification', 'number', 'Number', 'id'] if c in df_rep.columns), None)
    assign_col = next((c for c in ['Person assigned', 'predicted_assigned_to', 'assigned_to'] if c in df_rep.columns), None)

    if not num_col or not assign_col:
        print(f"[VERIFICACIÓN] Columnas clave no encontradas en '{report_path}'.")
        return pd.DataFrame()

    # Normalizar IDs para búsqueda case-insensitive y sin espacios
    target_ids_set = {str(t).strip().upper() for t in ticket_ids if t and pd.notna(t)}
    df_rep['_id_norm'] = df_rep[num_col].astype(str).str.strip().str.upper()

    matching_df = df_rep[df_rep['_id_norm'].isin(target_ids_set)].copy()

    if ticket_type:
        type_col = next((c for c in ['Ticket type', 'ticket_type'] if c in matching_df.columns), None)
        if type_col:
            matching_df = matching_df[matching_df[type_col].astype(str).str.lower().str.contains(ticket_type.lower())]

    if matching_df.empty:
        print(f"[VERIFICACIÓN] No se encontraron registros coincidentes para los tickets en '{report_path}'.")
        return pd.DataFrame()

    # Tomar el último registro de cada ticket (el más reciente de la última ejecución)
    matching_df = matching_df.drop_duplicates(subset=['_id_norm'], keep='last')

    res_df = pd.DataFrame()
    res_df['number'] = matching_df[num_col]
    res_df['predicted_assigned_to'] = matching_df[assign_col]

    # fecha_resolucion / due_date
    date_col = next((c for c in ['Predicted end date', 'fecha_resolucion', 'due_date'] if c in matching_df.columns), None)
    if date_col:
        res_df['fecha_resolucion'] = matching_df[date_col].fillna('')
    else:
        res_df['fecha_resolucion'] = ""

    # Grupo asignado
    group_col = next((c for c in ['Predicted group', 'predicted_assignment_group', 'assignment_group'] if c in matching_df.columns), None)
    if group_col:
        res_df['predicted_assignment_group'] = matching_df[group_col].fillna('')

    # Asignado previo
    orig_col = next((c for c in ['Previous person assigned', 'original_assigned_to'] if c in matching_df.columns), None)
    if orig_col:
        res_df['original_assigned_to'] = matching_df[orig_col].fillna('')

    type_col = next((c for c in ['Ticket type', 'ticket_type'] if c in matching_df.columns), None)
    if type_col:
        res_df['Ticket type'] = matching_df[type_col]

    return res_df


def get_latest_training_dataset(ticket_type: str, kind: str = 'preparados',
                                explicit_path: str = None,
                                base_dir: str = None,
                                use_previous_version: bool = False,
                                verbose: bool = True) -> str:
    """
    Resuelve dinámicamente el archivo de dataset de entrenamiento, priorizando la fecha
    y hora de modificación (os.path.getmtime) como discriminante principal.

    - ticket_type: 'incidentes' (o 'incidents') | 'requerimientos' (o 'requirements')
    - kind: 'preparados' (*Preparados*.csv), 'categorizados' (*Categorizados_v*.csv),
            'depurado' (*depurado*.csv), o cualquier patrón específico.
    - explicit_path: Ruta forzada específica (o leída de entorno TRAINING_DATA_PATH).
    - use_previous_version: Si es True y hay múltiples versiones (ej. en Categorizados donde la última
                            recibe las nuevas predicciones activas), selecciona la versión previa inmediatamente anterior.
    """
    # 1. Verificar si hay ruta explícita o variable de entorno
    if not explicit_path:
        explicit_path = os.environ.get('TRAINING_DATA_PATH', '').strip()

    if explicit_path:
        if os.path.exists(explicit_path):
            if verbose:
                print(f"[DatasetResolver] Usando dataset explícito: {explicit_path}")
            return os.path.normpath(explicit_path)
        else:
            print(f"[DatasetResolver] Advertencia: la ruta explícita '{explicit_path}' no existe. Buscando dinámicamente...")

    # 2. Determinar directorio base según ticket_type
    ticket_lower = str(ticket_type).lower()
    is_incidents = 'incid' in ticket_lower

    if base_dir is None:
        workspace = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        domain_folder = "Incidentes" if is_incidents else "Requerimientos"
        base_dir = os.path.join(workspace, domain_folder, "Entrenamiento", "Datos")

    if not os.path.exists(base_dir):
        domain_folder = "Incidentes" if is_incidents else "Requerimientos"
        base_dir = os.path.join(domain_folder, "Entrenamiento", "Datos")

    if not os.path.exists(base_dir):
        raise FileNotFoundError(f"Directorio de datos de entrenamiento no encontrado: {base_dir}")

    # 3. Definir patrones de búsqueda según 'kind'
    kind_lower = str(kind).lower()
    if 'prep' in kind_lower:
        patterns = ["*Preparados*.csv", "*preparados*.csv"]
    elif 'categ' in kind_lower:
        patterns = ["*Categorizados_v*.csv", "*categorizados_v*.csv", "*Categorizados*.csv"]
    elif 'depur' in kind_lower:
        patterns = ["*depurado*.csv", "*Depurado*.csv"]
    else:
        patterns = [f"*{kind}*.csv", f"{kind}"]

    candidates = []
    for pat in patterns:
        search_path = os.path.join(base_dir, pat)
        candidates.extend(glob.glob(search_path))

    candidates = list(set(os.path.normpath(c) for c in candidates if os.path.isfile(c)))

    if not candidates:
        all_csvs = glob.glob(os.path.join(base_dir, "*.csv"))
        candidates = [os.path.normpath(c) for c in all_csvs if os.path.isfile(c)]

    if not candidates:
        raise FileNotFoundError(f"No se encontró ningún archivo CSV de entrenamiento en: {base_dir}")

    def _extract_v(filepath):
        fname = os.path.basename(filepath)
        m = re.search(r"_v(\d+)\.csv$", fname, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    # 4. Ordenar con prioridad principal en FECHA DE MODIFICACIÓN (getmtime descendente)
    # y secundariamente por número de versión
    candidates.sort(key=lambda f: (os.path.getmtime(f), _extract_v(f)), reverse=True)

    # 5. Manejar opción de versión previa para datasets categorizados
    if use_previous_version and len(candidates) > 1 and 'categ' in kind_lower:
        by_version = sorted(candidates, key=lambda f: _extract_v(f), reverse=True)
        if _extract_v(by_version[0]) > 0:
            selected_file = by_version[1]
            if verbose:
                print(f"[DatasetResolver] Seleccionada versión anterior consolidada: {os.path.basename(selected_file)}")
        else:
            selected_file = candidates[1]
    else:
        selected_file = candidates[0]

    if verbose:
        mtime_dt = datetime.fromtimestamp(os.path.getmtime(selected_file)).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[DatasetResolver] Dataset resuelto dinámicamente ({kind}): {os.path.basename(selected_file)} [mtime: {mtime_dt}]")

    return selected_file


