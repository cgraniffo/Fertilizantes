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
# Rutas base
# =============================
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "app" / "assets"  # app/assets/logo_bdata.png, favicon.png
DATA_DIR = BASE_DIR / "data"
SOLVER_PATH = BASE_DIR / "optim" / "solver.py"

# Page config (reemplaza tu set_page_config por este)
st.set_page_config(
    page_title="Optimizador de Fertilización | Boost Data",
    page_icon=str(ASSETS_DIR / "favicon.png"),
    layout="wide",
)

# CSS: tema suave + ocultar footer/hamburguesa default y dar estilo a headers / tarjetas
CUSTOM_CSS = f"""
<style>
/* tipografía base */
html, body, [class*="css"] {{
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, "Helvetica Neue", Arial, "Noto Sans", "Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol" !important;
}}
/* header container */
.bdata-header {{
  display:flex; align-items:center; gap:16px; margin-bottom: 4px;
}}
.bdata-claim {{
  font-size: 14px; color:#5f6c72; margin-top:2px;
}}
/* cards suaves */
.block-container {{
  padding-top: 1.2rem;
}}
/* esconder footer streamlit y el menú */
footer {{ visibility: hidden; }}
#MainMenu {{ visibility: hidden; }}

/* métricas más elegantes */
div[data-testid="stMetricValue"] {{
  font-weight: 800;
}}
/* botones primarios un poco más marcados */
.stButton>button {{
  border-radius: 10px;
  padding: 0.55rem 0.9rem;
  font-weight: 600;
}}
/* subtítulos de secciones */
h3, h4 {{
  scroll-margin-top: 72px;
}}
/* línea divisoria sutil */
.bdata-divider {{
  height:1px; background:linear-gradient(to right, #e9eef1 0%, #e9eef1 60%, transparent 100%);
  margin: 6px 0 14px 0;
}}
/* pie de página propio */
.bdata-footer {{
  margin-top: 24px; padding: 12px 0 40px 0; color:#6b7b83; font-size: 12px;
  border-top: 1px solid #eef2f4;
}}
.bdata-badge {{
  display:inline-flex; align-items:center; gap:6px;
  background:#eef7f0; color:#2f7a3e; border-radius: 16px; padding:4px 10px; font-size:12px; font-weight:600;
}}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# HEADER con logo + título
c1, c2 = st.columns([1, 6], gap="small")
with c1:
    try:
        st.image(str(ASSETS_DIR / "logo_bdata.png"), use_container_width=True)
    except Exception:
        st.write("")  # por si no está el logo aún
with c2:
    st.title("Optimizador de Fertilización")
    st.markdown('<div class="bdata-claim">Planifica mezclas óptimas por potrero, cumpliendo N–P–K al menor costo.</div>', unsafe_allow_html=True)
st.markdown('<div class="bdata-divider"></div>', unsafe_allow_html=True)

# helper: toast seguro (Streamlit 1.38 lo soporta)
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


# =============================
# Utilidades generales
# =============================
def formato_clp(n: int) -> str:
    """Formatea CLP con punto de miles (estilo Chile)."""
    try:
        return f"${n:,.0f}".replace(",", ".")
    except Exception:
        return str(n)


def costo_total_desde_txt(path: Path) -> int:
    """Lee un _resumen.txt y extrae el número de CLP."""
    if not path.exists():
        return 0
    raw = path.read_text(encoding="utf-8")
    dig = "".join(ch for ch in raw if ch.isdigit())
    return int(dig) if dig else 0


def df_to_md_table(df: pd.DataFrame) -> str:
    """Convierte un DataFrame en tabla Markdown sin depender de 'tabulate'."""
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = [str(x) for x in row.tolist()]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


# =============================
# PDF helpers (ReportLab)
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
    """Genera PDF (bytes) con un informe corto en chileno."""
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

    # Encabezado con logo (opcional)
    if logo_path and logo_path.exists():
        story.append(RLImage(str(logo_path), width=3.5 * cm, height=3.5 * cm))
        story.append(Spacer(1, 0.2 * cm))

    story.append(Paragraph("Informe en Chileno – Comparación A vs B", styles["Tit"]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(datetime.now().strftime("%d/%m/%Y %H:%M"), styles["Body"]))
    story.append(Spacer(1, 0.5 * cm))

    # Costos
    story.append(Paragraph("💰 Costo total", styles["Sub"]))
    story.append(Paragraph(
        f"En plata: A = <b>{formato_clp(costoA)}</b>, B = <b>{formato_clp(costoB)}</b>. "
        f"Diferencia (B − A): <b>{formato_clp(dif_cost)}</b> "
        f"({'más caro 💸' if dif_cost > 0 else 'más barato 💰' if dif_cost < 0 else 'igual de caro 🤝'}).",
        styles["Body"]
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Potreros (resumen)
    story.append(Paragraph("🌾 Potreros", styles["Sub"]))
    if pot_mayor_sube is not None and pot_mayor_baja is not None:
        story.append(Paragraph(
            f"Donde más <b>sube</b> la dosis (B vs A) es en <b>{pot_mayor_sube}</b>; "
            f"y donde más <b>baja</b> es en <b>{pot_mayor_baja}</b>.",
            styles["Body"]
        ))
    else:
        story.append(Paragraph("Se muestran cambios por potrero más adelante.", styles["Body"]))
    story.append(Spacer(1, 0.3 * cm))

    # Totales por potrero (tabla corta)
    tot_show = tot_por_pot.copy()
    cols = [c for c in ["A", "B"] if c in tot_show.columns]
    if len(cols) > 0:
        story.append(Paragraph("Totales por potrero (kg/ha)", styles["Sub"]))
        story.append(_tabla_pdf(tot_show[cols].round(2).reset_index(), col_widths=[4 * cm, 3.5 * cm, 3.5 * cm]))
        story.append(Spacer(1, 0.4 * cm))

    # Producto que más sube/baja en pot_sel
    story.append(Paragraph(f"🧪 Mezclas en {pot_sel}", styles["Sub"]))
    if len(diff_prod) > 0:
        p_up = diff_prod.idxmax()
        p_dn = diff_prod.idxmin()
        story.append(Paragraph(
            f"En <b>{pot_sel}</b>, el producto que más <b>sube</b> con B vs A es <b>{p_up}</b> "
            f"({diff_prod.max():.1f} kg/ha) y el que más <b>baja</b> es <b>{p_dn}</b> "
            f"({diff_prod.min():.1f} kg/ha).",
            styles["Body"]
        ))
    else:
        story.append(Paragraph("No hay diferencias de mezcla en el potrero seleccionado.", styles["Body"]))
    story.append(Spacer(1, 0.4 * cm))

    # Minitabla de muestras A/B
    story.append(Paragraph("Muestras de dosis por potrero y producto (A/B)", styles["Sub"]))
    mini = dfAB_head.copy()
    keep = [c for c in ["potrero", "producto", "kg_ha", "escenario"] if c in mini.columns]
    mini = mini[keep]
    story.append(_tabla_pdf(mini, col_widths=[3.5 * cm, 4 * cm, 3 * cm, 2.5 * cm]))
    story.append(Spacer(1, 0.4 * cm))

    # Conclusión
    story.append(Paragraph("🧠 Interpretación", styles["Sub"]))
    story.append(Paragraph(
        "Si el escenario B te salió más caro, probablemente apretaste alguna restricción "
        "(menos N máximo, menos mezcla por pasada) y el modelo se apoya en productos más concentrados "
        "o sube dosis en potreros clave. Si B es más barato, diste más holgura (tolerancia mayor, N máximo más alto) "
        "y se encontró una mezcla más eficiente. En simple: si querís eficiencia, revisa dónde B gasta menos sin perder "
        "nutrientes; si querís asegurar techo productivo, mira dónde B sube dosis o cambia mezcla.",
        styles["Body"]
    ))

    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("Desarrollado por BData 🌾 – Demo con PuLP + Streamlit", styles["Chip"]))

    doc.build(story)
    return buf.getvalue()


# =============================
# Subida de archivos
# =============================
with st.expander("📂 Cargar datos de entrada", expanded=True):
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
# Parámetros de optimización A/B
# =============================
colA, colB = st.columns(2)
with colA:
    st.markdown("#### Escenario A")
    nA = st.number_input("N máx A (kg/ha)", 0, 500, 300, 10, key="nA")
    mixA = st.number_input("Mezcla máx A (kg/ha)", 0, 1000, 600, 10, key="mixA")
    tolA = st.number_input("Tolerancia A (%)", 0.0, 10.0, 2.0, 0.5, key="tolA")

with colB:
    st.markdown("#### Escenario B")
    nB = st.number_input("N máx B (kg/ha)", 0, 500, 250, 10, key="nB")
    mixB = st.number_input("Mezcla máx B (kg/ha)", 0, 1000, 500, 10, key="mixB")
    tolB = st.number_input("Tolerancia B (%)", 0.0, 10.0, 1.0, 0.5, key="tolB")


# =============================
# Ejecutar solver (por escenario)
# =============================

def run_solver(nmax: int, mixmax: int, tol_pct: float, costo_ap_ton: int, tag: str):
    """
    Ejecuta el solver con un TAG (A/B) y valida que existan las salidas esperadas.
    Retorna: (proc, csv_path, txt_path, ok)
    """
    # Archivos de salida esperados con sufijo por TAG (A / B)
    csv_path = DATA_DIR / f"resultados_dosis_{tag}.csv"
    txt_path = DATA_DIR / f"_resumen_{tag}.txt"

    # (Opcional) borra salidas viejas para no confundir la validación
    for p in (csv_path, txt_path):
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # Lanza el solver con los parámetros
    proc = subprocess.run(
        [
            sys.executable, str(SOLVER_PATH),
            "--nmax",   str(nmax),
            "--mixmax", str(mixmax),
            "--tol",    str(tol_pct/100.0),
            "--costoap",str(costo_ap_ton),
            "--tag",    tag,                      # ⚠️ el solver debe aceptar --tag
        ],
        capture_output=True,
        text=True
    )

    # Éxito: returncode OK y archivos de salida presentes
    ok = (proc.returncode == 0) and csv_path.exists() and txt_path.exists()
    return proc, csv_path, txt_path, ok


# =============================
# Botón: ejecutar A/B (con textos + toasts + delta)
# === REEMPLAZA TU BLOQUE POR ESTE ===
# =============================
if st.button("🚜 Ejecutar escenarios A y B", key="run_ab"):
    with st.spinner("Ejecutando optimizaciones A y B..."):
        resA, csvA, txtA, okA = run_solver(nA, mixA, tolA, 0, "A")
        resB, csvB, txtB, okB = run_solver(nB, mixB, tolB, 0, "B")

    # Mensajes según resultado real
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

    # A partir de aquí, carga lo que SÍ exista (A y/o B) sin reventar
    costoA = costoB = None
    if okA:
        costoA = costo_total_desde_txt(txtA)
    if okB:
        costoB = costo_total_desde_txt(txtB)

    # Métricas: solo muestra lo que tengas
    cols = []
    if costoA is not None: cols.append(("Costo A", costoA))
    if costoB is not None: cols.append(("Costo B", costoB))
    if costoA is not None and costoB is not None:
        dif_cost = costoB - costoA
        cols.append(("Diferencia (B - A)", dif_cost))

    if cols:
        c = st.columns(len(cols))
        for i, (label, val) in enumerate(cols):
            st.metric(label, formato_clp(val))

    # Texto resumen (solo si hay ambos)
    if (costoA is not None) and (costoB is not None):
        dif_cost = costoB - costoA
        st.markdown(
            f"""
