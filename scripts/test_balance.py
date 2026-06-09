import os
import sys
sys.path.append(os.path.abspath('.'))
import pandas as pd
from Programas.LoadBalancer import WorkloadBalancer

csv_in = os.path.join('Entrada', 'tickets_clasificados_completo_Logistic_Regression_2026-06-09.csv')
out_dir = os.path.join('scripts')
os.makedirs(out_dir, exist_ok=True)

print('Loading CSV:', csv_in)
# Intentar leer con utf-8-sig para manejar BOM; fallback a latin-1
try:
    df = pd.read_csv(csv_in, encoding='utf-8-sig', engine='python', on_bad_lines='skip')
except Exception:
    try:
        df = pd.read_csv(csv_in, encoding='latin-1', engine='python', on_bad_lines='skip')
    except Exception as e:
        print('Error reading CSV with utf-8-sig and latin-1:', e)
        raise

# Normalizar nombres de columna: quitar BOM/espacios y mapear variantes de "clasificacion"
import unicodedata, re
clean_cols = []
for c in df.columns:
    if isinstance(c, str):
        c2 = c.lstrip('\ufeff').strip()
    else:
        c2 = c
    clean_cols.append(c2)
df.columns = clean_cols

rename_map = {}
for orig in df.columns:
    if not isinstance(orig, str):
        continue
    ascii_norm = unicodedata.normalize('NFKD', orig).encode('ascii', 'ignore').decode('utf-8').lower()
    ascii_norm = re.sub(r'\s+', ' ', ascii_norm).strip()
    if 'clasific' in ascii_norm:  # captura Clasificación, ClasificaciÃ³n, etc.
        rename_map[orig] = 'Clasificación'
    if ascii_norm == 'number' or ascii_norm == 'nro' or ascii_norm == 'id':
        rename_map[orig] = 'number'

if rename_map:
    df.rename(columns=rename_map, inplace=True)

print('Columns found:', list(df.columns))

balancer = WorkloadBalancer()
print('Running balance_assignment...')
df_assigned = balancer.balance_assignment(df, classification_col='Clasificación', assigned_col='assigned_to')

out_file = os.path.join(out_dir, 'test_assignments_Logistic_Regression_2026-06-09.csv')
df_assigned.to_csv(out_file, index=False, encoding='utf-8-sig')
print('Saved:', out_file)

cols_to_show = [c for c in ['number', 'Clasificación', 'assigned_to'] if c in df_assigned.columns]
print('\nFirst 20 assignments:')
print(df_assigned[cols_to_show].head(20).to_string(index=False))

# Summary of special statuses (robusto: evita KeyError si no existen etiquetas)
special_labels = ['SIN_CLASIFICACION', 'SIN_ASIGNAR_SIN_GRUPO', 'SIN ASIGNAR (SIN MIEMBROS)']
vc = df_assigned['assigned_to'].value_counts()
print('\nSpecial assignment counts:')
for lbl in special_labels:
    print(f"{lbl}: {int(vc.get(lbl, 0))}")

print('\nTop 20 assignees:')
print(df_assigned['assigned_to'].value_counts().head(20).to_string())
