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

# Ajustes de PyAutoGUI
pyautogui.FAILSAFE = True  # Mover cursor a la esquina superior izquierda para abortar ejecución
pyautogui.PAUSE = 0.8      # Pausa después de cada acción de GUI (en segundos)

# Configuraciones de espera
LOAD_TIME = 5.0            # Tiempo de espera para cargar la página del ticket
CLIPBOARD_TIME = 0.5       # Tiempo de espera tras copiar/pegar en la consola

# Directorios de datos y configuración
ESPECIFICACIONES_DIR = "Especificaciones"
USUARIOS_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "Grupos - Usuarios.csv")
ENTRADA_DIR = "Entrada"
SALIDA_DIR = "Salida"

# ==========================================
# CATORGA DE MAPEO DE USUARIOS
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
    print("\n" + "="*50)
    print("              1. FASE DE DESCARGA DE CSV")
    print("="*50)
    
    if download_incidents:
        incident_url = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=assignment_group=e6313131f874ee55056b262c30cbb3551^ORassignment_group=36ea16e087548210f2e1cbf80cbb35fd^assigned_toISEMPTY^stateIN1,2&CSV"
        print(f"Abriendo lista de incidentes: {incident_url}")
        webbrowser.open(incident_url)
        print("Se abrió una ventana del navegador.")
        input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
        
        if not move_latest_download("*incident*.csv", "incident.csv"):
            print("Advertencia: Asegúrese de que exista Entrada/incident.csv.")
            
    if download_requirements:
        req_url = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=assignment_group=36ea16e087548210f2e1cbf80cbb35fd^ORassignment_group=e6313131f874ee55056b262c30cbb3551^state=1^assigned_toISEMPTY&CSV"
        print(f"\nAbriendo lista de requerimientos: {req_url}")
        webbrowser.open(req_url)
        print("Se abrió una ventana del navegador.")
        input("Presione Intro una vez que el archivo se haya descargado en su carpeta de Descargas...")
        
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

def build_js_payloads(is_requirement, assignee_name, sys_id, due_date_str="", app_sys_id=""):
    """
    Construye las funciones ejecutables en JS para la consola DevTools de ServiceNow.
    Retorna una tupla (js_payload_1, js_payload_2). Para incidentes, js_payload_2 es None.
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
        return clean_js(js), None
    else:
        # REQUERIMIENTOS
        due_clean = str(due_date_str).replace("'", "\\'")
        
        # Payload 1: Asignación de Persona, Aplicación y Estado a "En proceso"
        js_1 = f"""(function() {{
            var sysId = '{sys_id_clean}';
            var name = '{assignee_clean}';
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
            console.log('Payload 1 ejecutado.');
        }})();"""

        # Payload 2: Actualización de Fecha y Guardar
        js_2 = f"""(function() {{
            var dueStr = '{due_clean}';
            if (dueStr) {{
                if (typeof g_form !== 'undefined') {{
                    try {{ g_form.setValue('u_fecha_prevista_de_finalizaci_n', dueStr); }} catch(e) {{}}
                }}
                var due = document.getElementById('sc_req_item.u_fecha_prevista_de_finalizaci_n');
                if (due) {{
                    due.value = dueStr;
                    due.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    due.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    due.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                }}
            }}
            setTimeout(function() {{
                {submit_code}
            }}, 500);
        }})();"""
        
        return clean_js(js_1), clean_js(js_2)

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
    print("      RPA DEVTOOLS DOM UPDATE WILL START IN 5 SECONDS")
    print("  Make sure your browser window responds to hotkeys.")
    print("!"*50)
    for i in range(5, 0, -1):
        print(f"Starting in {i}...")
        time.sleep(1)
        
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
        
        # Construir JavaScript payloads
        js_payload_1, js_payload_2 = build_js_payloads(is_requirement, assignee, sys_id, due_date_str, app_sys_id)
        
        # 1. Abrir ticket en el navegador
        ticket_url = f"{SERVICENOW_BASE_URL}/{table_name}.do?sysparm_query=number={ticket_id}"
        webbrowser.open(ticket_url, new=2)
        time.sleep(LOAD_TIME)
        
        # 2. Abrir consola DevTools (Ctrl+Shift+J)
        pyautogui.hotkey('ctrl', 'shift', 'j')
        time.sleep(1.0)
        
        # 3. Copiar script JS 1 al portapapeles y pegar en la consola
        pyperclip.copy(js_payload_1)
        time.sleep(CLIPBOARD_TIME)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(CLIPBOARD_TIME)
        pyautogui.press('enter')
        
        # 4. Si hay un segundo script (requerimientos), esperar 5 segundos y ejecutar
        if js_payload_2:
            print("Esperando 5 segundos para que cargue el campo de fecha y se resuelva la CMDB...")
            time.sleep(5.0)
            pyperclip.copy(js_payload_2)
            time.sleep(CLIPBOARD_TIME)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(CLIPBOARD_TIME)
            pyautogui.press('enter')
            
        time.sleep(1.5)
        
    print("\nServiceNow DevTools DOM update loop finished!")

def run_rpa_loop(min_mtime=None):
    """Ejecuta el pipeline E2E con actualización DOM."""
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
    print("6. Salir")
    
    choice = input("\nSeleccione una opción (1-6): ").strip()
    
    if choice == '1':
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
        print("\n--- Procesando únicamente Incidentes (Solo DOM) ---")
        inc_csv = find_latest_output_file("incidentes_con_asignacion_*.csv")
        if inc_csv:
            update_tickets_in_servicenow_dom(inc_csv, is_requirement=False)
        else:
            print("No se encontró archivo de salida de predicción para Incidentes.")
    elif choice == '3':
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
        print("\n--- Procesando únicamente Requerimientos (Solo DOM) ---")
        req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv")
        if req_csv:
            update_tickets_in_servicenow_dom(req_csv, is_requirement=True)
        else:
            print("No se encontró archivo de salida de predicción para Requerimientos.")
    elif choice == '5':
        run_rpa_loop()
    elif choice == '6':
        print("Saliendo...")
        sys.exit(0)
    else:
        print("Opción inválida.")

if __name__ == "__main__":
    main()
