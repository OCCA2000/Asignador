#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Herramienta RPA E2E para Asignación en ServiceNow
Automatiza:
1. Descarga de listas de incidentes/requerimientos desde ServiceNow.
2. Ejecución de modelos de aprendizaje automático para asignación.
3. Actualización del campo Asignado a en ServiceNow mediante coordenadas de pantalla.
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

# Modo seguro Dry Run: navegará y llenará campos pero NO hará clic en "Actualizar/Guardar"
DRY_RUN = True

# Tiempo de espera en segundos para que se completen las descargas cuando DRY_RUN = False
DOWNLOAD_WAIT_TIME = 5.0

# Execution interval in minutes for the periodic run option (Option 6)
PERIODIC_INTERVAL_MINUTES = 30.0

# Ajustes de PyAutoGUI
pyautogui.FAILSAFE = True  # Mover cursor a la esquina superior izquierda para abortar ejecución
pyautogui.PAUSE = 1.0      # Pausa después de cada acción de GUI (en segundos)

# Configuraciones de espera (ajustar según velocidad de red y respuesta de ServiceNow)
LOAD_TIME = 5.0            # Tiempo de espera para cargar la página del ticket
CLIPBOARD_TIME = 0.5       # Tiempo de espera tras operaciones de copiar/pegar

# Ventana emergente de notificación antes de iniciar el proceso
SHOW_NOTIFICATION_POPUP = True
NOTIFICATION_COUNTDOWN_SECONDS = 5

_notification_shown_this_cycle = False

def reset_notification_state():
    global _notification_shown_this_cycle
    _notification_shown_this_cycle = False

