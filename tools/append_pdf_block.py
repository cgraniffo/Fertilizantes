from pathlib import Path

BLOCK = r'''

# ===============================
# Descargas extra: CSV comparativo, Markdown breve y PDF con logo
# (se muestran si ya existen resultados A/B en data/)
# ===============================
try:
    csvA_path = DATA_DIR / "resultados_A.csv"
    csvB_path = DATA_DIR / "resultados_B.csv"
    txtA_path = DATA_DIR / "_resumen_A.txt"
    txtB_path = DATA_DIR / "_resumen_B.txt"
    if csvA_path.exists() and csvB_path.exists():
        dfA = pd.read_csv(csvA_path)
        dfB = pd.read_csv(csvB_path)
        if not dfA.empty and not dfB.empty:
            dfA["escenario"] = "A"
            dfB["escenario"] = "B"
            dfAB = pd.concat([dfA, dfB], ignore_index=True)

            costoA = costo_total_desde_txt(txtA_path)
            costoB = costo_total_desde_txt(txtB_path)
            dif_cost = costoB - costoA

            tot_por_pot = (
                dfAB.groupby(["potrero", "escenario"])["kg_ha"]
                    .sum().unstack("escenario").fillna(0)
            )
            dif_pot = (tot_por_pot.get("B", 0) - tot_por_pot.get("A", 0)).rename("dif")
            pot_mayor_sube = dif_pot.idxmax() if hasattr(dif_pot, "idxmax") and len(dif_pot)>0 else None
            pot_mayor_baja = dif_pot.idxmin() if hasattr(dif_pot, "idxmin") and len(dif_pot)>0 else None

            st.markdown("### Descargas")
            st.download_button(
                "📥 Descargar comparación A/B (CSV)",
                data=dfAB.to_csv(index=False).encode("utf-8"),
                file_name="comparacion_AB.csv",
                mime="text/csv",
                key="dl_ab_tail"
            )

            # Markdown corto en chileno
            pot_sel = dfAB["potrero"].iloc[0] if len(dfAB)>0 else "-"
            mix_pot = (
                dfAB[dfAB["potrero"] == pot_sel]
                    .pivot_table(index="producto", columns="escenario", values="kg_ha", aggfunc="sum")
                    .fillna(0)
            )
            diff_prod = (mix_pot.get("B", 0) - mix_pot.get("A", 0)) if "A" in mix_pot.columns else mix_pot.get("B", 0)
            p_up = (diff_prod.idxmax() if hasattr(diff_prod, "idxmax") and len(diff_prod)>0 else "-")
            p_dn = (diff_prod.idxmin() if hasattr(diff_prod, "idxmin") and len(diff_prod)>0 else "-")

            resumen_txt2 = f"""
# Informe – Comparación de Escenarios A y B

## Costo total
A: {formato_clp(costoA)}  
B: {formato_clp(costoB)}  
Dif (B-A): {formato_clp(dif_cost)}  

## Potreros
Mayor aumento: {pot_mayor_sube}  
Mayor baja: {pot_mayor_baja}

## Mezclas ({pot_sel})
Sube más: {p_up} (+{getattr(diff_prod,'max',lambda:0)():.1f} kg/ha)  
Baja más: {p_dn} ({getattr(diff_prod,'min',lambda:0)():.1f} kg/ha)

## Conclusión
Si B es más caro: restricciones más apretadas (N/mezcla) → productos más concentrados/caros.  
Si B es más barato: más flexibilidad (tolerancia o N máximo) → mezcla más eficiente.
""".strip()

            st.download_button(
                "📥 Descargar reporte en chileno (Markdown)",
                data=resumen_txt2.encode("utf-8"),
                file_name="reporte_en_chileno.md",
                mime="text/markdown",
                key="dl_chileno_tail"
            )

            # PDF con logo usando Pillow (sin dependencias adicionales)
            from io import BytesIO
            from PIL import Image, ImageDraw, ImageFont

            def _wrap_text(draw, font, text, maxw):
                lines = []
                for para in text.split("\n"):
                    if not para:
                        lines.append("")
                        continue
                    words = para.split()
                    line = []
                    while words:
                        line.append(words.pop(0))
                        w = draw.textlength(" ".join(line), font=font)
                        if w > maxw and len(line) > 1:
                            last = line.pop()
                            lines.append(" ".join(line))
                            line = [last]
                    if line:
                        lines.append(" ".join(line))
                return lines

            def build_pdf_bytes():
                W, H = 794, 1123
                margin = 40
                img = Image.new("RGB", (W, H), "white")
                draw = ImageDraw.Draw(img)
                font_b = ImageFont.load_default()
                font_p = ImageFont.load_default()
                y = margin

                # Logo
                logo_path = DATA_DIR / "logo.png"
                if logo_path.exists():
                    try:
                        logo = Image.open(str(logo_path)).convert("RGBA")
                        lw = min(180, logo.width)
                        lh = int(logo.height * (lw / logo.width))
                        logo = logo.resize((lw, lh))
                        img.paste(logo, (W - margin - lw, y), logo)
                    except Exception:
                        pass

                # Título
                draw.text((margin, y), "Informe – Comparación Escenarios A y B", fill="black", font=font_b)
                y += 24

                # Costos
                draw.text((margin, y), "Costo total", fill="black", font=font_b)
                y += 16
                costos = f"A: {formato_clp(costoA)}  |  B: {formato_clp(costoB)}  |  Dif: {formato_clp(dif_cost)}"
                for ln in _wrap_text(draw, font_p, costos, W-2*margin):
                    draw.text((margin, y), ln, fill="black", font=font_p)
                    y += 14

                y += 10
                # Potreros
                draw.text((margin, y), "Potreros – dónde sube/baja", fill="black", font=font_b)
                y += 16
                potline = f"Mayor aumento: {pot_mayor_sube}  |  Mayor baja: {pot_mayor_baja}"
                for ln in _wrap_text(draw, font_p, potline, W-2*margin):
                    draw.text((margin, y), ln, fill="black", font=font_p)
                    y += 14

                y += 10
                # Mezclas
                draw.text((margin, y), f"Mezclas en {pot_sel}", fill="black", font=font_b)
                y += 16
                if hasattr(diff_prod, "max") and len(diff_prod)>0:
                    mixline = f"Sube más: {diff_prod.idxmax()} (+{diff_prod.max():.1f} kg/ha)  |  Baja más: {diff_prod.idxmin()} ({diff_prod.min():.1f} kg/ha)"
                    for ln in _wrap_text(draw, font_p, mixline, W-2*margin):
                        draw.text((margin, y), ln, fill="black", font=font_p)
                        y += 14

                y += 10
                # Totales por potrero
                draw.text((margin, y), "Totales por potrero (kg/ha)", fill="black", font=font_b)
                y += 16
                try:
                    tpp = tot_por_pot.fillna(0).round(2)
                    header = f"{'Potrero':<14}  {'A':>8}  {'B':>8}"
                    draw.text((margin, y), header, fill="black", font=font_p)
                    y += 14
                    for pot in tpp.index.tolist():
                        a = tpp.loc[pot].get("A", 0.0)
                        b = tpp.loc[pot].get("B", 0.0)
                        line = f"{str(pot):<14}  {a:>8.2f}  {b:>8.2f}"
                        draw.text((margin, y), line, fill="black", font=font_p)
                        y += 14
                except Exception:
                    pass

                y += 10
                # Ojo rápido
                draw.text((margin, y), "Ojo rápido – dosis A/B", fill="black", font=font_b)
                y += 16
                try:
                    sample = (dfAB.sort_values(["kg_ha"], ascending=False).head(8))
                    for _, r in sample.iterrows():
                        line = f"{r['potrero']} - {r['producto']}: {r['kg_ha']:.1f} kg/ha ({r['escenario']})"
                        for ln in _wrap_text(draw, font_p, line, W-2*margin):
                            draw.text((margin, y), ln, fill="black", font=font_p)
                            y += 14
                except Exception:
                    pass

                y += 10
                # Conclusión
                draw.text((margin, y), "Conclusión", fill="black", font=font_b)
                y += 16
                concl = (
                    "Si B es más caro, suele ser por restricciones más apretadas (N/mezcla) y uso de productos más concentrados/caros. "
                    "Si B es más barato, probablemente hay más flexibilidad (tolerancia o N máximo), permitiendo mezclas más eficientes."
                )
                for ln in _wrap_text(draw, font_p, concl, W-2*margin):
                    draw.text((margin, y), ln, fill="black", font=font_p)
                    y += 14

                bio = BytesIO()
                img.save(bio, format="PDF")
                return bio.getvalue()

            pdf_bytes = build_pdf_bytes()
            st.download_button(
                "📄 Descargar informe (PDF con logo)",
                data=pdf_bytes,
                file_name="informe_AB.pdf",
                mime="application/pdf",
                key="dl_pdf_tail"
            )
except Exception:
    pass
'''

target = Path('app/optimizador.py')
target.write_text(target.read_text(encoding='utf-8') + BLOCK, encoding='utf-8')
print('PDF export block appended to app/optimizador.py')
