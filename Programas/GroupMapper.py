import pandas as pd
import os

def add_group_to_predictions(df, prediction_col="predicted_assigned_to", output_col="predicted_assignment_group", groups_path="Especificaciones/Grupos.csv"):
    """
    Mapea los nombres de asignados predichos a su grupo primario según Grupos.csv
    """
    if prediction_col not in df.columns:
        return df
        
    print("Mapping predicted assignees to their primary group...")
    
    # Verificar si Grupos.csv existe
    if not os.path.exists(groups_path):
        print(f"Warning: {groups_path} not found. Cannot map groups.")
        df[output_col] = "NO GROUP FOUND"
        return df
        
    try:
        # Cargar Grupos.csv
        df_groups = pd.read_csv(groups_path, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')
        
        # Crear un diccionario mapeando NOMBRE a GRUPO 1
        mapping_dict = {}
        for _, row in df_groups.iterrows():
            # Obtener el nombre y convertirlo a mayúsculas para un emparejamiento robusto
            name = str(row.get('NOMBRE', '')).strip().upper()
            
            # Obtener el grupo primario (GRUPO 1)
            group = str(row.get('GRUPO 1', '')).strip()
            
            # Si el grupo está vacío o es nan, asignar "NO GROUP FOUND"
            if not group or group.lower() == 'nan':
                group = "NO GROUP FOUND"
                
            if name and name.lower() != 'nan':
                mapping_dict[name] = group
                
        # Función para mapear nombres individuales
        def map_group(name):
            if pd.isna(name):
                return "NO GROUP FOUND"
                
            name_str = str(name).strip().upper()
            
            # Casos especiales
            if name_str == "TURNO":
                return "TURNO"
                
            return mapping_dict.get(name_str, "NO GROUP FOUND")
            
        # Aplicar el mapeo
        df[output_col] = df[prediction_col].apply(map_group)
        print("Group mapping completed successfully.")
        
    except Exception as e:
        print(f"Error mapping groups: {e}")
        df[output_col] = "NO GROUP FOUND"
        
    return df
