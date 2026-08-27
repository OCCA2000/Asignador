import glob
import os
import shutil
import sys
import traceback
from datetime import datetime


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


def archive_previous_files(base_dir: str, pattern: str):
    """
    Mueve los archivos que coincidan con 'pattern' en la raíz de 'base_dir' hacia subcarpetas de fecha 'base_dir/YYYY-MM-DD/'.
    """
    if not os.path.exists(base_dir):
        return

    active_log_path = None
    if hasattr(sys.stdout, 'log_file') and getattr(sys.stdout, 'log_file', None):
        try:
            active_log_path = os.path.abspath(sys.stdout.log_file.name)
        except Exception:
            pass

    search_path = os.path.join(base_dir, pattern)
    target_files = [f for f in glob.glob(search_path) if os.path.isfile(f)]
    for filepath in target_files:
        if active_log_path and os.path.abspath(filepath) == active_log_path:
            continue  # Omitir el archivo de log actualmente en uso
        filename = os.path.basename(filepath)
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


def clean_csv_file(input_path: str, output_path: str, encoding: str = "utf-8",
                   replacement: str = " ", change_separator: bool = True,
                   new_separator: str = ';'):
    """
    Lee un archivo completo (CSV o texto), corrige saltos de línea dentro de comillas dobles
    y opcionalmente cambia los separadores de coma a 'new_separator' fuera de comillas.
    Escribe el resultado en output_path.
    """
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(input_path, 'r', encoding=encoding, newline='') as f:
        content = f.read()

    # 1) Corregir saltos de línea dentro de comillas
    cleaned = fix_newlines_inside_quotes(content, replacement=replacement)

    # 2) Cambiar separador fuera de comillas
    if change_separator:
        cleaned = replace_commas_outside_quotes(cleaned, to_separator=new_separator)

    with open(output_path, 'w', encoding=encoding, newline='') as f:
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
            self.original_stream.write(message)
            self.original_stream.flush()
        if self.log_file and not self.log_file.closed:
            self.log_file.write(message)
            self.log_file.flush()

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()
        if self.log_file and not self.log_file.closed:
            self.log_file.flush()

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

