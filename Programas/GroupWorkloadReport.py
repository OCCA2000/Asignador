import pandas as pd
import os
import sys
from datetime import datetime

# Agregar el directorio padre a sys.path para poder importar Programas.LoadBalancer
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Programas.LoadBalancer import WorkloadBalancer

def generate_report():
    print("Generating comprehensive group workload report...")
    
    # 1. Obtener cargas de trabajo usando la clase WorkloadBalancer existente
    # Ocultamos la salida estándar de esta parte para mantener limpia la consola
    import io
    from contextlib import redirect_stdout
    
    with io.StringIO() as buf, redirect_stdout(buf):
        balancer = WorkloadBalancer()
    
    workload = balancer.workload
    
    # 2. Analizar CSV de Grupos para mapear grupos a usuarios
    groups_path = "Especificaciones/Grupos - Incidentes(Grupos).csv"
    if not os.path.exists(groups_path):
        print(f"Error: {groups_path} not found.")
        return
        
    try:
        df_groups = pd.read_csv(groups_path, sep=',', encoding='latin-1', dtype=str)
        if len(df_groups.columns) == 1:
            df_groups = pd.read_csv(groups_path, sep=';', encoding='latin-1', dtype=str)
    except Exception:
        df_groups = pd.read_csv(groups_path, sep=';', encoding='latin-1', dtype=str)
    
    # Mapeo: Nombre de grupo -> Lista de usuarios (dict con nombre y estado activo)
    groups_to_users = {}
    
    for col in df_groups.columns:
        macro_group = str(col).strip().upper()
        if not macro_group or macro_group == 'NAN':
            continue
            
        if macro_group not in groups_to_users:
            groups_to_users[macro_group] = []
            
        for val in df_groups[col]:
            if pd.isna(val):
                continue
            name = str(val).strip().upper()
            if not name or name == 'NAN':
                continue
                
            # Verificar si el usuario ya está en este grupo
            if not any(u['name'] == name for u in groups_to_users[macro_group]):
                groups_to_users[macro_group].append({
                    'name': name,
                    'display': balancer.display_name(name),
                    'active': balancer.is_active(name),
                    'tickets': workload.get(name, 0)
                })
                    
    # 3. Formatear salida
    from Programas.CleaningData import get_output_path_date
    report_path, timing = get_output_path_date("reporte_carga_por_grupos", base_dir="Salida", ext=".txt")
    
    report_lines = []
    report_lines.append(f"Comprehensive Group Workload Report - {timing}")
    report_lines.append("=" * 65)
    report_lines.append("Includes users from all their assigned groups (Hierarchy independent)\n")
    
    # Ordenar grupos alfabéticamente
    for group in sorted(groups_to_users.keys()):
        report_lines.append(f"\nGroup: {group}")
        report_lines.append("-" * 65)
        
        users = groups_to_users[group]
        # Ordenar usuarios por cantidad de tickets (descendente) y luego alfabéticamente
        users.sort(key=lambda x: (-x['tickets'], x['name']))
        
        total_tickets = 0
        for user in users:
            status = "" if user['active'] else " [INACTIVE]"
            report_lines.append(f"{user['display'].ljust(50)} {user['tickets']:>3} tickets{status}")
            total_tickets += user['tickets']
            
        report_lines.append("-" * 65)
        report_lines.append(f"Total Users in Group: {len(users)}")
        report_lines.append(f"Total Tickets in Group: {total_tickets}\n")
        
    output_text = "\n".join(report_lines)
    
    # Imprimir en consola
    print("\n" + output_text)
    
    # Guardar en archivo
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(output_text)
        
    print(f"\nReport successfully saved to: {report_path}")

if __name__ == "__main__":
    generate_report()
