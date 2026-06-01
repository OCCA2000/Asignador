"""
Prueba rápida del WorkloadBalancer sin necesidad de archivos externos.
Ejecutar desde la raíz del proyecto: python test_load_balancer.py
"""
import os
import sys
import pandas as pd

# ── Crear carpeta y archivos temporales de entrada ───────────────────────────
os.makedirs("Entrada", exist_ok=True)

# Grupos.csv de prueba con agentes del CSV real
grupos_data = """NOMBRE;GRUPO 1;GRUPO 2;GRUPO 3;ACTIVO
JOSEPH ANGELO HERRERA GUERRA;TEC_TCS_N1_RYR_APLICACIONES;;;S
LEONELA JACKELINE DELGADO MENDIETA;TEC_TCS_N1_RYR_APLICACIONES;;;S
LUISA VERONICA MORENO LEMA;TEC_TCS_N1_RYR_APLICACIONES;;;S
LUIS SEBASTIAN CATOTA CAIZALUISA;TEC_TCS_N1_RYR_APLICACIONES;;;S
"""
with open("Entrada/Grupos.csv", "w", encoding="latin-1") as f:
    f.write(grupos_data)

# Historial con carga preexistente: Joseph tiene 5 tickets abiertos, Leonela 2
assigned_data = """number,state,assigned_to
INC001,En proceso,JOSEPH ANGELO HERRERA GUERRA
INC002,En proceso,JOSEPH ANGELO HERRERA GUERRA
INC003,En proceso,JOSEPH ANGELO HERRERA GUERRA
INC004,En proceso,JOSEPH ANGELO HERRERA GUERRA
INC005,En proceso,JOSEPH ANGELO HERRERA GUERRA
INC006,En proceso,LEONELA JACKELINE DELGADO MENDIETA
INC007,En proceso,LEONELA JACKELINE DELGADO MENDIETA
INC008,Resuelto,JOSEPH ANGELO HERRERA GUERRA
INC009,Resuelto,JOSEPH ANGELO HERRERA GUERRA
INC010,Resuelto,JOSEPH ANGELO HERRERA GUERRA
"""
with open("Entrada/assigned_incidents.csv", "w", encoding="utf-8") as f:
    f.write(assigned_data)

with open("Entrada/assigned_requirements.csv", "w", encoding="utf-8") as f:
    f.write("number,state,assigned_to\n")

# ── Cargar balanceador ────────────────────────────────────────────────────────
from Programas.LoadBalancer import WorkloadBalancer

balancer = WorkloadBalancer()

# ── Mostrar carga inicial ─────────────────────────────────────────────────────
print("\n=== CARGA INICIAL ===")
print(f"{'Agente':<45} {'Abiertos':>8} {'Resueltos':>10} {'Efectiva':>9}")
print("-" * 75)
for nombre in sorted(balancer.workload.keys()):
    abiertos  = balancer.workload.get(nombre, 0)
    resueltos = balancer.resolved_workload.get(nombre, 0)
    efectiva  = balancer._effective_workload(nombre)
    print(f"{nombre:<45} {abiertos:>8} {resueltos:>10} {efectiva:>9.1f}")

# ── Simular 8 tickets nuevos a balancear ─────────────────────────────────────
# El modelo predice siempre a Joseph (el más común en histórico)
# El balanceador debe redirigir a quien tenga menor carga efectiva
df_nuevos = pd.DataFrame({
    "number": [f"INC_NEW_{i}" for i in range(1, 9)],
    "short_description": ["Ticket de prueba"] * 8,
    "predicted_assigned_to": ["JOSEPH ANGELO HERRERA GUERRA"] * 8,
    "predicted_assignment_group": [""] * 8,
})

print("\n=== ANTES DEL BALANCEO ===")
print(df_nuevos[["number", "predicted_assigned_to"]].to_string(index=False))

df_resultado = balancer.balance_assignment(df_nuevos.copy())

print("\n=== DESPUÉS DEL BALANCEO ===")
print(df_resultado[["number", "predicted_assigned_to", "predicted_assignment_group"]].to_string(index=False))

print("\n=== CARGA FINAL TRAS ASIGNACIONES ===")
print(f"{'Agente':<45} {'Abiertos':>8} {'Efectiva':>9}")
print("-" * 65)
for nombre in sorted(balancer.workload.keys()):
    abiertos = balancer.workload.get(nombre, 0)
    efectiva = balancer._effective_workload(nombre)
    print(f"{nombre:<45} {abiertos:>8} {efectiva:>9.1f}")
