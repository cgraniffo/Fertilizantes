# optim/solver.py — versión con A/B, lector tolerante, pre-chequeo y diagnósticos
import argparse
import sys
from pathlib import Path

import pandas as pd
import pulp as pl

# -----------------------
# Rutas base (data/)
# -----------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
POTREROS_CSV = DATA_DIR / "potreros.csv"
REQS_CSV     = DATA_DIR / "requerimientos.csv"
PRODS_CSV    = DATA_DIR / "productos.csv"

# -----------------------
# CLI
# -----------------------
parser = argparse.ArgumentParser()
parser.add_argument("--nmax",    type=float, default=0.0)   # Tope de N total (kg/ha) — 0 = sin límite
parser.add_argument("--mixmax",  type=float, default=0.0)   # Tope mezcla total (kg/ha) — 0 = sin límite
parser.add_argument("--tol",     type=float, default=0.02)  # Tolerancia relativa (0.02 = 2%)
parser.add_argument("--costoap", type=float, default=0.0)   # CLP por tonelada aplicada
parser.add_argument("--out_csv", type=str,   default="")    # (compat) ignorado si usamos --tag
parser.add_argument("--out_txt", type=str,   default="")    # (compat) ignorado si usamos --tag
parser.add_argument("--tag",     type=str,   default="")    # 'A', 'B' o vacío
args = parser.parse_args()

# Rutas de salida según tag (A/B)
tag_suffix = f"_{args.tag}" if args.tag else ""
CSV_OUT = DATA_DIR / f"resultados_dosis{tag_suffix}.csv"
TXT_OUT = DATA_DIR / f"_resumen{tag_suffix}.txt"

# -----------------------
# Lector tolerante de CSV
# -----------------------
def read_csv_flexible(path: Path) -> pd.DataFrame:
    """Lee CSV detectando separador (; o ,), limpia BOM y corrige encabezados comunes."""
    df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    df.columns = [c.strip().lstrip("\ufeff") for c in df.columns]

    # Correcciones frecuentes
    ren = {}
    if "P205_req_kg_ha" in df.columns:              # 0 vs O
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
reqs     = read_csv_flexible(REQS_CSV).set_index("cultivo")
prods    = read_csv_flexible(PRODS_CSV).set_index("producto")

# Validaciones mínimas
for col in ["potrero", "cultivo", "superficie_ha"]:
    if col not in potreros.columns:
        print(f"ERROR: faltan columnas en potreros.csv (requiere potrero, cultivo, superficie_ha). Falta: {col}")
        sys.exit(2)

for col in ["N_req_kg_ha", "P2O5_req_kg_ha", "K2O_req_kg_ha"]:
    if col not in reqs.columns:
        print(f"ERROR: faltan columnas en requerimientos.csv (requiere {col})")
        sys.exit(2)

for col in ["N_pct", "P2O5_pct", "K2O_pct", "precio_CLP_ton", "dosis_min_kg_ha", "dosis_max_kg_ha"]:
    if col not in prods.columns:
        print(f"ERROR: faltan columnas en productos.csv (requiere {col})")
        sys.exit(2)

# Sanitizar tipos/NaN
prods = prods.copy()
prods["dosis_min_kg_ha"] = pd.to_numeric(prods["dosis_min_kg_ha"], errors="coerce").fillna(0.0)
prods["dosis_max_kg_ha"] = pd.to_numeric(prods["dosis_max_kg_ha"], errors="coerce").fillna(1e6)
prods["precio_CLP_ton"]  = pd.to_numeric(prods["precio_CLP_ton"],  errors="coerce").fillna(0.0)
for pct in ["N_pct", "P2O5_pct", "K2O_pct"]:
    prods[pct] = pd.to_numeric(prods[pct], errors="coerce").fillna(0.0)

# Diccionarios y listas útiles
N = (prods["N_pct"]    / 100.0).to_dict()
P = (prods["P2O5_pct"] / 100.0).to_dict()
K = (prods["K2O_pct"]  / 100.0).to_dict()

precio_ton = prods["precio_CLP_ton"].to_dict()
dmin       = prods["dosis_min_kg_ha"].to_dict()
dmax       = prods["dosis_max_kg_ha"].to_dict()

productos            = list(prods.index)
lotes                = list(potreros["potrero"])
superficie           = potreros.set_index("potrero")["superficie_ha"].to_dict()
cultivo_por_potrero  = potreros.set_index("potrero")["cultivo"].to_dict()

