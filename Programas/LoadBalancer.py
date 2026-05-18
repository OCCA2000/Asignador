import pandas as pd
import os
from Programas.CleaningData import limpiar_archivo_csv
import random

class WorkloadBalancer:
    def __init__(self, grupos_path="Entrada/Grupos.csv", assigned_incidents="Entrada/assigned_incidents.csv", assigned_requirements="Entrada/assigned_requirements.csv"):
        self.grupos_path = grupos_path
        self.assigned_incidents = assigned_incidents
        self.assigned_requirements = assigned_requirements
        self.workload = {}
        self.group_members = {}
        self.name_to_group = {}
        
        self._load_grupos()
        self._load_initial_workload()

    def _load_grupos(self):
        if not os.path.exists(self.grupos_path):
            print(f"Warning: {self.grupos_path} not found.")
            return
            
        df_grupos = pd.read_csv(self.grupos_path, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')
        
        for _, row in df_grupos.iterrows():
            nombre = str(row.get('NOMBRE', '')).strip().upper()
            grupo = str(row.get('GRUPO 1', '')).strip()
            activo = str(row.get('ACTIVO', '')).strip().upper()
            
            if not grupo or grupo.lower() == 'nan':
                grupo = "NO GROUP FOUND"
                
            if nombre and nombre.lower() != 'nan':
                self.name_to_group[nombre] = grupo
                # Initialize workload counter
                if nombre not in self.workload:
                    self.workload[nombre] = 0
                
                # Add to group members if active
                if activo == 'S':
                    if grupo not in self.group_members:
                        self.group_members[grupo] = []
                    self.group_members[grupo].append(nombre)

    def _load_initial_workload(self):
        print("Calculating initial workload...")
        for file_path in [self.assigned_incidents, self.assigned_requirements]:
            if os.path.exists(file_path):
                temp_cleaned = file_path + ".temp.csv"
                try:
                    limpiar_archivo_csv(
                        ruta_entrada=file_path,
                        ruta_salida=temp_cleaned,
                        encoding="latin-1",
                        replacement=" ",
                        cambiar_separador=True,
                        nuevo_separador=';'
                    )
                    
                    df = pd.read_csv(temp_cleaned, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')
                    
                    # Filter out 'Resuelto' and 'Cerrado'
                    if 'state' in df.columns:
                        df = df[~df['state'].str.strip().str.title().isin(['Resuelto', 'Cerrado'])]
                        
                    if 'assigned_to' in df.columns:
                        for name in df['assigned_to'].dropna():
                            name_str = str(name).strip().upper()
                            if name_str in self.workload:
                                self.workload[name_str] += 1
                            else:
                                self.workload[name_str] = 1
                except Exception as e:
                    print(f"Error processing {file_path} for workload: {e}")
                finally:
                    if os.path.exists(temp_cleaned):
                        os.remove(temp_cleaned)

    def balance_assignment(self, df, prediction_col="predicted_assigned_to", group_col="predicted_assignment_group"):
        if prediction_col not in df.columns:
            return df
            
        print("Applying load balancing logic...")
        
        groups_assigned = []
        new_assignees = []
        
        for name in df[prediction_col]:
            if pd.isna(name):
                new_assignees.append("NO GROUP FOUND")
                groups_assigned.append("NO GROUP FOUND")
                continue
                
            name_str = str(name).strip().upper()
            
            if name_str == "TURNO":
                new_assignees.append("TURNO")
                groups_assigned.append("TURNO")
                continue
                
            grupo = self.name_to_group.get(name_str, "NO GROUP FOUND")
            groups_assigned.append(grupo)
            
            if grupo == "NO GROUP FOUND" or grupo not in self.group_members or not self.group_members[grupo]:
                # Keep original if no active members found in the assigned group
                new_assignees.append(name_str) 
                continue
                
            # Find active member with lowest workload
            members = self.group_members[grupo]
            random.shuffle(members)  # prevent always picking the same person on ties
            best_member = min(members, key=lambda m: self.workload.get(m, 0))
            
            # Assign and increment workload
            new_assignees.append(best_member)
            self.workload[best_member] = self.workload.get(best_member, 0) + 1
            
        # Overwrite the prediction column
        df[prediction_col] = new_assignees
        df[group_col] = groups_assigned
        
        return df
