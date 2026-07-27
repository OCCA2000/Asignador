import glob
import os
import shutil
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
    Mueve los archivos que coincidan con 'pattern' que estén en la raíz de 'base_dir'
    hacia su respectiva subcarpeta por fecha 'base_dir/YYYY-MM-DD/'.
    """
    if not os.path.exists(base_dir):
        return
    search_path = os.path.join(base_dir, pattern)
    archivos = [f for f in glob.glob(search_path) if os.path.isfile(f)]
    for filepath in archivos:
        filename = os.path.basename(filepath)
        mtime = os.path.getmtime(filepath)
        fecha_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')
        target_dir = os.path.join(base_dir, fecha_str)
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
            print(f"Archivado ejecucion previa: {filename} -> {fecha_str}/")
        except Exception as e:
            print(f"No se pudo archivar {filepath}: {e}")


def get_output_path_date(prefix: str, base_dir: str = "Entrada", timing: str = None, ext: str = ".csv", archivar_previos: bool = True) -> tuple:
    """
    Archiva primero cualquier archivo anterior que coincida con prefix en la raíz de base_dir
    hacia su respectiva carpeta base_dir/YYYY-MM-DD/.
    Luego devuelve la nueva ruta directamente en la raíz de base_dir y el timing.
    """
    now = datetime.now()
    if timing is None:
        timing = now.strftime('%Y-%m-%d_%H-%M-%S')

    if not ext.startswith("."):
        ext = "." + ext

    os.makedirs(base_dir, exist_ok=True)

    if archivar_previos:
        archive_previous_files(base_dir, f"{prefix}_*{ext}")

    ruta_salida = os.path.join(base_dir, f"{prefix}_{timing}{ext}")
    return ruta_salida, timing


def clean_csv_file(ruta_entrada: str, ruta_salida: str, encoding: str = "utf-8",
                   replacement: str = " ", cambiar_separador: bool = True,
                   nuevo_separador: str = ';'):
    """
    Lee un archivo completo (CSV o texto), limpia saltos de línea dentro de comillas dobles
    y opcionalmente cambia el separador de coma a 'nuevo_separador' fuera de comillas.
    Escribe el resultado en ruta_salida.
    """
    dir_salida = os.path.dirname(ruta_salida)
    if dir_salida:
        os.makedirs(dir_salida, exist_ok=True)

    with open(ruta_entrada, 'r', encoding=encoding, newline='') as f:
        contenido = f.read()

    # 1) Arreglar saltos de línea dentro de comillas
    limpio = fix_newlines_inside_quotes(contenido, replacement=replacement)

    # 2) Cambiar separador solo fuera de comillas
    if cambiar_separador:
        limpio = replace_commas_outside_quotes(limpio, to_separator=nuevo_separador)

    with open(ruta_salida, 'w', encoding=encoding, newline='') as f:
        f.write(limpio)


def clean_csv_text(texto: str, replacement: str = " ", cambiar_separador: bool = True,
                   nuevo_separador: str = ';') -> str:
    """Atajo para procesar un string en memoria."""
    limpio = fix_newlines_inside_quotes(texto, replacement=replacement)
    if cambiar_separador:
        limpio = replace_commas_outside_quotes(limpio, to_separator=nuevo_separador)
    return limpio