# -----------------------
# Pre-chequeo de factibilidad (diagnóstico rápido)
# -----------------------
def precheck_factibilidad(potreros, prods, reqs, args, cultivo_por_potrero):
    msgs = []
    Nv = (prods["N_pct"]    / 100.0)
    Pv = (prods["P2O5_pct"] / 100.0)
    Kv = (prods["K2O_pct"]  / 100.0)
    dmin = prods["dosis_min_kg_ha"]
    dmax = prods["dosis_max_kg_ha"]

    min_mix_total = dmin.sum()       # mezcla mínima si todos van a dmin
    for _, row in potreros.iterrows():
        p    = row["potrero"]
        cult = cultivo_por_potrero[p]

        Nreq = (1.0 - args.tol) * float(reqs.loc[cult, "N_req_kg_ha"])
        Preq = (1.0 - args.tol) * float(reqs.loc[cult, "P2O5_req_kg_ha"])
        Kreq = (1.0 - args.tol) * float(reqs.loc[cult, "K2O_req_kg_ha"])

        mix_cap = args.mixmax if (args.mixmax and args.mixmax > 0) else float("inf")

        # dmin vs mixmax
        if args.mixmax and args.mixmax > 0 and min_mix_total - 1e-9 > args.mixmax:
            msgs.append(f"Potrero {p}: la suma de dosis mínimas ({min_mix_total:.1f}) supera la mezcla máx ({args.mixmax:.1f}).")

        # cota grosera con dmax y mixmax
        maxN_dmax = (dmax * Nv).sum()
        maxP_dmax = (dmax * Pv).sum()
        maxK_dmax = (dmax * Kv).sum()

        if mix_cap < float("inf"):
            maxN = min(maxN_dmax, mix_cap * (Nv.max() if len(Nv) else 0.0))
            maxP = min(maxP_dmax, mix_cap * (Pv.max() if len(Pv) else 0.0))
            maxK = min(maxK_dmax, mix_cap * (Kv.max() if len(Kv) else 0.0))
        else:
            maxN, maxP, maxK = maxN_dmax, maxP_dmax, maxK_dmax

        if args.nmax and args.nmax > 0:
            maxN = min(maxN, args.nmax)

        if Nreq - 1e-6 > maxN:
            msgs.append(f"Potrero {p}: N requerido {Nreq:.1f} > N máximo alcanzable {maxN:.1f} (nmax/mixmax/dmax).")
        if Preq - 1e-6 > maxP:
            msgs.append(f"Potrero {p}: P2O5 requerido {Preq:.1f} > P máximo alcanzable {maxP:.1f} (mixmax/dmax).")
        if Kreq - 1e-6 > maxK:
            msgs.append(f"Potrero {p}: K2O requerido {Kreq:.1f} > K máximo alcanzable {maxK:.1f} (mixmax/dmax).")

    return msgs

# Ejecutar pre-chequeo (ahora que YA tenemos args, CSVs y diccionarios)
msgs = precheck_factibilidad(potreros, prods, reqs, args, cultivo_por_potrero)
if msgs:
    for m in msgs:
        print("DIAGNOSTICO:", m)
    print("ERROR: modelo Infeasible por los diagnósticos anteriores.")
    sys.exit(2)

# -----------------------
# Modelo de optimización
# -----------------------
x = pl.LpVariable.dicts("x", [(i, p) for i in productos for p in lotes], lowBound=0)
prob = pl.LpProblem("OptFertilizacion", pl.LpMinimize)

# Objetivo: costo de producto + (opcional) costo de aplicación
costo_productos = pl.lpSum(
    x[(i, p)] * superficie[p] * (precio_ton[i] / 1000.0)
    for i in productos for p in lotes
)
costo_aplicacion = 0
if args.costoap and args.costoap > 0:
    costo_aplicacion = pl.lpSum(
        x[(i, p)] * superficie[p] * (args.costoap / 1000.0)
        for i in productos for p in lotes
    )
prob += costo_productos + costo_aplicacion

# Restricciones por potrero
for p in lotes:
    cult = cultivo_por_potrero[p]
    if cult not in reqs.index:
        print(f"ERROR: cultivo '{cult}' del potrero '{p}' no está en requerimientos.csv")
        sys.exit(2)

    # Requerimientos con tolerancia
    Nreq = (1.0 - args.tol) * float(reqs.loc[cult, "N_req_kg_ha"])
    Preq = (1.0 - args.tol) * float(reqs.loc[cult, "P2O5_req_kg_ha"])
    Kreq = (1.0 - args.tol) * float(reqs.loc[cult, "K2O_req_kg_ha"])

    prob += pl.lpSum(x[(i, p)] * N[i] for i in productos) >= Nreq
    prob += pl.lpSum(x[(i, p)] * P[i] for i in productos) >= Preq
    prob += pl.lpSum(x[(i, p)] * K[i] for i in productos) >= Kreq

    if args.mixmax and args.mixmax > 0:
        prob += pl.lpSum(x[(i, p)] for i in productos) <= args.mixmax

    if args.nmax and args.nmax > 0:
        prob += pl.lpSum(x[(i, p)] * N[i] for i in productos) <= args.nmax

    for i in productos:
        prob += x[(i, p)] >= float(dmin[i])
        prob += x[(i, p)] <= float(dmax[i])

# -----------------------
# Resolver
# -----------------------
prob.solve(pl.PULP_CBC_CMD(msg=False))
status = pl.LpStatus[prob.status]
if status != "Optimal":
    print(f"ERROR: modelo {status}. Revisa límites, tolerancia y datos.")
    sys.exit(2)

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
df.to_csv(CSV_OUT, index=False, encoding="utf-8")

costo_total = 0.0
for i in productos:
    for p in lotes:
        v = (x[(i, p)].value() or 0.0)
        if v:
            costo_total += v * superficie[p] * (precio_ton[i] / 1000.0)
            if args.costoap and args.costoap > 0:
                costo_total += v * superficie[p] * (args.costoap / 1000.0)

TXT_OUT.write_text(f"Costo total (CLP): {int(round(costo_total, 0))}\n", encoding="utf-8")

print("OK ->", CSV_OUT.name, "|", TXT_OUT.name)
sys.exit(0)
