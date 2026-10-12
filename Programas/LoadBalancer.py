import pandas as pd
import os
import re
import unicodedata
from datetime import datetime, timedelta
from Programas.PipelineUtils import clean_csv_file, get_windows_date_format
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
            df = None
            for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                for sep in (';', ','):
                    try:
                        df_tmp = pd.read_csv(self.shifts_path, sep=sep, encoding=enc, dtype=str)
                        if df_tmp is not None and not df_tmp.empty:
                            clean_cols = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df_tmp.columns]
                            if any(c.lower() == 'fecha' for c in clean_cols):
                                df_tmp.columns = clean_cols
                                df = df_tmp
                                break
                    except Exception:
                        continue
                if df is not None:
                    break

            if df is not None:
                fecha_col = next((c for c in df.columns if c.lower() == 'fecha'), 'Fecha')
                if fecha_col != 'Fecha':
                    df.rename(columns={fecha_col: 'Fecha'}, inplace=True)
                df['Fecha'] = df['Fecha'].str.strip()
                self.df_shifts = df
                print(f"Successfully loaded shifts configuration from {self.shifts_path}")
            else:
                print(f"Warning: could not parse shifts configuration from {self.shifts_path}")
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
            win_fmt = get_windows_date_format()
            dt = pd.to_datetime(str(sys_created_on).strip(), format=f"{win_fmt} %H:%M:%S", errors='coerce')
            if pd.isna(dt):
                dt = pd.to_datetime(str(sys_created_on).strip(), format=win_fmt, errors='coerce')
            if pd.isna(dt):
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

            if 'Fecha' not in self.df_shifts.columns:
                return None

            # Parsear la columna 'Fecha' dinámicamente asegurando comparación uniforme de fechas (YYYY-MM-DD)
            parsed_dt = pd.to_datetime(self.df_shifts['Fecha'], format=win_fmt, errors='coerce')
            if parsed_dt.isna().any():
                fallback_dt = pd.to_datetime(self.df_shifts['Fecha'], dayfirst=True, errors='coerce')
                parsed_dt = parsed_dt.fillna(fallback_dt)
            if parsed_dt.isna().any():
                fallback_dt2 = pd.to_datetime(self.df_shifts['Fecha'], errors='coerce')
                parsed_dt = parsed_dt.fillna(fallback_dt2)
            parsed_fecha_col = parsed_dt.dt.strftime('%Y-%m-%d')

            def _get_row(target_d):
                target_str = target_d.strftime('%Y-%m-%d')
                matches = self.df_shifts[parsed_fecha_col == target_str]
                if not matches.empty:
                    return matches.iloc[0]
                return None

            def _clean_val(row_s, col):
                if row_s is not None and col in row_s:
                    v = row_s[col]
                    if pd.notna(v) and str(v).strip() != '':
                        return str(v).strip().upper()
                return None

            assignee = None

            if time_val < t0600:
                # Madrugada (00:00 a 05:59): pertenece al turno nocturno de la noche anterior
                prev_date = date_val - timedelta(days=1)
                row_prev = _get_row(prev_date)
                
                # 1) Si la noche anterior tuvo Turno 3 asignado
                t3_prev = _clean_val(row_prev, "Turno 3")
                if t3_prev:
                    assignee = t3_prev
                else:
                    # 2) Si la noche anterior fue fin de semana o feriado, estuvo en Stand-by
                    sb_prev = _clean_val(row_prev, "Stand-by")
                    if sb_prev:
                        assignee = sb_prev
                    else:
                        # Fallback al Stand-by del día de hoy
                        row_curr = _get_row(date_val)
                        assignee = _clean_val(row_curr, "Stand-by")
            else:
                # Jornada diurna, vespertina y nocturna del día actual (>= 06:00)
                row_curr = _get_row(date_val)
                if row_curr is None:
                    return None

                t1 = _clean_val(row_curr, "Turno 1")
                t2 = _clean_val(row_curr, "Turno 2")
                t3 = _clean_val(row_curr, "Turno 3")
                t4 = _clean_val(row_curr, "Turno 4")
                sb = _clean_val(row_curr, "Stand-by")

                if t0600 <= time_val < t1400:
                    # Franja mañana (06:00 a 13:59):
                    # En fines de semana y feriados (como hoy con guardia diurna), Turno 4 es quien cubre.
                    # Si Turno 4 está definido y (Turno 1 está vacío o es fin de semana): Turno 4
                    if t4 and (not t1 or weekday in [5, 6]):
                        assignee = t4
                    elif t1:
                        assignee = t1
                    elif t4:
                        assignee = t4
                    else:
                        assignee = sb

                elif t1400 <= time_val < t2200:
                    # Franja tarde (14:00 a 21:59):
                    # En días ordinarios: Turno 2
                    # En fines de semana o feriados sin Turno 2: Stand-by a partir de las 14:00
                    if t2:
                        assignee = t2
                    else:
                        assignee = sb

                else:
                    # Franja noche (>= 22:00):
                    # En días ordinarios: Turno 3
                    # En fines de semana o feriados sin Turno 3: Stand-by
                    if t3:
                        assignee = t3
                    else:
                        assignee = sb

            if assignee:
                return self._canonical_assignee(assignee)
        except Exception as e:
            print(f"Error resolving shift user: {e}")
        return None

    def _load_groups(self):
        if not os.path.exists(self.groups_path):
            print(f"Warning: {self.groups_path} not found.")
            return

        try:
            df_groups = None
            for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                for sep in (',', ';'):
                    try:
                        df_tmp = pd.read_csv(self.groups_path, sep=sep, encoding=enc, dtype=str)
                        if df_tmp is not None and len(df_tmp.columns) > 1:
                            clean_cols = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df_tmp.columns]
                            df_tmp.columns = clean_cols
                            df_groups = df_tmp
                            break
                    except Exception:
                        continue
                if df_groups is not None:
                    break

            if df_groups is None:
                print(f"Warning: could not parse groups configuration from {self.groups_path}")
                return

            def _singularize_phrase(s):
                tokens = s.split()
                tokens = [t[:-1] if t.endswith('s') else t for t in tokens]
                return ' '.join(tokens)

            for col in df_groups.columns:
                macro_group = str(col).strip().upper()
                if not macro_group or macro_group == 'NAN':
                    continue

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
        except Exception as e:
            print(f"Warning: failed to load {self.groups_path}: {e}")

    def _load_users(self):
        if not os.path.exists(self.users_path):
            print(f"Warning: {self.users_path} not found.")
            return

        try:
            df_users = None
            for enc in ('utf-8-sig', 'utf-8', 'latin-1', 'cp1252'):
                for sep in (';', ','):
                    try:
                        df_tmp = pd.read_csv(self.users_path, sep=sep, encoding=enc, dtype=str)
                        if df_tmp is not None and not df_tmp.empty:
                            clean_cols = [re.sub(r'^[\ufeffï»¿"]+|["\s]+$', '', str(c)).strip() for c in df_tmp.columns]
                            if any(c.lower() == 'nombre' for c in clean_cols) and any(c.lower() == 'usuario' for c in clean_cols):
                                df_tmp.columns = clean_cols
                                df_users = df_tmp
                                break
                    except Exception:
                        continue
                if df_users is not None:
                    break

            if df_users is None:
                print(f"Warning: {self.users_path} missing expected columns 'Nombre'/'Usuario'.")
                return

            col_map = {c.lower(): c for c in df_users.columns}
            nombre_col = col_map.get('nombre', 'Nombre')
            usuario_col = col_map.get('usuario', 'Usuario')
            estado_col = next((c for k, c in col_map.items() if k in ('estado', 'activo')), None)

            for _, row in df_users.iterrows():
                username_raw = row.get(usuario_col)
                name_raw = row.get(nombre_col)
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

                status_raw = row.get(estado_col) if estado_col else None
                is_active = str(status_raw).strip() in ('1', 'S', 's', 'TRUE', 'true') if (status_raw is not None and not pd.isna(status_raw)) else True
                if is_active:
                    self.active_usernames.add(username)
            print(f"Successfully loaded {len(self.username_to_realname)} users ({len(self.active_usernames)} active) from {self.users_path}")
        except Exception as e:
            print(f"Warning: failed to load {self.users_path}: {e}")

    def _canonical_assignee(self, name):
        """Resuelve un valor de `assigned_to` (username o nombre real) al username canónico."""
        if not name or pd.isna(name):
            return ""
        name_upper = str(name).strip().upper()
        if name_upper in self.username_to_realname:
            return name_upper

        token_key = ' '.join(sorted(_normalize_text(name_upper).upper().split()))
        if token_key in self.name_tokens_to_username:
            return self.name_tokens_to_username[token_key]

        # Búsqueda difusa por coincidencia de tokens
        words = set(_normalize_text(name_upper).upper().split())
        if len(words) >= 2:
            best_match = None
            max_common = 1
            for tk, uname in self.name_tokens_to_username.items():
                tk_words = set(tk.split())
                common = len(words & tk_words)
                if common > max_common and common >= len(words) - 1:
                    max_common = common
                    best_match = uname
            if best_match:
                return best_match

        return name_upper

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