**¿Cómo leerlo?**  
- **A:** {formato_clp(costoA)}  ·  **B:** {formato_clp(costoB)}  
- La diferencia (**B − A**) es **{formato_clp(dif_cost)}** → {'sube' if dif_cost>0 else 'baja' if dif_cost<0 else 'no cambia'} con B.  
Si está **en positivo**, B es **más caro**; si está **en negativo**, B es **más barato**.
            """
        )

    # Tablas / gráficos comparativos, solo si existen ambos CSV
    if (okA and okB):
        dfA = pd.read_csv(csvA); dfA["escenario"] = "A"
        dfB = pd.read_csv(csvB); dfB["escenario"] = "B"
        dfAB = pd.concat([dfA, dfB], ignore_index=True)
        # … (resto de tus gráficos/validaciones que ya tenías)




        # 1) Tabla de dosis A vs B
        st.subheader("📊 Comparación de dosis (A vs B)")
        st.dataframe(dfAB, use_container_width=True)

        top_filas = (dfAB.sort_values("kg_ha", ascending=False)
                         .head(3)[["potrero", "producto", "kg_ha", "escenario"]].values.tolist())
        texto_top = " · ".join([f"{p}-{prod}: {kg:.0f} kg/ha ({esc})" for p, prod, kg, esc in top_filas]) if top_filas else "—"
        st.markdown(
            f"""
