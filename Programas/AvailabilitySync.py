"""Deshabilita/reactiva usuarios en 'Grupos - Usuarios.csv' según turnos y vacaciones.

Reglas:
- Quien tiene Turno 1-3, inducción o soporte de turno en la semana calendario actual queda deshabilitado (Turno 4 y Stand-by no cuentan).
- Quien inicia un turno o unas vacaciones deja de recibir tickets 3 días hábiles antes del inicio
  (inicio en lunes => deshabilitado desde el miércoles anterior).
- Durante unas vacaciones queda deshabilitado hasta la fecha 'Hasta'.
Solo se reactivan los usuarios que este módulo deshabilitó; los deshabilitados a mano no se tocan.
Si alguien habilita a mano a un usuario dentro de su ventana de bloqueo, se respeta hasta que esa ventana termine.
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

DELIM = ";"
LEAD_BUSINESS_DAYS = 3
SHIFT_ROLES = ("Turno 1", "Turno 2", "Turno 3")
STATE_FILE = "estado_automatico.json"


def _read_rows(path):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.reader(f, delimiter=DELIM))
        except UnicodeDecodeError:
            continue
    return []


def _to_date(text):
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return None


def _minus_business_days(d, n):
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _week_end(d):
    return d + timedelta(days=6 - d.weekday())


def _induction_days(inductions_path):
    days = {}
    path = Path(inductions_path) if inductions_path else None
    if not path or not path.exists():
        return days
    for r in _read_rows(path)[1:]:
        d = _to_date(r[1]) if len(r) >= 2 else None
        if r and r[0].strip() and d:
            days.setdefault(r[0].strip().lower(), set()).add(d)
    return days


def _shift_windows(shifts_path, inductions_path=None):
    """{usuario: [(desde, hasta)]} a partir de bloques de días consecutivos con turno o inducción."""
    days = {}
    path = Path(shifts_path)
    if not path.exists():
        path = None
    rows = _read_rows(path) if path else []
    if not rows:
        rows = [["Fecha"]]
    header = [h.strip() for h in rows[0]]
    for r in rows[1:]:
        rec = dict(zip(header, (c.strip() for c in r)))
        d = _to_date(rec.get("Fecha", ""))
        if not d:
            continue
        for role in SHIFT_ROLES:
            user = rec.get(role, "").lower()
            if user:
                days.setdefault(user, set()).add(d)

    windows = {}
    for user, ds in _induction_days(inductions_path).items():
        days.setdefault(user, set()).update(ds)
    for user, ds in days.items():
        ordered = sorted(ds)
        start = prev = ordered[0]
        blocks = []
        for d in ordered[1:]:
            if (d - prev).days > 1:
                blocks.append((start, prev))
                start = d
            prev = d
        blocks.append((start, prev))
        windows[user] = [(_minus_business_days(s, LEAD_BUSINESS_DAYS), _week_end(e)) for s, e in blocks]
    return windows


def _vacation_windows(vacations_path):
    windows = {}
    path = Path(vacations_path)
    if not path.exists():
        return windows
    rows = _read_rows(path)
    for r in rows[1:]:
        if len(r) < 3:
            continue
        start, end = _to_date(r[1]), _to_date(r[2])
        if r[0].strip() and start and end:
            windows.setdefault(r[0].strip().lower(), []).append((_minus_business_days(start, LEAD_BUSINESS_DAYS), end))
    return windows


def blocked_users(shifts_path, vacations_path, today=None, inductions_path=None):
    """Usuarios que no deben recibir tickets en la fecha dada."""
    today = today or date.today()
    blocked = set()
    for windows in (_shift_windows(shifts_path, inductions_path), _vacation_windows(vacations_path)):
        for user, ranges in windows.items():
            if any(a <= today <= b for a, b in ranges):
                blocked.add(user)
    return blocked


def _load_state(state_path):
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    exceptions = {}
    for user, until in (data.get("excepciones") or {}).items():
        d = _to_date(until)
        if d:
            exceptions[user] = d
    return set(data.get("usuarios", [])), exceptions


def _save_state(state_path, users, exceptions):
    data = {"usuarios": sorted(users),
            "excepciones": {u: d.isoformat() for u, d in sorted(exceptions.items())}}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _window_end(user, config_dir, today):
    """Fin de la ventana de bloqueo (la más larga) que contiene hoy para el usuario, o None."""
    config_dir = Path(config_dir)
    ends = []
    for windows in (_shift_windows(config_dir / "Turnos.csv", config_dir / "Apoyos_Turno.csv"),
                    _vacation_windows(config_dir / "Vacaciones.csv")):
        ends += [b for a, b in windows.get(user, []) if a <= today <= b]
    return max(ends) if ends else None


def forget_auto_disabled(username, config_dir="Especificaciones", enabled=False, today=None):
    """Registra un cambio manual de estado: deja de ser automático y, si se habilita dentro de una
    ventana de bloqueo, se respeta hasta que esa ventana termine."""
    user = username.strip().lower()
    state_path = Path(config_dir) / STATE_FILE
    auto, exceptions = _load_state(state_path)
    auto.discard(user)
    exceptions.pop(user, None)
    if enabled:
        end = _window_end(user, config_dir, today or date.today())
        if end:
            exceptions[user] = end
    _save_state(state_path, auto, exceptions)

def apply_availability_rules(config_dir="Especificaciones"):
    """Sincroniza el estado de los usuarios sin interrumpir la asignación si algo falla."""
    try:
        disabled, reenabled = sync_user_status(config_dir)
        if disabled:
            print(f"[DISPONIBILIDAD] Deshabilitados por turno/vacaciones: {', '.join(disabled)}")
        if reenabled:
            print(f"[DISPONIBILIDAD] Reactivados: {', '.join(reenabled)}")
    except Exception as e:
        print(f"[ADVERTENCIA] No se pudo sincronizar la disponibilidad de usuarios: {e}")


def sync_user_status(config_dir="Especificaciones", today=None, users_file="Grupos - Usuarios.csv"):
    """Aplica las reglas y persiste Estado en el CSV de usuarios. Devuelve (deshabilitados, reactivados)."""
    config_dir = Path(config_dir)
    users_path = config_dir / users_file
    state_path = config_dir / STATE_FILE
    if not users_path.exists():
        return [], []

    rows = _read_rows(users_path)
    if not rows:
        return [], []
    header = [h.strip().lstrip("\ufeff").lower() for h in rows[0]]
    try:
        user_idx = header.index("usuario")
        estado_idx = next(i for i, h in enumerate(header) if h in ("estado", "activo"))
    except (ValueError, StopIteration):
        return [], []

    blocked = blocked_users(config_dir / "Turnos.csv", config_dir / "Vacaciones.csv", today, config_dir / "Apoyos_Turno.csv")
    auto, exceptions = _load_state(state_path)
    today = today or date.today()
    exceptions = {u: d for u, d in exceptions.items() if d >= today}
    disabled, reenabled, changed = [], [], False
    present = set()

    for r in rows[1:]:
        if len(r) <= max(user_idx, estado_idx):
            continue
        user = r[user_idx].strip().lower()
        present.add(user)
        is_on = r[estado_idx].strip() in ("1", "S", "s", "true", "True")
        if user in blocked and user in exceptions:
            continue
        if user in blocked and is_on:
            r[estado_idx] = "0"
            auto.add(user)
            disabled.append(user)
            changed = True
        elif user not in blocked and user in auto:
            if not is_on:
                r[estado_idx] = "1"
                reenabled.append(user)
                changed = True
            auto.discard(user)

    auto &= present
    exceptions = {u: d for u, d in exceptions.items() if u in present}
    if changed:
        with users_path.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=DELIM, lineterminator="\n").writerows(rows)
    _save_state(state_path, auto, exceptions)
    return disabled, reenabled
