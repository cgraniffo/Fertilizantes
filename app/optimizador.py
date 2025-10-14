# app/optimizador.py
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

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
DATA_DIR = BASE_DIR / "data"
SOLVER_PATH = BASE_DIR / "optim" / "solver.py"

st.set_page_config(page_title="Optimizador de Fertilización", layout="wide")
st.title("🌱 Optimizador de Fertilización")
st.write("Sube tus archivos o usa los de ejemplo para calcular el plan más económico.")


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
def run_solver(nmax: int, mixmax: int, tol_pct: float, costoap: int, label: str):
    """Ejecuta solver.py con parámetros y archivos de salida etiquetados."""
    out_csv = DATA_DIR / f"resultados_{label}.csv"
    out_txt = DATA_DIR / f"_resumen_{label}.txt"
    result = subprocess.run([
        sys.executable, str(SOLVER_PATH),
        "--nmax", str(nmax),
        "--mixmax", str(mixmax),
        "--tol", str(tol_pct / 100.0),
        "--costoap", str(costoap),
        "--out_csv", str(out_csv),
        "--out_txt", str(out_txt)
    ], capture_output=True, text=True)
    return result, out_csv, out_txt


# =============================
# Botón: ejecutar A/B (con textos)
# =============================
if st.button("🚜 Ejecutar escenarios A y B", key="run_ab"):
    with st.spinner("Ejecutando optimizaciones A y B..."):
        resA, csvA, txtA = run_solver(nA, mixA, tolA, 0, "A")
        resB, csvB, txtB = run_solver(nB, mixB, tolB, 0, "B")
    st.success("Optimización completada ✅")

    costoA = costo_total_desde_txt(txtA)
    costoB = costo_total_desde_txt(txtB)
    dif_cost = costoB - costoA

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Costo A", formato_clp(costoA))
    with c2:
        st.metric("Costo B", formato_clp(costoB))
    with c3:
        st.metric("Diferencia (B - A)", formato_clp(dif_cost))

    st.markdown(
        f"""
**¿Qué significa esto?**  
- **Escenario A** te sale **{formato_clp(costoA)}** y **Escenario B** **{formato_clp(costoB)}**.  
- La diferencia es **{formato_clp(dif_cost)}** — {'sube' if dif_cost>0 else 'baja' if dif_cost<0 else 'no cambia'} con B.  
Si es **positivo**, B es **más caro**; si es **negativo**, B es **más barato**.
        """
    )

    if csvA.exists() and csvB.exists():
        dfA = pd.read_csv(csvA)
        dfB = pd.read_csv(csvB)
        dfA["escenario"] = "A"
        dfB["escenario"] = "B"
        dfAB = pd.concat([dfA, dfB], ignore_index=True)

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
# 🧾 Informe en Chileno – Comparación de Escenarios A y B

## 💰 Costo total
En plata, el escenario A te sale **{formato_clp(costoA)}**,
mientras que el escenario B te sale **{formato_clp(costoB)}**.
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
Si el escenario B te salió más caro, probablemente apretaste una **restricción**
(por ejemplo **menos N máximo** o **menos mezcla por pasada**).
El modelo entonces se ve obligado a usar **productos más concentrados o caros**.

Si B es más barato, quizá diste más **holgura** (tolerancia mayor, N máximo más alto)
y encontró una **mezcla más eficiente**.

En simple:
- Si buscai **eficiencia económica**, fíjate dónde B gasta menos sin perder nutrientes.
- Si buscai **techo productivo**, mira dónde B sube dosis o cambia mezcla.

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
