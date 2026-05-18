import pandas as pd
import os

def add_group_to_predictions(df, prediction_col="predicted_assigned_to", output_col="predicted_assignment_group", grupos_path="Entrada/Grupos.csv"):
    """
    Maps the predicted assignee names to their primary group based on Grupos.csv
    """
    if prediction_col not in df.columns:
        return df
        
    print("Mapping predicted assignees to their primary group...")
    
    # Check if Grupos.csv exists
    if not os.path.exists(grupos_path):
        print(f"Warning: {grupos_path} not found. Cannot map groups.")
        df[output_col] = "NO GROUP FOUND"
        return df
        
    try:
        # Load Grupos.csv. Assuming utf-8 or latin-1 encoding might be used.
        # We will use python engine and skip bad lines just in case
        df_grupos = pd.read_csv(grupos_path, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')
        
        # Create a dictionary mapping NOMBRE to GRUPO 1
        mapping_dict = {}
        for _, row in df_grupos.iterrows():
            # Get name and uppercase it for robust matching
            nombre = str(row.get('NOMBRE', '')).strip().upper()
            
            # Get the primary group (GRUPO 1)
            grupo = str(row.get('GRUPO 1', '')).strip()
            
            # If the group is empty or nan, assign "NO GROUP FOUND"
            if not grupo or grupo.lower() == 'nan':
                grupo = "NO GROUP FOUND"
                
            if nombre and nombre.lower() != 'nan':
                mapping_dict[nombre] = grupo
                
        # Function to map individual names
        def map_group(name):
            if pd.isna(name):
                return "NO GROUP FOUND"
                
            name_str = str(name).strip().upper()
            
            # Special cases
            if name_str == "TURNO":
                return "TURNO"
                
            return mapping_dict.get(name_str, "NO GROUP FOUND")
            
        # Apply the mapping
        df[output_col] = df[prediction_col].apply(map_group)
        print("Group mapping completed successfully.")
        
    except Exception as e:
        print(f"Error mapping groups: {e}")
        df[output_col] = "NO GROUP FOUND"
        
    return df
