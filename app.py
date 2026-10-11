from pathlib import Path
import csv
import io
import os
import re
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

ROOT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = ROOT_DIR / "Especificaciones"
SALIDA_DIR = ROOT_DIR / "Salida"
ENTRADA_DIR = ROOT_DIR / "Entrada"

DELIM = ";"
USERS_FILE = CONFIG_DIR / "Grupos - Usuarios.csv"
INC_FILE = CONFIG_DIR / "Grupos - Incidentes(Grupos).csv"
REQ_FILE = CONFIG_DIR / "Grupos - Requerimientos(Grupos).csv"
SHIFTS_FILE = CONFIG_DIR / "Turnos.csv"
REPORT_FILE = SALIDA_DIR / "reporte_detalle_asignaciones.csv"

ROLES = ["Turno 1", "Turno 2", "Turno 3", "Turno 4", "Stand-by"]


def read_csv_file(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo {path}")
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.reader(f, delimiter=DELIM))
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def write_csv_file(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=DELIM, lineterminator="\n")
        writer.writerows(rows)


def user_rows():
    if not USERS_FILE.exists():
        return ["Nombre", "Usuario", "ServiceNow ID", "Estado"], []
    rows = read_csv_file(USERS_FILE)
    headers = rows[0] if rows else ["Nombre", "Usuario", "ServiceNow ID", "Estado"]
    result = []
    for r in rows[1:]:
        r = (r + ["", "", "", ""])[:4]
        result.append({
            "nombre": r[0].strip(),
            "usuario": r[1].strip(),
            "snow_id": r[2].strip(),
            "estado": r[3].strip()
        })
    return headers, result


def save_users(users):
    rows = [["Nombre", "Usuario", "ServiceNow ID", "Estado"]]
    for u in users:
        rows.append([u["nombre"], u["usuario"], u["snow_id"], str(u["estado"])])
    write_csv_file(USERS_FILE, rows)


def read_groups(file_path: Path):
    if not file_path.exists():
        return []
    rows = read_csv_file(file_path)
    if not rows:
        return []
    headers = rows[0]
    groups = []
    for i, h in enumerate(headers):
        clean_name = h.strip()
        if not clean_name:
            continue
        members = []
        for r in rows[1:]:
            if i < len(r) and r[i].strip() and r[i].strip() not in members:
                members.append(r[i].strip())
        groups.append({"nombre": clean_name, "miembros": members})
    return groups


def save_groups(file_path: Path, groups: list):
    max_rows = max([len(g["miembros"]) for g in groups], default=0)
    rows = [[g["nombre"] for g in groups]]
    for ri in range(max_rows):
        rows.append([g["miembros"][ri] if ri < len(g["miembros"]) else "" for g in groups])
    write_csv_file(file_path, rows)


def read_shifts():
    if not SHIFTS_FILE.exists():
        headers = ["Fecha"] + ROLES
        return headers, []
    rows = read_csv_file(SHIFTS_FILE)
    if not rows:
        return ["Fecha"] + ROLES, []
    headers = [h.strip() for h in rows[0]]
    result = []
    for r in rows[1:]:
        r = (r + [""] * len(headers))[:len(headers)]
        result.append(dict(zip(headers, [x.strip() for x in r])))
    return headers, result


def save_shifts(headers, rows):
    write_csv_file(SHIFTS_FILE, [headers] + [[r.get(h, "") for h in headers] for r in rows])