# Directorios de configuración y datos
ESPECIFICACIONES_DIR = "Especificaciones"
INCIDENT_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "rpa_config_incidents.json")
REQUIREMENT_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "rpa_config_requirements.json")
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
# MODO SETUP / CALIBRACIÓN DE COORDENADAS
# ==========================================
def run_setup():
    """Captura interactivamente coordenadas en pantalla para campos de entrada y botones."""
    os.makedirs(ESPECIFICACIONES_DIR, exist_ok=True)
    print("\n" + "="*50)
    print("      CONFIGURACIÓN DE RPA DE SERVICENOW Y CALIBRACIÓN DE COORDENADAS")
    print("="*50)
    print("Elija qué configuración desea calibrar:")
    print("1. Incidentes (2 coordenadas: Asignado a, Guardar/Actualizar)")
    print("2. Requerimientos (5 coordenadas: Asignado a, Estado, Fecha de vencimiento, Aplicación, Guardar/Actualizar)")
    print("3. Ambos")
    
    choice = input("Seleccione una opción (1-3): ").strip()
    
    if choice in ('1', '3'):
        print("\n" + "="*40)
        print("          CALIBRANDO COORDENADAS DE INCIDENTES")
        print("="*40)
        print("Abra su navegador, maximícelo, navegue a una página de INCIDENTE de ServiceNow,")
        print("y asegúrese de que sea totalmente visible en su monitor principal.")
        
        print("\n--- PASO 1: Calibrar el cuadro de texto 'Asignado a' ---")
        print("Acción: Mueva el cursor del ratón directamente sobre el centro del cuadro de entrada 'Asignado a' (o 'Assigned to').")
        input("Una vez posicionado el cursor, vuelva aquí y presione Intro para guardar...")
        assigned_to_x, assigned_to_y = pyautogui.position()
        print(f"Coordenadas de 'Asignado a' capturadas: X={assigned_to_x}, Y={assigned_to_y}")
        
        print("\n--- PASO 2: Calibrar el botón 'Actualizar' o 'Guardar' ---")
        print("Acción: Mueva el cursor del ratón directamente sobre el centro del botón 'Actualizar' (o 'Update' / 'Save').")
        input("Una vez posicionado el cursor, vuelva aquí y presione Intro para guardar...")
        update_x, update_y = pyautogui.position()
        print(f"Coordenadas de 'Actualizar' capturadas: X={update_x}, Y={update_y}")
        
        config = {
            "assigned_to_x": assigned_to_x,
            "assigned_to_y": assigned_to_y,
            "update_x": update_x,
            "update_y": update_y
        }
        
        with open(INCIDENT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"Configuración de incidentes guardada exitosamente en: {INCIDENT_CONFIG_FILE}")
        
    if choice in ('2', '3'):
        print("\n" + "="*40)
        print("          CALIBRANDO COORDENADAS DE REQUERIMIENTOS")
        print("="*40)
        print("Abra su navegador, maximícelo, navegue a una página de REQUERIMIENTO de ServiceNow.")
        print("Nota: Si 'Fecha de vencimiento' no es visible, cambie temporalmente el estado a 'En proceso'.")
        print("Asegúrese de que sea totalmente visible en su monitor principal.")
        
        print("\n--- PASO 1: Calibrar el cuadro de texto 'Asignado a' ---")
        input("Posicione el cursor sobre el cuadro de entrada 'Asignado a' y presione Intro...")
        assignation_textbox_x, assignation_textbox_y = pyautogui.position()
        print(f"Capturado: X={assignation_textbox_x}, Y={assignation_textbox_y}")
        
        print("\n--- PASO 2: Calibrar el cuadro combinado 'Estado' ---")
        input("Posicione el cursor sobre el cuadro combinado 'Estado' y presione Intro...")
        status_combobox_x, status_combobox_y = pyautogui.position()
        print(f"Capturado: X={status_combobox_x}, Y={status_combobox_y}")
        
        print("\n--- PASO 3: Calibrar el cuadro de texto 'Fecha de vencimiento' ---")
        input("Posicione el cursor sobre el cuadro de entrada 'Fecha de vencimiento' y presione Intro...")
        due_date_textbox_x, due_date_textbox_y = pyautogui.position()
        print(f"Capturado: X={due_date_textbox_x}, Y={due_date_textbox_y}")
        
        print("\n--- PASO 4: Calibrar el cuadro de texto 'Aplicación' ---")
        input("Posicione el cursor sobre el cuadro de entrada 'Aplicación' y presione Intro...")
        application_textbox_x, application_textbox_y = pyautogui.position()
        print(f"Capturado: X={application_textbox_x}, Y={application_textbox_y}")
        
        print("\n--- PASO 5: Calibrar el botón 'Guardar/Actualizar' ---")
        input("Posicione el cursor sobre el botón 'Guardar' o 'Actualizar' y presione Intro...")
        save_button_x, save_button_y = pyautogui.position()
        print(f"Capturado: X={save_button_x}, Y={save_button_y}")
        
        config = {
            "assignation_textbox_x": assignation_textbox_x,
            "assignation_textbox_y": assignation_textbox_y,
            "status_combobox_x": status_combobox_x,
            "status_combobox_y": status_combobox_y,
            "due_date_textbox_x": due_date_textbox_x,
            "due_date_textbox_y": due_date_textbox_y,
            "application_textbox_x": application_textbox_x,
            "application_textbox_y": application_textbox_y,
            "save_button_x": save_button_x,
            "save_button_y": save_button_y
        }
        
        with open(REQUIREMENT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"Configuración de requerimientos guardada exitosamente en: {REQUIREMENT_CONFIG_FILE}")
        
    print("\n" + "="*50)
    print("Fase de calibración de configuración completada.")
    print("Ahora puede ejecutar el script en modo estándar o de prueba (dry-run).")
    print("="*50 + "\n")