**Para leer la tabla:**  
- Cada fila muestra **kg/ha por producto y potrero**, y **qué escenario**.  
- Compara el mismo potrero-producto entre A y B para ver dónde sube o baja.  
- **3 valores más altos** (ojo rápido): {texto_top}.
            """
        )

        # 2) Total kg/ha por potrero (A vs B)
        st.subheader("📈 Total kg/ha por potrero (A vs B)")
        tot_por_pot = (
            dfAB.groupby(["potrero", "escenario"])["kg_ha"]
                .sum().unstack("escenario").fillna(0).sort_index()
        )
        st.bar_chart(tot_por_pot)

        dif_pot = (tot_por_pot.get("B", 0) - tot_por_pot.get("A", 0)).rename("dif")
        pot_mayor_sube = dif_pot.idxmax() if hasattr(dif_pot, "idxmax") and len(dif_pot) else None
        pot_mayor_baja = dif_pot.idxmin() if hasattr(dif_pot, "idxmin") and len(dif_pot) else None

        sube_txt = f"{pot_mayor_sube} (+{dif_pot.max():.1f} kg/ha)" if pot_mayor_sube else "—"
        baja_txt = f"{pot_mayor_baja} ({dif_pot.min():.1f} kg/ha)" if pot_mayor_baja else "—"
        st.markdown(
            f"""
