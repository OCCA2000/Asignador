"""Convierte el Excel maestro de turnos en Turnos.csv y Vacaciones.csv."""
import csv
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

DELIM = ";"
ROLES = ["Turno 1", "Turno 2", "Turno 3", "Turno 4", "Stand-by"]
FIRST_DATA_COL = 2
HEADER_ROW = 2
FIRST_DATA_ROW = 3

_WEEKDAY_PREFIXES = (("lun", 0), ("mar", 1), ("mi", 2), ("jue", 3), ("vie", 4), ("s", 5), ("dom", 6))


def _tokens(text):
    s = unicodedata.normalize("NFKD", str(text).replace("\xa0", " "))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return set(re.findall(r"[a-z]+", s.lower()))


def _read_users(users_path):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(users_path, encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f, delimiter=DELIM))
            break
        except UnicodeDecodeError:
            continue
    return [(r["Nombre"], r["Usuario"].strip().lower()) for r in rows if r.get("Nombre") and r.get("Usuario")]


def _match_user(excel_name, users):
    wanted = _tokens(excel_name)
    if not wanted:
        return None
    exact = [u for n, u in users if _tokens(n) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [u for n, u in users if wanted <= _tokens(n)]
    return partial[0] if len(partial) == 1 else None


def _pick_sheets(wb, sheet):
    """Hojas a importar: la indicada o todas las de TURNOS del año actual en adelante (la más reciente si ninguna aplica)."""
    if sheet:
        return [wb[sheet]]
    candidates = [n for n in wb.sheetnames if "turnos" in n.lower()]
    if not candidates:
        raise ValueError("El Excel no contiene una hoja de turnos (nombre con 'TURNOS').")

    def year_of(name):
        m = re.search(r"\d{4}", name)
        return int(m.group()) if m else 0

    current = [n for n in candidates if year_of(n) >= date.today().year]
    chosen = current or [max(candidates, key=year_of)]
    return [wb[n] for n in sorted(chosen, key=year_of)]


def _sheet_year(ws):
    m = re.search(r"\d{4}", ws.title)
    return int(m.group()) if m else date.today().year


def _parse_header_date(value, year):
    """Devuelve una fecha confiable de la cabecera o None si es dudosa."""
    if isinstance(value, datetime):
        return value.date() if year - 1 <= value.year <= year + 1 else None
    if isinstance(value, str):
        m = re.match(r"^\s*(\S+?)\W*,\s*(\d{1,2})-(\d{1,2})\s*$", value.replace("\xa0", " "))
        if not m:
            return None
        prefix = unicodedata.normalize("NFKD", m.group(1).lower())[:3]
        wd = next((n for p, n in _WEEKDAY_PREFIXES if prefix.startswith(p)), None)
        for y in (year, year - 1, year + 1):
            try:
                d = date(y, int(m.group(3)), int(m.group(2)))
            except ValueError:
                continue
            if wd is None or d.weekday() == wd:
                return d
    return None


def _resolve_dates(ws, last_col, year, warnings):
    """Reconstruye la fecha de cada columna; las cabeceras dudosas se interpolan desde la vecina confiable."""
    trusted = {c: _parse_header_date(ws.cell(HEADER_ROW, c).value, year) for c in range(FIRST_DATA_COL, last_col + 1)}
    trusted = {c: d for c, d in trusted.items() if d}
    if not trusted:
        raise ValueError("No se pudo interpretar ninguna fecha de la cabecera.")
    # La fecha dominante (fecha - columna) descarta anclas aisladas con año o día equivocado
    offsets = Counter((d - timedelta(days=c)) for c, d in trusted.items())
    base, _ = offsets.most_common(1)[0]
    dates = {}
    for c in range(FIRST_DATA_COL, last_col + 1):
        dates[c] = base + timedelta(days=c)
        if c in trusted and trusted[c] != dates[c]:
            warnings.append(f"Fecha de cabecera {trusted[c]} en columna {c} no encaja con la secuencia; se usa {dates[c]}.")
    return dates


def _last_header_col(ws):
    last = FIRST_DATA_COL
    for c in range(FIRST_DATA_COL, min(ws.max_column, 2000) + 1):
        if ws.cell(HEADER_ROW, c).value not in (None, ""):
            last = c
    return last


def _role_of(value):
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ").replace("*", " ")).strip().upper()
    m = re.fullmatch(r"TURNO ?([1-4])", text)
    if m:
        return f"Turno {m.group(1)}"
    if re.fullmatch(r"STAND ?-?BY", text):
        return "Stand-by"
    return None


def _is_vacation(value):
    return value is not None and "VACACION" in str(value).upper()


def _is_induction(value):
    """Inducción o soporte de turno (INDUCCION T1, SOPORTE TURNO 2...); los de estados de cuenta (EC) no cuentan."""
    return value is not None and re.search(r"(INDUC\w*|SOPORTE)\s*(T|TURNO)\s*\d", str(value).upper()) is not None


def _parse_sheet(ws, users):
    """Devuelve (turnos, vacaciones, inducciones, advertencias) de una hoja.
    turnos: {fecha: {rol: usuario}}; vacaciones: [(usuario, desde, hasta)]; inducciones: [(usuario, fecha)]."""
    year = _sheet_year(ws)
    warnings = []

    last_col = _last_header_col(ws)
    dates = _resolve_dates(ws, last_col, year, warnings)

    row_user = {}
    unmapped = []
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not isinstance(name, str) or not name.strip():
            continue
        username = _match_user(name, users)
        if username:
            row_user[r] = username
        else:
            unmapped.append(name.replace("\xa0", " ").strip())
    if unmapped:
        warnings.append(f"[{ws.title}] Sin usuario en 'Grupos - Usuarios' (omitidos): " + ", ".join(unmapped))

    turnos = {d: {} for d in dates.values()}
    inducciones = set()
    soportes = []
    for r, username in row_user.items():
        for c in range(FIRST_DATA_COL, last_col + 1):
            value = ws.cell(r, c).value
            if _is_induction(value):
                inducciones.add((username, dates[c]))
                support = re.search(r"SOPORTE\s*TURNO\s*([1-4])", str(value).upper())
                if support:
                    soportes.append((dates[c], f"Turno {support.group(1)}", username))
                continue
            role = _role_of(value)
            if not role:
                continue
            slot = turnos[dates[c]]
            if slot.get(role) and slot[role] != username:
                # Un segundo nombre en el mismo turno y día es un acompañante en inducción
                inducciones.add((username, dates[c]))
            else:
                slot[role] = username

    # Si nadie más cubre ese turno, quien da soporte figura como responsable del turno
    for fecha, role, username in soportes:
        if not turnos[fecha].get(role):
            turnos[fecha][role] = username

    vacaciones = []
    covered = set()
    for rng in ws.merged_cells.ranges:
        if rng.min_row not in row_user or not _is_vacation(ws.cell(rng.min_row, rng.min_col).value):
            continue
        lo, hi = max(rng.min_col, FIRST_DATA_COL), min(rng.max_col, last_col)
        if lo > hi:
            continue
        vacaciones.append((row_user[rng.min_row], dates[lo], dates[hi]))
        covered.add((rng.min_row, rng.min_col))
    for r, username in row_user.items():
        for c in range(FIRST_DATA_COL, last_col + 1):
            if (r, c) not in covered and _is_vacation(ws.cell(r, c).value):
                vacaciones.append((username, dates[c], dates[c]))
    vacaciones.sort(key=lambda v: (v[1], v[0]))
    return turnos, vacaciones, sorted(inducciones, key=lambda i: (i[1], i[0])), warnings


def parse_workbook(xlsx_path, users_path, sheet=None):
    """Combina las hojas de turnos; si una fecha está en dos hojas, prevalece la hoja más reciente."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    users = _read_users(users_path)
    turnos, vacaciones, inducciones, warnings = {}, set(), set(), []
    for ws in _pick_sheets(wb, sheet):
        t, v, i, w = _parse_sheet(ws, users)
        for d, slot in t.items():
            turnos.setdefault(d, {}).update(slot)
        vacaciones.update(v)
        inducciones.update(i)
        warnings.extend(w)
    return (turnos, sorted(vacaciones, key=lambda v: (v[1], v[0])),
            sorted(inducciones, key=lambda i: (i[1], i[0])), warnings)


def _parse_shift_date(text):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _read_existing_shifts(path):
    """{fecha (date): {rol: usuario}}; las fechas con formato desconocido se descartan."""
    path = Path(path)
    if not path.exists():
        return {}
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open(encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f, delimiter=DELIM))
            break
        except UnicodeDecodeError:
            continue
    existing = {}
    for r in rows:
        d = _parse_shift_date((r.get("Fecha") or "").strip())
        if d:
            existing[d] = {role: (r.get(role) or "").strip() for role in ROLES}
    return existing


def import_excel(xlsx_path, users_path, shifts_path, vacations_path, inductions_path, sheet=None, today=None):
    """Importa desde el inicio del mes en curso hasta el último día con alguien asignado.

    Turnos.csv conserva el historial previo (sin los días vacíos posteriores al último turno asignado);
    Vacaciones.csv y Apoyos_Turno.csv (inducciones y soportes) se reemplazan con lo vigente.
    """
    start = (today or date.today()).replace(day=1)
    turnos, vacaciones, inducciones, warnings = parse_workbook(xlsx_path, users_path, sheet)

    assigned = [d for d, slot in turnos.items() if any(slot.values()) and d >= start]
    last = max(assigned) if assigned else None
    turnos = {d: slot for d, slot in turnos.items() if last and start <= d <= last}
    vacaciones = [v for v in vacaciones if v[2] >= start]
    inducciones = [i for i in inducciones if i[1] >= start]

    merged = _read_existing_shifts(shifts_path)
    if last:
        merged = {d: s for d, s in merged.items() if d <= last or any(s.values())}
    for d, slot in turnos.items():
        merged[d] = {role: slot.get(role, "") for role in ROLES}

    shifts_path, vacations_path = Path(shifts_path), Path(vacations_path)
    with shifts_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=DELIM, lineterminator="\n")
        w.writerow(["Fecha"] + ROLES)
        for d in sorted(merged):
            w.writerow([d.isoformat()] + [merged[d].get(role, "") for role in ROLES])
    with vacations_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=DELIM, lineterminator="\n")
        w.writerow(["Usuario", "Desde", "Hasta"])
        for username, v_start, v_end in vacaciones:
            w.writerow([username, v_start.isoformat(), v_end.isoformat()])
    with Path(inductions_path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=DELIM, lineterminator="\n")
        w.writerow(["Usuario", "Fecha"])
        for username, fecha in inducciones:
            w.writerow([username, fecha.isoformat()])

    return {
        "dias_turnos": len(turnos),
        "desde": start.isoformat(),
        "hasta": last.isoformat() if last else None,
        "vacaciones": len(vacaciones),
        "dias_induccion": len(inducciones),
        "advertencias": warnings,
    }
