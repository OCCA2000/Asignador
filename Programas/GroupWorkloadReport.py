import pandas as pd
import os
import sys
from datetime import datetime

# Add the parent directory to sys.path so we can import Programas.LoadBalancer
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Programas.LoadBalancer import WorkloadBalancer

def generate_report():
    print("Generating comprehensive group workload report...")
    
    # 1. Get workloads using the existing WorkloadBalancer class
    # We suppress standard output for this part just to keep the console clean
    import io
    from contextlib import redirect_stdout
    
    with io.StringIO() as buf, redirect_stdout(buf):
        balancer = WorkloadBalancer()
    
    workload = balancer.workload
    
    # 2. Parse Grupos.csv to map groups to users
    grupos_path = "Entrada/Grupos.csv"
    if not os.path.exists(grupos_path):
        print(f"Error: {grupos_path} not found.")
        return
        
    df_grupos = pd.read_csv(grupos_path, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')
    
    # Map: Group Name -> List of Users (dict containing name and active status)
    groups_to_users = {}
    
    for _, row in df_grupos.iterrows():
        nombre = str(row.get('NOMBRE', '')).strip().upper()
        if not nombre or nombre.lower() == 'nan':
            continue
            
        activo = str(row.get('ACTIVO', '')).strip().upper()
        
        # Check all three group columns
        for col in ['GRUPO 1', 'GRUPO 2', 'GRUPO 3']:
            grupo = str(row.get(col, '')).strip()
            if grupo and grupo.lower() != 'nan':
                if grupo not in groups_to_users:
                    groups_to_users[grupo] = []
                
                # Check if user is already in this group
                if not any(u['nombre'] == nombre for u in groups_to_users[grupo]):
                    groups_to_users[grupo].append({
                        'nombre': nombre,
                        'activo': activo == 'S',
                        'tickets': workload.get(nombre, 0)
                    })
                    
    # 3. Format Output
    timing = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    os.makedirs("Salida", exist_ok=True)
    report_path = f"Salida/reporte_carga_por_grupos_{timing}.txt"
    
    report_lines = []
    report_lines.append(f"Comprehensive Group Workload Report - {timing}")
    report_lines.append("=" * 65)
    report_lines.append("Includes users from all their assigned groups (Hierarchy independent)\n")
    
    # Sort groups alphabetically
    for grupo in sorted(groups_to_users.keys()):
        report_lines.append(f"\nGroup: {grupo}")
        report_lines.append("-" * 65)
        
        users = groups_to_users[grupo]
        # Sort users by ticket count (descending), then alphabetically
        users.sort(key=lambda x: (-x['tickets'], x['nombre']))
        
        total_tickets = 0
        for user in users:
            status = "" if user['activo'] else " [INACTIVE]"
            report_lines.append(f"{user['nombre'].ljust(45)} {user['tickets']:>3} tickets{status}")
            total_tickets += user['tickets']
            
        report_lines.append("-" * 65)
        report_lines.append(f"Total Users in Group: {len(users)}")
        report_lines.append(f"Total Tickets in Group: {total_tickets}\n")
        
    output_text = "\n".join(report_lines)
    
    # Print to console
    print("\n" + output_text)
    
    # Save to file
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(output_text)
        
    print(f"\nReport successfully saved to: {report_path}")

if __name__ == "__main__":
    generate_report()