**¿Cómo leer este gráfico?**  
- Muestra el **total de kg/ha** (todos los productos) por **potrero** comparando A vs B.  
- **Mayor aumento**: {sube_txt}.  **Mayor baja**: {baja_txt}.  
*(Valores aprox. para captar la tendencia).*
            """
        )

        # 3) Diferencia total (B − A) por potrero
        st.subheader("📉 Diferencia total (B − A) por potrero")
        st.bar_chart(dif_pot)

        # 4) Comparación por producto en potrero
        pot_sel = st.selectbox("🔎 Comparar mezcla por producto en potrero:", sorted(dfAB["potrero"].unique()))
        mix_pot = (
            dfAB[dfAB["potrero"] == pot_sel]
                .pivot_table(index="producto", columns="escenario", values="kg_ha", aggfunc="sum")
                .fillna(0).sort_index()
        )
        st.subheader(f"🧪 Mezcla en {pot_sel} (kg/ha)")
        st.bar_chart(mix_pot)

        prod_top_A = mix_pot["A"].idxmax() if "A" in mix_pot.columns and len(mix_pot) else "—"
        prod_top_B = mix_pot["B"].idxmax() if "B" in mix_pot.columns and len(mix_pot) else "—"
        st.markdown(
            f"""
**¿Cómo leer este gráfico?**  
- Compara **producto por producto** en **{pot_sel}** entre A y B.  
- **Más fuerte en A:** {prod_top_A}.  **Más fuerte en B:** {prod_top_B}.  
Si B usa más de un producto, puede ser por **límite de mezcla** o **N máx** más apretado.
            """
        )

        # 5) Diferencia por producto (B − A) en potrero seleccionado
        st.subheader(f"📊 Diferencia por producto en {pot_sel} (B − A)")
        diff_prod = (mix_pot.get("B", 0) - mix_pot.get("A", 0)).rename("Diferencia (kg/ha)")
        st.bar_chart(diff_prod)

        if len(diff_prod) > 0:
            p_up = diff_prod.idxmax()
            p_dn = diff_prod.idxmin()
            st.markdown(
                f"""
