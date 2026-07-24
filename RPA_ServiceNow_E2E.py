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
import pandas as pd
import pyautogui
import pyperclip

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
CONFIG_FILE = "rpa_config.json"
ENTRADA_DIR = "Entrada"
SALIDA_DIR = "Salida"

# ==========================================
# SETUP / COORDINATES CALIBRATION MODE
# ==========================================
def run_setup():
    """Interactively captures screen coordinates for input fields and buttons."""
    print("\n" + "="*50)
    print("      SERVICENOW RPA SETUP & COORDINATES CALIBRATION")
    print("="*50)
    print("This mode captures the direct screen coordinates of fields on your monitor.")
    print("Please open your browser, maximize it, navigate to a ServiceNow ticket page,")
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
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
        
    print("\n" + "="*50)
    print(f"Setup completed successfully! Config saved to: {CONFIG_FILE}")
    print("You can now run the script in standard or dry-run mode.")
    print("="*50 + "\n")

# ==========================================
# CONFIG RESOLUTION
# ==========================================
def load_config():
    """Loads calibration coordinates from the JSON configuration file."""
    if not os.path.exists(CONFIG_FILE):
        print(f"\n[ERROR] Configuration file '{CONFIG_FILE}' not found.")
        print("Please run Setup Mode (Option 4) first to calibrate your screen coordinates.")
        return None
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading calibration config: {e}")
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

def find_latest_output_file(pattern):
    """Returns the path to the most recent output prediction CSV."""
    search_path = os.path.join(SALIDA_DIR, pattern)
    files = glob.glob(search_path)
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
    incident_url = f"{SERVICENOW_BASE_URL}/incident_list.do?sysparm_query=active=true^assigned_toISEMPTY&CSV"
    print(f"Opening Incident list page: {incident_url}")
    webbrowser.open(incident_url)
    print("A browser window was opened.")
    print("Please export the list to CSV if the download doesn't trigger automatically.")
    input("Press Enter once the file is downloaded to your Downloads folder...")
    
    # Move download
    if not move_latest_download("*incident*.csv", "incident.csv"):
        print("Warning: Could not automatically find/move incident CSV file. Please make sure Entrada/incident.csv exists.")
        
    # 2. Requirements
    req_url = f"{SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query=active=true^assigned_toISEMPTY&CSV"
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
        # Click at the exact calibrated coordinates
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
        
        # 2. Click Update/Save button (if not in dry run)
        if not DRY_RUN:
            pyautogui.click(update_x, update_y)
            print(f"Clicked 'Update' button at ({update_x}, {update_y})")
            time.sleep(LOAD_TIME)
        else:
            print(f"[DRY RUN] Bypassing click on 'Update' button at ({update_x}, {update_y}). Changes not saved.")
            time.sleep(1.0)
            
    print("\nServiceNow UI update loop finished!")

def run_rpa_loop():
    """Orchestrates the UI update loop for both incidents and requirements."""
    # Load coordinates first
    coords = load_config()
    if not coords:
        return
        
    print("\n" + "="*50)
    print("              3. SERVICENOW UI UPDATING PHASE")
    print("="*50)
    
    latest_incident_csv = find_latest_output_file("incidentes_con_asignacion_*.csv")
    if latest_incident_csv:
        print(f"Latest Incident prediction file found: {latest_incident_csv}")
        update_tickets_in_servicenow(latest_incident_csv, coords, is_requirement=False)
    else:
        print("No incident predictions output file found in Salida/ to process.")
        
    latest_req_csv = find_latest_output_file("requerimientos_con_asignacion_*.csv")
    if latest_req_csv:
        print(f"Latest Requirement prediction file found: {latest_req_csv}")
        update_tickets_in_servicenow(latest_req_csv, coords, is_requirement=True)
    else:
        print("No requirement predictions output file found in Salida/ to process.")

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
    print("5. Exit")
    
    choice = input("\nSelect an option (1-5): ").strip()
    
    global SKIP_DOWNLOAD, DRY_RUN
    
    if choice == '1':
        SKIP_DOWNLOAD = False
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        run_downloads()
        run_predictions()
        run_rpa_loop()
        
    elif choice == '2':
        SKIP_DOWNLOAD = True
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        run_predictions()
        run_rpa_loop()
        
    elif choice == '3':
        dry_choice = input("Run in DRY RUN mode? (Navigates/fills fields without saving) [y/N]: ").strip().lower()
        DRY_RUN = dry_choice != 'n'
        
        run_rpa_loop()
        
    elif choice == '4':
        run_setup()
        
    elif choice == '5':
        print("Exiting. Have a great day!")
        return
        
    else:
        print("Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
