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


def limpiar_archivo_csv(ruta_entrada: str, ruta_salida: str, encoding: str = "utf-8",
                        replacement: str = " ", cambiar_separador: bool = True,
                        nuevo_separador: str = ';'):
    """
    Lee un archivo completo (CSV o texto), limpia saltos de línea dentro de comillas dobles
    y opcionalmente cambia el separador de coma a 'nuevo_separador' fuera de comillas.
    Escribe el resultado en ruta_salida.
    """
    with open(ruta_entrada, 'r', encoding=encoding, newline='') as f:
        contenido = f.read()

    # 1) Arreglar saltos de línea dentro de comillas
    limpio = fix_newlines_inside_quotes(contenido, replacement=replacement)

    # 2) Cambiar separador solo fuera de comillas
    if cambiar_separador:
        limpio = replace_commas_outside_quotes(limpio, to_separator=nuevo_separador)

    with open(ruta_salida, 'w', encoding=encoding, newline='') as f:
        f.write(limpio)


def limpiar_texto_csv(texto: str, replacement: str = " ", cambiar_separador: bool = True,
                      nuevo_separador: str = ';') -> str:
    """Atajo para procesar un string en memoria."""
    limpio = fix_newlines_inside_quotes(texto, replacement=replacement)
    if cambiar_separador:
        limpio = replace_commas_outside_quotes(limpio, to_separator=nuevo_separador)
    return limpio