**En simple:**  
- En **{pot_sel}**, **sube más**: {p_up} (+{diff_prod.max():.1f} kg/ha).  
- **Baja más**: {p_dn} ({diff_prod.min():.1f} kg/ha).  
Así ves **dónde está ajustando la mezcla** el modelo cuando cambias parámetros.
                """
            )

        # =============================
        # Resumen en chileno por potrero (A vs B)
        # =============================
        def render_resumen_chileno_ab():
            if "dfAB" not in st.session_state:
                return
            dfAB = st.session_state["dfAB"]
            if dfAB is None or dfAB.empty:
                return

            st.markdown("### 🧾 Resumen para terreno (en chileno)")

            # Resumen de costos si los tenemos guardados
            costoA = st.session_state.get("costoA")
            costoB = st.session_state.get("costoB")
            if isinstance(costoA, (int, float)) and isinstance(costoB, (int, float)):
                dif_cost = (costoB - costoA)
                st.markdown(
                    f"- **Costo A**: {formato_clp(costoA)} | **Costo B**: {formato_clp(costoB)} | "
                    f"**Diferencia (B − A)**: {formato_clp(dif_cost)} "
                    f"→ {'B más caro' if dif_cost>0 else 'B más barato' if dif_cost<0 else 'igual'}."
                )

            # Total kg/ha por potrero y escenario
            tot = (
                dfAB.groupby(["potrero", "escenario"])["kg_ha"]
                .sum()
                .unstack(fill_value=0)
            )
            if "A" not in tot.columns:
                tot["A"] = 0.0
            if "B" not in tot.columns:
                tot["B"] = 0.0
            tot["dif_BA"] = tot["B"] - tot["A"]

            # Para cada potrero: cambios de productos (top 3 por magnitud)
            for potrero, sub in dfAB.groupby("potrero", sort=False):
                matriz = (
                    sub.pivot_table(
                        index="producto", columns="escenario",
                        values="kg_ha", aggfunc="sum", fill_value=0.0
                    )
                )
                if "A" not in matriz.columns:
                    matriz["A"] = 0.0
                if "B" not in matriz.columns:
                    matriz["B"] = 0.0
                matriz["dif_BA"] = matriz["B"] - matriz["A"]

                # Orden por cambio absoluto y tomar los top 3 “movedores”
                orden = matriz["dif_BA"].abs().sort_values(ascending=False).index
                movers = matriz.loc[orden].head(3)

                suben = [f"{p}: +{v:.1f} kg/ha" for p, v in movers[movers["dif_BA"] > 0]["dif_BA"].items()]
                bajan = [f"{p}: {v:.1f} kg/ha" for p, v in movers[movers["dif_BA"] < 0]["dif_BA"].items()]

                totalA = float(tot.loc[potrero, "A"]) if potrero in tot.index else 0.0
                totalB = float(tot.loc[potrero, "B"]) if potrero in tot.index else 0.0
                dtotal = float(tot.loc[potrero, "dif_BA"]) if potrero in tot.index else 0.0

                etiqueta = (
                    "más mezcla total en B" if dtotal > 0
                    else "menos mezcla total en B" if dtotal < 0
                    else "misma mezcla total"
                )

                with st.expander(
                    f"**{potrero}** — total A: {totalA:.1f} kg/ha · total B: {totalB:.1f} kg/ha "
                    f"({('+' if dtotal>0 else '')}{dtotal:.1f}) → {etiqueta}",
                    expanded=False
                ):
                    if suben:
                        st.markdown("- **Sube**: " + ", ".join(suben))
                    if bajan:
                        st.markdown("- **Baja**: " + ", ".join(bajan))
                    if not suben and not bajan:
                        st.markdown("- Sin cambios relevantes de productos.")

                    # Tiro un tip corto, útil para conversación con el agricultor:
                    tip = (
                        "Si el potrero anda justo en N/P/K, ojo con no pasarse por arriba en mezcla total. "
                        "Si se ve **subcumplimiento**, mueve dosis desde los que **suben** hacia los productos que faltan, "
                        "manteniendo el tope de mezcla (kg/ha) que aguanta tu maquinaria."
                    )
                    st.caption(tip)

        # === Llamar al render (ponlo debajo de tus gráficos/tablas A/B)
        render_resumen_chileno_ab()


        # 6) Descarga CSV
        st.download_button(
            "📥 Descargar comparación A/B (CSV)",
            data=dfAB.to_csv(index=False).encode("utf-8"),
            file_name="comparacion_AB.csv",
            mime="text/csv",
            key="dl_ab"
        )

        # 7) Reporte “en chileno” (Markdown)
        resumen_txt = f"""
