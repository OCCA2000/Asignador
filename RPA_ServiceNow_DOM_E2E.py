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
from Programas.CleaningData import archive_previous_files, get_windows_date_format

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

def move_latest_download(pattern, destination_name):
    """Busca la descarga más reciente que coincida con un patrón y la mueve a Entrada/"""
    downloads_dir = get_downloads_folder()
    search_path = os.path.join(downloads_dir, pattern)
    files = glob.glob(search_path)
    
    if not files:
        print(f"No se encontraron archivos en Descargas que coincidan con: {pattern}")
        return False
        
    files.sort(key=os.path.getmtime, reverse=True)
    latest_file = files[0]
    
    dest_path = os.path.join(ENTRADA_DIR, destination_name)
    os.makedirs(ENTRADA_DIR, exist_ok=True)
    
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass

    try:
        shutil.move(latest_file, dest_path)
        print(f"Archivo movido: {latest_file} -> {dest_path}")
        return True
    except Exception as e:
        print(f"Error al mover el archivo {latest_file}: {e}")
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
def run_downloads(download_incidents=True, download_requirements=True):
    """Maneja la descarga de tickets desde ServiceNow."""
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
    print("\n" + "="*50)
    print("              1. FASE DE DESCARGA DE CSV")
    print("="*50)
    
    config_params = load_config_parameters()
    
    def resolve_url(url, default_url):
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
    
    if download_incidents:
        default_incident = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=assignment_group=e6313131f874ee55056b262c30cbb3551^ORassignment_group=36ea16e087548210f2e1cbf80cbb35fd^assigned_toISEMPTY^stateIN1,2&CSV"
        incident_url = resolve_url(config_params.get("incident_download_url"), default_incident)
        print(f"Abriendo lista de incidentes en navegador independiente: {incident_url}")
        open_url_in_browser(incident_url)
        print("Se abrió la ventana del navegador.")
        if DRY_RUN:
            input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
        else:
            print(f"Esperando {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
            time.sleep(DOWNLOAD_WAIT_TIME)
        
        if not move_latest_download("*incident*.csv", "incident.csv"):
            print("Advertencia: Asegúrese de que exista Entrada/incident.csv.")
            
    if download_requirements:
        default_req = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=assignment_group=36ea16e087548210f2e1cbf80cbb35fd^ORassignment_group=e6313131f874ee55056b262c30cbb3551^state=1^assigned_toISEMPTY&CSV"
        req_url = resolve_url(config_params.get("requirement_download_url"), default_req)
        print(f"\nAbriendo lista de requerimientos en navegador independiente: {req_url}")
        open_url_in_browser(req_url)
        print("Se abrió la ventana del navegador.")
        if DRY_RUN:
            input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
        else:
            print(f"Esperando {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
            time.sleep(DOWNLOAD_WAIT_TIME)
        
        if not move_latest_download("*sc_req_item*.csv", "sc_req_item.csv"):
            print("Advertencia: Asegúrese de que exista Entrada/sc_req_item.csv.")

def run_predictions(run_incidents=True, run_requirements=True):
    """Ejecuta los scripts de predicción de aprendizaje automático."""
    print("\n" + "="*50)
    print("              2. FASE DE MODELOS DE PREDICCIÓN")
    print("="*50)
    
    archive_previous_files(SALIDA_DIR, "*.csv")
    archive_previous_files(SALIDA_DIR, "*.txt")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if run_incidents:
        print("Running Assigner_Incidents.py...")
        try:
            subprocess.run([sys.executable, os.path.join(script_dir, "Assigner_Incidents.py")], check=True, cwd=script_dir)
            print("Incident predictions complete!")
        except subprocess.CalledProcessError as e:
            print(f"Error executing Assigner_Incidents.py: {e}")
            
    if run_requirements:
        print("\nRunning Assigner_Requirements.py...")
        try:
            subprocess.run([sys.executable, os.path.join(script_dir, "Assigner_Requirements.py")], check=True, cwd=script_dir)
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
def update_tickets_in_servicenow_dom(csv_path, is_requirement=False):
    """
    Lee las asignaciones y actualiza los tickets abriendo la consola DevTools (Ctrl+Shift+J)
    e inyectando JavaScript directamente.
    """
    if not csv_path or not os.path.exists(csv_path):
        print("No prediction file found for processing.")
        return
        
    user_map = load_user_id_map()
    config_params = load_config_parameters()
    app_sys_ids = config_params.get("configuration_items", {})
    
    print(f"\nProcessing assignments DOM-mode from: {csv_path}")
    df = pd.read_csv(csv_path, sep=';', encoding='latin-1', dtype=str)
    
    num_col = next((c for c in ['number', 'Number', 'id'] if c in df.columns), None)
    assign_col = 'assigned_to'
    
    if not num_col or assign_col not in df.columns:
        print("Error: Required columns ('number' and 'assigned_to') not found in prediction output.")
        return
        
    tickets_to_process = df.dropna(subset=[num_col, assign_col])
    print(f"Found {len(tickets_to_process)} tickets with predicted assignments.")
    
    if len(tickets_to_process) == 0:
        return
        
    print("\n" + "!"*50)
    print(f"      RPA DEVTOOLS DOM UPDATE WILL START IN {NOTIFICATION_COUNTDOWN_SECONDS} SECONDS")
    print("  Make sure your browser window responds to hotkeys.")
    print("!"*50)
    
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
        
    table_name = "sc_req_item" if is_requirement else "incident"
    
    for idx, row in tickets_to_process.iterrows():
        ticket_id = row[num_col]
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

        # 4. Gestión de pestañas: solo cerrar si se completó con éxito Y DRY_RUN es False
        if ticket_success and not DRY_RUN:
            print(f"Cerrando pestaña del ticket {ticket_id} (DRY_RUN=False)...")
            pyautogui.hotkey('ctrl', 'w')
            time.sleep(0.5)
        else:
            if DRY_RUN:
                print(f"[DRY_RUN=True] Pestaña mantenida abierta para {ticket_id} para revisión y guardado manual.")
            else:
                print(f"[ADVERTENCIA] Pestaña mantenida abierta para {ticket_id} por error o proceso incompleto.")
        
    print("\nServiceNow DevTools DOM update loop finished!")

def run_rpa_loop(min_mtime=None):
    """Ejecuta el pipeline E2E con actualización DOM."""
    reset_notification_state()
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
    if not SKIP_DOWNLOAD:
        run_downloads()
    else:
        print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
        
    run_predictions()
    
    print("\n" + "="*50)
    print("              3. FASE DE ACTUALIZACIÓN DOM EN SERVICENOW")
    print("="*50)
    
    # Process Incidents
    inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv", min_mtime)
    if inc_csv:
        print(f"\n--- Procesando Incidentes desde: {inc_csv} ---")
        update_tickets_in_servicenow_dom(inc_csv, is_requirement=False)
    else:
        print("\nNo se encontró archivo de salida para Incidentes.")
        
    # Process Requirements
    req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv", min_mtime)
    if req_csv:
        print(f"\n--- Procesando Requerimientos desde: {req_csv} ---")
        update_tickets_in_servicenow_dom(req_csv, is_requirement=True)
    else:
        print("\nNo se encontró archivo de salida para Requerimientos.")

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
    print("7. Salir")
    
    choice = input("\nSeleccione una opción (1-7): ").strip()
    
    if choice == '1':
        reset_notification_state()
        if not SKIP_DOWNLOAD:
            run_downloads(download_incidents=True, download_requirements=False)
        else:
            print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
        run_predictions(run_incidents=True, run_requirements=False)
        inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv")
        if inc_csv:
            update_tickets_in_servicenow_dom(inc_csv, is_requirement=False)
        else:
            print("No se encontró archivo de salida de predicción para Incidentes.")
    elif choice == '2':
        reset_notification_state()
        print("\n--- Procesando únicamente Incidentes (Solo DOM) ---")
        inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv")
        if inc_csv:
            update_tickets_in_servicenow_dom(inc_csv, is_requirement=False)
        else:
            print("No se encontró archivo de salida de predicción para Incidentes.")
    elif choice == '3':
        reset_notification_state()
        if not SKIP_DOWNLOAD:
            run_downloads(download_incidents=False, download_requirements=True)
        else:
            print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
        run_predictions(run_incidents=False, run_requirements=True)
        req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv")
        if req_csv:
            update_tickets_in_servicenow_dom(req_csv, is_requirement=True)
        else:
            print("No se encontró archivo de salida de predicción para Requerimientos.")
    elif choice == '4':
        reset_notification_state()
        print("\n--- Procesando únicamente Requerimientos (Solo DOM) ---")
        req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv")
        if req_csv:
            update_tickets_in_servicenow_dom(req_csv, is_requirement=True)
        else:
            print("No se encontró archivo de salida de predicción para Requerimientos.")
    elif choice == '5':
        run_rpa_loop()
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
        
        print("\n" + "="*50)
        print(f"Modo Periódico activado! Intervalo: {interval_mins} min ({interval_secs}s)")
        print(f"Configuración actual: SKIP_DOWNLOAD={SKIP_DOWNLOAD}, DRY_RUN={DRY_RUN}")
        print("Presione Ctrl+C en esta terminal para detener la automatización.")
        print("="*50 + "\n")
        
        while True:
            cycle_start = time.time()
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{current_time}] Iniciando ciclo de automatización...")
            
            try:
                run_rpa_loop(min_mtime=cycle_start)
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Ciclo finalizado exitosamente.")
            except KeyboardInterrupt:
                print("\nAutomatización detenida por el usuario (Ctrl+C). Saliendo del ciclo.")
                break
            except Exception as e:
                print(f"\n[ERROR] Ocurrió una excepción en el ciclo: {e}")
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
        print("Saliendo...")
        sys.exit(0)
    else:
        print("Opción inválida.")

if __name__ == "__main__":
    main()
