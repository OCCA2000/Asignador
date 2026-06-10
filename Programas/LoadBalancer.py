import pandas as pd
import os
import re
import unicodedata
from datetime import datetime, timedelta
from Programas.CleaningData import limpiar_archivo_csv
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
    def __init__(self, grupos_path="Entrada/Grupos - Incidentes(Grupos).csv", usuarios_path="Entrada/Grupos - Incidentes(Usuarios).csv", assigned_incidents="Entrada/assigned_incidents.csv", assigned_requirements="Entrada/assigned_requirements.csv", resolved_weight=0.5, resolved_days_window=7):
        self.grupos_path = grupos_path
        self.usuarios_path = usuarios_path
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
        self.username_to_realname = {}
        self.name_tokens_to_username = {}
        self.active_usernames = set()

        self._load_grupos()
        self._load_usuarios()
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

    def _load_usuarios(self):
        if not os.path.exists(self.usuarios_path):
            print(f"Warning: {self.usuarios_path} not found.")
            return

        try:
            try:
                # Intentar leer por coma primero
                df_usuarios = pd.read_csv(self.usuarios_path, sep=',', encoding='latin-1', dtype=str)
                if len(df_usuarios.columns) == 1:
                    # Fallback a punto y coma
                    df_usuarios = pd.read_csv(self.usuarios_path, sep=';', encoding='latin-1', dtype=str)
            except Exception:
                df_usuarios = pd.read_csv(self.usuarios_path, sep=';', encoding='latin-1', dtype=str)

            df_usuarios.columns = [str(c).strip() for c in df_usuarios.columns]

            if 'Nombre' not in df_usuarios.columns or 'Usuario' not in df_usuarios.columns:
                print(f"Warning: {self.usuarios_path} missing expected columns 'Nombre'/'Usuario'.")
                return

            for _, row in df_usuarios.iterrows():
                usuario_raw = row.get('Usuario')
                nombre_raw = row.get('Nombre')
                if pd.isna(usuario_raw) or pd.isna(nombre_raw):
                    continue

                username = str(usuario_raw).strip().upper()
                nombre = str(nombre_raw).strip().upper()
                if not username or not nombre:
                    continue

                self.username_to_realname[username] = nombre

                token_key = ' '.join(sorted(_normalize_text(nombre).upper().split()))
                if token_key:
                    self.name_tokens_to_username[token_key] = username

                estado_raw = row.get('Estado')
                is_active = str(estado_raw).strip() == '1' if not pd.isna(estado_raw) else True
                if is_active:
                    self.active_usernames.add(username)
        except Exception as e:
            print(f"Warning: failed to load {self.usuarios_path}: {e}")

    def _canonical_assignee(self, name):
        """Resuelve un valor de `assigned_to` (username o nombre real) al username canónico.

        Permite combinar la carga de tickets registrados con el username (ej. LJDELGAD)
        con la carga de tickets antiguos registrados con el nombre completo
        (ej. LEONELA JACKELINE DELGADO MENDIETA), evitando que se traten como dos
        personas distintas en self.workload / self.resolved_workload.
        """
        name_upper = str(name).strip().upper()
        if name_upper in self.username_to_realname:
            return name_upper

        token_key = ' '.join(sorted(_normalize_text(name_upper).upper().split()))
        return self.name_tokens_to_username.get(token_key, name_upper)

    def is_active(self, name):
        """Devuelve True si el usuario está activo (Estado=1) en el CSV de usuarios.

        Acepta tanto username (ej. LJDELGAD) como nombre completo (ej. LEONELA JACKELINE DELGADO).
        Si no hay información de estado cargada, asume activo.
        """
        if not self.active_usernames:
            return True
        name_upper = str(name).strip().upper()
        if name_upper in self.active_usernames:
            return True
        token_key = ' '.join(sorted(_normalize_text(name_upper).upper().split()))
        username = self.name_tokens_to_username.get(token_key)
        return username in self.active_usernames if username else False

    def display_name(self, key):
        if key in self.username_to_realname:
            return f"{self.username_to_realname[key]} ({key})"
        return key

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
