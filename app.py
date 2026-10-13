from pathlib import Path
import collections
import csv
import io
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template

from Programas.PipelineUtils import ensure_execution_summary_csv, append_execution_summary

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

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
SUMMARY_FILE = SALIDA_DIR / "resumen_ejecuciones.csv"

ROLES = ["Turno 1", "Turno 2", "Turno 3", "Turno 4", "Stand-by"]

# Gestor de proceso en segundo plano para ejecución del pipeline
pipeline_lock = threading.Lock()
pipeline_process = None
pipeline_state = {
    "status": "idle",       # "idle", "running", "success", "error", "stopped"
    "mode": None,           # "rpa_full", "ml_only"
    "started_at": None,
    "finished_at": None,
    "duration_seconds": 0,
    "pid": None,
    "exit_code": None,
    "error_message": "",
    "log_file": ""
}


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
        return ["Nombre", "Usuario", "Estado"], []
    rows = read_csv_file(USERS_FILE)
    if not rows:
        return ["Nombre", "Usuario", "Estado"], []

    raw_headers = [str(h).strip() for h in rows[0]]
    if raw_headers:
        raw_headers[0] = re.sub(r'^[\ufeffï»¿"]+', '', raw_headers[0])

    header_lower = [h.lower() for h in raw_headers]
    name_idx = next((i for i, h in enumerate(header_lower) if "nombre" in h), 0)
    user_idx = next((i for i, h in enumerate(header_lower) if "usuario" in h), 1)
    snow_idx = next((i for i, h in enumerate(header_lower) if any(k in h for k in ("servicenow", "sys_id", "snow"))), None)
    estado_idx = next((i for i, h in enumerate(header_lower) if any(k in h for k in ("estado", "activo"))), None)

    if estado_idx is None:
        if len(raw_headers) == 3 and snow_idx is None:
            estado_idx = 2
        elif len(raw_headers) >= 4:
            estado_idx = 3

    if snow_idx is None and len(raw_headers) >= 4 and estado_idx != 2:
        snow_idx = 2

    result = []
    for r in rows[1:]:
        if not r or not any(x.strip() for x in r):
            continue
        nombre = r[name_idx].strip() if name_idx < len(r) else ""
        usuario = r[user_idx].strip() if user_idx < len(r) else ""
        if not usuario and not nombre:
            continue
        snow_id = r[snow_idx].strip() if (snow_idx is not None and snow_idx < len(r)) else ""
        estado_raw = r[estado_idx].strip() if (estado_idx is not None and estado_idx < len(r)) else "1"
        estado = "1" if estado_raw in ("1", "S", "s", "true", "True") else "0"

        result.append({
            "nombre": nombre,
            "usuario": usuario,
            "snow_id": snow_id,
            "estado": estado
        })
    return raw_headers, result


def save_users(users):
    orig_headers, _ = user_rows()
    orig_lower = [h.lower() for h in orig_headers]
    has_snow_header = any("servicenow" in h or "sys_id" in h or "snow" in h for h in orig_lower)
    has_any_snow = any(bool(str(u.get("snow_id", "")).strip()) for u in users)

    if has_snow_header or has_any_snow:
        headers = ["Nombre", "Usuario", "ServiceNow ID", "Estado"]
        rows = [headers]
        for u in users:
            rows.append([
                u.get("nombre", "").strip(),
                u.get("usuario", "").strip(),
                u.get("snow_id", "").strip(),
                "1" if str(u.get("estado", "1")).strip() == "1" else "0"
            ])
    else:
        headers = ["Nombre", "Usuario", "Estado"]
        rows = [headers]
        for u in users:
            rows.append([
                u.get("nombre", "").strip(),
                u.get("usuario", "").strip(),
                "1" if str(u.get("estado", "1")).strip() == "1" else "0"
            ])
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


