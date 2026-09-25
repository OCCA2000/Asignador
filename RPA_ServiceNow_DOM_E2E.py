#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Herramienta RPA E2E DOM para Asignación en ServiceNow
Automatiza:
1. Descarga de listas de incidentes/requerimientos desde ServiceNow.
2. Ejecución de modelos de aprendizaje automático para asignación.
3. Actualización del campo Asignado a en ServiceNow inyectando código JavaScript
   a través de la consola DevTools del navegador (Ctrl+Shift+J) combinada con PyAutoGUI,
   evitando problemas de resolución de pantalla, zoom o adjuntos.
"""

import os
import glob
import sys
import time
import json
import shutil
import subprocess
import webbrowser
from datetime import datetime, timedelta
import pandas as pd
import pyautogui
import pyperclip
from Programas.PipelineUtils import (
    archive_previous_files,
    get_windows_date_format,
    ExecutionLogger,
    clean_all_input_csv_files,
    check_file_freshness,
    delete_unprocessed_input_files,
    get_retry_dataframe_from_assignment_report,
)

# ==========================================
# CONFIGURACIÓN
# ==========================================
SERVICENOW_BASE_URL = "https://bancopichincha.service-now.com"

# Determina si descargar archivos de ServiceNow o usar los existentes en Entrada/
SKIP_DOWNLOAD = True

# Modo seguro Dry Run: navegará e inyectará campos pero NO guardará el ticket si es True
DRY_RUN = True

# Tiempo de espera en segundos para que se completen las descargas cuando DRY_RUN = False
DOWNLOAD_WAIT_TIME = 5.0

# Ajustes de PyAutoGUI
pyautogui.FAILSAFE = True  # Mover cursor a la esquina superior izquierda para abortar ejecución
pyautogui.PAUSE = 0.8      # Pausa después de cada acción de GUI (en segundos)

# Configuraciones de espera
LOAD_TIME = 5.0            # Tiempo de espera para cargar la página del ticket
CLIPBOARD_TIME = 0.5       # Tiempo de espera tras copiar/pegar en la consola

# Ventana emergente de notificación antes de iniciar el proceso
SHOW_NOTIFICATION_POPUP = True
NOTIFICATION_COUNTDOWN_SECONDS = 5

# Cierre automático de todo el navegador al finalizar la iteración completa del ciclo (vía Alt+F4)
CLOSE_BROWSER_AT_END = True
CLOSE_BROWSER_WAIT_TIME = 10.0  # Tiempo de espera personalizable en segundos antes de cerrar el navegador al final

# Verificación y reasignación de tickets (solo cuando DRY_RUN = False)
VERIFICATION_WAIT_TIME = 60.0    # Tiempo de espera en segundos antes de verificar persistencia en ServiceNow
MAX_VERIFICATION_RETRIES = 2     # Número máximo de reintentos de reescritura

_notification_shown_this_cycle = False

def reset_notification_state():
    global _notification_shown_this_cycle
    _notification_shown_this_cycle = False

# Directorios de datos y configuración
ESPECIFICACIONES_DIR = "Especificaciones"
USUARIOS_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "Grupos - Usuarios.csv")
ENTRADA_DIR = "Entrada"
SALIDA_DIR = "Salida"

# ==========================================
# GESTIÓN DE NAVEGADOR INDEPENDIENTE (EDGE / CHROME)
# ==========================================
_browser_window_opened = False

def find_browser_executable():
    """
    Busca la ruta del ejecutable del navegador priorizando Microsoft Edge sobre Google Chrome.
    Devuelve (browser_path, browser_name).
    """
    # 1. Buscar Microsoft Edge
    edge_candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Microsoft\\Edge\\Application\\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Microsoft\\Edge\\Application\\msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft\\Edge\\Application\\msedge.exe"),
        shutil.which("msedge"),
        shutil.which("msedge.exe")
    ]
    for path in edge_candidates:
        if path and os.path.isfile(path):
            return path, "Edge"

    # 2. Buscar Google Chrome
    chrome_candidates = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Google\\Chrome\\Application\\chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Google\\Chrome\\Application\\chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google\\Chrome\\Application\\chrome.exe"),
        shutil.which("chrome"),
        shutil.which("chrome.exe")
    ]
    for path in chrome_candidates:
        if path and os.path.isfile(path):
            return path, "Chrome"

    return None, "Default"

def open_url_in_browser(url, force_new_window=False):
    """
    Abre una URL en una ventana de navegador independiente (priorizando Edge sobre Chrome).
    Si es la primera llamada o force_new_window=True, abre una nueva ventana (--new-window).
    De lo contrario, abre una nueva pestaña en esa ventana.
    """
    global _browser_window_opened
    browser_path, browser_name = find_browser_executable()
    
    if browser_path:
        try:
            if not _browser_window_opened or force_new_window:
                print(f"[NAVEGADOR] Abriendo NUEVA VENTANA independiente en {browser_name} ({browser_path})...")
                subprocess.Popen([browser_path, "--new-window", url])
                _browser_window_opened = True
            else:
                print(f"[NAVEGADOR] Abriendo pestaña en {browser_name}...")
                subprocess.Popen([browser_path, url])
            return True
        except Exception as e:
            print(f"[ERROR] No se pudo lanzar {browser_name}: {e}. Usando navegador predeterminado del sistema.")

    if not _browser_window_opened or force_new_window:
        webbrowser.open_new(url)
        _browser_window_opened = True
    else:
        webbrowser.open(url, new=2)
    return False

# ==========================================
# VENTANA EMERGENTE DE NOTIFICACIÓN DE INICIO
# ==========================================
def show_pre_start_notification(seconds=NOTIFICATION_COUNTDOWN_SECONDS):
    """
    Muestra una ventana emergente (Topmost) de aviso 5 segundos antes de que el proceso inicie,
    para que el usuario sepa que debe soltar el teclado/mouse si está ocupado.
    Se muestra ÚNICAMENTE UNA VEZ por ciclo de ejecución para evitar alertas repetidas.
    """
    global _notification_shown_this_cycle
    if not SHOW_NOTIFICATION_POPUP or seconds <= 0 or _notification_shown_this_cycle:
        return

    _notification_shown_this_cycle = True
    print(f"\n[NOTIFICACIÓN] Desplegando ventana emergente ({seconds}s antes de iniciar)...")
    
    try:
        import tkinter as tk
        
        root = tk.Tk()
        root.title("⚠️ Atención: Automatización RPA ServiceNow")
        root.attributes("-topmost", True)
        root.geometry("460x190")
        root.resizable(False, False)
        
        # Centrar ventana en la pantalla
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f'+{x}+{y}')
        
        # Diseño visual de la alerta
        root.configure(bg='#1e1e2e')
        
        lbl_title = tk.Label(
            root, 
            text="⚠️ AUTOMATIZACIÓN RPA A PUNTO DE INICIAR", 
            font=("Arial", 11, "bold"), 
            fg="#f38ba8", 
            bg="#1e1e2e",
            pady=12
        )
        lbl_title.pack()
        
        lbl_msg = tk.Label(
            root, 
            text="El proceso tomará el control del navegador y teclado.\nPor favor, deje de interactuar para evitar interrupciones.", 
            font=("Arial", 9), 
            fg="#cdd6f4", 
            bg="#1e1e2e"
        )
        lbl_msg.pack()
        
        lbl_timer = tk.Label(
            root, 
            text=f"El proceso iniciará en {seconds} segundos...", 
            font=("Arial", 11, "bold"), 
            fg="#fab387", 
            bg="#1e1e2e",
            pady=12
        )
        lbl_timer.pack()
        
        remaining = [seconds]
        
        def update_countdown():
            if remaining[0] > 1:
                remaining[0] -= 1
                lbl_timer.config(text=f"El proceso iniciará en {remaining[0]} segundos...")
                root.after(1000, update_countdown)
            else:
                root.destroy()
                
        root.after(1000, update_countdown)
        root.mainloop()
        
    except Exception as e:
        print(f"[ADVERTENCIA] No se pudo desplegar la ventana gráfica ({e}). Usando temporizador de consola.")
        for i in range(seconds, 0, -1):
            print(f"El proceso iniciará en {i} segundos...")
            time.sleep(1)

# ==========================================
# CIERRE DE NAVEGADOR AL FINAL DE LA ITERACIÓN
# ==========================================
def close_browser_at_end():
    """
    Al finalizar TODA la iteración del ciclo, si CLOSE_BROWSER_AT_END es True y DRY_RUN es False,
    espera CLOSE_BROWSER_WAIT_TIME segundos y cierra la ventana del navegador con Alt+F4.
    """
    global _browser_window_opened
    if not _browser_window_opened:
        return

    if CLOSE_BROWSER_AT_END and not DRY_RUN:
        print(f"\n[FINAL DE CICLO] Esperando {CLOSE_BROWSER_WAIT_TIME} segundos antes de cerrar la ventana del navegador (Alt+F4)...")
        time.sleep(CLOSE_BROWSER_WAIT_TIME)
        print("[FINAL DE CICLO] Cerrando ventana del navegador con Alt+F4...")
        pyautogui.hotkey('alt', 'f4')
        time.sleep(1.0)
        _browser_window_opened = False
    else:
        if DRY_RUN:
            print(f"\n[DRY_RUN=True] El navegador y sus pestañas se mantienen abiertos para revisión y guardado manual.")
        else:
            print(f"\n[CONFIG] Cierre automático del navegador desactivado (CLOSE_BROWSER_AT_END=False).")

# ==========================================
# CARGA DE MAPEO DE USUARIOS
# ==========================================
def load_user_id_map():
    """
    Carga el archivo Grupos - Usuarios.csv y crea un diccionario de mapeo de 
    Nombre/Usuario -> ServiceNow ID.
    """
    user_map = {}
    if not os.path.exists(USUARIOS_CONFIG_FILE):
        print(f"[ADVERTENCIA] No se encontró el archivo de usuarios '{USUARIOS_CONFIG_FILE}'.")
        return user_map
        
    try:
        df_users = pd.read_csv(USUARIOS_CONFIG_FILE, sep=';', dtype=str, encoding='utf-8-sig')
    except Exception:
        try:
            df_users = pd.read_csv(USUARIOS_CONFIG_FILE, sep=';', dtype=str, encoding='latin-1')
        except Exception as e:
            print(f"[ERROR] No se pudo leer '{USUARIOS_CONFIG_FILE}': {e}")
            return user_map

    for _, row in df_users.iterrows():
        nombre = str(row.get('Nombre', '')).strip()
        usuario = str(row.get('Usuario', '')).strip()
        sys_id = str(row.get('ServiceNow ID', '')).strip()
        
        if sys_id and sys_id.lower() != 'nan':
            if nombre:
                user_map[nombre.upper()] = sys_id
            if usuario:
                user_map[usuario.lower()] = sys_id
                
    print(f"Cargados {len(user_map)} mapeos de ServiceNow ID desde {USUARIOS_CONFIG_FILE}.")
    return user_map

def load_config_parameters():
    """
    Carga el archivo rpa_config_parameters.json y devuelve un diccionario
    con configuraciones generales de ServiceNow (por ejemplo, Sys IDs de CIs).
    """
    config_file = os.path.join(ESPECIFICACIONES_DIR, "rpa_config_parameters.json")
    if not os.path.exists(config_file):
        return {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] No se pudo leer '{config_file}': {e}")
        return {}

# ==========================================
# UTILIDADES DE ARCHIVOS
# ==========================================
def get_downloads_folder():
    """Resuelve la ruta a la carpeta Descargas por defecto del usuario."""
    return os.path.join(os.path.expanduser("~"), "Downloads")

def move_latest_download(pattern, destination_name, min_mtime=None, max_age_seconds=None, timeout_seconds=None):
    """
    Busca la descarga más reciente que coincida con un patrón en Descargas,
    valida que sea reciente (frescura/timestamp) y la mueve a Entrada/destination_name.
    Si se proporciona timeout_seconds, sondea periódicamente hasta encontrar un archivo reciente o agotarse el tiempo.
    """
    downloads_dir = get_downloads_folder()
    search_path = os.path.join(downloads_dir, pattern)
    
    poll_timeout = float(timeout_seconds) if timeout_seconds is not None else 0.0
    poll_interval = 1.0
    start_poll = time.time()
    last_reason = "No se encontraron archivos coincidentes"

    while True:
        files = glob.glob(search_path)
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            latest_file = files[0]
            
            is_fresh, reason = check_file_freshness(latest_file, min_mtime=min_mtime, max_age_seconds=max_age_seconds)
            last_reason = reason
            if is_fresh:
                dest_path = os.path.join(ENTRADA_DIR, destination_name)
                os.makedirs(ENTRADA_DIR, exist_ok=True)
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                try:
                    shutil.move(latest_file, dest_path)
                    print(f"Archivo descargado reciente movido con éxito: {latest_file} -> {dest_path}")
                    return True
                except Exception as e:
                    print(f"[ERROR] Error al mover el archivo {latest_file}: {e}")
                    return False
        
        elapsed = time.time() - start_poll
        if elapsed >= poll_timeout:
            break
        time.sleep(min(poll_interval, poll_timeout - elapsed))

    # Si se llegó aquí, no se encontró un archivo fresco dentro del tiempo
    print(f"[ERROR] No se obtuvo una descarga válida y reciente para '{pattern}'. Razón: {last_reason}")
    return False

def find_latest_output_file(pattern, min_mtime=None):
    """Devuelve la ruta al CSV de predicción más reciente en la raíz de Salida/."""
    search_path = os.path.join(SALIDA_DIR, pattern)
    files = [f for f in glob.glob(search_path) if os.path.isfile(f)]
    
    if min_mtime is not None:
        files = [f for f in files if os.path.getmtime(f) >= min_mtime]

    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

# ==========================================
# EJECUTORES DE PREDICCIÓN Y DESCARGA
# ==========================================
# UTILIDADES DE DESCARGA Y NAVEGACIÓN
# ==========================================
def resolve_url(url, default_url):
    """Resuelve la URL absoluta para ServiceNow asegurando el parámetro &CSV."""
    if not url:
        return default_url
    if not url.startswith("http"):
        url = f"{SERVICENOW_BASE_URL.rstrip('/')}/{url.lstrip('/')}"
    if "CSV" not in url.upper():
        if "?" in url:
            url = url + "CSV" if url.endswith("&") else url + "&CSV"
        else:
            url = url + "?CSV"
    return url

def run_downloads(download_incidents=True, download_requirements=True, min_mtime=None):
    """Maneja la descarga de tickets desde ServiceNow con validación estricta de timestamps y eliminación preventiva."""
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
    print("\n" + "="*50)
    print("              1. FASE DE DESCARGA DE CSV")
    print("="*50)
    
    config_params = load_config_parameters()
    max_age_seconds = config_params.get("max_download_age_seconds", 300)
    
    # Eliminación preventiva: borrar incident.csv y sc_req_item.csv residuales en Entrada/
    delete_unprocessed_input_files(ENTRADA_DIR, ["incident.csv", "sc_req_item.csv"])
    
    download_errors = []
    
    if download_incidents:
        inc_start = time.time()
        effective_min_mtime = min_mtime if min_mtime is not None else inc_start
        default_incident = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=assignment_group=e6313131f874ee55056b262c30cbb3551^ORassignment_group=36ea16e087548210f2e1cbf80cbb35fd^assigned_toISEMPTY^stateIN1,2&CSV"
        incident_url = resolve_url(config_params.get("incident_download_url"), default_incident)
        print(f"Abriendo lista de incidentes en navegador independiente: {incident_url}")
        open_url_in_browser(incident_url)
        print("Se abrió la ventana del navegador.")
        if DRY_RUN:
            input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
            wait_timeout = DOWNLOAD_WAIT_TIME
        else:
            print(f"Esperando hasta {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
            wait_timeout = DOWNLOAD_WAIT_TIME
        
        moved = move_latest_download(
            "*incident*.csv",
            "incident.csv",
            min_mtime=effective_min_mtime,
            max_age_seconds=max_age_seconds,
            timeout_seconds=wait_timeout
        )
        dest_inc = os.path.join(ENTRADA_DIR, "incident.csv")
        fresh, reason = check_file_freshness(dest_inc, min_mtime=effective_min_mtime, max_age_seconds=max_age_seconds)
        if not moved or not fresh:
            err = f"Descarga fallida o inválida para Incidentes ({dest_inc}): {reason if not fresh else 'No se pudo mover el archivo reciente'}"
            print(f"[ERROR] {err}")
            download_errors.append(err)
            
    if download_requirements:
        req_start = time.time()
        effective_min_mtime = min_mtime if min_mtime is not None else req_start
        default_req = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=assignment_group=36ea16e087548210f2e1cbf80cbb35fd^ORassignment_group=e6313131f874ee55056b262c30cbb3551^state=1^assigned_toISEMPTY&CSV"
        req_url = resolve_url(config_params.get("requirement_download_url"), default_req)
        print(f"\nAbriendo lista de requerimientos en navegador independiente: {req_url}")
        open_url_in_browser(req_url)
        print("Se abrió la ventana del navegador.")
        if DRY_RUN:
            input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
            wait_timeout = DOWNLOAD_WAIT_TIME
        else:
            print(f"Esperando hasta {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
            wait_timeout = DOWNLOAD_WAIT_TIME
        
        moved = move_latest_download(
            "*sc_req_item*.csv",
            "sc_req_item.csv",
            min_mtime=effective_min_mtime,
            max_age_seconds=max_age_seconds,
            timeout_seconds=wait_timeout
        )
        dest_req = os.path.join(ENTRADA_DIR, "sc_req_item.csv")
        fresh, reason = check_file_freshness(dest_req, min_mtime=effective_min_mtime, max_age_seconds=max_age_seconds)
        if not moved or not fresh:
            err = f"Descarga fallida o inválida para Requerimientos ({dest_req}): {reason if not fresh else 'No se pudo mover el archivo reciente'}"
            print(f"[ERROR] {err}")
            download_errors.append(err)

    if download_errors:
        full_err_msg = " | ".join(download_errors)
        raise RuntimeError(f"Falla en la fase de descarga de ServiceNow: {full_err_msg}")

def run_subprocess_logged(cmd, cwd=None):
    """Ejecuta un subproceso transmitiendo stdout/stderr a sys.stdout en tiempo real."""
    env_vars = {**os.environ, "DISABLE_EXECUTION_LOGGER": "1"}
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, env=env_vars)
    for line in process.stdout:
        sys.stdout.write(line)
    process.wait()
    sys.stdout.flush()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)

def run_predictions(run_incidents=True, run_requirements=True):
    """Ejecuta los scripts de predicción de aprendizaje automático."""
    print("\n" + "="*50)
    print("              2. FASE DE MODELOS DE PREDICCIÓN")
    print("="*50)
    
    # Saneamiento previo de archivos de entrada en Entrada/ (Idempotente)
    try:
        clean_all_input_csv_files(directories=["Entrada"], verbose=False)
    except Exception as e:
        print(f"Advertencia: no se pudo verificar codificación de archivos de Entrada/: {e}")
    
    archive_previous_files(SALIDA_DIR, "*.csv")
    archive_previous_files(SALIDA_DIR, "*.txt")
    archive_previous_files(SALIDA_DIR, "*.log")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if run_incidents:
        print("Running Assigner_Incidents.py...")
        try:
            run_subprocess_logged([sys.executable, os.path.join(script_dir, "Assigner_Incidents.py")], cwd=script_dir)
            print("Incident predictions complete!")
        except subprocess.CalledProcessError as e:
            print(f"Error executing Assigner_Incidents.py: {e}")
            
    if run_requirements:
        print("\nRunning Assigner_Requirements.py...")
        try:
            run_subprocess_logged([sys.executable, os.path.join(script_dir, "Assigner_Requirements.py")], cwd=script_dir)
            print("Requirement predictions complete!")
        except subprocess.CalledProcessError as e:
            print(f"Error executing Assigner_Requirements.py: {e}")

# ==========================================
# GENERADOR DE PAYLOADS JAVASCRIPT DOM
# ==========================================
def clean_js(js_code):
    clean_lines = []
    for line in js_code.splitlines():
        line_clean = line.split("//")[0].strip()
        if line_clean:
            clean_lines.append(line_clean)
    return " ".join(clean_lines)

def build_js_payload(is_requirement, assignee_name, sys_id, due_date_str="", app_sys_id=""):
    """
    Construye la función ejecutable en JS para la consola DevTools de ServiceNow.
    """
    submit_code = """
        if (typeof gsftSubmit !== 'undefined') {
            gsftSubmit(document.getElementById('sysverb_update'));
        } else if (document.getElementById('sysverb_update')) {
            document.getElementById('sysverb_update').click();
        }
    """ if not DRY_RUN else "console.log('[DRY_RUN] Campos actualizados mediante DOM. Guardado omitido.');"

    assignee_clean = str(assignee_name).replace("'", "\\'")
    sys_id_clean = str(sys_id).replace("'", "\\'") if sys_id else ""
    app_sys_id_clean = str(app_sys_id).replace("'", "\\'") if app_sys_id else ""

    if not is_requirement:
        # INCIDENTES
        js = f"""(function() {{
            var sysId = '{sys_id_clean}';
            var name = '{assignee_clean}';
            
            if (typeof g_form !== 'undefined') {{
                try {{
                    if (sysId) {{ g_form.setValue('assigned_to', sysId, name); }}
                    else {{ g_form.setValue('assigned_to', name); }}
                }} catch(e) {{}}
            }}
            
            /* 1. Campo de ID oculto (incident.assigned_to) */
            var hid = document.getElementById('incident.assigned_to');
            if (hid) {{
                if (sysId) {{ hid.value = sysId; }}
                hid.dispatchEvent(new Event('change', {{ bubbles: true }}));
                if (typeof onChange === 'function') {{
                    try {{ onChange('incident.assigned_to'); }} catch(e) {{}}
                }}
            }}
            
            /* 2. Campo de texto visible (sys_display.incident.assigned_to) */
            var disp = document.getElementById('sys_display.incident.assigned_to');
            if (disp) {{
                disp.value = name;
                disp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                disp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                disp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }}
            
            /* 3. Campo de texto original (sys_display.original.incident.assigned_to) */
            var orig = document.getElementById('sys_display.original.incident.assigned_to');
            if (orig) {{
                orig.value = name;
            }}
            
            {submit_code}
        }})();"""
    else:
        # REQUERIMIENTOS
        due_clean = str(due_date_str).replace("'", "\\'")
        js = f"""(function() {{
            var sysId = '{sys_id_clean}';
            var name = '{assignee_clean}';
            var dueStr = '{due_clean}';
            var appSysId = '{app_sys_id_clean}';
            var appName = 'Bancs';
            
            /* 1. Asignado a */
            if (typeof g_form !== 'undefined') {{
                try {{
                    if (sysId) {{ g_form.setValue('assigned_to', sysId, name); }}
                    else {{ g_form.setValue('assigned_to', name); }}
                }} catch(e) {{}}
            }}
            var hid = document.getElementById('sc_req_item.assigned_to');
            if (hid) {{
                if (sysId) {{ hid.value = sysId; }}
                hid.dispatchEvent(new Event('change', {{ bubbles: true }}));
                if (typeof onChange === 'function') {{
                    try {{ onChange('sc_req_item.assigned_to'); }} catch(e) {{}}
                }}
            }}
            var disp = document.getElementById('sys_display.sc_req_item.assigned_to');
            if (disp) {{
                disp.value = name;
                disp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                disp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                disp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }}
            var orig = document.getElementById('sys_display.original.sc_req_item.assigned_to');
            if (orig) {{ orig.value = name; }}
            
            /* 2. Elemento de configuración (configuration_item -> Bancs) */
            if (typeof g_form !== 'undefined') {{
                try {{
                    if (appSysId) {{ g_form.setValue('configuration_item', appSysId, appName); }}
                    else {{ g_form.setValue('configuration_item', appName); }}
                }} catch(e) {{}}
            }}
            var appDisp = document.getElementById('sys_display.sc_req_item.configuration_item');
            if (appDisp) {{
                appDisp.value = appName;
                appDisp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                appDisp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                appDisp.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            }}
            var appOrig = document.getElementById('sys_display.original.sc_req_item.configuration_item');
            if (appOrig) {{ appOrig.value = appName; }}
            
            /* 3. Estado -> En proceso ('2') */
            if (typeof g_form !== 'undefined') {{
                try {{ g_form.setValue('state', '2'); }} catch(e) {{}}
            }}
            var st = document.getElementById('sc_req_item.state');
            if (st) {{
                st.value = '2';
                st.dispatchEvent(new Event('change', {{ bubbles: true }}));
                if (typeof onChange === 'function') {{
                    try {{ onChange('sc_req_item.state'); }} catch(e) {{}}
                }}
            }}
            
            /* 4. Polling dinámico para esperar que se resuelva la CMDB y se active due_date */
            var checkCount = 0;
            var maxChecks = 30;
            
            function proceedIfReady() {{
                var hiddenCi = document.getElementById('sc_req_item.configuration_item');
                var dueField = document.getElementById('sc_req_item.u_fecha_prevista_de_finalizaci_n');
                var ciReady = appSysId || (hiddenCi && hiddenCi.value !== '');
                var dueReady = (dueField && (dueField.offsetWidth > 0 || dueField.offsetHeight > 0) && !dueField.disabled);
                
                if ((ciReady && dueReady) || checkCount >= maxChecks) {{
                    if (dueField && dueStr) {{
                        if (typeof g_form !== 'undefined') {{
                            try {{ g_form.setValue('u_fecha_prevista_de_finalizaci_n', dueStr); }} catch(e) {{}}
                        }}
                        dueField.value = dueStr;
                        dueField.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        dueField.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        dueField.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    }}
                    setTimeout(function() {{
                        {submit_code}
                    }}, 300);
                }} else {{
                    checkCount++;
                    setTimeout(proceedIfReady, 100);
                }}
            }}
            setTimeout(proceedIfReady, 100);
        }})();"""

    return clean_js(js)

# ==========================================
# ACTUALIZACIÓN DE TICKETS VÍA DEVTOOLS CONSOLE
# ==========================================
# ACTUALIZACIÓN DE TICKETS VÍA DEVTOOLS CONSOLE
# ==========================================
def update_tickets_in_servicenow_dom(csv_path_or_df, is_requirement=False):
    """
    Lee las asignaciones y actualiza los tickets abriendo la consola DevTools (Ctrl+Shift+J)
    e inyectando JavaScript directamente.
    Acepta una ruta a archivo CSV o directamente un DataFrame de pandas.
    Devuelve la lista de IDs de tickets procesados exitosamente.
    """
    if csv_path_or_df is None:
        return []
        
    user_map = load_user_id_map()
    config_params = load_config_parameters()
    app_sys_ids = config_params.get("configuration_items", {})
    
    if isinstance(csv_path_or_df, pd.DataFrame):
        df = csv_path_or_df.copy()
        print(f"\nProcessing assignments DOM-mode from DataFrame ({len(df)} records)...")
    else:
        csv_path = csv_path_or_df
        if not csv_path or not os.path.exists(csv_path):
            print("No prediction file found for processing.")
            return []
            
        print(f"\nProcessing assignments DOM-mode from: {csv_path}")
        df = None
        for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
            try:
                df = pd.read_csv(csv_path, sep=';', encoding=enc, dtype=str)
                break
            except Exception:
                continue
        if df is None:
            df = pd.read_csv(csv_path, sep=';', encoding='latin-1', dtype=str)

    import re
    df.columns = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df.columns]
    
    num_col = next((c for c in ['number', 'Number', 'id', 'ticket_id', 'Ticket identification'] if c in df.columns), None)
    assign_col = next((c for c in ['predicted_assigned_to', 'Person assigned', 'assigned_to'] if c in df.columns), None)
    
    if not num_col or not assign_col or assign_col not in df.columns:
        print("Error: Required columns ('number' and 'predicted_assigned_to') not found in prediction output.")
        return []
        
    tickets_to_process = df.dropna(subset=[num_col, assign_col])
    print(f"Found {len(tickets_to_process)} tickets with predicted assignments.")
    
    if len(tickets_to_process) == 0:
        return []
        
    print("\n" + "!"*50)
    print(f"      RPA DEVTOOLS DOM UPDATE WILL START IN {NOTIFICATION_COUNTDOWN_SECONDS} SECONDS")
    print("  Make sure your browser window responds to hotkeys.")
    print("!"*50)
    
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
        
    table_name = "sc_req_item" if is_requirement else "incident"
    processed_ticket_ids = []
    
    for idx, row in tickets_to_process.iterrows():
        ticket_id = str(row[num_col]).strip()
        assignee = str(row[assign_col]).strip()
        
        if not assignee or assignee.lower() == 'nan':
            print(f"Skipping ticket {ticket_id}: Assignee is empty.")
            continue
            
        # Buscar ServiceNow ID
        sys_id = user_map.get(assignee.upper()) or user_map.get(assignee.lower(), "")
        print(f"\n>>> Updating {ticket_id} -> Assignee: {assignee} (Sys_ID: '{sys_id}') (DRY_RUN={DRY_RUN})")
        
        due_date_str = ""
        if is_requirement:
            due_date = row.get('fecha_resolucion')
            if (due_date is None or pd.isna(due_date) or not str(due_date).strip()) and 'Predicted end date' in row:
                due_date = row.get('Predicted end date')
            if pd.notna(due_date) and str(due_date).strip():
                win_fmt = get_windows_date_format()
                formats_to_try = (
                    f"{win_fmt} %H:%M:%S",
                    win_fmt,
                    '%Y-%m-%d %H:%M:%S',
                    '%d/%m/%Y %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S.%f',
                    '%Y-%m-%d',
                    '%d/%m/%Y'
                )
                for fmt in formats_to_try:
                    try:
                        dt = datetime.strptime(str(due_date).strip(), fmt)
                        due_date_str = dt.strftime('%d/%m/%Y %H:%M:%S')
                        break
                    except ValueError:
                        continue
                if not due_date_str:
                    due_date_str = str(due_date).strip()
            else:
                due_date_dt = datetime.now() + timedelta(days=30)
                due_date_str = due_date_dt.strftime('%d/%m/%Y %H:%M:%S')
                
        # Obtener el Sys ID de la aplicación si aplica (solo requerimientos)
        app_sys_id = app_sys_ids.get("Bancs", "") if is_requirement else ""
        
        # Construir JavaScript payload
        js_payload = build_js_payload(is_requirement, assignee, sys_id, due_date_str, app_sys_id)
        
        # 1. Abrir ticket en el navegador independiente
        ticket_url = f"{SERVICENOW_BASE_URL}/{table_name}.do?sysparm_query=number={ticket_id}"
        open_url_in_browser(ticket_url)
        time.sleep(LOAD_TIME)
        
        ticket_success = False
        try:
            # 2. Abrir consola DevTools (Ctrl+Shift+J)
            pyautogui.hotkey('ctrl', 'shift', 'j')
            time.sleep(1.0)
            
            # 3. Copiar script JS al portapapeles y pegar en la consola
            pyperclip.copy(js_payload)
            time.sleep(CLIPBOARD_TIME)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(CLIPBOARD_TIME)
            pyautogui.press('enter')
            time.sleep(1.5)
            
            ticket_success = True
        except Exception as err:
            print(f"[ERROR] Falló la actualización DOM del ticket {ticket_id}: {err}")
            ticket_success = False

        # 4. Gestión de pestañas y finalización de ticket
        if ticket_success:
            print(f"Inyección completada exitosamente para el ticket {ticket_id}.")
            processed_ticket_ids.append(ticket_id)
        else:
            print(f"[ADVERTENCIA] Proceso incompleto o con errores en el ticket {ticket_id}.")
        
    print("\nServiceNow DevTools DOM update loop finished!")
    return processed_ticket_ids


def check_servicenow_tickets_status(ticket_ids: list, is_requirement: bool = False, timeout_seconds: float = DOWNLOAD_WAIT_TIME) -> tuple:
    """
    Descarga exclusivamente los tickets especificados en ticket_ids desde ServiceNow
    usando sysparm_query=numberIN<id1>,<id2>...&CSV y verifica cuáles de ellos
    aún no tienen asignatario (assigned_to vacío) o no figuran en la descarga.
    
    Devuelve (éxito: bool, lista_de_tickets_sin_asignar: list).
    """
    if not ticket_ids:
        return True, []
        
    config_params = load_config_parameters()
    table_name = "sc_req_item" if is_requirement else "incident"
    pattern = "*sc_req_item*.csv" if is_requirement else "*incident*.csv"
    dest_name = "verify_sc_req_item.csv" if is_requirement else "verify_incident.csv"
    dest_path = os.path.join(ENTRADA_DIR, dest_name)
    
    # Query específico: solo los tickets asignados en este ciclo para evitar incluir tickets nuevos creados por otros usuarios
    numbers_str = ",".join(str(t).strip() for t in ticket_ids if str(t).strip())
    verify_url = f"{SERVICENOW_BASE_URL}/{table_name}_list.do?sysparm_query=numberIN{numbers_str}&CSV"
    
    print(f"\n[VERIFICACIÓN] Descargando estado de {len(ticket_ids)} {'requerimientos' if is_requirement else 'incidentes'} desde ServiceNow...")
    print(f"URL de verificación: {verify_url}")
    
    check_start = time.time()
    open_url_in_browser(verify_url)
    
    max_age_seconds = config_params.get("max_download_age_seconds", 300)
    moved = move_latest_download(
        pattern,
        dest_name,
        min_mtime=check_start,
        max_age_seconds=max_age_seconds,
        timeout_seconds=timeout_seconds
    )
    
    if not moved or not os.path.exists(dest_path):
        print(f"[ADVERTENCIA] No se pudo obtener la descarga de verificación para {table_name}. Se conservarán como pendientes.")
        return False, list(ticket_ids)
        
    df = None
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            df = pd.read_csv(dest_path, sep=';', encoding=enc, dtype=str)
            break
        except Exception:
            continue
    if df is None:
        try:
            df = pd.read_csv(dest_path, sep=';', encoding='latin-1', dtype=str)
        except Exception as e:
            print(f"[ERROR] No se pudo leer archivo de verificación {dest_path}: {e}")
            if os.path.exists(dest_path):
                try: os.remove(dest_path)
                except Exception: pass
            return False, list(ticket_ids)
            
    import re
    df.columns = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df.columns]
    num_col = next((c for c in ['number', 'Number', 'id', 'ticket_id', 'Ticket identification'] if c in df.columns), None)
    assign_col = next((c for c in ['assigned_to', 'Assigned to', 'assigned_to_name'] if c in df.columns), None)
    
    downloaded_map = {}
    if num_col and not df.empty:
        for _, row in df.iterrows():
            val_id = str(row[num_col]).strip().upper()
            if val_id and val_id != 'NAN':
                downloaded_map[val_id] = row
                
    still_unassigned = []
    for t_id in ticket_ids:
        t_norm = str(t_id).strip().upper()
        if t_norm not in downloaded_map:
            print(f"  [PENDIENTE] Ticket {t_id}: no retornado en la consulta de ServiceNow.")
            still_unassigned.append(t_id)
        else:
            row = downloaded_map[t_norm]
            if assign_col:
                val_assignee = row.get(assign_col)
                if pd.isna(val_assignee) or not str(val_assignee).strip() or str(val_assignee).strip().lower() in ('nan', 'none', 'null'):
                    print(f"  [PENDIENTE] Ticket {t_id}: campo '{assign_col}' está vacío en ServiceNow.")
                    still_unassigned.append(t_id)
                else:
                    print(f"  [CONFIRMADO] Ticket {t_id}: asignado a '{str(val_assignee).strip()}'.")
            else:
                print(f"  [PENDIENTE] Ticket {t_id}: columna de asignatario no disponible en CSV descargado.")
                still_unassigned.append(t_id)
                
    # Limpiar archivo temporal de verificación
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass
            
    return True, still_unassigned


def verify_and_reassign_tickets(processed_incidents: list = None, processed_requirements: list = None):
    """
    Verifica si los tickets asignados en el ciclo efectivamente quedaron guardados
    en ServiceNow tras un lapso de espera (por defecto 1 minuto / 60 segundos).
    Si DRY_RUN es True o no hay tickets procesados, no realiza acción.
    
    Descarga exclusivamente los tickets procesados y si alguno permanece sin asignatario,
    consulta 'Salida/reporte_detalle_asignaciones.csv' y reescribe los datos en ServiceNow.
    Permite hasta MAX_VERIFICATION_RETRIES reintentos.
    """
    global DRY_RUN
    if DRY_RUN:
        return
        
    pending_incidents = [str(t).strip() for t in (processed_incidents or []) if str(t).strip()]
    pending_requirements = [str(t).strip() for t in (processed_requirements or []) if str(t).strip()]
    
    total_to_verify = len(pending_incidents) + len(pending_requirements)
    if total_to_verify == 0:
        return
        
    config_params = load_config_parameters()
    wait_time = float(config_params.get("verification_wait_seconds", VERIFICATION_WAIT_TIME))
    max_retries = int(config_params.get("max_verification_retries", MAX_VERIFICATION_RETRIES))
    
    print("\n" + "="*60)
    print("      VERIFICACIÓN DE ASIGNACIONES EN SERVICENOW")
    print(f"      Tickets a verificar: {len(pending_incidents)} incidentes, {len(pending_requirements)} requerimientos")
    print(f"      Tiempo de asentamiento: {int(wait_time)}s | Reintentos máximos: {max_retries}")
    print("="*60)
    
    for attempt in range(1, max_retries + 1):
        print(f"\n[VERIFICACIÓN - Intento {attempt}/{max_retries}] Esperando {int(wait_time)} segundos para asentamiento en ServiceNow...")
        wait_rem = int(wait_time)
        try:
            while wait_rem > 0:
                step = min(10, wait_rem)
                time.sleep(step)
                wait_rem -= step
                if wait_rem > 0:
                    print(f"Verificando en {wait_rem} segundos...")
        except KeyboardInterrupt:
            print("\n[VERIFICACIÓN] Espera interrumpida por el usuario (Ctrl+C). Omitiendo verificación restante.")
            break
            
        unassigned_incidents = []
        if pending_incidents:
            ok, unassigned_incidents = check_servicenow_tickets_status(pending_incidents, is_requirement=False)
            
        unassigned_requirements = []
        if pending_requirements:
            ok, unassigned_requirements = check_servicenow_tickets_status(pending_requirements, is_requirement=True)
            
        if not unassigned_incidents and not unassigned_requirements:
            print(f"\n[VERIFICACIÓN EXITOSA] ¡Confirmado! Todos los tickets ({total_to_verify}) tienen asignatario en ServiceNow.")
            return
            
        print(f"\n[ALERTA DE PERSISTENCIA - Intento {attempt}] Se detectaron tickets pendientes:")
        if unassigned_incidents:
            print(f"  - Incidentes sin asignación ({len(unassigned_incidents)}): {unassigned_incidents}")
            retry_df_inc = get_retry_dataframe_from_assignment_report(unassigned_incidents, ticket_type="incid")
            if not retry_df_inc.empty:
                print(f"  Reescribiendo {len(retry_df_inc)} incidentes en ServiceNow según Salida/reporte_detalle_asignaciones.csv...")
                update_tickets_in_servicenow_dom(retry_df_inc, is_requirement=False)
            else:
                print(f"  [ERROR] No se encontraron datos para los incidentes pendientes en reporte_detalle_asignaciones.csv.")
                
        if unassigned_requirements:
            print(f"  - Requerimientos sin asignación ({len(unassigned_requirements)}): {unassigned_requirements}")
            retry_df_req = get_retry_dataframe_from_assignment_report(unassigned_requirements, ticket_type="req")
            if not retry_df_req.empty:
                print(f"  Reescribiendo {len(retry_df_req)} requerimientos en ServiceNow según Salida/reporte_detalle_asignaciones.csv...")
                update_tickets_in_servicenow_dom(retry_df_req, is_requirement=True)
            else:
                print(f"  [ERROR] No se encontraron datos para los requerimientos pendientes en reporte_detalle_asignaciones.csv.")
                
        pending_incidents = unassigned_incidents
        pending_requirements = unassigned_requirements
        
    print(f"\n[VERIFICACIÓN FINAL] Se completaron los {max_retries} intentos de verificación.")
    if pending_incidents or pending_requirements:
        print(f"[ADVERTENCIA] Quedaron tickets pendientes que no pudieron ser confirmados:")
        if pending_incidents:
            print(f"  - Incidentes: {pending_incidents}")
        if pending_requirements:
            print(f"  - Requerimientos: {pending_requirements}")
        print("Verifique la conectividad de red o revise los registros manualmente en ServiceNow.")


def run_rpa_loop(min_mtime=None):
    """Ejecuta el pipeline E2E con actualización DOM."""
    reset_notification_state()
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
    loop_start = min_mtime if min_mtime is not None else time.time()
    if not SKIP_DOWNLOAD:
        run_downloads(min_mtime=loop_start)
    else:
        print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
        
    run_predictions()
    
    print("\n" + "="*50)
    print("              3. FASE DE ACTUALIZACIÓN DOM EN SERVICENOW")
    print("="*50)
    
    processed_incidents = []
    # Process Incidents
    inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv", loop_start)
    if inc_csv:
        print(f"\n--- Procesando Incidentes desde: {inc_csv} ---")
        processed_incidents = update_tickets_in_servicenow_dom(inc_csv, is_requirement=False) or []
    else:
        print("\nNo se encontró archivo de salida para Incidentes.")
        
    processed_requirements = []
    # Process Requirements
    req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv", loop_start)
    if req_csv:
        print(f"\n--- Procesando Requerimientos desde: {req_csv} ---")
        processed_requirements = update_tickets_in_servicenow_dom(req_csv, is_requirement=True) or []
    else:
        print("\nNo se encontró archivo de salida para Requerimientos.")
        
    # Verificación post-asignación en ServiceNow (solo si DRY_RUN=False)
    verify_and_reassign_tickets(processed_incidents, processed_requirements)

    # Cierre automático de todo el navegador con Alt+F4 al finalizar toda la iteración
    close_browser_at_end()

# ==========================================
# MENÚ PRINCIPAL
# ==========================================
def main():
    global SKIP_DOWNLOAD, DRY_RUN
    
    print("\n" + "="*50)
    print("  RPA SERVICENOW DOM (DEVTOOLS CONSOLE INJECTION)")
    print("="*50)
    print(f"Configuración actual: SKIP_DOWNLOAD={SKIP_DOWNLOAD}, DRY_RUN={DRY_RUN}")
    print("\nOpciones:")
    print("1. Solo INCIDENTES: Ejecutar Predicciones y Actualizar DOM")
    print("2. Solo INCIDENTES: Solo Actualizar DOM (usando última predicción)")
    print("3. Solo REQUERIMIENTOS: Ejecutar Predicciones y Actualizar DOM")
    print("4. Solo REQUERIMIENTOS: Solo Actualizar DOM (usando última predicción)")
    print("5. Ejecución Completa (Incidentes + Requerimientos)")
    print("6. Ejecución Completa Periódica (Incidentes + Requerimientos)")
    print("7. Limpiar y corregir codificación de archivos CSV (Entrada, Datos, Especificaciones)")
    print("8. Salir")
    
    choice = input("\nSeleccione una opción (1-8): ").strip()
    
    if choice == '1':
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_incidentes"):
            reset_notification_state()
            try:
                cycle_start = time.time()
                if not SKIP_DOWNLOAD:
                    run_downloads(download_incidents=True, download_requirements=False, min_mtime=cycle_start)
                else:
                    print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
                run_predictions(run_incidents=True, run_requirements=False)
                inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv", min_mtime=cycle_start if not SKIP_DOWNLOAD else None)
                processed_inc = []
                if inc_csv:
                    processed_inc = update_tickets_in_servicenow_dom(inc_csv, is_requirement=False) or []
                else:
                    print("No se encontró archivo de salida de predicción para Incidentes.")
                verify_and_reassign_tickets(processed_incidents=processed_inc, processed_requirements=[])
            except Exception as e:
                print(f"\n[ERROR] Proceso de incidentes cancelado: {e}")
            finally:
                close_browser_at_end()
    elif choice == '2':
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_incidentes"):
            reset_notification_state()
            print("\n--- Procesando únicamente Incidentes (Solo DOM) ---")
            inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv")
            processed_inc = []
            if inc_csv:
                processed_inc = update_tickets_in_servicenow_dom(inc_csv, is_requirement=False) or []
            else:
                print("No se encontró archivo de salida de predicción para Incidentes.")
            verify_and_reassign_tickets(processed_incidents=processed_inc, processed_requirements=[])
            close_browser_at_end()
    elif choice == '3':
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_requerimientos"):
            reset_notification_state()
            try:
                cycle_start = time.time()
                if not SKIP_DOWNLOAD:
                    run_downloads(download_incidents=False, download_requirements=True, min_mtime=cycle_start)
                else:
                    print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
                run_predictions(run_incidents=False, run_requirements=True)
                req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv", min_mtime=cycle_start if not SKIP_DOWNLOAD else None)
                processed_req = []
                if req_csv:
                    processed_req = update_tickets_in_servicenow_dom(req_csv, is_requirement=True) or []
                else:
                    print("No se encontró archivo de salida de predicción para Requerimientos.")
                verify_and_reassign_tickets(processed_incidents=[], processed_requirements=processed_req)
            except Exception as e:
                print(f"\n[ERROR] Proceso de requerimientos cancelado: {e}")
            finally:
                close_browser_at_end()
    elif choice == '4':
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_requerimientos"):
            reset_notification_state()
            print("\n--- Procesando únicamente Requerimientos (Solo DOM) ---")
            req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv")
            processed_req = []
            if req_csv:
                processed_req = update_tickets_in_servicenow_dom(req_csv, is_requirement=True) or []
            else:
                print("No se encontró archivo de salida de predicción para Requerimientos.")
            verify_and_reassign_tickets(processed_incidents=[], processed_requirements=processed_req)
            close_browser_at_end()
    elif choice == '5':
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_completa"):
            try:
                run_rpa_loop()
            except Exception as e:
                print(f"\n[ERROR] Ejecución completa cancelada: {e}")
    elif choice == '6':
        print("\n" + "="*50)
        print("   EJECUCIÓN COMPLETA PERIÓDICA (INCIDENTES + REQUERIMIENTOS)")
        print("="*50)
        
        interval_str = input("Ingrese el intervalo de espera en minutos [por defecto 30]: ").strip()
        try:
            interval_mins = float(interval_str) if interval_str else 30.0
        except ValueError:
            print("Número inválido. Usando 30.0 minutos por defecto.")
            interval_mins = 30.0
            
        interval_secs = int(interval_mins * 60)
        
        config_params = load_config_parameters()
        max_failures = config_params.get("max_consecutive_download_failures", 3)
        consecutive_failures = 0
        
        print("\n" + "="*50)
        print(f"Modo Periódico activado! Intervalo: {interval_mins} min ({interval_secs}s)")
        print(f"Límite de fallos consecutivos antes de detención: {max_failures}")
        print(f"Configuración actual: SKIP_DOWNLOAD={SKIP_DOWNLOAD}, DRY_RUN={DRY_RUN}")
        print("Presione Ctrl+C en esta terminal para detener la automatización.")
        print("="*50 + "\n")
        
        with ExecutionLogger(SALIDA_DIR, prefix="ejecucion_dom_periodica"):
            while True:
                cycle_start = time.time()
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"\n[{current_time}] Iniciando ciclo de automatización...")
                
                try:
                    run_rpa_loop(min_mtime=cycle_start)
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Ciclo finalizado exitosamente.")
                    consecutive_failures = 0
                except KeyboardInterrupt:
                    print("\nAutomatización detenida por el usuario (Ctrl+C). Saliendo del ciclo.")
                    break
                except Exception as e:
                    consecutive_failures += 1
                    print(f"\n[ERROR] Ocurrió una excepción en el ciclo: {e}")
                    print(f"[CONTROL] Intentos fallidos consecutivos: {consecutive_failures} de {max_failures}")
                    
                    if consecutive_failures >= max_failures:
                        print("\n" + "!"*60)
                        print(f"[DETENCIÓN CRÍTICA] Se alcanzó el límite de {max_failures} fallos consecutivos.")
                        print("El proceso se detiene automáticamente para que el administrador verifique el estado.")
                        print("!"*60 + "\n")
                        break
                        
                    print("Reintentando en el siguiente ciclo...")
                
                next_run_time = (datetime.now() + timedelta(seconds=interval_secs)).strftime('%H:%M:%S')
                print(f"Esperando {interval_mins} minutos. Siguiente ejecución a las {next_run_time}...")
                
                sleep_left = interval_secs
                try:
                    while sleep_left > 0:
                        time.sleep(min(5, sleep_left))
                        sleep_left -= 5
                except KeyboardInterrupt:
                    print("\nAutomatización detenida por el usuario (Ctrl+C). Saliendo del ciclo.")
                    break
    elif choice == '7':
        clean_all_input_csv_files(verbose=True)
    elif choice == '8':
        print("Saliendo...")
        sys.exit(0)
    else:
        print("Opción inválida.")

if __name__ == "__main__":
    main()
