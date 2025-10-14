# optim/solver.py — versión con A/B + restricciones y lector tolerante
import argparse
from pathlib import Path

import pandas as pd
import pulp as pl

# -----------------------
# Rutas base (data/)
# -----------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
POTREROS_CSV = DATA_DIR / "potreros.csv"
REQS_CSV = DATA_DIR / "requerimientos.csv"
PRODS_CSV = DATA_DIR / "productos.csv"

# -----------------------
# CLI (para escenarios y salidas personalizadas)
# -----------------------
parser = argparse.ArgumentParser()
parser.add_argument("--nmax", type=float, default=0.0)        # Límite total de N (kg/ha). 0 = sin límite
parser.add_argument("--mixmax", type=float, default=0.0)      # Límite de mezcla total (kg/ha). 0 = sin límite
parser.add_argument("--tol", type=float, default=0.02)        # Tolerancia relativa. 0.02 = 2%
parser.add_argument("--costoap", type=int, default=0)         # CLP por tonelada aplicada (costo de aplicación)
parser.add_argument("--out_csv", type=str, default="")        # Ruta de salida resultados dosis
parser.add_argument("--out_txt", type=str, default="")        # Ruta de salida resumen costo
args = parser.parse_args()

# Salidas (por defecto a data/, pero pueden venir personalizadas por CLI)
OUT_CSV = Path(args.out_csv) if args.out_csv else (DATA_DIR / "resultados_dosis.csv")
OUT_TXT = Path(args.out_txt) if args.out_txt else (DATA_DIR / "_resumen.txt")

# -----------------------
# Lector tolerante de CSV
# -----------------------
def read_csv_flexible(path: Path) -> pd.DataFrame:
    """
    Lee CSV detectando separador (; o ,), limpia BOM (\ufeff) y corrige encabezados comunes.
    """
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]

    # Correcciones típicas de nombres
    ren = {}
    if "P205_req_kg_ha" in df.columns:   # cero vs O
        ren["P205_req_kg_ha"] = "P2O5_req_kg_ha"
    if "Cultivo" in df.columns and "cultivo" not in df.columns:
        ren["Cultivo"] = "cultivo"
    if "Producto" in df.columns and "producto" not in df.columns:
        ren["Producto"] = "producto"
    if ren:
        df = df.rename(columns=ren)
    return df

# -----------------------
# Cargar datos
# -----------------------
potreros = read_csv_flexible(POTREROS_CSV)
reqs = read_csv_flexible(REQS_CSV).set_index("cultivo")
prods = read_csv_flexible(PRODS_CSV).set_index("producto")

# -----------------------
# Parámetros
# -----------------------
N = (prods["N_pct"] / 100.0).to_dict()
P = (prods["P2O5_pct"] / 100.0).to_dict()
K = (prods["K2O_pct"] / 100.0).to_dict()

precio_ton = prods["precio_CLP_ton"].to_dict()     # CLP / tonelada
dmin = prods["dosis_min_kg_ha"].to_dict()          # kg/ha
dmax = prods["dosis_max_kg_ha"].to_dict()          # kg/ha

productos = list(prods.index)
lotes = list(potreros["potrero"])
superficie = potreros.set_index("potrero")["superficie_ha"].to_dict()
cultivo_por_potrero = potreros.set_index("potrero")["cultivo"].to_dict()

# -----------------------
# Modelo
# -----------------------
x = pl.LpVariable.dicts("x", [(i, p) for i in productos for p in lotes], lowBound=0)
prob = pl.LpProblem("OptFertilizacion", pl.LpMinimize)

# Objetivo: costo de producto
costo_productos = pl.lpSum(
    x[(i, p)] * superficie[p] * (precio_ton[i] / 1000.0)
    for i in productos for p in lotes
)

# Costo de aplicación por tonelada aplicada (opcional)
costo_aplicacion = 0
if args.costoap > 0:
    costo_aplicacion = pl.lpSum(
        x[(i, p)] * superficie[p] * (args.costoap / 1000.0)
        for i in productos for p in lotes
    )

prob += costo_productos + costo_aplicacion

# Restricciones por potrero
for p in lotes:
    cult = cultivo_por_potrero[p]

    # Requerimientos con tolerancia (permitir quedar debajo hasta tol)
    Nreq_eff = (1.0 - args.tol) * float(reqs.loc[cult, "N_req_kg_ha"])
    Preq_eff = (1.0 - args.tol) * float(reqs.loc[cult, "P2O5_req_kg_ha"])
    Kreq_eff = (1.0 - args.tol) * float(reqs.loc[cult, "K2O_req_kg_ha"])

    # Cumplimientos (>= requerimiento efectivo)
    prob += pl.lpSum(x[(i, p)] * N[i] for i in productos) >= Nreq_eff
    prob += pl.lpSum(x[(i, p)] * P[i] for i in productos) >= Preq_eff
    prob += pl.lpSum(x[(i, p)] * K[i] for i in productos) >= Kreq_eff

    # Límite de mezcla total por pasada (kg/ha)
    if args.mixmax > 0:
        prob += pl.lpSum(x[(i, p)] for i in productos) <= args.mixmax

    # Tope de N total (kg/ha)
    if args.nmax > 0:
        prob += pl.lpSum(x[(i, p)] * N[i] for i in productos) <= args.nmax

    # Límites de dosis por producto
    for i in productos:
        # Si dmin[i] es 0, deja el bound inferior en 0 (ya está con lowBound=0).
        # Aun así, mantenemos la restricción explícita por si vienen dmin>0.
        prob += x[(i, p)] >= dmin[i]
        prob += x[(i, p)] <= dmax[i]

# -----------------------
# Resolver
# -----------------------
prob.solve(pl.PULP_CBC_CMD(msg=False))

# -----------------------
# Exportar resultados
# -----------------------
rows = []
for i in productos:
    for p in lotes:
        val = x[(i, p)].value()
        if val and val > 1e-6:
            rows.append({"potrero": p, "producto": i, "kg_ha": round(val, 2)})

df = pd.DataFrame(rows).sort_values(["potrero", "producto"])
df.to_csv(OUT_CSV, index=False, encoding="utf-8")

# Costo total (incluye costo de aplicación si corresponde)
costo_total = sum(
    (x[(i, p)].value() or 0) * superficie[p] * (precio_ton[i] / 1000.0)
    for i in productos for p in lotes
)
if args.costoap > 0:
    costo_total += sum(
        (x[(i, p)].value() or 0) * superficie[p] * (args.costoap / 1000.0)
        for i in productos for p in lotes
    )

OUT_TXT.write_text(f"Costo total (CLP): {int(round(costo_total, 0))}\n", encoding="utf-8")

print("OK ->", OUT_CSV.name, "|", OUT_TXT.name)
