import unicodedata
import pandas as pd
from pathlib import Path

# Cargar directamente desde el CSV final
output_dir = Path.cwd()
if not (output_dir / "Data").exists():
    output_dir = output_dir.parent
ruta_entrada = output_dir / "Data" / "tickets_completos_clasificados_FINAL.csv"

try:
    df_final = pd.read_csv(ruta_entrada, encoding='utf-8-sig')
except UnicodeDecodeError:
    df_final = pd.read_csv(ruta_entrada, encoding='latin-1')

print(f"CSV cargado: {ruta_entrada.resolve()}")
print(f"Total tickets: {len(df_final)}")
print(f"\nDistribución inicial:")
print(df_final["clasificacion"].value_counts().to_string())

def normalizar(s):
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s))
        if unicodedata.category(c) != 'Mn'
    ).lower()

texto = (
    df_final["short_description"].fillna("") + " " +
    df_final["description"].fillna("")
).apply(normalizar)

# Reglas en orden de prioridad (la última gana si hay conflicto)
# 1 mayor prioridad = soporte_transacciones_test  (última)
# 2                 = iniciativas
# 3                 = estados_cuenta
reglas = {
    "glif_journal_contabilidad_test":   r'\bglif{1,2}s?\b',
    "operaciones_credito_amortizacion": r'tabla[s]?\s+(de\s+)?amortizacion',
    "revision":                         r'soporte\s+bancs\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{4}',
    "sobregiros":                       r'sobregiro[s]?',
    "estados_cuenta":                   r'estados?\s+de\s+cuenta',
    "iniciativas":                      r'(caso|causa|solucion)\s+raiz|\bmejora[s]?\b',
    "soporte_transacciones_test":       r'bancs\s+tests?',
}

# Calcular qué reglas aplican a cada ticket
df_matches = pd.concat([
    texto.str.contains(pat, regex=True, na=False).rename(cat)
    for cat, pat in reglas.items()
], axis=1)

# Aplicar reglas en orden (la última sobreescribe)
n_cambios = {}
for cat, pat in reglas.items():
    mask = df_matches[cat]
    df_final.loc[mask, "clasificacion"] = cat
    n_cambios[cat] = int(mask.sum())

# Detectar tickets con más de una regla
df_final["_n_reglas"]            = df_matches.sum(axis=1)
df_final["_reglas_competidoras"] = df_matches.apply(
    lambda r: " | ".join(c for c in df_matches.columns if r[c]), axis=1
)

mask_multi = df_final["_n_reglas"] > 1

# Resumen de cambios
print("\nTickets reclasificados por regla:")
for cat, n in n_cambios.items():
    print(f"  {cat:<45}: {n} tickets")

print(f"\nTickets con más de una regla aplicable: {mask_multi.sum()}")
for _, row in df_final[mask_multi][["number", "description", "clasificacion", "_reglas_competidoras"]].iterrows():
    print(f"\n  [{row['number']}]")
    print(f"  Clasificacion final : {row['clasificacion']}")
    print(f"  Reglas competidoras : {row['_reglas_competidoras']}")
    print(f"  Descripcion         : {str(row['description'])[:300]}")

# Eliminar columnas auxiliares y exportar
df_final = df_final.drop(columns=["_n_reglas", "_reglas_competidoras"])

ruta_salida = output_dir / "Data" / "tickets_completos_clasificados_BASE_SUPERVISADO.csv"
df_final.to_csv(ruta_salida, index=False, encoding="utf-8-sig")

print(f"\nExportado: {ruta_salida.resolve()}")
print(f"Total: {len(df_final)} tickets")
print(f"\nDistribución final:")
print(df_final["clasificacion"].value_counts().to_string())