# 🧾 Informe – Comparación de Escenarios A y B

## 💰 Costo total
En plata, el escenario A cuesta **{formato_clp(costoA)}**,
mientras que el escenario B cuesta **{formato_clp(costoB)}**.
La diferencia es de **{formato_clp(dif_cost)}**,
así que el escenario B es **{'más caro 💸' if dif_cost>0 else 'más barato 💰' if dif_cost<0 else 'igual de caro 🤝'}**.

## 🌾 Potreros
Donde más **sube** la dosis (B vs A): **{sube_txt}**.  
Donde más **baja** la dosis (B vs A): **{baja_txt}**.

## 🧪 Mezclas y productos
En el potrero **{pot_sel}**,
el producto que más **aumenta** con B vs A es **{p_up if len(diff_prod)>0 else '—'}** ({diff_prod.max():.1f} kg/ha),
y el que más **disminuye** es **{p_dn if len(diff_prod)>0 else '—'}** ({diff_prod.min():.1f} kg/ha).

## 🧠 Interpretación
Si el escenario B te cuesta más caro, probablemente apretaste una **restricción**
(por ejemplo **menos N máximo** o **menos mezcla por pasada**).
El modelo entonces se ve obligado a usar **productos más concentrados o caros**.

Si B es más barato, quizá diste más **holgura** (tolerancia mayor, N máximo más alto)
y encontró una **mezcla más eficiente**.

En simple:
- Si buscas **eficiencia económica**, fíjate dónde B gasta menos sin perder nutrientes.
- Si buscas **techo productivo**, mira dónde B sube dosis o cambia mezcla.

---
_Desarrollado por BData 🌾 – herramienta demo con PuLP + Streamlit_
        """.strip()

        st.download_button(
            "📥 Descargar reporte en chileno (Markdown)",
            data=resumen_txt.encode("utf-8"),
            file_name="reporte_en_chileno.md",
            mime="text/markdown",
            key="dl_chileno"
        )

        # 8) Reporte PDF en chileno (con logo opcional)
        logo_path = DATA_DIR / "logo-bdata.png"  # pon tu logo aquí; si no existe, se omite
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
            "📥 Descargar informe en chileno (PDF)",
            data=pdf_bytes,
            file_name="informe_en_chileno.pdf",
            mime="application/pdf",
            key="dl_pdf_chileno"
        )

st.caption("Desarrollado por BData 🌾 | Demo técnico con PuLP + Streamlit")