def read_execution_summaries():
    ensure_execution_summary_csv(str(SALIDA_DIR))
    if not SUMMARY_FILE.exists():
        return []
    rows = []
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with SUMMARY_FILE.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f, delimiter=DELIM)
                for r in reader:
                    cleaned = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k}
                    rows.append(cleaned)
            break
        except Exception:
            continue

    # Sincronizar automáticamente con archivos .log en Salida/ que no hayan sido asentados aún
    registered_names = {Path(r.get("archivo_log", "")).name for r in rows if r.get("archivo_log")}
    from Programas.PipelineUtils import parse_log_summary

    for log_p in sorted(SALIDA_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime):
        if log_p.name not in registered_names:
            try:
                stats = parse_log_summary(str(log_p))
                mtime_str = datetime.fromtimestamp(log_p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                entry = {
                    "timestamp": mtime_str,
                    "tipo_ejecucion": "RPA_DOM" if "dom" in log_p.name else "INFERENCIA",
                    "estado": stats.get("estado", "EXITOSO"),
                    "duracion_seg": "0.0",
                    "tickets_procesados": str(stats.get("tickets_procesados", 0)),
                    "reintentos": str(stats.get("reintentos", 0)),
                    "advertencias": str(stats.get("advertencias", 0)),
                    "errores": str(stats.get("errores", 0)),
                    "motivo_error": stats.get("motivo_error", "Ninguno"),
                    "archivo_log": log_p.name
                }
                append_execution_summary(str(SALIDA_DIR), entry)
                rows.append(entry)
                registered_names.add(log_p.name)
            except Exception:
                pass

    return rows


def get_system_health(summaries, log_text=""):
    # 1. Analizar exhaustivamente el log actual en pantalla
    log_errors = 0
    log_warns = 0
    log_retries = 0
    log_cycle_retries = 0
    log_down_reason = ""
    is_periodic_waiting = False

    if log_text:
        err_matches = re.findall(r'(\[ERROR\]|\bRuntimeError:|\bTraceback \(most recent call last\):|\bFalla en la fase de descarga\b)', log_text, re.I)
        log_errors = len(err_matches)

        warn_matches = re.findall(r'(\[ADVERTENCIA\]|\bADVERTENCIA:|\bWarning:)', log_text, re.I)
        log_warns = len(warn_matches)

        # Reintentos en ServiceNow
        snow_retries = re.findall(r'\[VERIFICACI[OÓ]N\s*-\s*Intento\s*(\d+)/(\d+)\]', log_text, re.I)
        if snow_retries:
            log_retries += max(max(int(m[0]) - 1 for m in snow_retries), 0)

        # Reintentos consecutivos de ciclo periódico
        cycle_retries = re.findall(r'Intentos fallidos consecutivos:\s*(\d+)\s*de\s*(\d+)', log_text, re.I)
        if cycle_retries:
            log_cycle_retries = int(cycle_retries[-1][0])
            log_retries += log_cycle_retries

        if "Siguiente ejecución a las" in log_text and "Esperando" in log_text:
            is_periodic_waiting = True

        # Extraer motivo legible del último error
        err_candidates = [
            line.strip() for line in log_text.splitlines()
            if "[ERROR]" in line or "RuntimeError:" in line or "Falla en la fase de descarga" in line
        ]
        if err_candidates:
            clean_err = err_candidates[-1]
            clean_err = re.sub(r'^\[ERROR\]\s*(Ocurrió una excepción en el ciclo periódico:\s*)?', '', clean_err)
            log_down_reason = clean_err[:240]

    # 2. Analizar historial reciente
    recent = summaries[-10:] if summaries else []
    hist_retry_count = sum(int(r.get("reintentos", 0) or 0) for r in recent)
    hist_warning_count = sum(int(r.get("advertencias", 0) or 0) for r in recent)
    hist_error_count = sum(int(r.get("errores", 0) or 0) for r in recent)

    total_retries = max(hist_retry_count, log_retries)
    total_warnings = max(hist_warning_count, log_warns)
    total_errors = max(hist_error_count, log_errors)

    latest = summaries[-1] if summaries else {}
    last_status = latest.get("estado", "EXITOSO").upper()
    motivo = latest.get("motivo_error", "Ninguno")

    with pipeline_lock:
        pipe_status = pipeline_state.get("status", "idle")
        is_running = (pipe_status == "running")
        elapsed = 0
        if pipeline_state.get("started_at"):
            try:
                st = datetime.strptime(pipeline_state["started_at"], "%Y-%m-%d %H:%M:%S")
                elapsed = int((datetime.now() - st).total_seconds())
            except Exception:
                pass

        if pipe_status == "error":
            last_status = "ERROR_CRITICO"
            motivo = pipeline_state.get("error_message") or motivo

    # 3. Determinar métricas de la ejecución mostrada / activa
    has_cycle_error = (log_errors > 0 or log_cycle_retries > 0)

    # Las métricas en pantalla corresponden a la ejecución actual / log activo
    if log_text:
        active_retries = log_retries
        active_warnings = log_warns
        active_errors = log_errors
    else:
        active_retries = int(latest.get("reintentos", 0) or 0)
        active_warnings = int(latest.get("advertencias", 0) or 0)
        active_errors = int(latest.get("errores", 0) or 0)

    if is_running:
        if has_cycle_error:
            is_down = True
            down_reason = log_down_reason or "Error detectado en el ciclo actual"
            last_status = "ERROR"
        else:
            is_down = False
            down_reason = ""
            last_status = "EJECUTANDO"
    elif pipe_status == "stopped":
        is_down = False
        down_reason = ""
        last_status = "DETENIDO"
    else:
        # En reposo o finalizado
        if has_cycle_error and log_down_reason:
            motivo = log_down_reason
            last_status = "ERROR"
        is_down = last_status in ("ERROR", "ERROR_CRITICO") or (motivo != "Ninguno" and "error" in motivo.lower())
        down_reason = motivo if is_down else ""

    return {
        "is_running": is_running,
        "is_down": is_down,
        "cycle_error": has_cycle_error if is_running else False,
        "cycle_consecutive_failures": log_cycle_retries,
        "is_periodic_waiting": is_periodic_waiting,
        "status": last_status,
        "down_reason": down_reason,
        "elapsed_seconds": elapsed,
        "retry_count": active_retries,
        "cycle_retries": log_cycle_retries,
        "warning_count": active_warnings,
        "error_count": active_errors,
        "last_run_time": pipeline_state.get("started_at") if is_running else latest.get("timestamp", "Sin registro reciente"),
        "last_log": latest.get("archivo_log", "")
    }


def build_performance_metrics(user_display_map=None):
    if user_display_map is None:
        user_display_map = {}
    rows = read_report()
    if not rows:
        return {
            "workload": [],
            "models": [],
            "top_groups": [],
            "reassignments": {"total": 0, "reassigned": 0, "pct": 0.0}
        }

    user_counts = collections.Counter()
    model_counts = collections.Counter()
    group_counts = collections.Counter()
    total_tickets = len(rows)
    reassigned_count = 0

    for r in rows:
        person = (r.get("Person assigned") or "").strip()
        if person:
            user_counts[person] += 1

        mtype = (r.get("Model type") or "").strip()
        mname = (r.get("Model name") or "").strip()
        if "hnlp" in mtype.lower() or "hnlp" in mname.lower():
            model_label = "HNLP-MC (Multicanal Semisupervisado)"
        elif "logistic" in mname.lower() or "tfidf" in mtype.lower() or mtype.lower() == "semisupervised":
            model_label = "TF-IDF (Línea Base)"
        elif "svm" in mname.lower() or "supervised" in mtype.lower():
            model_label = "SVM (Supervisado)"
        elif mtype:
            model_label = mtype
        else:
            model_label = "Regla Operativa / Turno"
        model_counts[model_label] += 1

        group = (r.get("Predicted group") or "").strip()
        if group:
            group_counts[group] += 1

        prev = (r.get("Previous person assigned") or "").strip()
        if prev and prev.upper() != person.upper():
            reassigned_count += 1

    workload = [
        {
            "user": u,
            "label": user_display_map.get(u.lower(), user_display_map.get(u.upper(), u)),
            "count": cnt,
            "pct": round((cnt / total_tickets) * 100, 1) if total_tickets else 0
        }
        for u, cnt in user_counts.most_common(10)
    ]

    models = [
        {
            "name": m,
            "count": cnt,
            "pct": round((cnt / total_tickets) * 100, 1) if total_tickets else 0
        }
        for m, cnt in model_counts.most_common(6)
    ]

    top_groups = [
        {"group": g, "count": cnt}
        for g, cnt in group_counts.most_common(8)
    ]

    reassignments = {
        "total": total_tickets,
        "reassigned": reassigned_count,
        "pct": round((reassigned_count / total_tickets) * 100, 1) if total_tickets else 0.0
    }

    return {
        "workload": workload,
        "models": models,
        "top_groups": top_groups,
        "reassignments": reassignments
    }


def run_pipeline_worker(config):
    global pipeline_process, pipeline_state
    start_time = time.time()
    st_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Normalizar acción recibida
    action = str(config.get("action", config.get("mode", "6"))).strip()
    if action == "rpa_full":
        action = "5"
    elif action == "ml_only":
        action = "8"

    download = bool(config.get("download", True))
    dry_run = bool(config.get("dry_run", False))
    show_popup = bool(config.get("show_popup", True))
    popup_seconds = int(config.get("popup_seconds", 5))
    download_wait = float(config.get("download_wait", 10.0))
    load_time = float(config.get("load_time", 10.0))
    clipboard_time = float(config.get("clipboard_time", 1.0))
    interval_mins = float(config.get("interval_mins", 30.0))
    verification_wait = float(config.get("verification_wait", 30.0))
    close_browser_wait = float(config.get("close_browser_wait", 10.0))

    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["mode"] = action
        pipeline_state["started_at"] = st_str
        pipeline_state["finished_at"] = None
        pipeline_state["error_message"] = ""
        pipeline_state["exit_code"] = None
        pipeline_state["config"] = {
            "action": action,
            "download": download,
            "dry_run": dry_run,
            "show_popup": show_popup,
            "popup_seconds": popup_seconds,
            "download_wait": download_wait,
            "load_time": load_time,
            "clipboard_time": clipboard_time,
            "interval_mins": interval_mins,
            "verification_wait": verification_wait,
            "close_browser_wait": close_browser_wait
        }

    try:
        cmd = [
            sys.executable,
            str(ROOT_DIR / "RPA_ServiceNow_DOM_Web.py"),
            "--action", action,
            "--download" if download else "--skip-download",
            "--dry-run" if dry_run else "--no-dry-run",
            "--show-popup" if show_popup else "--no-popup",
            "--popup-seconds", str(popup_seconds),
            "--download-wait", str(download_wait),
            "--load-time", str(load_time),
            "--clipboard-time", str(clipboard_time),
            "--interval-mins", str(interval_mins),
            "--verification-wait", str(verification_wait),
            "--close-browser-wait", str(close_browser_wait),
        ]
        env = {**os.environ}
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        with pipeline_lock:
            pipeline_process = proc
            pipeline_state["pid"] = proc.pid

        stdout, _ = proc.communicate()
        return_code = proc.returncode

        duration = round(time.time() - start_time, 2)
        with pipeline_lock:
            pipeline_process = None
            pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pipeline_state["duration_seconds"] = duration
            pipeline_state["exit_code"] = return_code
            if pipeline_state["status"] != "stopped":
                if return_code == 0:
                    pipeline_state["status"] = "success"
                else:
                    pipeline_state["status"] = "error"
                    pipeline_state["error_message"] = f"El proceso finalizó con código de error {return_code}"

    except Exception as exc:
        duration = round(time.time() - start_time, 2)
        with pipeline_lock:
            pipeline_process = None
            pipeline_state["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pipeline_state["duration_seconds"] = duration
            pipeline_state["status"] = "error"
            pipeline_state["error_message"] = str(exc)


def stop_pipeline_process():
    global pipeline_process, pipeline_state
    with pipeline_lock:
        if pipeline_process and pipeline_process.poll() is None:
            try:
                pipeline_process.terminate()
                time.sleep(0.5)
                if pipeline_process.poll() is None:
                    pipeline_process.kill()
            except Exception:
                pass
            pipeline_state["status"] = "stopped"
            pipeline_state["error_message"] = "Proceso detenido manualmente por el usuario."
            pipeline_process = None
            return True
    return False


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
    summaries = read_execution_summaries()
    health = get_system_health(summaries, log_text)
    performance = build_performance_metrics(user_display_map)

    with pipeline_lock:
        current_pipeline = dict(pipeline_state)

    return jsonify(
        log=log_text,
        active_log=active_rel_path,
        active_log_size=log_size,
        available_logs=available_logs,
        incidentes=incidentes_data,
        requerimientos=requerimientos_data,
        pendientes=pending_tickets,
        health=health,
        performance=performance,
        pipeline=current_pipeline,
        summaries=summaries[-35:] if summaries else []
    )


@app.post("/api/pipeline/start")
def pipeline_start():
    d = request.get_json(silent=True) or {}
    with pipeline_lock:
        if pipeline_state["status"] == "running":
            return jsonify(error="Ya existe una ejecución en progreso."), 409

    t = threading.Thread(target=run_pipeline_worker, args=(d,), daemon=True)
    t.start()

    with pipeline_lock:
        action = pipeline_state.get("mode", "5")
        return jsonify(ok=True, message=f"Ejecución iniciada (Opción/Modo: {action}).", pipeline=dict(pipeline_state))


@app.post("/api/pipeline/stop")
def pipeline_stop():
    stopped = stop_pipeline_process()
    with pipeline_lock:
        return jsonify(ok=True, stopped=stopped, pipeline=dict(pipeline_state))


@app.get("/api/pipeline/status")
def pipeline_status():
    with pipeline_lock:
        return jsonify(pipeline=dict(pipeline_state))


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
    required = ["nombre", "usuario"]
    if any(not str(d.get(k, "")).strip() for k in required):
        return jsonify(error="Completa Nombre y Usuario."), 400
    _, users = user_rows()
    username = d["usuario"].strip()
    if any(u["usuario"].lower() == username.lower() for u in users):
        return jsonify(error="Ya existe un usuario con ese identificador."), 409
    estado = "1" if str(d.get("estado", "1")) == "1" else "0"
    u = {
        "nombre": d["nombre"].strip(),
        "usuario": username,
        "snow_id": str(d.get("snow_id", "")).strip(),
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
    dias_payload = d.get("dias", {})
    try:
        monday = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return jsonify(error="Fecha de inicio inválida."), 400
    if monday.weekday() != 0:
        return jsonify(error="Selecciona el lunes de la semana."), 400

    _, users = user_rows()
    known_users = {u["usuario"].lower() for u in users}

    headers, rows = read_shifts()
    date_col = "Fecha" if "Fecha" in headers else headers[0]

    for offset in range(7):
        day = monday + timedelta(days=offset)
        date_str = day.strftime("%d/%m/%Y")
        iso_str = day.strftime("%Y-%m-%d")
        row = next((r for r in rows if r.get(date_col, "").strip() in (date_str, iso_str)), None)
        if row is None:
            row = {h: "" for h in headers}
            row[date_col] = date_str
            rows.append(row)

        day_data = (dias_payload.get(date_str) or dias_payload.get(iso_str)) if dias_payload else None
        if day_data:
            for role in ROLES:
                val = day_data.get(role, "").strip()
                if val and val.lower() not in known_users:
                    return jsonify(error=f"'{val}' en {date_str} no existe en Grupos - Usuarios."), 400
                if role in headers:
                    row[role] = val
        else:
            # Lógica operativa estándar con espacios vacíos
            if offset < 5:  # Lunes a Viernes
                t1 = assignments.get("turno_1", assignments.get("Turno 1", "")).strip()
                t2 = assignments.get("turno_2", assignments.get("Turno 2", "")).strip()
                t3 = assignments.get("turno_3", assignments.get("Turno 3", "")).strip()
                for val in [t1, t2, t3]:
                    if val and val.lower() not in known_users:
                        return jsonify(error=f"'{val}' no existe en Grupos - Usuarios."), 400
                row["Turno 1"] = t1
                row["Turno 2"] = t2
                row["Turno 3"] = t3
                row["Turno 4"] = ""
                row["Stand-by"] = ""
            elif offset == 5:  # Sábado
                t4 = assignments.get("sabado_turno_4", assignments.get("Turno 4", "")).strip()
                sb = assignments.get("sabado_standby", assignments.get("Stand-by", "")).strip()
                for val in [t4, sb]:
                    if val and val.lower() not in known_users:
                        return jsonify(error=f"'{val}' no existe en Grupos - Usuarios."), 400
                row["Turno 1"] = ""
                row["Turno 2"] = ""
                row["Turno 3"] = ""
                row["Turno 4"] = t4
                row["Stand-by"] = sb
            else:  # Domingo
                sb = assignments.get("domingo_standby", assignments.get("Stand-by", "")).strip()
                if sb and sb.lower() not in known_users:
                    return jsonify(error=f"'{sb}' no existe en Grupos - Usuarios."), 400
                row["Turno 1"] = ""
                row["Turno 2"] = ""
                row["Turno 3"] = ""
                row["Turno 4"] = ""
                row["Stand-by"] = sb

    def parse_shift_date(r):
        val = r.get(date_col, "").strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(val, fmt)
            except Exception:
                pass
        return datetime.min

    rows.sort(key=parse_shift_date)
    save_shifts(headers, rows)
    return jsonify(ok=True, message=f"Turnos guardados correctamente para la semana del {monday.strftime('%d/%m/%Y')}.")


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
