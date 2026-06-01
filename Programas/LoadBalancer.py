import pandas as pd
import os
from datetime import datetime, timedelta
from Programas.CleaningData import limpiar_archivo_csv
import random

class WorkloadBalancer:
    def __init__(self, grupos_path="Entrada/Grupos.csv", assigned_incidents="Entrada/assigned_incidents.csv", assigned_requirements="Entrada/assigned_requirements.csv", resolved_weight=0.5, resolved_days_window=7):
        self.grupos_path = grupos_path
        self.assigned_incidents = assigned_incidents
        self.assigned_requirements = assigned_requirements
        # Peso aplicado a los tickets resueltos al calcular la carga efectiva.
        # Valor entre 0 y 1: 0 = ignorar resueltos, 1 = equivalen a tickets abiertos.
        # Ejemplo: resolved_weight=0.5 → resolver 10 tickets suma 5 de carga efectiva.
        # Ajustar según qué tan agresivo se quiera penalizar a quienes resuelven rápido.
        self.resolved_weight = resolved_weight
        # Ventana de días hacia atrás para contabilizar tickets resueltos.
        # Solo se cuentan resueltos dentro de los últimos N días.
        # Ejemplo: resolved_days_window=7 → solo resueltos de la última semana.
        # Usar None para considerar todo el historial sin límite de tiempo.
        self.resolved_days_window = resolved_days_window
        # Tickets actualmente abiertos por persona {NOMBRE: cantidad}
        self.workload = {}
        # Tickets resueltos/cerrados por persona {NOMBRE: cantidad}
        # Se usa junto con resolved_weight para calcular la carga efectiva.
        self.resolved_workload = {}
        self.group_members_l1 = {}
        self.group_members_l2 = {}
        self.group_members_l3 = {}
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
            grupo1 = str(row.get('GRUPO 1', '')).strip()
            grupo2 = str(row.get('GRUPO 2', '')).strip()
            grupo3 = str(row.get('GRUPO 3', '')).strip()
            activo = str(row.get('ACTIVO', '')).strip().upper()
            
            if not grupo1 or grupo1.lower() == 'nan':
                grupo1 = "NO GROUP FOUND"
                
            if nombre and nombre.lower() != 'nan':
                self.name_to_group[nombre] = grupo1
                # Initialize workload counter
                if nombre not in self.workload:
                    self.workload[nombre] = 0
                
                # Add to group members if active
                if activo == 'S':
                    if grupo1 and grupo1.lower() != 'nan':
                        self.group_members_l1.setdefault(grupo1, []).append(nombre)
                    if grupo2 and grupo2.lower() != 'nan':
                        self.group_members_l2.setdefault(grupo2, []).append(nombre)
                    if grupo3 and grupo3.lower() != 'nan':
                        self.group_members_l3.setdefault(grupo3, []).append(nombre)

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

                    # --- MODIFICACIÓN: contabilizar resueltos para penalización parcial ---
                    # Antes se ignoraban los tickets cerrados; ahora se acumulan en resolved_workload
                    # para que personas que resuelven muchos tickets también tengan mayor carga efectiva
                    # y no reciban desproporcionadamente más asignaciones que sus compañeros.
                    if 'state' in df.columns and 'assigned_to' in df.columns:
                        df_resolved = df[df['state'].str.strip().str.title().isin(['Resuelto', 'Cerrado'])]
                        # Filtrar por ventana de tiempo si está configurada y existe columna de fecha
                        if self.resolved_days_window is not None and 'resolved_at' in df_resolved.columns:
                            cutoff = datetime.now() - timedelta(days=self.resolved_days_window)
                            fechas = pd.to_datetime(df_resolved['resolved_at'], dayfirst=True, errors='coerce')
                            df_resolved = df_resolved[fechas >= cutoff]
                        for name in df_resolved['assigned_to'].dropna():
                            name_str = str(name).strip().upper()
                            self.resolved_workload[name_str] = self.resolved_workload.get(name_str, 0) + 1

                    # Solo los tickets abiertos representan carga activa real (workload)
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

    def _effective_workload(self, name):
        """Calcula la carga efectiva de una persona combinando tickets abiertos y resueltos.

        Fórmula:
            carga_efectiva = tickets_abiertos + tickets_resueltos * resolved_weight

        El objetivo es que las personas que resuelven muchos tickets también acumulen
        carga efectiva, evitando que el balanceador les siga asignando tickets
        por el simple hecho de tener pocos tickets abiertos en ese momento.

        Ejemplo con resolved_weight=0.5:
            - Ana:  2 abiertos + 20 resueltos * 0.5 = 12.0 de carga efectiva
            - Luis: 4 abiertos +  2 resueltos * 0.5 =  5.0 de carga efectiva
            → Luis recibe el próximo ticket aunque Ana tenga menos abiertos.
        """
        return self.workload.get(name, 0) + self.resolved_workload.get(name, 0) * self.resolved_weight

    def balance_assignment(self, df, prediction_col="predicted_assigned_to", group_col="predicted_assignment_group"):
        if prediction_col not in df.columns:
            return df
            
        print("Applying load balancing logic with priorities and thresholds...")
        
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
            
            l1_candidates = self.group_members_l1.get(grupo, [])
            l2_candidates = self.group_members_l2.get(grupo, [])
            l3_candidates = self.group_members_l3.get(grupo, [])
            
            all_cands = list(set(l1_candidates + l2_candidates + l3_candidates))
            
            if grupo == "NO GROUP FOUND" or not all_cands:
                # Keep original if no active members found in any group level
                new_assignees.append(name_str) 
                continue
                
            # El umbral se calcula sobre la carga efectiva (no solo abiertos),
            # de modo que quienes resuelven muchos tickets también contribuyen
            # a elevar el umbral del grupo y no skippean la selección.
            group_mean = sum(self._effective_workload(m) for m in all_cands) / len(all_cands)
            threshold = group_mean + 3

            best_member = None

            # Level 1 priority
            if l1_candidates:
                random.shuffle(l1_candidates)
                cand = min(l1_candidates, key=self._effective_workload)
                if self._effective_workload(cand) <= threshold:
                    best_member = cand

            # Level 2 priority
            if not best_member and l2_candidates:
                random.shuffle(l2_candidates)
                cand = min(l2_candidates, key=self._effective_workload)
                if self._effective_workload(cand) <= threshold:
                    best_member = cand

            # Level 3 priority
            if not best_member and l3_candidates:
                random.shuffle(l3_candidates)
                cand = min(l3_candidates, key=self._effective_workload)
                if self._effective_workload(cand) <= threshold:
                    best_member = cand

            # Fallback if everyone is overloaded
            if not best_member:
                random.shuffle(all_cands)
                best_member = min(all_cands, key=self._effective_workload)
                
            # Registrar la nueva asignación en workload (tickets abiertos).
            # resolved_workload NO se incrementa aquí; solo crece cuando el ticket se cierra.
            new_assignees.append(best_member)
            self.workload[best_member] = self.workload.get(best_member, 0) + 1
            
        # Overwrite the prediction column
        df[prediction_col] = new_assignees
        df[group_col] = groups_assigned
        
        return df
