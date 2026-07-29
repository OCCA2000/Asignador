import pandas as pd
import os
import re
import unicodedata
from datetime import datetime, timedelta
from Programas.CleaningData import clean_csv_file
import random

def _normalize_text(text):
    if pd.isna(text):
        return ''
    s = str(text)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    s = s.lower().replace('.', '').replace('/', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s

class WorkloadBalancer:
    def __init__(self, groups_path="Especificaciones/Grupos - Incidentes(Grupos).csv", users_path="Especificaciones/Grupos - Usuarios.csv", assigned_incidents="Especificaciones/assigned_incidents.csv", assigned_requirements="Especificaciones/assigned_requirements.csv", resolved_weight=0.5, resolved_days_window=7, shifts_path="Especificaciones/Turnos.csv"):
        self.groups_path = groups_path
        self.users_path = users_path
        self.assigned_incidents = assigned_incidents
        self.assigned_requirements = assigned_requirements
        self.resolved_weight = resolved_weight
        self.resolved_days_window = resolved_days_window
        self.shifts_path = shifts_path
        self.workload = {}
        self.resolved_workload = {}
        self.group_members_l1 = {}
        self.group_members_l2 = {}
        self.group_members_l3 = {}
        self.classification_to_group = {}
        self.name_to_group = {}
        self.username_to_realname = {}
        self.name_tokens_to_username = {}
        self.active_usernames = set()
        self.df_shifts = None

        self._load_groups()
        self._load_users()
        self._load_shifts()
        self._load_initial_workload()

    def _load_shifts(self):
        if not self.shifts_path or not os.path.exists(self.shifts_path):
            print(f"Warning: {self.shifts_path} not found. Shift assignments will default to 'TURNO'.")
            return
        try:
            df = pd.read_csv(self.shifts_path, sep=';', encoding='latin-1', dtype=str)
            if len(df.columns) == 1:
                df = pd.read_csv(self.shifts_path, sep=',', encoding='latin-1', dtype=str)
            df.columns = [str(c).strip() for c in df.columns]
            if 'Fecha' in df.columns:
                df['Fecha'] = df['Fecha'].str.strip()
            self.df_shifts = df
            print(f"Successfully loaded shifts configuration from {self.shifts_path}")
        except Exception as e:
            print(f"Warning: failed to load shifts configuration from {self.shifts_path}: {e}")

    def get_shift_user(self, row):
        if self.df_shifts is None:
            return None
        ts_col = next((c for c in ['sys_created_on', 'opened_at'] if c in row), None)
        if not ts_col:
            return None
        sys_created_on = row.get(ts_col)
        if pd.isna(sys_created_on):
            return None
        try:
            dt = pd.to_datetime(str(sys_created_on).strip(), format='%d/%m/%Y %H:%M:%S', errors='coerce')
            if pd.isna(dt):
                dt = pd.to_datetime(str(sys_created_on).strip(), errors='coerce')
            if pd.isna(dt):
                return None
            time_val = dt.time()
            date_val = dt.date()
            weekday = dt.weekday() # 0 = Monday, 5 = Saturday, 6 = Sunday
            
            t0600 = datetime.strptime("06:00:00", "%H:%M:%S").time()
            t1400 = datetime.strptime("14:00:00", "%H:%M:%S").time()
            t2200 = datetime.strptime("22:00:00", "%H:%M:%S").time()
            
            if weekday == 5: # Saturday
                if time_val < t0600:
                    shift_col = "Turno 3"
                    shift_date = date_val - timedelta(days=1)
                elif t0600 <= time_val < t1400:
                    shift_col = "Turno 4"
                    shift_date = date_val
                else:
                    shift_col = "Stand-by"
                    shift_date = date_val
            elif weekday == 6: # Sunday
                shift_col = "Stand-by"
                shift_date = date_val
            elif weekday == 0 and time_val < t0600: # Monday early morning
                shift_col = "Stand-by"
                shift_date = date_val - timedelta(days=1)
            else: # Monday after 06:00, and Tuesday to Friday
                if t0600 <= time_val < t1400:
                    shift_col = "Turno 1"
                    shift_date = date_val
                elif t1400 <= time_val < t2200:
                    shift_col = "Turno 2"
                    shift_date = date_val
                else:
                    shift_col = "Turno 3"
                    if time_val < t0600:
                        shift_date = date_val - timedelta(days=1)
                    else:
                        shift_date = date_val
            
            shift_date_str = shift_date.strftime('%d/%m/%Y')
            if 'Fecha' not in self.df_shifts.columns or shift_col not in self.df_shifts.columns:
                return None
            match_rows = self.df_shifts[self.df_shifts['Fecha'] == shift_date_str]
            if match_rows.empty:
                shift_date_str_alt = shift_date.strftime('%Y-%m-%d')
                match_rows = self.df_shifts[self.df_shifts['Fecha'] == shift_date_str_alt]
            if not match_rows.empty:
                val = match_rows.iloc[0][shift_col]
                if pd.notna(val) and str(val).strip() != '':
                    username = str(val).strip().upper()
                    return self._canonical_assignee(username)
        except Exception as e:
            print(f"Error resolving shift user: {e}")
        return None

    def _load_groups(self):
        if not os.path.exists(self.groups_path):
            print(f"Warning: {self.groups_path} not found.")
            return
            
        try:
            # Try comma first
            df_groups = pd.read_csv(self.groups_path, sep=',', encoding='latin-1', dtype=str)
            if len(df_groups.columns) == 1:
                # Fallback to semicolon
                df_groups = pd.read_csv(self.groups_path, sep=';', encoding='latin-1', dtype=str)
        except Exception:
            df_groups = pd.read_csv(self.groups_path, sep=';', encoding='latin-1', dtype=str)
            
        def _singularize_phrase(s):
            tokens = s.split()
            tokens = [t[:-1] if t.endswith('s') else t for t in tokens]
            return ' '.join(tokens)

        for col in df_groups.columns:
            macro_group = str(col).strip().upper()
            if not macro_group or macro_group == 'NAN':
                continue

            # Build classification -> macro_group mapping using normalized keys
            norm_col = _normalize_text(col)
            sing_col = _singularize_phrase(norm_col)
            if norm_col:
                self.classification_to_group[norm_col] = macro_group
            if sing_col and sing_col != norm_col:
                self.classification_to_group[sing_col] = macro_group

            for val in df_groups[col]:
                if pd.isna(val):
                    continue
                name = str(val).strip().upper()
                if not name or name == 'NAN':
                    continue

                self.group_members_l1.setdefault(macro_group, []).append(name)
                self.name_to_group[name] = macro_group

                if name not in self.workload:
                    self.workload[name] = 0

    def _load_users(self):
        if not os.path.exists(self.users_path):
            print(f"Warning: {self.users_path} not found.")
            return

        try:
            try:
                # Try comma first
                df_users = pd.read_csv(self.users_path, sep=',', encoding='latin-1', dtype=str)
                if len(df_users.columns) == 1:
                    # Fallback to semicolon
                    df_users = pd.read_csv(self.users_path, sep=';', encoding='latin-1', dtype=str)
            except Exception:
                df_users = pd.read_csv(self.users_path, sep=';', encoding='latin-1', dtype=str)

            df_users.columns = [str(c).strip() for c in df_users.columns]

            if 'Nombre' not in df_users.columns or 'Usuario' not in df_users.columns:
                print(f"Warning: {self.users_path} missing expected columns 'Nombre'/'Usuario'.")
                return

            for _, row in df_users.iterrows():
                username_raw = row.get('Usuario')
                name_raw = row.get('Nombre')
                if pd.isna(username_raw) or pd.isna(name_raw):
                    continue

                username = str(username_raw).strip().upper()
                name = str(name_raw).strip().upper()
                if not username or not name:
                    continue

                self.username_to_realname[username] = name

                token_key = ' '.join(sorted(_normalize_text(name).upper().split()))
                if token_key:
                    self.name_tokens_to_username[token_key] = username

                status_raw = row.get('Estado')
                is_active = str(status_raw).strip() == '1' if not pd.isna(status_raw) else True
                if is_active:
                    self.active_usernames.add(username)
        except Exception as e:
            print(f"Warning: failed to load {self.users_path}: {e}")

    def _canonical_assignee(self, name):
        """Resuelve un valor de `assigned_to` (username o nombre real) al username canónico."""
        name_upper = str(name).strip().upper()
        if name_upper in self.username_to_realname:
            return name_upper

        token_key = ' '.join(sorted(_normalize_text(name_upper).upper().split()))
        return self.name_tokens_to_username.get(token_key, name_upper)

    def is_active(self, name):
        """Devuelve True si el usuario está activo (Estado=1) en el CSV de usuarios."""
        canonical = self._canonical_assignee(name)
        if not self.active_usernames:
            return True
        return canonical in self.active_usernames

    def display_name(self, key):
        """Devuelve el username canónico o el nombre real."""
        canonical = self._canonical_assignee(key)
        return self.username_to_realname.get(canonical, canonical)

    def _load_initial_workload(self):
        print("Calculating initial workload...")
        for file_path in [self.assigned_incidents, self.assigned_requirements]:
            if os.path.exists(file_path):
                temp_cleaned = file_path + ".temp.csv"
                try:
                    clean_csv_file(
                        input_path=file_path,
                        output_path=temp_cleaned,
                        encoding="latin-1",
                        replacement=" ",
                        change_separator=True,
                        new_separator=';'
                    )
                    
                    df = pd.read_csv(temp_cleaned, sep=';', dtype=str, engine='python', on_bad_lines='skip', encoding='latin-1')

                    if 'state' in df.columns and 'assigned_to' in df.columns:
                        df_resolved = df[df['state'].str.strip().str.title().isin(['Resuelto', 'Cerrado'])]
                        # Filtrar por ventana de tiempo si está configurada y existe columna de fecha
                        if self.resolved_days_window is not None and 'resolved_at' in df_resolved.columns:
                            cutoff = datetime.now() - timedelta(days=self.resolved_days_window)
                            dates = pd.to_datetime(df_resolved['resolved_at'], dayfirst=True, errors='coerce')
                            df_resolved = df_resolved[dates >= cutoff]
                        for name in df_resolved['assigned_to'].dropna():
                            name_str = self._canonical_assignee(name)
                            self.resolved_workload[name_str] = self.resolved_workload.get(name_str, 0) + 1

                    # Solo los tickets abiertos representan carga activa real (workload)
                    if 'state' in df.columns:
                        df = df[~df['state'].str.strip().str.title().isin(['Resuelto', 'Cerrado'])]

                    if 'assigned_to' in df.columns:
                        for name in df['assigned_to'].dropna():
                            name_str = self._canonical_assignee(name)
                            self.workload[name_str] = self.workload.get(name_str, 0) + 1
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

        for idx, row in df.iterrows():
            category_val = str(row.get("category", "")).strip()
            subcategory_val = str(row.get("u_subcategory", "")).strip()
            contact_type_val = str(row.get("contact_type", "")).strip()
            
            is_metadata_shift = (
                category_val == "Operación TI" or
                subcategory_val == "Batch" or
                contact_type_val == "Monitoreo"
            )
            
            classification_val = row.get(available_cls_col, '')
            
            if is_metadata_shift:
                shift_user = self.get_shift_user(row)
                if shift_user:
                    new_assignees.append(shift_user)
                    self.workload[shift_user] = self.workload.get(shift_user, 0) + 1
                else:
                    new_assignees.append("TURNO")
                df.at[idx, available_cls_col] = "turno"
                continue
                
            if(classification_val == 'trickle feed' or classification_val == 'reporte batch'):
                shift_user = self.get_shift_user(row)
                if shift_user:
                    new_assignees.append(shift_user)
                    self.workload[shift_user] = self.workload.get(shift_user, 0) + 1
                else:
                    new_assignees.append("TURNO")
                continue
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
            l1_candidates = [m for m in self.group_members_l1.get(macrogrupo, []) if self.is_active(m)]
            l2_candidates = [m for m in self.group_members_l2.get(macrogrupo, []) if self.is_active(m)]
            l3_candidates = [m for m in self.group_members_l3.get(macrogrupo, []) if self.is_active(m)]
            
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
