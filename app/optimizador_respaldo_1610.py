# app/optimizador.py
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional
import base64
import pandas as pd
import streamlit as st
import subprocess

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage

# =============================
# Utilidades para CSV locales
# =============================
def read_csv_flexible(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
    except Exception as e:
        st.error(f"Error leyendo {path.name}: {e}")
        raise

def exists_local_inputs() -> dict:
    files = {
        "potreros": DATA_DIR / "potreros.csv",
        "requerimientos": DATA_DIR / "requerimientos.csv",
        "productos": DATA_DIR / "productos.csv",
    }
    return {k: p for k, p in files.items() if p.exists()}

# =============================
# Rutas base
# =============================
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "app" / "assets"
DATA_DIR = BASE_DIR / "data"
SOLVER_PATH = BASE_DIR / "optim" / "solver.py"

# =============================
# Página
# =============================
st.set_page_config(
    page_title="Optimizador de Fertilización | Boost Data",
    page_icon=str(ASSETS_DIR / "favicon.png"),
    layout="wide",
)

# Estado persistente
if "last_run" not in st.session_state:
    st.session_state["last_run"] = {
        "okA": False, "okB": False,
        "csvA": None, "txtA": None,
        "csvB": None, "txtB": None,
        "costoA": None, "costoB": None,
        "mixA": None, "mixB": None,
        "nA": None, "nB": None,
        "tolA": None, "tolB": None,
    }
if "already_rendered" not in st.session_state:
    # evita duplicados entre el render inmediato post-ejecución y el render persistente
    st.session_state["already_rendered"] = False

# --- Sentinelas para evitar NameError en reruns
okA = okB = False
csvA = txtA = csvB = txtB = None
costoA = costoB = None

# =============================
# CSS
# =============================
CUSTOM_CSS = """
<style>
html, body, [class*="css"] {
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol" !important;
}
.bdata-header { display:flex; align-items:center; gap:16px; margin-bottom: 4px; }
.bdata-claim { font-size: 14px; color:#5f6c72; margin-top:2px; }
.block-container { padding-top: 1.2rem; }
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
div[data-testid="stMetricValue"] { font-weight: 800; }
.stButton>button { border-radius: 10px; padding: 0.55rem 0.9rem; font-weight: 600; }
h3, h4 { scroll-margin-top: 72px; }
.bdata-divider { height:1px; background:linear-gradient(to right, #e9eef1 0%, #e9eef1 60%, transparent 100%); margin: 6px 0 14px 0; }
.bdata-footer { margin-top: 24px; padding: 12px 0 40px 0; color:#6b7b83; font-size: 12px; border-top: 1px solid #eef2f4; }
.bdata-badge { display:inline-flex; align-items:center; gap:6px; background:#eef7f0; color:#2f7a3e; border-radius: 16px; padding:4px 10px; font-size:12px; font-weight:600; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# =============================
# Modal Manual (flotante)
# =============================
from textwrap import dedent
MANUAL_HTML = dedent("""\
<style>
.bdata-help-btn{position:fixed;bottom:24px;right:24px;background:#157347;color:#fff;border-radius:40px;padding:10px 18px;font-weight:600;cursor:pointer;box-shadow:0 3px 8px rgba(0,0,0,.25);z-index:9999;transition:background .2s}
.bdata-help-btn:hover{background:#0b5e2b}
.bdata-modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.6);display:none;align-items:center;justify-content:center;z-index:10000}
.bdata-modal-content{background:#fff;border-radius:16px;max-width:760px;width:92%;max-height:84%;overflow-y:auto;padding:24px 20px;box-shadow:0 4px 20px rgba(0,0,0,.3);position:relative}
.bdata-close{position:absolute;top:8px;right:12px;font-size:22px;font-weight:700;color:#444;cursor:pointer}
#manualToggle:checked ~ .bdata-modal{display:flex}
.bdata-chip{display:inline-block;background:#eef7f0;color:#196c39;padding:2px 8px;border-radius:12px;font-weight:700;font-size:12px;margin-left:6px}
.bdata-note{font-size:12px;color:#666}
.bdata-list-tight li{margin:2px 0}
details{background:#fafafa;border:1px solid #eee;border-radius:10px;padding:10px 12px;margin:8px 0}
details>summary{cursor:pointer;font-weight:700}
table{border-collapse:collapse;width:100%}
th,td{border:1px solid #e6e6e6;padding:6px 8px;font-size:13px}
th{background:#f4fbf6;color:#0b5e2b;text-align:left}
</style>

<input type="checkbox" id="manualToggle" hidden>
<label for="manualToggle" class="bdata-help-btn">📖 Ver manual</label>

<div class="bdata-modal">
<label for="manualToggle" style="position:absolute;inset:0;"></label>
<div class="bdata-modal-content" onclick="event.stopPropagation()">
<label for="manualToggle" class="bdata-close" title="Cerrar">&times;</label>

<h3>📘 Manual rápido para el agricultor <span class="bdata-chip">Resumen</span></h3>

<p><b>¿Qué hace?</b> Calcula la mezcla óptima de fertilizantes por potrero para cumplir N–P–K al menor costo.</p>

<h4>🪴 Pasos</h4>
<ol class="bdata-list-tight">
  <li><b>Dibuja</b> tus potreros en <b>🗺️ Mapa de potreros</b> y pulsa <b>“Calcular áreas y crear potreros.csv”</b>.</li>
  <li><b>Carga</b> <i>productos.csv</i> y <i>requerimientos.csv</i>.</li>
  <li><b>Ajusta</b> <i>N máx</i>, <i>Mezcla máx</i> y <i>Tolerancia</i> para A y B.</li>
  <li><b>Ejecuta 🚜</b> y compara costos, tablas y gráficos.</li>
</ol>

<details><summary>📂 Archivos que usa (formato breve)</summary>
  <table>
    <tr><th>Archivo</th><th>Columnas obligatorias</th><th>Ejemplo</th></tr>
    <tr><td><b>potreros.csv</b></td><td><code>potrero, cultivo, superficie_ha</code></td><td>Potrero_1, Trigo, 12.5</td></tr>
    <tr><td><b>productos.csv</b></td><td><code>producto, N_pct, P2O5_pct, K2O_pct, precio_CLP_ton, dosis_min_kg_ha, dosis_max_kg_ha</code></td><td>Urea, 46, 0, 0, 450000, 0, 300</td></tr>
    <tr><td><b>requerimientos.csv</b></td><td><code>cultivo, N_req_kg_ha, P2O5_req_kg_ha, K2O_req_kg_ha</code></td><td>Trigo, 160, 70, 0</td></tr>
  </table>
  <p class="bdata-note">El <b>potreros.csv</b> se genera solo desde el mapa; no necesitas subirlo.</p>
</details>

<details><summary>⚙️ Parámetros (qué significan)</summary>
  <ul class="bdata-list-tight">
    <li><b>N máx (kg/ha):</b> tope de N total por hectárea.</li>
    <li><b>Mezcla máx (kg/ha):</b> límite de kilos aplicables por pasada (capacidad de equipo).</li>
    <li><b>Tolerancia (%):</b> margen para aceptar leve subcumplimiento (2% ⇒ se pide 98%).</li>
  </ul>
</details>

<details><summary>🧠 Glosario express</summary>
  <ul class="bdata-list-tight">
    <li><b>Infactible/Infeasible:</b> no existe combinación que cumpla nutrientes y límites.</li>
    <li><b>Dosis mín/máx:</b> rango permitido por producto (kg/ha).</li>
    <li><b>Requerimiento efectivo:</b> requerimiento × (1 − tolerancia).</li>
  </ul>
</details>
<p class="bdata-note">Desarrollado por <b>BData 🌾</b>.</p>
</div>
</div>
""")
st.markdown(MANUAL_HTML, unsafe_allow_html=True)

# =============================
# Header
# =============================
c1, c2 = st.columns([1, 6], gap="small")
with c1:
    try:
        st.image(str(ASSETS_DIR / "logo_bdata.png"), use_container_width=True)
    except Exception:
        st.write("")
with c2:
    st.title("Optimizador de Fertilización")
    st.markdown('<div class="bdata-claim">Planifica mezclas óptimas por potrero, cumpliendo N–P–K al menor costo.</div>', unsafe_allow_html=True)
st.markdown('<div class="bdata-divider"></div>', unsafe_allow_html=True)

# =============================
# Manual largo (en página)
# =============================
with st.expander("📘 Manual rápido para el agricultor", expanded=False):
    st.markdown(dedent("""
    ### 🧭 ¿Qué hace esta herramienta?
    Planifica **mezclas óptimas de fertilizantes por potrero** cumpliendo **N, P₂O₅ y K₂O** al **menor costo**.  
    Optimiza dosis por producto y respeta límites de mezcla y N máx.

    ---

    ### 🪴 Flujo de trabajo
    1. **Mapa** → Dibuja potreros y presiona **“Calcular áreas y crear potreros.csv”**.  
    2. **Carga CSV** → Sube **productos.csv** y **requerimientos.csv**.  
    3. **Parámetros A/B** → Ajusta **N máx**, **Mezcla máx** y **Tolerancia**.  
    4. **Ejecutar 🚜** → Compara costos, tablas y gráficos. Exporta CSV/Markdown/PDF.

    ---

    ### 📂 Archivos y formatos (a prueba de errores)

    **potreros.csv**  *(se genera automáticamente desde el mapa)*  
    Columnas obligatorias:
    - `potrero` (texto) – nombre/ID del potrero  
    - `cultivo` (texto) – debe existir en `requerimientos.csv`  
    - `superficie_ha` (número) – hectáreas del polígono

    **Ejemplo**
    ```
    potrero,cultivo,superficie_ha
    Potrero_1,Trigo,12.53
    Potrero_2,Maiz,8.10
    ```

    **productos.csv**  
    Columnas obligatorias:
    - `producto` (texto)
    - `N_pct`, `P2O5_pct`, `K2O_pct` (0–100, % de nutriente)
    - `precio_CLP_ton` (CLP/ton)
    - `dosis_min_kg_ha`, `dosis_max_kg_ha` (kg/ha)

    **Ejemplo**
    ```
    producto,N_pct,P2O5_pct,K2O_pct,precio_CLP_ton,dosis_min_kg_ha,dosis_max_kg_ha
    Urea,46,0,0,450000,0,300
    MAP,11,52,0,620000,0,250
    KCl,0,0,60,380000,0,250
    ```

    **requerimientos.csv**  
    Columnas obligatorias:
    - `cultivo`
    - `N_req_kg_ha`, `P2O5_req_kg_ha`, `K2O_req_kg_ha` (kg/ha)

    **Ejemplo**
    ```
    cultivo,N_req_kg_ha,P2O5_req_kg_ha,K2O_req_kg_ha
    Trigo,160,70,0
    Maiz,180,60,80
    ```

    > La app corrige encabezados comunes (p. ej. `P205_req_kg_ha` → `P2O5_req_kg_ha`) y admite `;` o `,` como separador.

    ---

    ### ⚙️ Parámetros (cómo elegirlos)
    - **N máx (kg/ha):** tope de N por hectárea. Si está muy bajo, no se cumple y sube el costo.  
    - **Mezcla máx (kg/ha):** kilos/ha aplicables por pasada (limitación del equipo).  
    - **Tolerancia (%):** permite quedar bajo el requerimiento por un pequeño margen (2% → se pide 98%).  
    - **Costo de aplicación (CLP/ton, opcional):** se suma al objetivo si lo activas.

    **Sugerencias iniciales**
    - Tolerancia: 1–3%  
    - Mezcla máx: 400–700 kg/ha (según maquinaria)  
    - N máx: acorde a la recomendación técnica del cultivo/zona

    ---

    ### 🧠 Glosario
    - **Infactible / Infeasible:** no hay combinación que cumpla todo. Causas típicas: mezcla máx muy baja, N máx muy bajo, dosis mín altas, o falta de algún nutriente en `productos.csv`.  
    - **Requerimiento efectivo:** requerimiento × (1 − tolerancia).  
    - **Dosis mín/máx:** bandas por producto. La suma de mínimos es una cota mínima de mezcla total.  
    - **Costo total:** ∑(kg/ha × superficie × precio/ton / 1000) + costo de aplicación si corresponde.

    ---

    ### 🧯 Diagnóstico cuando falla
    1. **Aumenta Tolerancia:** de 1% → 2–3%.  
    2. **Sube Mezcla máx:** revisa que **∑ dmin** de los productos no exceda la mezcla.  
    3. **Relaja N máx:** si el cultivo exige alto N.  
    4. **Revisa productos:** que existan fuentes de los 3 nutrientes que necesitas.  
    5. **Chequea cultivos:** cada `cultivo` en `potreros.csv` debe estar en `requerimientos.csv`.

    > El solver hace un **pre-chequeo** y puede avisar: “Potrero X: P2O5 requerido 80 > P máximo alcanzable 62 (mixmax/dmax).”

    ---

    ### 💡 Buenas prácticas
    - Deja `dosis_min_kg_ha` en 0 salvo que quieras forzar uso.  
    - Evita `dosis_max_kg_ha` muy bajas si tu **mezcla máx** ya está apretada.  
    - Trabaja A/B: A = práctica estándar, B = hipótesis (más mezcla, otra tolerancia, etc.).  
    - Mira “Diferencia (B−A)” por potrero y por producto: verás dónde el modelo ajusta la mezcla.

    ---

    ### ❓FAQs rápidas
    - **¿Tengo que subir `potreros.csv`?** No, se genera desde el mapa.  
    - **¿Puedo cargar mis polígonos?** Sí, en “Cargar GeoJSON”.  
    - **¿Qué pasa si cambio el mapa?** Pulsa “Calcular áreas…” de nuevo.  
    - **¿Por qué B es más caro?** Más restricciones (menos mezcla / menos N / menor tolerancia).  
    - **¿Por qué B es más barato?** Más holgura → combinación más eficiente.

    ---

    ### 🧾 Salidas y reportes
    - **CSV** con dosis A/B por potrero y producto.  
    - **Markdown/PDF** “en chileno” con costos, diferencias y lectura simple.

    Desarrollado por **BData 🌾** — Optimizando la fertilización con ciencia de datos.
    """))


# =============================
# Helpers
# =============================
def toast_ok(msg: str):
    try:
        st.toast(msg, icon="✅")
    except Exception:
        st.success(msg)

def toast_warn(msg: str):
    try:
        st.toast(msg, icon="⚠️")
    except Exception:
        st.warning(msg)

def formato_clp(n: int) -> str:
    try:
        return f"${n:,.0f}".replace(",", ".")
    except Exception:
        return str(n)

def costo_total_desde_txt(path: Path) -> int:
    if not path or not path.exists():
        return 0
    raw = path.read_text(encoding="utf-8")
    dig = "".join(ch for ch in raw if ch.isdigit())
    return int(dig) if dig else 0

def df_to_md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = [str(x) for x in row.tolist()]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)

# =============================
# PDF helpers
# =============================
def _tabla_pdf(df: pd.DataFrame, col_widths=None):
    data = [list(df.columns)] + df.values.tolist()
    tbl = Table(data, colWidths=col_widths)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5f2e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0b5e2b")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl

def build_pdf_reporte_chileno(
    logo_path: Optional[Path],
    costoA: int, costoB: int, dif_cost: int,
    tot_por_pot: pd.DataFrame,
    pot_mayor_sube: Optional[str], pot_mayor_baja: Optional[str],
    pot_sel: str, diff_prod: pd.Series,
    dfAB_head: pd.DataFrame,
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Tit", fontName="Helvetica-Bold", fontSize=18, textColor=colors.HexColor("#0b5e2b")))
    styles.add(ParagraphStyle(name="Sub", fontName="Helvetica-Bold", fontSize=12, textColor=colors.HexColor("#0b5e2b")))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=10, leading=14))
    styles.add(ParagraphStyle(name="Chip", fontName="Helvetica-Bold", fontSize=11, textColor=colors.HexColor("#0b5e2b")))

    story = []
    if logo_path and logo_path.exists():
        story.append(RLImage(str(logo_path), width=3.5 * cm, height=3.5 * cm))
        story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Informe en Chileno – Comparación A vs B", styles["Tit"]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(datetime.now().strftime("%d/%m/%Y %H:%M"), styles["Body"]))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph("💰 Costo total", styles["Sub"]))
    story.append(Paragraph(
        f"A = <b>{formato_clp(costoA)}</b>, B = <b>{formato_clp(costoB)}</b>. "
        f"Diferencia (B − A): <b>{formato_clp(dif_cost)}</b> "
        f"({'más caro 💸' if dif_cost > 0 else 'más barato 💰' if dif_cost < 0 else 'igual 🤝'}).",
        styles["Body"]
    ))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("🌾 Potreros", styles["Sub"]))
    if pot_mayor_sube is not None and pot_mayor_baja is not None:
        story.append(Paragraph(
            f"Donde más <b>sube</b> la dosis (B vs A): <b>{pot_mayor_sube}</b>; "
            f"y donde más <b>baja</b>: <b>{pot_mayor_baja}</b>.",
            styles["Body"]
        ))
    story.append(Spacer(1, 0.3 * cm))

    tot_show = tot_por_pot.copy()
    cols = [c for c in ["A", "B"] if c in tot_show.columns]
    if len(cols) > 0:
        story.append(Paragraph("Totales por potrero (kg/ha)", styles["Sub"]))
        story.append(_tabla_pdf(tot_show[cols].round(2).reset_index(), col_widths=[4 * cm, 3.5 * cm, 3.5 * cm]))
        story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(f"🧪 Mezclas en {pot_sel}", styles["Sub"]))
    if len(diff_prod) > 0:
        p_up = diff_prod.idxmax(); p_dn = diff_prod.idxmin()
        story.append(Paragraph(
            f"En <b>{pot_sel}</b>, el producto que más <b>sube</b> es <b>{p_up}</b> "
            f"({diff_prod.max():.1f} kg/ha) y el que más <b>baja</b> es <b>{p_dn}</b> "
            f"({diff_prod.min():.1f} kg/ha).", styles["Body"]
        ))
    else:
        story.append(Paragraph("No hay diferencias de mezcla en el potrero seleccionado.", styles["Body"]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Muestras de dosis por potrero y producto (A/B)", styles["Sub"]))
    mini = dfAB_head.copy()
    keep = [c for c in ["potrero", "producto", "kg_ha", "escenario"] if c in mini.columns]
    mini = mini[keep]
    story.append(_tabla_pdf(mini, col_widths=[3.5 * cm, 4 * cm, 3 * cm, 2.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("🧠 Interpretación", styles["Sub"]))
    story.append(Paragraph(
        "Si B es más caro, probablemente apretaste algún límite (N máx o mezcla) y el modelo usa productos más concentrados. "
        "Si B es más barato, diste holgura (tolerancia/N máx) y encontró una mezcla más eficiente.",
        styles["Body"]
    ))

    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Desarrollado por BData 🌾 – Demo con PuLP + Streamlit", styles["Chip"]))
    doc.build(story)
    return buf.getvalue()

# =============================
# Subida de archivos
# =============================
state = exists_local_inputs()
st.markdown("**Estado de archivos en `data/`:**")
cols = st.columns(3)
cols[0].markdown(f"- potreros.csv: {'✅' if 'potreros' in state else '❌'}")
cols[1].markdown(f"- requerimientos.csv: {'✅' if 'requerimientos' in state else '❌'}")
cols[2].markdown(f"- productos.csv: {'✅' if 'productos' in state else '❌'}")

if 'potreros' in state:
    st.info("Usando **potreros.csv** generado desde el **mapa** (no necesitas subirlo).")
else:
    st.warning("Aún no existe `data/potreros.csv`. Puedes **dibujarlo en el mapa** o subirlo acá.")

with st.expander("📂 Cargar datos de entrada", expanded=False):
    pot_file = st.file_uploader("Archivo de potreros (CSV)", type=["csv"])
    req_file = st.file_uploader("Archivo de requerimientos (CSV)", type=["csv"])
    prod_file = st.file_uploader("Archivo de productos (CSV)", type=["csv"])

    if st.button("Guardar archivos", key="save_inputs"):
        for uploaded, name in [(pot_file, "potreros.csv"),
                               (req_file, "requerimientos.csv"),
                               (prod_file, "productos.csv")]:
            if uploaded:
                with open(DATA_DIR / name, "wb") as f:
                    f.write(uploaded.getbuffer())
                st.success(f"{name} guardado correctamente ✅")

# =============================
# Parámetros A/B
# =============================
colA, colB = st.columns(2)
with colA:
    st.markdown("#### Parámetros Escenario A")
    nA = st.number_input("N máx A (kg/ha)", 0, 500, 300, 10, key="nA")
    mixA = st.number_input("Mezcla máx A (kg/ha)", 0, 1000, 600, 10, key="mixA")
    tolA = st.number_input("Tolerancia A (%)", 0.0, 10.0, 2.0, 0.5, key="tolA")
with colB:
    st.markdown("#### Parámetros Escenario B")
    nB = st.number_input("N máx B (kg/ha)", 0, 500, 250, 10, key="nB")
    mixB = st.number_input("Mezcla máx B (kg/ha)", 0, 1000, 500, 10, key="mixB")
    tolB = st.number_input("Tolerancia B (%)", 0.0, 10.0, 1.0, 0.5, key="tolB")

# =============================
# Ejecutar solver
# =============================
def run_solver(nmax: int, mixmax: int, tol_pct: float, costo_ap_ton: int, tag: str):
    csv_path = DATA_DIR / f"resultados_dosis_{tag}.csv"
    txt_path = DATA_DIR / f"_resumen_{tag}.txt"
    for p in (csv_path, txt_path):
        if p.exists():
            try: p.unlink()
            except Exception: pass
    proc = subprocess.run(
        [
            sys.executable, str(SOLVER_PATH),
            "--nmax",   str(nmax),
            "--mixmax", str(mixmax),
            "--tol",    str(tol_pct/100.0),
            "--costoap",str(costo_ap_ton),
            "--tag",    tag,
        ],
        capture_output=True, text=True
    )
    ok = (proc.returncode == 0) and csv_path.exists() and txt_path.exists()
    return proc, csv_path, txt_path, ok

# === MAPA DE POTREROS (dibujar o cargar) ===
import json
import folium
from streamlit_folium import st_folium
from pyproj import Geod
from shapely.geometry import shape
GEOD = Geod(ellps="WGS84")
POTREROS_GEOJSON = DATA_DIR / "potreros.geojson"
POTREROS_CSV = DATA_DIR / "potreros.csv"

with st.expander("🗺️ Mapa de potreros (dibujar o cargar)", expanded=False):
    left, right = st.columns([3, 2])
    with right:
        st.markdown("**Base del mapa**")
        center_lat = st.number_input("Latitud centro", value=-34.50, step=0.01, format="%.6f")
        center_lon = st.number_input("Longitud centro", value=-71.20, step=0.01, format="%.6f")
        zoom = st.slider("Zoom", 8, 18, 14)
        st.markdown("**Cargar GeoJSON (opcional)**")
        up = st.file_uploader("Subir GeoJSON de potreros", type=["geojson", "json"])
        if up:
            try:
                gj = json.loads(up.read().decode("utf-8"))
                POTREROS_GEOJSON.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
                st.success("GeoJSON cargado y guardado en data/potreros.geojson ✅")
            except Exception as e:
                st.error(f"Error al leer GeoJSON: {e}")
        st.caption("Tip: si no tienes GeoJSON, dibuja tus potreros directo en el mapa.")
    with left:
        m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, tiles="OpenStreetMap")
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri WorldImagery", name="Satélite").add_to(m)
        if POTREROS_GEOJSON.exists():
            gj_prev = json.loads(POTREROS_GEOJSON.read_text(encoding="utf-8"))
            folium.GeoJson(gj_prev, name="Potreros").add_to(m)
        from folium.plugins import Draw
        Draw(draw_options={"polyline": False, "rectangle": False, "circle": False,
                           "circlemarker": False, "marker": False, "polygon": True},
             edit_options={"edit": True, "remove": True}).add_to(m)
        folium.LayerControl().add_to(m)
        map_state = st_folium(m, width=700, height=520, returned_objects=["all_drawings"])

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Guardar dibujo como GeoJSON"):
            features = []
            if POTREROS_GEOJSON.exists():
                prev = json.loads(POTREROS_GEOJSON.read_text(encoding="utf-8"))
                if prev.get("type") == "FeatureCollection":
                    features.extend(prev.get("features", []))
            nuevos = map_state.get("all_drawings") or []
            for feat in nuevos:
                geom = feat.get("geometry", {})
                if geom and geom.get("type") == "Polygon":
                    props = feat.get("properties") or {}
                    props.setdefault("potrero", f"Potrero_{len(features)+1}")
                    props.setdefault("cultivo", "SinCultivo")
                    features.append({"type": "Feature", "properties": props, "geometry": geom})
            if not features:
                st.warning("No hay polígonos para guardar.")
            else:
                gj_new = {"type": "FeatureCollection", "features": features}
                POTREROS_GEOJSON.write_text(json.dumps(gj_new, ensure_ascii=False), encoding="utf-8")
                st.success("GeoJSON guardado en data/potreros.geojson ✅")
    with c2:
        if st.button("🧮 Calcular áreas y crear potreros.csv"):
            if not POTREROS_GEOJSON.exists():
                st.warning("Primero guarda un GeoJSON.")
            else:
                gj = json.loads(POTREROS_GEOJSON.read_text(encoding="utf-8"))
                filas = []
                for f in gj.get("features", []):
                    geom = f.get("geometry", {})
                    if not geom or geom.get("type") != "Polygon":
                        continue
                    poly = shape(geom)
                    lon, lat = poly.exterior.coords.xy
                    area_m2, _ = GEOD.polygon_area_perimeter(lon, lat)
                    area_ha = abs(area_m2) / 10_000.0
                    potrero = f.get("properties", {}).get("potrero", "SinNombre")
                    cultivo = f.get("properties", {}).get("cultivo", "SinCultivo")
                    filas.append({"potrero": potrero, "cultivo": cultivo, "superficie_ha": round(area_ha, 3)})
                if not filas:
                    st.warning("No encontré polígonos válidos.")
                else:
                    dfpot = pd.DataFrame(filas)
                    try:
                        reqs = pd.read_csv(DATA_DIR / "requerimientos.csv", sep=None, engine="python")
                        cultivos_posibles = sorted(reqs["cultivo"].unique().tolist())
                    except Exception:
                        cultivos_posibles = []
                    st.markdown("### ✏️ Editar cultivos por potrero")
                    if cultivos_posibles:
                        dfpot["cultivo"] = dfpot["cultivo"].apply(
                            lambda x: x if x in cultivos_posibles else (cultivos_posibles[0] if cultivos_posibles else x)
                        )
                        dfpot = st.data_editor(
                            dfpot, num_rows="dynamic",
                            column_config={"cultivo": st.column_config.SelectboxColumn(options=cultivos_posibles)},
                            use_container_width=True
                        )
                    else:
                        st.dataframe(dfpot, use_container_width=True)
                    dfpot.to_csv(POTREROS_CSV, index=False, encoding="utf-8")
                    st.success("✅ Generado/actualizado data/potreros.csv listo para el solver")

# =============================
# BOTÓN: Ejecutar A/B
# =============================
if st.button("🚜 Ejecutar escenarios A y B", key="run_ab"):
    st.session_state["already_rendered"] = True  # para no duplicar abajo
    with st.spinner("Ejecutando optimizaciones A y B..."):
        resA, csvA, txtA, okA = run_solver(nA, mixA, tolA, 0, "A")
        resB, csvB, txtB, okB = run_solver(nB, mixB, tolB, 0, "B")

    if not okA and not okB:
        st.warning("Ninguno de los escenarios terminó bien. Revisa límites y datos.")
        st.caption("Logs A:"); st.code(resA.stderr or resA.stdout or "sin salida")
        st.caption("Logs B:"); st.code(resB.stderr or resB.stdout or "sin salida")
        st.stop()
    elif not okA:
        st.warning("El escenario A falló. Revisemos límites y datos.")
        st.caption("Logs A:"); st.code(resA.stderr or resA.stdout or "sin salida")
    elif not okB:
        st.warning("El escenario B falló. Revisemos límites y datos.")
        st.caption("Logs B:"); st.code(resB.stderr or resB.stdout or "sin salida")
    else:
        st.success("Optimización completada ✅")

    # Cargar costos
    costoA = costo_total_desde_txt(txtA) if okA else None
    costoB = costo_total_desde_txt(txtB) if okB else None

    # Métricas
    metros = []
    if costoA is not None: metros.append(("Costo A", costoA))
    if costoB is not None: metros.append(("Costo B", costoB))
    if (costoA is not None) and (costoB is not None):
        dif_cost = costoB - costoA
        metros.append(("Diferencia (B - A)", dif_cost))
    if metros:
        cols_m = st.columns(len(metros))
        for i, (lab, val) in enumerate(metros):
            cols_m[i].metric(lab, formato_clp(val))

    # Texto corto
    if (costoA is not None) and (costoB is not None):
        dif_cost = costoB - costoA
        st.markdown(
            f"""
**¿Cómo leerlo?**  
- **A:** {formato_clp(costoA)}  ·  **B:** {formato_clp(costoB)}  
- Diferencia (**B − A**): **{formato_clp(dif_cost)}** → {'sube' if dif_cost>0 else 'baja' if dif_cost<0 else 'no cambia'} con B.  
Si está **positivo**, B es **más caro**; si está **negativo**, B es **más barato**.
            """
        )

    # Guardar TODO en estado
    st.session_state["last_run"] = {
        "okA": okA, "okB": okB,
        "csvA": str(csvA) if okA else None,
        "txtA": str(txtA) if okA else None,
        "csvB": str(csvB) if okB else None,
        "txtB": str(txtB) if okB else None,
        "costoA": costoA if okA else None,
        "costoB": costoB if okB else None,
        "mixA": mixA, "mixB": mixB, "nA": nA, "nB": nB, "tolA": tolA, "tolB": tolB,
    }

    # ===== Resumen agronómico (inmediato)
    def resumen_agronomico(tag, csv_path, mix_lim):
        if not csv_path or not csv_path.exists():
            return
        st.markdown(f"### Escenario {tag}")
        df = pd.read_csv(csv_path)
        prods = pd.read_csv(DATA_DIR / "productos.csv", sep=None, engine="python")
        df = df.merge(prods[["producto","N_pct","P2O5_pct","K2O_pct"]], on="producto", how="left")
        df["N_aporte"] = df["kg_ha"] * df["N_pct"] / 100
        df["P_aporte"] = df["kg_ha"] * df["P2O5_pct"] / 100
        df["K_aporte"] = df["kg_ha"] * df["K2O_pct"] / 100
        resumen = (df.groupby("producto")[["kg_ha","N_aporte","P_aporte","K_aporte"]]
                     .sum()
                     .assign(**{"% mezcla": lambda x: 100*x["kg_ha"]/x["kg_ha"].sum()})
                     .round(2))
        st.dataframe(resumen, use_container_width=True)
        predom = resumen["% mezcla"].idxmax()
        tiene_N = resumen["N_aporte"].sum() > 0.5
        tiene_P = resumen["P_aporte"].sum() > 0.5
        tiene_K = resumen["K_aporte"].sum() > 0.5
        texto = f"La mezcla del escenario {tag} tiene **predominio de {predom}**"
        if   tiene_N and tiene_P: texto += ", por su doble aporte de N y P₂O₅"
        elif tiene_N:             texto += ", como fuente principal de N"
        elif tiene_P:             texto += ", como fuente principal de P₂O₅"
        elif tiene_K:             texto += ", aportando K₂O"
        texto += "."
        if not tiene_K:
            texto += " No se usa KCl ni otras fuentes de potasio porque K₂O no es requerido."
        total_mix = resumen["kg_ha"].sum()
        if mix_lim is not None:
            texto += " La mezcla total "
            if total_mix < 0.9*mix_lim: texto += "queda bajo el límite de mezcla (buena eficiencia)."
            elif total_mix <= mix_lim:  texto += "llega cerca del límite de mezcla (ajuste fino)."
            else:                       texto += "supera el límite de mezcla; revisa parámetros o dosis mínimas."
        st.markdown(f"> 🧩 {texto}")

    st.markdown("## 🌾 Interpretación agronómica de la mezcla")
    if okA: resumen_agronomico("A", csvA, mixA)
    if okB: resumen_agronomico("B", csvB, mixB)

    # ===== Comparativos / Reportes SOLO si existen A y B
    if okA and okB:
        dfA = pd.read_csv(csvA); dfA["escenario"] = "A"
        dfB = pd.read_csv(csvB); dfB["escenario"] = "B"
        dfAB = pd.concat([dfA, dfB], ignore_index=True)

        st.subheader("📊 Comparación de dosis (A vs B)")
        st.dataframe(dfAB, use_container_width=True)

        st.subheader("📈 Total kg/ha por potrero (A vs B)")
        tot_por_pot = (dfAB.groupby(["potrero","escenario"])["kg_ha"]
                          .sum().unstack("escenario").fillna(0).sort_index())
        st.bar_chart(tot_por_pot)

        dif_pot = (tot_por_pot.get("B",0) - tot_por_pot.get("A",0)).rename("dif")
        pot_mayor_sube = dif_pot.idxmax() if len(dif_pot) else None
        pot_mayor_baja = dif_pot.idxmin() if len(dif_pot) else None

        st.subheader("📉 Diferencia total (B − A) por potrero")
        st.bar_chart(dif_pot)

        pot_sel = st.selectbox("🔎 Comparar mezcla por producto en potrero:", sorted(dfAB["potrero"].unique()))
        mix_pot = (dfAB[dfAB["potrero"] == pot_sel]
                      .pivot_table(index="producto", columns="escenario", values="kg_ha", aggfunc="sum")
                      .fillna(0).sort_index())
        st.subheader(f"🧪 Mezcla en {pot_sel} (kg/ha)")
        st.bar_chart(mix_pot)

        st.subheader(f"📊 Diferencia por producto en {pot_sel} (B − A)")
        diff_prod = (mix_pot.get("B",0) - mix_pot.get("A",0)).rename("Diferencia (kg/ha)")
        st.bar_chart(diff_prod)

        # Descarga CSV comparación
        st.download_button(
            "📥 Descargar comparación A/B (CSV)",
            data=pd.concat([dfA, dfB]).to_csv(index=False).encode("utf-8"),
            file_name="comparacion_AB.csv",
            mime="text/csv",
            key="dl_ab",
        )

        # ===== Reporte “en chileno” (MD + PDF) — DENTRO del if okA and okB
        dif_cost = (costoB - costoA)
        sube_txt = f"{dif_pot.idxmax()} (+{dif_pot.max():.1f} kg/ha)" if len(dif_pot) else "—"
        baja_txt = f"{dif_pot.idxmin()} ({dif_pot.min():.1f} kg/ha)" if len(dif_pot) else "—"
        p_up = diff_prod.idxmax() if len(diff_prod)>0 else "—"
        p_dn = diff_prod.idxmin() if len(diff_prod)>0 else "—"

        resumen_txt = f"""
# 🧾 Informe – Comparación A y B

## 💰 Costo total
A: **{formato_clp(costoA)}** · B: **{formato_clp(costoB)}** · Diferencia: **{formato_clp(dif_cost)}** → {'B más caro 💸' if dif_cost>0 else 'B más barato 💰' if dif_cost<0 else 'igual 🤝'}.

## 🌾 Potreros
Mayor aumento: **{sube_txt}** · Mayor baja: **{baja_txt}**.

## 🧪 Mezclas y productos
En **{pot_sel}**: sube más **{p_up if len(diff_prod)>0 else '—'}**, baja más **{p_dn if len(diff_prod)>0 else '—'}**.

## 🧠 Interpretación
Si B cuesta más, apretaste límites (N máx o mezcla) y el modelo usa productos más concentrados.
Si B es más barato, diste holgura (tolerancia/N máx) y encontró una mezcla más eficiente.

_Desarrollado por BData 🌾 – PuLP + Streamlit_
        """.strip()

        st.download_button(
            "📥 Descargar reporte en chileno (Markdown)",
            data=resumen_txt.encode("utf-8"),
            file_name="reporte_en_chileno.md",
            mime="text/markdown",
            key="dl_chileno",
        )

        logo_path = DATA_DIR / "logo-bdata.png"
        dfAB_head = dfAB.head(10).copy()
        pdf_bytes = build_pdf_reporte_chileno(
            logo_path=logo_path if logo_path.exists() else None,
            costoA=costoA, costoB=costoB, dif_cost=dif_cost,
            tot_por_pot=tot_por_pot,
            pot_mayor_sube=pot_mayor_sube, pot_mayor_baja=pot_mayor_baja,
            pot_sel=pot_sel, diff_prod=diff_prod,
            dfAB_head=dfAB_head,
        )
        st.download_button(
            "📥 Descargar informe fertilización BData (PDF)",
            data=pdf_bytes,
            file_name="informe_fertilizacion_BData.pdf",
            mime="application/pdf",
            key="dl_pdf_chileno",
        )

# =============================
# Render persistente (último resultado) — evita duplicar si ya renderizamos
# =============================
from pathlib import Path as _Path
ctx = st.session_state.get("last_run", {})

if ctx and (ctx.get("okA") or ctx.get("okB")) and not st.session_state["already_rendered"]:
    costoA = ctx.get("costoA"); costoB = ctx.get("costoB")
    mixA = ctx.get("mixA"); mixB = ctx.get("mixB")
    csvA = _Path(ctx["csvA"]) if ctx.get("okA") and ctx.get("csvA") else None
    txtA = _Path(ctx["txtA"]) if ctx.get("okA") and ctx.get("txtA") else None
    csvB = _Path(ctx["csvB"]) if ctx.get("okB") and ctx.get("csvB") else None
    txtB = _Path(ctx["txtB"]) if ctx.get("okB") and ctx.get("txtB") else None

    st.markdown("## 🌾 Interpretación agronómica de la mezcla")

    def resumen_agronomico_persist(tag, csv_path, mix_lim):
        if not csv_path or not csv_path.exists():
            return
        st.markdown(f"### Escenario {tag}")
        df = pd.read_csv(csv_path)
        prods = pd.read_csv(DATA_DIR / "productos.csv", sep=None, engine="python")
        df = df.merge(prods[["producto","N_pct","P2O5_pct","K2O_pct"]], on="producto", how="left")
        df["N_aporte"] = df["kg_ha"] * df["N_pct"] / 100
        df["P_aporte"] = df["kg_ha"] * df["P2O5_pct"] / 100
        df["K_aporte"] = df["kg_ha"] * df["K2O_pct"] / 100
        resumen = (df.groupby("producto")[["kg_ha","N_aporte","P_aporte","K_aporte"]]
                     .sum()
                     .assign(**{"% mezcla": lambda x: 100*x["kg_ha"]/x["kg_ha"].sum()})
                     .round(2))
        st.dataframe(resumen, use_container_width=True)
        predom = resumen["% mezcla"].idxmax()
        tiene_N = resumen["N_aporte"].sum() > 0.5
        tiene_P = resumen["P_aporte"].sum() > 0.5
        tiene_K = resumen["K_aporte"].sum() > 0.5
        texto = f"La mezcla del escenario {tag} tiene **predominio de {predom}**"
        if   tiene_N and tiene_P: texto += ", por su doble aporte de N y P₂O₅"
        elif tiene_N:             texto += ", como fuente principal de N"
        elif tiene_P:             texto += ", como fuente principal de P₂O₅"
        elif tiene_K:             texto += ", aportando K₂O"
        texto += "."
        if not tiene_K:
            texto += " No se usa KCl ni otras fuentes de potasio porque K₂O no es requerido."
        total_mix = resumen["kg_ha"].sum()
        if mix_lim is not None:
            texto += " La mezcla total "
            if total_mix < 0.9*mix_lim: texto += "queda bajo el límite de mezcla (buena eficiencia)."
            elif total_mix <= mix_lim:  texto += "llega cerca del límite de mezcla (ajuste fino)."
            else:                       texto += "supera el límite; revisa parámetros o dósis mínimas."
        st.markdown(f"> 🧩 {texto}")

    if ctx.get("okA"): resumen_agronomico_persist("A", csvA, mixA)
    if ctx.get("okB"): resumen_agronomico_persist("B", csvB, mixB)

    if ctx.get("okA") and ctx.get("okB"):
        dfA = pd.read_csv(csvA); dfA["escenario"] = "A"
        dfB = pd.read_csv(csvB); dfB["escenario"] = "B"
        dfAB = pd.concat([dfA, dfB], ignore_index=True)

        st.subheader("📊 Comparación de dosis (A vs B)")
        st.dataframe(dfAB, use_container_width=True)

        st.subheader("📈 Total kg/ha por potrero (A vs B)")
        tot_por_pot = (dfAB.groupby(["potrero","escenario"])["kg_ha"]
                          .sum().unstack("escenario").fillna(0).sort_index())
        st.bar_chart(tot_por_pot)

        dif_pot = (tot_por_pot.get("B",0) - tot_por_pot.get("A",0)).rename("dif")
        st.subheader("📉 Diferencia total (B − A) por potrero")
        st.bar_chart(dif_pot)

        pot_sel = st.selectbox("🔎 Comparar mezcla por producto en potrero:",
                               sorted(dfAB["potrero"].unique()), key="sel_persist")
        mix_pot = (dfAB[dfAB["potrero"] == pot_sel]
                      .pivot_table(index="producto", columns="escenario", values="kg_ha", aggfunc="sum")
                      .fillna(0).sort_index())
        st.subheader(f"🧪 Mezcla en {pot_sel} (kg/ha)")
        st.bar_chart(mix_pot)

        st.subheader(f"📊 Diferencia por producto en {pot_sel} (B − A)")
        diff_prod = (mix_pot.get("B",0) - mix_pot.get("A",0)).rename("Diferencia (kg/ha)")
        st.bar_chart(diff_prod)

        st.download_button(
            "📥 Descargar comparación A/B (CSV)",
            data=pd.concat([dfA, dfB]).to_csv(index=False).encode("utf-8"),
            file_name="comparacion_AB.csv",
            mime="text/csv",
            key="dl_ab_persist",
        )

# Pie
st.caption("Desarrollado por BData 🌾 | Digitalizando el campo Chileno")
