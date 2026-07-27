#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ServiceNow End-to-End RPA Assignment Tool
Automates:
1. Downloading incidents/requirements lists from ServiceNow.
2. Executing machine learning assignment models.
3. Updating the Assigned To field in ServiceNow using direct coordinates.
"""

import os
import glob
import time
import json
import shutil
import subprocess
import webbrowser
from datetime import datetime, timedelta
import pandas as pd
import pyautogui
import pyperclip
from Programas.CleaningData import archive_previous_files

# ==========================================
# CONFIGURATION
# ==========================================
SERVICENOW_BASE_URL = "https://bancopichincha.service-now.com.mcas.ms"

# Toggle whether to download files from ServiceNow or use existing files in Entrada/
SKIP_DOWNLOAD = True

# Safety Dry Run Mode: Will navigate and fill fields but NOT click "Update/Save"
DRY_RUN = True

# PyAutoGUI settings
pyautogui.FAILSAFE = True  # Move mouse to top-left corner to abort execution
pyautogui.PAUSE = 1.0      # Pause after each GUI action (in seconds)

# Delay configs (adjust based on your network speed/ServiceNow response time)
LOAD_TIME = 5.0            # Time to wait for ticket page to load
CLIPBOARD_TIME = 0.5       # Time to wait after copy/paste operations

# Configuration and data directories
ESPECIFICACIONES_DIR = "Especificaciones"
INCIDENT_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "rpa_config_incidents.json")
REQUIREMENT_CONFIG_FILE = os.path.join(ESPECIFICACIONES_DIR, "rpa_config_requirements.json")
ENTRADA_DIR = "Entrada"
SALIDA_DIR = "Salida"

# ==========================================
# SETUP / COORDINATES CALIBRATION MODE
# ==========================================
def run_setup():
    """Interactively captures screen coordinates for input fields and buttons."""
    os.makedirs(ESPECIFICACIONES_DIR, exist_ok=True)
    print("\n" + "="*50)
    print("      SERVICENOW RPA SETUP & COORDINATES CALIBRATION")
    print("="*50)
    print("Choose which configuration to calibrate:")
    print("1. Incidents (2 coordinates: Assigned to, Save/Update)")
    print("2. Requirements (5 coordinates: Assigned to, Status, Due date, Application, Save/Update)")
    print("3. Both")
    
    choice = input("Select an option (1-3): ").strip()
    
    if choice in ('1', '3'):
        print("\n" + "="*40)
        print("          CALIBRATING INCIDENT COORDINATES")
        print("="*40)
        print("Please open your browser, maximize it, navigate to a ServiceNow INCIDENT page,")
        print("and make sure it is fully visible on your primary monitor.")
        
        print("\n--- STEP 1: Calibrate 'Assigned to' Input Box ---")
        print("Action: Move your mouse cursor directly over the center of the 'Assigned to' (or 'Asignado a') INPUT text box.")
        input("Once the cursor is positioned, return here and press Enter to save coordinates...")
        assigned_to_x, assigned_to_y = pyautogui.position()
        print(f"Captured 'Assigned to' Coordinates: X={assigned_to_x}, Y={assigned_to_y}")
        
        print("\n--- STEP 2: Calibrate 'Update' or 'Save' Button ---")
        print("Action: Move your mouse cursor directly over the center of the 'Update' (or 'Actualizar' / 'Save') button.")
        input("Once the cursor is positioned, return here and press Enter to save coordinates...")
        update_x, update_y = pyautogui.position()
        print(f"Captured 'Update' Coordinates: X={update_x}, Y={update_y}")
        
        config = {
            "assigned_to_x": assigned_to_x,
            "assigned_to_y": assigned_to_y,
            "update_x": update_x,
            "update_y": update_y
        }
        
        with open(INCIDENT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"Incident configuration saved successfully to: {INCIDENT_CONFIG_FILE}")
        
    if choice in ('2', '3'):
        print("\n" + "="*40)
        print("          CALIBRATING REQUIREMENT COORDINATES")
        print("="*40)
        print("Please open your browser, maximize it, navigate to a ServiceNow REQUIREMENT page.")
        print("Note: If 'Due date' is not visible, temporarily change status to 'En proceso' first.")
        print("Make sure it is fully visible on your primary monitor.")
        
        print("\n--- STEP 1: Calibrate 'Assigned to' Input Box ---")
        print("Action: Move your mouse cursor directly over the center of the 'Assigned to' (or 'Asignado a') INPUT text box.")
        input("Once the cursor is positioned, return here and press Enter...")
        assigned_to_x, assigned_to_y = pyautogui.position()
        
        print("\n--- STEP 2: Calibrate 'Status' Combobox ---")
        print("Action: Move your mouse cursor directly over the center of the 'Status' (or 'Estado') COMBOBOX.")
        input("Once the cursor is positioned, return here and press Enter...")
        status_x, status_y = pyautogui.position()
        
        print("\n--- STEP 3: Calibrate 'Due date' Input Box ---")
        print("Action: Move your mouse cursor directly over the center of the 'Due date' (or 'Fecha de vencimiento/compromiso') INPUT text box.")
        input("Once the cursor is positioned, return here and press Enter...")
        due_date_x, due_date_y = pyautogui.position()
        
        print("\n--- STEP 4: Calibrate 'Application' Input Box ---")
        print("Action: Move your mouse cursor directly over the center of the 'Application' (or 'Aplicación') INPUT text box.")
        input("Once the cursor is positioned, return here and press Enter...")
        application_x, application_y = pyautogui.position()
        
        print("\n--- STEP 5: Calibrate 'Update' or 'Save' Button ---")
        print("Action: Move your mouse cursor directly over the center of the 'Update' (or 'Actualizar' / 'Save') button.")
        input("Once the cursor is positioned, return here and press Enter...")
        update_x, update_y = pyautogui.position()
        
        config = {
            "assignation_textbox_x": assigned_to_x,
            "assignation_textbox_y": assigned_to_y,
            "status_combobox_x": status_x,
            "status_combobox_y": status_y,
            "due_date_textbox_x": due_date_x,
            "due_date_textbox_y": due_date_y,
            "application_textbox_x": application_x,
            "application_textbox_y": application_y,
            "save_button_x": update_x,
            "save_button_y": update_y
        }
        
        with open(REQUIREMENT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
        print(f"Requirement configuration saved successfully to: {REQUIREMENT_CONFIG_FILE}")
        
    print("\n" + "="*50)
    print("Setup calibration phase completed.")
    print("You can now run the script in standard or dry-run mode.")
    print("="*50 + "\n")

# ==========================================
# CONFIG RESOLUTION
# ==========================================
def load_config(config_file):
    """Loads calibration coordinates from the JSON configuration file."""
    # Legacy fallback for incidents
    if config_file == INCIDENT_CONFIG_FILE and not os.path.exists(config_file):
        legacy_spec = os.path.join(ESPECIFICACIONES_DIR, "rpa_config.json")
        if os.path.exists(legacy_spec):
            print("Using legacy configuration file: Especificaciones/rpa_config.json")
            config_file = legacy_spec
        elif os.path.exists("rpa_config.json"):
            print("Using legacy configuration file: rpa_config.json")
            config_file = "rpa_config.json"
        
    if not os.path.exists(config_file):
        print(f"\n[ERROR] Configuration file '{config_file}' not found.")
        print("Please run Setup Mode (Option 4) first to calibrate your screen coordinates.")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading calibration config '{config_file}': {e}")
        return None

# ==========================================
# FILE UTILITIES
# ==========================================
def get_downloads_folder():
    """Resolves the path to the user's default Downloads folder."""
    return os.path.join(os.path.expanduser("~"), "Downloads")

