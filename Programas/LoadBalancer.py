import pandas as pd
import os
import re
import unicodedata
from datetime import datetime, timedelta
from Programas.CleaningData import limpiar_archivo_csv
import random

class WorkloadBalancer:
    def __init__(self, grupos_path="Entrada/Grupos - Incidentes(Grupos).csv", assigned_incidents="Entrada/assigned_incidents.csv", assigned_requirements="Entrada/assigned_requirements.csv", resolved_weight=0.5, resolved_days_window=7):
        self.grupos_path = grupos_path
        self.assigned_incidents = assigned_incidents
        self.assigned_requirements = assigned_requirements
        self.resolved_weight = resolved_weight
        self.resolved_days_window = resolved_days_window
        self.workload = {}
        self.resolved_workload = {}
        self.group_members_l1 = {}
        self.group_members_l2 = {}
        self.group_members_l3 = {}
        self.classification_to_group = {}
        self.name_to_group = {}
        
        self._load_grupos()
        self._load_initial_workload()

    def _load_grupos(self):
        if not os.path.exists(self.grupos_path):
            print(f"Warning: {self.grupos_path} not found.")
            return
            
        try:
            # Intentar leer por coma primero
            df_grupos = pd.read_csv(self.grupos_path, sep=',', encoding='latin-1', dtype=str)
            if len(df_grupos.columns) == 1:
                # Fallback a punto y coma
                df_grupos = pd.read_csv(self.grupos_path, sep=';', encoding='latin-1', dtype=str)
        except Exception:
            df_grupos = pd.read_csv(self.grupos_path, sep=';', encoding='latin-1', dtype=str)
            
        # El nuevo formato: Las columnas son los Macrogrupos, las filas debajo son los miembros
        def _normalize_text(text):
            if pd.isna(text):
                return ''
            s = str(text)
            s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
            s = s.lower().replace('.', '').replace('/', ' ')
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        def _singularize_phrase(s):
            tokens = s.split()
            tokens = [t[:-1] if t.endswith('s') else t for t in tokens]
            return ' '.join(tokens)

        for col in df_grupos.columns:
            macrogrupo = str(col).strip().upper()
            if not macrogrupo or macrogrupo == 'NAN':
                continue

            # Build classification -> macrogrupo mapping using normalized keys
            norm_col = _normalize_text(col)
            sing_col = _singularize_phrase(norm_col)
            if norm_col:
                self.classification_to_group[norm_col] = macrogrupo
            if sing_col and sing_col != norm_col:
                self.classification_to_group[sing_col] = macrogrupo

            for val in df_grupos[col]:
                if pd.isna(val):
                    continue
                nombre = str(val).strip().upper()
                if not nombre or nombre == 'NAN':
                    continue

                # Asignamos la persona al macrogrupo en Nivel 1 (igual prioridad para todos)
                self.group_members_l1.setdefault(macrogrupo, []).append(nombre)
                self.name_to_group[nombre] = macrogrupo

                if nombre not in self.workload:
                    self.workload[nombre] = 0

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

    def balance_assignment(self, df, classification_col="Clasificación", assigned_col="assigned_to"):
        """Balancea asignaciones usando directamente la columna de `Clasificación`.

        - Busca la primera columna disponible entre `classification_col`, `Clasificacion`, `classification`.
        - Normaliza la clasificación y la mapea al grupo usando `self.classification_to_group`.
        - Si no hay mapping exacto, intenta coincidencias parciales.
        """
        classification_col_candidates = [classification_col, 'Clasificacion', 'classification']

        def _normalize_text(text):
            if pd.isna(text):
                return ''
            s = str(text)
            s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
            s = s.lower().replace('.', '').replace('/', ' ')
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        def _singularize_phrase(s):
            tokens = s.split()
            tokens = [t[:-1] if t.endswith('s') else t for t in tokens]
            return ' '.join(tokens)

        # Seleccionar la columna real de clasificación disponible
        available_cls_col = next((c for c in classification_col_candidates if c in df.columns), None)
        if not available_cls_col:
            print(f"Warning: no se encontró ninguna columna de clasificación entre {classification_col_candidates}.")
            return df

        print(f"Aplicando balanceo de carga usando la columna: {available_cls_col}")

        new_assignees = []

        for _, row in df.iterrows():
            classification_val = row.get(available_cls_col, '')
            if pd.isna(classification_val) or str(classification_val).strip() == '':
                new_assignees.append("SIN_CLASIFICACION")
                continue

            norm_cls = _normalize_text(classification_val)
            sing = _singularize_phrase(norm_cls)

            # 1) mapping directo desde classification_to_group
            macrogrupo = None
            if norm_cls in self.classification_to_group:
                macrogrupo = self.classification_to_group[norm_cls]
            elif sing in self.classification_to_group:
                macrogrupo = self.classification_to_group[sing]
            else:
                # 2) búsqueda por inclusión en las claves normalizadas
                found = None
                for key_norm, val_group in self.classification_to_group.items():
                    if norm_cls == key_norm or norm_cls in key_norm or key_norm in norm_cls:
                        found = val_group
                        break
                macrogrupo = found

            if not macrogrupo:
                # No se pudo mapear: marcar sin macrogrupo
                new_assignees.append("SIN_ASIGNAR_SIN_GRUPO")
                continue

            # Obtener candidatos por nombre de macrogrupo (las keys en group_members_l1 son UPPER)
            l1_candidates = self.group_members_l1.get(macrogrupo, [])
            l2_candidates = self.group_members_l2.get(macrogrupo, [])
            l3_candidates = self.group_members_l3.get(macrogrupo, [])
            
            all_cands = list(set(l1_candidates + l2_candidates + l3_candidates))
            
            if not all_cands:
                # Nadie configurado para este macrogrupo
                new_assignees.append("SIN ASIGNAR (SIN MIEMBROS)") 
                continue
                
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
                
            new_assignees.append(best_member)
            self.workload[best_member] = self.workload.get(best_member, 0) + 1
            
        # Creamos/Sobreescribimos la columna de asignación final
        df[assigned_col] = new_assignees
        
        return df