# ==========================================
# RESOLUCIÓN DE CONFIGURACIÓN
# ==========================================
def load_config(config_file):
    """Carga las coordenadas de calibración desde el archivo JSON de configuración."""
    # Fallback legacy para incidentes
    if config_file == INCIDENT_CONFIG_FILE and not os.path.exists(config_file):
        legacy_spec = os.path.join(ESPECIFICACIONES_DIR, "rpa_config.json")
        if os.path.exists(legacy_spec):
            print("Usando archivo de configuración heredado: Especificaciones/rpa_config.json")
            config_file = legacy_spec
        elif os.path.exists("rpa_config.json"):
            print("Usando archivo de configuración heredado: rpa_config.json")
            config_file = "rpa_config.json"
        
    if not os.path.exists(config_file):
        print(f"\n[ERROR] Archivo de configuración '{config_file}' no encontrado.")
        print("Por favor, ejecute el modo Setup (Opción 4) primero para calibrar sus coordenadas de pantalla.")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error al cargar la configuración de calibración '{config_file}': {e}")
        return None

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
        
    # Ordenar archivos por fecha de modificación (más reciente primero)
    files.sort(key=os.path.getmtime, reverse=True)
    latest_file = files[0]
    
    dest_path = os.path.join(ENTRADA_DIR, destination_name)
    os.makedirs(ENTRADA_DIR, exist_ok=True)
    
    # Remove destination file if it already exists to avoid conflicts
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
# EJECUTORES E2E
# ==========================================
def run_downloads():
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
    
    # 1. Incidentes
    default_incident = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=assignment_group=e6313131f874ee55056b262c30cbb3551^ORassignment_group=36ea16e087548210f2e1cbf80cbb35fd^assigned_toISEMPTY^stateIN1,2&CSV"
    incident_url = resolve_url(config_params.get("incident_download_url"), default_incident)
    print(f"Abriendo lista de incidentes en navegador independiente: {incident_url}")
    open_url_in_browser(incident_url)
    print("Se abrió una ventana del navegador.")
    print("Exporte la lista a CSV si la descarga no se inicia automáticamente.")
    if DRY_RUN:
        input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
    else:
        print(f"Esperando {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
        time.sleep(DOWNLOAD_WAIT_TIME)
    
    # Mover descarga
    if not move_latest_download("*incident*.csv", "incident.csv"):
        print("Advertencia: No se pudo encontrar/mover automáticamente el CSV de incidentes. Asegúrese de que exista Entrada/incident.csv.")
        
    # 2. Requerimientos
    default_req = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=assignment_group=36ea16e087548210f2e1cbf80cbb35fd^ORassignment_group=e6313131f874ee55056b262c30cbb3551^state=1^assigned_toISEMPTY&CSV"
    req_url = resolve_url(config_params.get("requirement_download_url"), default_req)
    print(f"\nAbriendo lista de requerimientos en navegador independiente: {req_url}")
    open_url_in_browser(req_url)
    print("Se abrió una ventana del navegador.")
    print("Exporte la lista a CSV si la descarga no se inicia automáticamente.")
    if DRY_RUN:
        input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
    else:
        print(f"Esperando {DOWNLOAD_WAIT_TIME} segundos para que se complete la descarga...")
        time.sleep(DOWNLOAD_WAIT_TIME)
    
    if not move_latest_download("*sc_req_item*.csv", "sc_req_item.csv"):
        print("Advertencia: No se pudo encontrar/mover automáticamente el CSV de requerimientos. Asegúrese de que exista Entrada/sc_req_item.csv.")

def run_predictions():
    """Ejecuta los scripts de predicción de aprendizaje automático."""
    print("\n" + "="*50)
    print("              2. FASE DE MODELOS DE PREDICCIÓN")
    print("="*50)
    
    # Archivar ejecuciones anteriores en Salida/ hacia sus carpetas por fecha
    archive_previous_files(SALIDA_DIR, "*.csv")
    archive_previous_files(SALIDA_DIR, "*.txt")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Run Incident Assigner
    print("Running Assigner_Incidents.py...")
    try:
        subprocess.run([sys.executable, os.path.join(script_dir, "Assigner_Incidents.py")], check=True, cwd=script_dir)
        print("Incident predictions complete!")
    except subprocess.CalledProcessError as e:
        print(f"Error executing Assigner_Incidents.py: {e}")
        
    # Run Requirement Assigner
    print("\nRunning Assigner_Requirements.py...")
    try:
        subprocess.run([sys.executable, os.path.join(script_dir, "Assigner_Requirements.py")], check=True, cwd=script_dir)
        print("Requirement predictions complete!")
    except subprocess.CalledProcessError as e:
        print(f"Error executing Assigner_Requirements.py: {e}")

def update_tickets_in_servicenow(csv_path, coordinates, is_requirement=False):
    """Lee las asignaciones predichas y actualiza los tickets a través del control del navegador."""
    if not csv_path or not os.path.exists(csv_path):
        print(f"No prediction file found for processing.")
        return
        
    print(f"\nProcessing assignments from: {csv_path}")
    df = pd.read_csv(csv_path, sep=';', encoding='latin-1', dtype=str)
    
    # Identificar nombres de columnas
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
    print("              RPA UI UPDATE WILL START IN 5 SECONDS")
    print("WARNING: DO NOT MOVE THE MOUSE OR TYPE WHILE IT RUNS.")
    print("To abort at any time, move your mouse pointer to the TOP-LEFT CORNER of the screen.")
    print("!"*50)
    for i in range(5, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)
        
    table_name = "sc_req_item" if is_requirement else "incident"
    
    if is_requirement:
        assigned_to_x = coordinates["assignation_textbox_x"]
        assigned_to_y = coordinates["assignation_textbox_y"]
        status_x = coordinates["status_combobox_x"]
        status_y = coordinates["status_combobox_y"]
        due_date_x = coordinates["due_date_textbox_x"]
        due_date_y = coordinates["due_date_textbox_y"]
        application_x = coordinates["application_textbox_x"]
        application_y = coordinates["application_textbox_y"]
        update_x = coordinates["save_button_x"]
        update_y = coordinates["save_button_y"]
    else:
        assigned_to_x = coordinates["assigned_to_x"]
        assigned_to_y = coordinates["assigned_to_y"]
        update_x = coordinates["update_x"]
        update_y = coordinates["update_y"]
        
    for idx, row in tickets_to_process.iterrows():
        ticket_id = row[num_col]
        assignee = row[assign_col]
        
        if pd.isna(assignee) or not str(assignee).strip():
            print(f"Skipping ticket {ticket_id}: Assignee is empty.")
            continue
            
        print(f"\n>>> Updating {ticket_id} -> Assignee: {assignee} (DRY_RUN={DRY_RUN})")
        
        ticket_url = f"{SERVICENOW_BASE_URL}/{table_name}.do?sysparm_query=number={ticket_id}"
        
        # Abrir el ticket en una pestaña del navegador independiente
        open_url_in_browser(ticket_url)
        time.sleep(LOAD_TIME)
            
        # 1. Hacer clic y enfocar el cuadro de texto "Asignado a"
        pyautogui.click(assigned_to_x, assigned_to_y)
        time.sleep(0.5)
        
        # Limpiar campo y pegar el nombre del asignado
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(CLIPBOARD_TIME)
        pyperclip.copy(str(assignee))
        time.sleep(CLIPBOARD_TIME)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(CLIPBOARD_TIME)
        pyautogui.press('enter')
        time.sleep(1.0)  # Esperar a que se asiente el menú desplegable de autocompletado
        pyautogui.press('tab')
        time.sleep(0.5)
        
        if is_requirement:
            # 2. Hacer clic en el cuadro combinado de Estado y cambiar a "En proceso"
            print("Changing status from 'Nuevo' to 'En proceso'...")
            pyautogui.click(status_x, status_y)
            time.sleep(0.5)
            pyautogui.press('down')
            time.sleep(0.5)
            pyautogui.press('enter')
            # Esperar a que aparezca el cuadro de texto de fecha de vencimiento tras cambiar el estado
            print("Waiting for due date textbox to appear...")
            time.sleep(2.0)
            
            # 3. Llenar cuadro de texto de Fecha de vencimiento
            due_date = row.get('fecha_resolucion')
            due_date_str = ""
            if pd.notna(due_date) and str(due_date).strip():
                try:
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
                except Exception:
                    due_date_str = str(due_date).strip()
            else:
                # Fallback a fecha actual más 30 días
                due_date_dt = datetime.now() + timedelta(days=30)
                due_date_str = due_date_dt.strftime('%d/%m/%Y %H:%M:%S')
            
            print(f"Setting due date: {due_date_str}...")
            pyautogui.click(due_date_x, due_date_y)
            time.sleep(0.5)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            time.sleep(CLIPBOARD_TIME)
            pyperclip.copy(due_date_str)
            time.sleep(CLIPBOARD_TIME)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(CLIPBOARD_TIME)
            pyautogui.press('enter')
            time.sleep(0.5)
            pyautogui.press('tab')
            time.sleep(0.5)
            
            # 4. Llenar cuadro de texto de Aplicación (siempre "Bancs")
            application_str = "Bancs"
            print(f"Setting application: {application_str}...")
            pyautogui.click(application_x, application_y)
            time.sleep(0.5)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            time.sleep(CLIPBOARD_TIME)
            pyperclip.copy(application_str)
            time.sleep(CLIPBOARD_TIME)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(CLIPBOARD_TIME)
            pyautogui.press('enter')
            time.sleep(0.5)
            pyautogui.press('tab')
            time.sleep(0.5)
            
        # Hacer clic en el botón Actualizar/Guardar (si no está en modo de prueba)
        if not DRY_RUN:
            pyautogui.click(update_x, update_y)
            print(f"Clicked 'Update/Save' button at ({update_x}, {update_y})")
            time.sleep(LOAD_TIME)
            print(f"Cerrando pestaña del ticket {ticket_id} (DRY_RUN=False)...")
            pyautogui.hotkey('ctrl', 'w')
            time.sleep(0.5)
        else:
            print(f"[DRY RUN] Bypassing click on 'Update/Save' button at ({update_x}, {update_y}). Changes not saved. Pestaña mantenida abierta para revisión.")
            time.sleep(1.0)
            
    print("\nServiceNow UI update loop finished!")

def run_rpa_loop(min_mtime=None):
    """Orquesta el ciclo de actualización de interfaz gráfica para incidentes y requerimientos."""
    reset_notification_state()
    show_pre_start_notification(NOTIFICATION_COUNTDOWN_SECONDS)
    # Cargar coordenadas primero
    coords_incidents = load_config(INCIDENT_CONFIG_FILE)
    coords_requirements = load_config(REQUIREMENT_CONFIG_FILE)
    
    print("\n" + "="*50)
    print("              3. SERVICENOW UI UPDATING PHASE")
    print("="*50)
    
    latest_incident_csv = find_latest_output_file("incidentes_con_asignacion_*.csv", min_mtime=min_mtime)
    if latest_incident_csv:
        if coords_incidents:
            print(f"Latest Incident prediction file found: {latest_incident_csv}")
            update_tickets_in_servicenow(latest_incident_csv, coords_incidents, is_requirement=False)
        else:
            print("Skipping Incident updating: Incident config coordinates not loaded.")
    else:
        print("No incident predictions output file found for this cycle to process.")
        
    latest_req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv", min_mtime=min_mtime)
    if latest_req_csv:
        if coords_requirements:
            print(f"Latest Requirement prediction file found: {latest_req_csv}")
            update_tickets_in_servicenow(latest_req_csv, coords_requirements, is_requirement=True)
        else:
            print("Skipping Requirement updating: Requirement config coordinates not loaded.")
    else:
        print("No requirement predictions output file found for this cycle to process.")

# ==========================================
# MODO DAEMON / AUTOMÁTICO
# ==========================================
def run_daemon_mode():
    """Ejecuta el ciclo de automatización RPA continuamente en intervalos configurados."""
    print("\n" + "="*50)
    print("              5. DAEMON AUTOMATION MODE")
    print("="*50)
    
    print("Select base run mode:")
    print("1. [Full E2E Pipeline] Run downloads, models, and update ServiceNow.")
    print("2. [Models & Update] Skip downloads, run models on local Entrada/, and update.")
    print("3. [Updates Only] Skip models, just update ServiceNow using latest Salida/ CSVs.")
    
    mode_choice = input("Select mode (1-3) [default 2]: ").strip()
    if not mode_choice:
        mode_choice = '2'
        
    dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [Y/n]: ").strip().lower()
    daemon_dry_run = dry_choice != 'n'
    
    interval_str = input("Enter sleep interval in minutes [default 60]: ").strip()
    try:
        interval_mins = float(interval_str) if interval_str else 60.0
    except ValueError:
        print("Invalid number. Defaulting to 60.0 minutes.")
        interval_mins = 60.0
        
    interval_secs = int(interval_mins * 60)
    
    print("\n" + "="*50)
    print(f"Daemon mode activated! Interval: {interval_mins} mins ({interval_secs}s)")
    print(f"Base Mode: {mode_choice} | Dry Run: {daemon_dry_run}")
    print("Press Ctrl+C in this terminal to stop the daemon.")
    print("="*50 + "\n")
    
    global SKIP_DOWNLOAD, DRY_RUN
    DRY_RUN = daemon_dry_run
    
    while True:
        cycle_start = time.time()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n[{current_time}] Starting automation cycle...")
        
        try:
            if mode_choice == '1':
                SKIP_DOWNLOAD = False
                run_downloads()
                run_predictions()
                run_rpa_loop(min_mtime=cycle_start)
            elif mode_choice == '2':
                SKIP_DOWNLOAD = True
                run_predictions()
                run_rpa_loop(min_mtime=cycle_start)
            elif mode_choice == '3':
                SKIP_DOWNLOAD = True
                run_rpa_loop(min_mtime=None)
            else:
                print("Invalid mode chosen. Defaulting to Option 2 flow.")
                SKIP_DOWNLOAD = True
                run_predictions()
                run_rpa_loop(min_mtime=cycle_start)
                
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cycle finished successfully.")
        except KeyboardInterrupt:
            print("\nDaemon stopped by user (Ctrl+C). Exiting loop.")
            break
        except Exception as e:
            print(f"\n[ERROR] Exception occurred in daemon cycle: {e}")
            print("Retrying in the next cycle...")
            
        next_run_time = (datetime.now() + timedelta(seconds=interval_secs)).strftime('%H:%M:%S')
        print(f"Sleeping for {interval_mins} minutes. Next run at {next_run_time}...")
        
        # Pausar en incrementos de 5 segundos para mantener respuesta a interrupciones Ctrl+C
        sleep_left = interval_secs
        try:
            while sleep_left > 0:
                time.sleep(min(5, sleep_left))
                sleep_left -= 5
        except KeyboardInterrupt:
            print("\nDaemon stopped by user (Ctrl+C). Exiting.")
            break

# ==========================================
# MAIN INTERFACE
# ==========================================
def main():
    print("="*50)
    print("      SERVICENOW RPA AUTOMATION ORCHESTRATOR")
    print("="*50)
    print("1. [Run E2E RPA Pipeline] Run downloads, models, and update ServiceNow.")
    print("2. [Run Models & Update] Skip downloads, run models on local Entrada/, and update.")
    print("3. [Run Updates Only] Skip models, just update ServiceNow using latest Salida/ CSVs.")
    print("4. [Setup Mode] Calibrate monitor coordinates for input box and update button.")
    print("5. [Daemon Mode] Run automation continuously at a set interval (daemon loop).")
    print("6. [Periodic Mode] Run E2E pipeline periodically (both Incidents & Requirements).")
    print("7. Exit")
    
    choice = input("\nSelect an option (1-7): ").strip()
    
    global SKIP_DOWNLOAD, DRY_RUN
    
    if choice == '1':
        SKIP_DOWNLOAD = False
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        cycle_start = time.time()
        run_downloads()
        run_predictions()
        run_rpa_loop(min_mtime=cycle_start)
        
    elif choice == '2':
        SKIP_DOWNLOAD = True
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        cycle_start = time.time()
        run_predictions()
        run_rpa_loop(min_mtime=cycle_start)
        
    elif choice == '3':
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        run_rpa_loop(min_mtime=None)
        
    elif choice == '4':
        run_setup()
        
    elif choice == '5':
        run_daemon_mode()
        
    elif choice == '6':
        print("\n" + "="*50)
        print("   RUN PIPELINE PERIODICALLY (INCIDENTS & REQUIREMENTS)")
        print("="*50)
        
        mode_choice = input("Select base run mode:\n1. [Full E2E Pipeline] Run downloads, models, and update ServiceNow.\n2. [Run Models & Update] Skip downloads, run models on local Entrada/, and update.\n3. [Run Updates Only] Skip models, just update ServiceNow using latest Salida/ CSVs.\nSelect mode (1-3) [default 1]: ").strip()
        if not mode_choice:
            mode_choice = '1'
            
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [Y/n]: ").strip().lower()
        run_dry_run = dry_choice != 'n'
        
        interval_secs = int(PERIODIC_INTERVAL_MINUTES * 60)
        
        print("\n" + "="*50)
        print(f"Periodic Mode activated! Interval: {PERIODIC_INTERVAL_MINUTES} mins ({interval_secs}s)")
        print(f"Base Mode: {mode_choice} | Dry Run: {run_dry_run}")
        print("Press Ctrl+C in this terminal to stop the execution.")
        print("="*50 + "\n")
        
        DRY_RUN = run_dry_run
        
        while True:
            cycle_start = time.time()
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{current_time}] Starting automation cycle...")
            
            try:
                if mode_choice == '1':
                    SKIP_DOWNLOAD = False
                    run_downloads()
                    run_predictions()
                    run_rpa_loop(min_mtime=cycle_start)
                elif mode_choice == '2':
                    SKIP_DOWNLOAD = True
                    run_predictions()
                    run_rpa_loop(min_mtime=cycle_start)
                elif mode_choice == '3':
                    SKIP_DOWNLOAD = True
                    run_rpa_loop(min_mtime=None)
                else:
                    print("Invalid mode chosen. Defaulting to Option 1 flow.")
                    SKIP_DOWNLOAD = False
                    run_downloads()
                    run_predictions()
                    run_rpa_loop(min_mtime=cycle_start)
                    
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Cycle finished successfully.")
            except KeyboardInterrupt:
                print("\nStopped by user (Ctrl+C). Exiting loop.")
                break
            except Exception as e:
                print(f"\n[ERROR] Exception occurred in cycle: {e}")
                print("Retrying in the next cycle...")
                
            next_run_time = (datetime.now() + timedelta(seconds=interval_secs)).strftime('%H:%M:%S')
            print(f"Sleeping for {PERIODIC_INTERVAL_MINUTES} minutes. Next run at {next_run_time}...")
            
            sleep_left = interval_secs
            try:
                while sleep_left > 0:
                    time.sleep(min(5, sleep_left))
                    sleep_left -= 5
            except KeyboardInterrupt:
                print("\nStopped by user (Ctrl+C). Exiting.")
                break
        
    elif choice == '7':
        print("Exiting. Have a great day!")
        return
        
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