def move_latest_download(pattern, destination_name):
    """Finds the most recent download matching a pattern and moves it to Entrada/"""
    downloads_dir = get_downloads_folder()
    search_path = os.path.join(downloads_dir, pattern)
    files = glob.glob(search_path)
    
    if not files:
        print(f"No files found in Downloads matching: {pattern}")
        return False
        
    # Sort files by modification time (most recent first)
    files.sort(key=os.path.getmtime, reverse=True)
    latest_file = files[0]
    
    dest_path = os.path.join(ENTRADA_DIR, destination_name)
    os.makedirs(ENTRADA_DIR, exist_ok=True)
    
    try:
        shutil.copy2(latest_file, dest_path)
        print(f"Copied latest file: {latest_file} -> {dest_path}")
        return True
    except Exception as e:
        print(f"Error copying file {latest_file}: {e}")
        return False

def find_latest_output_file(pattern, min_mtime=None):
    """Returns the path to the most recent output prediction CSV in root Salida/."""
    search_path = os.path.join(SALIDA_DIR, pattern)
    files = [f for f in glob.glob(search_path) if os.path.isfile(f)]
    
    if min_mtime is not None:
        files = [f for f in files if os.path.getmtime(f) >= min_mtime]

    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]

# ==========================================
# E2E RUNNERS
# ==========================================
def run_downloads():
    """Handles the downloading of tickets from ServiceNow."""
    print("\n" + "="*50)
    print("              1. CSV DOWNLOADING PHASE")
    print("="*50)
    
    # 1. Incidents
    incident_url = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=assignment_group=e6313131f874ee55056b262c30cbb3551^ORassignment_group=36ea16e087548210f2e1cbf80cbb35fd^assigned_toISEMPTY^stateIN1,2&CSV"
    print(f"Opening Incident list page: {incident_url}")
    webbrowser.open(incident_url)
    print("A browser window was opened.")
    print("Please export the list to CSV if the download doesn't trigger automatically.")
    input("Press Enter once the file is downloaded to your Downloads folder...")
    
    # Move download
    if not move_latest_download("*incident*.csv", "incident.csv"):
        print("Warning: Could not automatically find/move incident CSV file. Please make sure Entrada/incident.csv exists.")
        
    # 2. Requirements
    req_url = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=assignment_group=36ea16e087548210f2e1cbf80cbb35fd^ORassignment_group=e6313131f874ee55056b262c30cbb3551^state=1^assigned_toISEMPTY&CSV"
    print(f"\nOpening Requirements list page: {req_url}")
    webbrowser.open(req_url)
    print("A browser window was opened.")
    print("Please export the list to CSV if the download doesn't trigger automatically.")
    input("Press Enter once the file is downloaded to your Downloads folder...")
    
    if not move_latest_download("*sc_req_item*.csv", "sc_req_item.csv"):
        print("Warning: Could not automatically find/move requirements CSV file. Please make sure Entrada/sc_req_item.csv exists.")