def get_available_logs():
    """Busca archivos .log en Salida/ y sus subcarpetas, ordenados por fecha de modificación."""
    if not SALIDA_DIR.exists():
        return []
    logs = []
    for p in SALIDA_DIR.rglob("*.log"):
        try:
            stat = p.stat()
            rel = p.relative_to(SALIDA_DIR).as_posix()
            logs.append({
                "nombre": p.name,
                "rel_path": rel,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
        except OSError:
            continue
    logs.sort(key=lambda x: x["mtime"], reverse=True)
    return logs


def read_log_content(selected_rel_path: str = None):
    available = get_available_logs()
    if not available:
        return "No se encontraron archivos de registro (.log) en la carpeta Salida/.", "", available, 0

    target_entry = None
    if selected_rel_path:
        target_entry = next((item for item in available if item["rel_path"] == selected_rel_path), None)
    if not target_entry:
        target_entry = available[0]

    target_path = SALIDA_DIR / target_entry["rel_path"]
    try:
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                with target_path.open("r", encoding=enc, errors="replace") as f:
                    content = f.read()
                    return content[-60000:], target_entry["rel_path"], available, target_entry["size_bytes"]
            except UnicodeDecodeError:
                continue
    except OSError as exc:
        return f"Error al leer el archivo de registro ({exc}).", target_entry["rel_path"], available, 0

    return "No se pudo decodificar el contenido del registro.", target_entry["rel_path"], available, 0


def count_input_tickets():
    """Retorna la cantidad de tickets pendientes de procesamiento en Entrada/."""
    counts = {"incidentes": 0, "requerimientos": 0}
    inc_p = ENTRADA_DIR / "incident.csv"
    req_p = ENTRADA_DIR / "sc_req_item.csv"

    for key, path in [("incidentes", inc_p), ("requerimientos", req_p)]:
        if path.exists():
            try:
                for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                    try:
                        with path.open("r", encoding=enc, newline="") as f:
                            reader = csv.reader(f, delimiter=DELIM)
                            rows = list(reader)
                            if len(rows) > 1:
                                counts[key] = max(0, len(rows) - 1)
                        break
                    except UnicodeDecodeError:
                        continue
            except Exception:
                pass
    return counts


def read_report():
    if not REPORT_FILE.exists():
        return []
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with REPORT_FILE.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f, delimiter=DELIM)
                rows = []
                for row in reader:
                    cleaned = {}
                    for key, value in row.items():
                        clean_key = (key or "").replace("\ufeff", "").strip()
                        cleaned[clean_key] = value.strip() if isinstance(value, str) else value
                    rows.append(cleaned)
                return rows
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def parse_timestamp(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            pass
    return None


def build_daily_chart(ticket_type, user_display_map=None):
    if user_display_map is None:
        user_display_map = {}
    records = []
    users = set()
    for row in read_report():
        kind = (row.get("Ticket type") or "").strip().lower()
        if ticket_type == "incidentes":
            matches = kind in ("incidente", "incident", "incidents") or (row.get("Ticket identification") or "").strip().upper().startswith("INC")
        else:
            matches = kind in ("requerimiento", "requirement", "request", "requerimientos") or (row.get("Ticket identification") or "").strip().upper().startswith("RITM")
        if not matches:
            continue
        dt = parse_timestamp(row.get("Assignation timestamp"))
        if not dt:
            continue
        person = (row.get("Person assigned") or "").strip()
        if person:
            users.add(person)
        records.append({"fecha": dt.strftime("%Y-%m-%d"), "usuario": person})
    all_dates = sorted({r["fecha"] for r in records})

    sorted_users = sorted(users, key=str.casefold)
    user_options = [
        {"id": u, "label": user_display_map.get(u.lower(), user_display_map.get(u.upper(), u))}
        for u in sorted_users
    ]

    return {
        "fechas": all_dates,
        "usuarios": sorted_users,
        "user_options": user_options,
        "series": {
            person: [{"fecha": day, "cantidad": sum(1 for r in records if r["fecha"] == day and r["usuario"] == person)} for day in all_dates]
            for person in sorted_users
        },
        "total": [{"fecha": day, "cantidad": sum(1 for r in records if r["fecha"] == day)} for day in all_dates],
        "registros": len(records)
    }


# ==============================================================================
# Rutas y Endpoints
# ==============================================================================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    selected_log = request.args.get("log_file", "").strip()
    log_text, active_rel_path, available_logs, log_size = read_log_content(selected_log)

    # Mapa de nombres reales para presentar usuarios en filtros
    _, users = user_rows()
    user_display_map = {
        u["usuario"].lower(): f"{u['nombre']} ({u['usuario']})"
        for u in users
    }
    user_display_map.update({
        u["usuario"].upper(): f"{u['nombre']} ({u['usuario']})"
        for u in users
    })

    incidentes_data = build_daily_chart("incidentes", user_display_map)
    requerimientos_data = build_daily_chart("requerimientos", user_display_map)
    pending_tickets = count_input_tickets()

    return jsonify(
        log=log_text,
        active_log=active_rel_path,
        active_log_size=log_size,
        available_logs=available_logs,
        incidentes=incidentes_data,
        requerimientos=requerimientos_data,
        pendientes=pending_tickets
    )


@app.get("/api/state")
def state():
    headers, users = user_rows()
    shift_headers, shifts = read_shifts()
    return jsonify({
        "users": users,
        "incidentes": read_groups(INC_FILE),
        "requerimientos": read_groups(REQ_FILE),
        "turnos": {"headers": shift_headers, "rows": shifts},
        "roles": ROLES,
        "pendientes": count_input_tickets()
    })


@app.post("/api/users")
def add_user():
    d = request.get_json(force=True)
    required = ["nombre", "usuario", "snow_id"]
    if any(not str(d.get(k, "")).strip() for k in required):
        return jsonify(error="Completa Nombre, Usuario y ServiceNow ID."), 400
    _, users = user_rows()
    username = d["usuario"].strip()
    if any(u["usuario"].lower() == username.lower() for u in users):
        return jsonify(error="Ya existe un usuario con ese identificador."), 409
    estado = "1" if str(d.get("estado", "1")) == "1" else "0"
    u = {
        "nombre": d["nombre"].strip(),
        "usuario": username,
        "snow_id": d["snow_id"].strip(),
        "estado": estado
    }
    users.append(u)
    save_users(users)

    # Vincular membresía en los grupos seleccionados
    for key, file_path in [("incidentes", INC_FILE), ("requerimientos", REQ_FILE)]:
        chosen = d.get(key, []) or []
        groups = read_groups(file_path)
        for g in groups:
            if g["nombre"] in chosen and username not in g["miembros"]:
                g["miembros"].append(username)
        save_groups(file_path, groups)

    return jsonify(ok=True, user=u)


@app.patch("/api/users/<username>")
def update_user(username):
    d = request.get_json(force=True)
    _, users = user_rows()
    u = next((x for x in users if x["usuario"].lower() == username.lower()), None)
    if not u:
        return jsonify(error="Usuario no encontrado."), 404
    if "estado" in d:
        u["estado"] = "1" if str(d["estado"]) == "1" else "0"
    if "nombre" in d and str(d["nombre"]).strip():
        u["nombre"] = str(d["nombre"]).strip()
    if "snow_id" in d and str(d["snow_id"]).strip():
        u["snow_id"] = str(d["snow_id"]).strip()
    save_users(users)
    return jsonify(ok=True, user=u)


@app.delete("/api/users/<username>")
def delete_user(username):
    _, users = user_rows()
    u_match = next((x for x in users if x["usuario"].lower() == username.lower()), None)
    if not u_match:
        return jsonify(error="Usuario no encontrado."), 404
    canonical_username = u_match["usuario"]
    save_users([u for u in users if u["usuario"] != canonical_username])

    # Eliminar de grupos de incidentes y requerimientos
    for file_path in [INC_FILE, REQ_FILE]:
        groups = read_groups(file_path)
        for g in groups:
            g["miembros"] = [m for m in g["miembros"] if m.lower() != canonical_username.lower()]
        save_groups(file_path, groups)

    # Eliminar de cuadrantes de turnos
    headers, shifts = read_shifts()
    for row in shifts:
        for role in ROLES:
            if row.get(role, "").lower() == canonical_username.lower():
                row[role] = ""
    save_shifts(headers, shifts)
    return jsonify(ok=True)


@app.post("/api/groups/<kind>")
def create_group(kind):
    file_path = INC_FILE if kind == "incidentes" else REQ_FILE if kind == "requerimientos" else None
    if not file_path:
        return jsonify(error="Tipo de grupo inválido."), 400
    d = request.get_json(force=True)
    name = str(d.get("nombre", "")).strip()
    members = d.get("miembros", []) or []
    if not name:
        return jsonify(error="Escribe el nombre del nuevo grupo."), 400
    groups = read_groups(file_path)
    if any(g["nombre"].casefold() == name.casefold() for g in groups):
        return jsonify(error="Ya existe un grupo con ese nombre."), 409
    _, users = user_rows()
    known = {u["usuario"].lower() for u in users}
    unknown = [m for m in members if m.lower() not in known]
    if unknown:
        return jsonify(error="Hay integrantes que no existen en Grupos - Usuarios: " + ", ".join(unknown)), 400
    groups.append({"nombre": name, "miembros": list(dict.fromkeys(members))})
    save_groups(file_path, groups)
    return jsonify(ok=True, message=f"Grupo creado exitosamente: {name}")


@app.put("/api/groups/<kind>/<path:group_name>")
def update_group(kind, group_name):
    file_path = INC_FILE if kind == "incidentes" else REQ_FILE if kind == "requerimientos" else None
    if not file_path:
        return jsonify(error="Tipo de grupo inválido."), 400
    d = request.get_json(force=True)
    members = d.get("miembros", []) or []
    _, users = user_rows()
    known = {u["usuario"].lower() for u in users}
    unknown = [m for m in members if m.lower() not in known]
    if unknown:
        return jsonify(error="Hay integrantes que no existen en Grupos - Usuarios: " + ", ".join(unknown)), 400
    groups = read_groups(file_path)
    g = next((g for g in groups if g["nombre"] == group_name), None)
    if not g:
        return jsonify(error="Grupo no encontrado."), 404
    g["miembros"] = list(dict.fromkeys(members))
    save_groups(file_path, groups)
    return jsonify(ok=True)


@app.put("/api/shifts/week")
def update_week():
    d = request.get_json(force=True)
    start = d.get("fecha_inicio", "")
    assignments = d.get("asignaciones", {})
    try:
        monday = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="Fecha de inicio inválida."), 400
    if monday.weekday() != 0:
        return jsonify(error="Selecciona el lunes de la semana."), 400

    _, users = user_rows()
    active = {u["usuario"] for u in users if u["estado"] == "1"}

    for role in ROLES:
        val = assignments.get(role, "")
        if val and val not in active:
            return jsonify(error=f"{val} no está habilitado para recibir tickets (Estado 0)."), 400

    assigned_vals = [v for v in assignments.values() if v]
    if len(assigned_vals) != len(set(assigned_vals)):
        return jsonify(error="Selecciona una persona diferente para cada rol de turno."), 400

    headers, rows = read_shifts()
    date_col = "Fecha" if "Fecha" in headers else headers[0]

    for offset in range(7):
        day = monday + timedelta(days=offset)
        date_str = day.strftime("%d/%m/%Y")
        row = next((r for r in rows if r.get(date_col, "") == date_str), None)
        if row is None:
            row = {h: "" for h in headers}
            row[date_col] = date_str
            rows.append(row)
        for role in ROLES:
            if role in headers:
                row[role] = assignments.get(role, "")

    def parse_shift_date(r):
        val = r.get(date_col, "")
        try:
            return datetime.strptime(val, "%d/%m/%Y")
        except Exception:
            return datetime.min

    rows.sort(key=parse_shift_date)
    save_shifts(headers, rows)
    return jsonify(ok=True, message=f"Turnos actualizados para la semana del {monday.strftime('%d/%m/%Y')}.")


@app.get("/api/health")
def health():
    return jsonify(
        ok=True,
        config_dir=str(CONFIG_DIR),
        salida_dir=str(SALIDA_DIR),
        entrada_dir=str(ENTRADA_DIR)
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