def run_predictions():
    """Runs the machine learning prediction scripts."""
    print("\n" + "="*50)
    print("              2. PREDICTION MODELS PHASE")
    print("="*50)
    
    # Archivar ejecuciones anteriores en Salida/ hacia sus carpetas por fecha
    archive_previous_files(SALIDA_DIR, "*.csv")
    archive_previous_files(SALIDA_DIR, "*.txt")
    
    # Run Incident Assigner
    print("Running Assigner_Incidents.py...")
    try:
        subprocess.run(["py", "Assigner_Incidents.py"], check=True)
        print("Incident predictions complete!")
    except subprocess.CalledProcessError as e:
        print(f"Error executing Assigner_Incidents.py: {e}")
        
    # Run Requirement Assigner
    print("\nRunning Assigner_Requirements.py...")
    try:
        subprocess.run(["py", "Assigner_Requirements.py"], check=True)
        print("Requirement predictions complete!")
    except subprocess.CalledProcessError as e:
        print(f"Error executing Assigner_Requirements.py: {e}")

def update_tickets_in_servicenow(csv_path, coordinates, is_requirement=False):
    """Reads predicted assignments and updates tickets via browser control."""
    if not csv_path or not os.path.exists(csv_path):
        print(f"No prediction file found for processing.")
        return
        
    print(f"\nProcessing assignments from: {csv_path}")
    df = pd.read_csv(csv_path, sep=';', encoding='latin-1', dtype=str)
    
    # Identify column names
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
        
        # Open the ticket in a new browser tab
        webbrowser.open(ticket_url, new=2)
        time.sleep(LOAD_TIME)
            
        # 1. Click and focus "Assigned to" input box
        pyautogui.click(assigned_to_x, assigned_to_y)
        time.sleep(0.5)
        
        # Clear field and paste assignee name
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        time.sleep(CLIPBOARD_TIME)
        pyperclip.copy(str(assignee))
        time.sleep(CLIPBOARD_TIME)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(CLIPBOARD_TIME)
        pyautogui.press('enter')
        time.sleep(1.0)  # Wait for autocomplete dropdown to settle
        pyautogui.press('tab')
        time.sleep(0.5)
        
        if is_requirement:
            # 2. Click Status combobox and change to "En proceso"
            print("Changing status from 'Nuevo' to 'En proceso'...")
            pyautogui.click(status_x, status_y)
            time.sleep(0.5)
            pyperclip.copy("En proceso")
            time.sleep(CLIPBOARD_TIME)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(CLIPBOARD_TIME)
            pyautogui.press('enter')
            # Wait for due date textbox to appear after status is changed
            print("Waiting for due date textbox to appear...")
            time.sleep(2.0)
            
            # 3. Fill Due Date textbox
            due_date = row.get('fecha_resolucion')
            due_date_str = ""
            if pd.notna(due_date) and str(due_date).strip():
                try:
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d'):
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
                # Fallback to current date plus 30 days
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
            
            # 4. Fill Application textbox (always "Bancs")
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
            
        # Click Update/Save button (if not in dry run)
        if not DRY_RUN:
            pyautogui.click(update_x, update_y)
            print(f"Clicked 'Update/Save' button at ({update_x}, {update_y})")
            time.sleep(LOAD_TIME)
        else:
            print(f"[DRY RUN] Bypassing click on 'Update/Save' button at ({update_x}, {update_y}). Changes not saved.")
            time.sleep(1.0)
            
    print("\nServiceNow UI update loop finished!")

def run_rpa_loop(min_mtime=None):
    """Orchestrates the UI update loop for both incidents and requirements."""
    # Load coordinates first
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
# DAEMON MODE
# ==========================================
def run_daemon_mode():
    """Runs the RPA automation loop continuously at set intervals."""
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
        
        # Sleep in 5-second increments to stay responsive to Ctrl+C interrupts
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
    print("6. Exit")
    
    choice = input("\nSelect an option (1-6): ").strip()
    
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
        print("Exiting. Have a great day!")
        return
        
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
