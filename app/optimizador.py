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
    page_title="Asistente de Fertilización Inteligente | Boost Data",
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
    st.session_state["already_rendered"] = False  # evita duplicados tras ejecutar

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
    st.title("Asistente de Fertilización Inteligente")
    st.markdown('<div class="bdata-claim">Planifica mezclas óptimas por potrero, cumpliendo N–P–K al menor costo.</div>', unsafe_allow_html=True)
st.markdown('<div class="bdata-divider"></div>', unsafe_allow_html=True)







# =============================
# 1️⃣ Manual rápido (en página)
# =============================

st.info("📘 Aquí tienes una guía rápida de cómo usar el asistente. No necesitas leerlo completo ahora; puedes volver cuando quieras repasar formatos o ejemplos.")

with st.expander("1️⃣ Manual rápido para el agricultor📖", expanded=False):
    st.markdown(dedent("""
    Solo necesitas leer esto si quieres entender cómo funciona el cálculo detrás.
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

    ### 📂 Archivos y formatos

    **potreros.csv** *(se genera desde el mapa)*  
    Columnas: `potrero, cultivo, superficie_ha`.

    **productos.csv**  
    Columnas: `producto, N_pct, P2O5_pct, K2O_pct, precio_CLP_ton, dosis_min_kg_ha, dosis_max_kg_ha`.

    **requerimientos.csv**  
    Columnas: `cultivo, N_req_kg_ha, P2O5_req_kg_ha, K2O_req_kg_ha`.

    --- 

    ### ⚙️ Parámetros
    - **N máx (kg/ha)**, **Mezcla máx (kg/ha)**, **Tolerancia (%)**.

    --- 

    ### 🧯 Diagnóstico rápido
    Sube tolerancia, mezcla o relaja N máx si el modelo queda infactible; revisa dosis mín/máx y que existan fuentes N/P/K.

    --- 

    ### 🧾 Salidas y reportes
    CSV + Markdown/PDF “en chileno”.
    """))

# =============================
# 2️⃣ Cargar datos de entrada
# =============================
st.info("📦 En este paso cargas tus archivos base: potreros, requerimientos y productos. Son los insumos mínimos para que el modelo calcule la mezcla.")

with st.expander("2️⃣ Cargar datos de entrada📂", expanded=False):
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
# 3️⃣ Mapa de potreros (dibujar o cargar)
# =============================
st.info("🗺️ Dibuja o carga tus potreros. El sistema calculará las superficies automáticamente y guardará el archivo listo para usar en el optimizador.")

with st.expander("3️⃣ Mapa de potreros (dibujar o cargar)🌎", expanded=False):
    import json
    import folium
    from streamlit_folium import st_folium
    from pyproj import Geod
    from shapely.geometry import shape
    GEOD = Geod(ellps="WGS84")
    POTREROS_GEOJSON = DATA_DIR / "potreros.geojson"
    POTREROS_CSV = DATA_DIR / "potreros.csv"

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
# 4️⃣ Análisis de suelo (opcional) – PASO 2
# =============================
st.info("🌾 Si tienes análisis de suelo, ingrésalos acá. El sistema ajustará automáticamente los requerimientos por potrero. Si no, puedes seguir sin este paso.")

from textwrap import dedent as _dedent
with st.expander("4️⃣ Análisis de suelo (opcional)🧪", expanded=False):
    SUELO_CSV = DATA_DIR / "analisis_suelo.csv"
    REQ_AJUSTADOS_CSV = DATA_DIR / "requerimientos_ajustados_por_potrero.csv"

    st.markdown(_dedent("""
    **¿Para qué sirve?**  
    Si ingresas el **aporte del suelo (kg/ha)** por potrero, calculamos **requerimientos ajustados**:
    `requerimiento_ajustado = max(0, requerimiento - suelo)` para **N, P₂O₅ y K₂O**.

    Esto **no cambia** aún el solver: solo guarda un CSV con los ajustes por potrero y te muestra el efecto.
    En el **PASO 3** podremos conectar esto al modelo para correr A/B con suelo incorporado.
    """))

    tiene_potreros = (DATA_DIR / "potreros.csv").exists()
    tiene_reqs     = (DATA_DIR / "requerimientos.csv").exists()

    if not (tiene_potreros and tiene_reqs):
        st.warning("Para usar esta sección, asegúrate de tener `data/potreros.csv` y `data/requerimientos.csv`.")
        st.stop()

    df_potr = read_csv_flexible(DATA_DIR / "potreros.csv")
    df_req  = read_csv_flexible(DATA_DIR / "requerimientos.csv")

    cols_potr_ok = {"potrero", "cultivo", "superficie_ha"}
    cols_req_ok  = {"cultivo", "N_req_kg_ha", "P2O5_req_kg_ha", "K2O_req_kg_ha"}
    faltan_potr = cols_potr_ok - set(df_potr.columns)
    faltan_req  = cols_req_ok - set(df_req.columns)
    if faltan_potr:
        st.error(f"`potreros.csv` no trae columnas requeridas: {sorted(faltan_potr)}")
        st.stop()
    if faltan_req:
        st.error(f"`requerimientos.csv` no trae columnas requeridas: {sorted(faltan_req)}")
        st.stop()

    base_suelo = df_potr[["potrero","cultivo","superficie_ha"]].copy()
    base_suelo["N_suelo_kg_ha"]    = 0.0
    base_suelo["P2O5_suelo_kg_ha"] = 0.0
    base_suelo["K2O_suelo_kg_ha"]  = 0.0

    if SUELO_CSV.exists():
        try:
            prev = read_csv_flexible(SUELO_CSV)
            base_suelo = base_suelo.merge(
                prev[["potrero","N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"]],
                on="potrero", how="left", suffixes=("","_prev")
            )
            for col in ["N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"]:
                if col + "_prev" in base_suelo.columns:
                    base_suelo[col] = base_suelo[col + "_prev"].fillna(base_suelo[col])
                    base_suelo.drop(columns=[col + "_prev"], inplace=True)
        except Exception as e:
            st.warning(f"No se pudo leer `analisis_suelo.csv` previo: {e}")

    st.markdown("#### 1) Cargar CSV de suelo (opcional)")
    st.caption("Formato esperado: potrero, N_suelo_kg_ha, P2O5_suelo_kg_ha, K2O_suelo_kg_ha")
    up_suelo = st.file_uploader("Subir análisis de suelo por potrero (CSV)", type=["csv"], key="suelo_csv_up")
    if up_suelo:
        try:
            df_up = pd.read_csv(up_suelo, sep=None, engine="python")
            must = {"potrero","N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"}
            if not must.issubset(set(df_up.columns)):
                st.error(f"El CSV debe incluir estas columnas: {sorted(must)}")
            else:
                base_suelo = base_suelo.drop(columns=["N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"])
                base_suelo = base_suelo.merge(
                    df_up[list(must)], on="potrero", how="left"
                )
                for col in ["N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"]:
                    base_suelo[col] = base_suelo[col].fillna(0.0)
                st.success("Análisis de suelo cargado desde CSV ✅")
        except Exception as e:
            st.error(f"Error leyendo CSV de suelo: {e}")

    st.markdown("#### 2) Editar/ingresar suelo manualmente (kg/ha)")
    st.caption("Si no tienes CSV, edita directo acá. Los valores son **kg/ha disponibles** por potrero.")
    suelo_edit = st.data_editor(
        base_suelo,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "N_suelo_kg_ha":    st.column_config.NumberColumn(step=1.0, min_value=0.0),
            "P2O5_suelo_kg_ha": st.column_config.NumberColumn(step=1.0, min_value=0.0),
            "K2O_suelo_kg_ha":  st.column_config.NumberColumn(step=1.0, min_value=0.0),
        },
        key="soil_editor",
    )

    c_s1, c_s2 = st.columns([1,1])
    with c_s1:
        if st.button("💾 Guardar análisis de suelo en data/analisis_suelo.csv"):
            try:
                cols_keep = ["potrero","N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"]
                suelo_edit[cols_keep].to_csv(SUELO_CSV, index=False, encoding="utf-8")
                st.success("Guardado `data/analisis_suelo.csv` ✅")
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")

    st.markdown("#### 3) Previsualizar requerimientos ajustados (por potrero)")
    st.caption("Regla simple: ajustado = max(0, requerimiento_por_cultivo − suelo_por_potrero)")

    req_map = df_potr.merge(df_req, on="cultivo", how="left")
    req_map = req_map.merge(
        suelo_edit[["potrero","N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha"]],
        on="potrero", how="left"
    ).fillna({"N_suelo_kg_ha":0.0,"P2O5_suelo_kg_ha":0.0,"K2O_suelo_kg_ha":0.0})

    req_map["N_req_aj_kg_ha"]    = (req_map["N_req_kg_ha"]    - req_map["N_suelo_kg_ha"]).clip(lower=0.0)
    req_map["P2O5_req_aj_kg_ha"] = (req_map["P2O5_req_kg_ha"] - req_map["P2O5_suelo_kg_ha"]).clip(lower=0.0)
    req_map["K2O_req_aj_kg_ha"]  = (req_map["K2O_req_kg_ha"]  - req_map["K2O_suelo_kg_ha"]).clip(lower=0.0)

    vista = req_map[[
        "potrero","cultivo","superficie_ha",
        "N_req_kg_ha","P2O5_req_kg_ha","K2O_req_kg_ha",
        "N_suelo_kg_ha","P2O5_suelo_kg_ha","K2O_suelo_kg_ha",
        "N_req_aj_kg_ha","P2O5_req_aj_kg_ha","K2O_req_aj_kg_ha",
    ]].copy()

    st.dataframe(vista, use_container_width=True)

    st.markdown("##### Guardar salida de requerimientos ajustados por potrero")
    st.caption("Este archivo es solo **por potrero**. En el PASO 3 lo conectaremos al solver.")
    if st.button("📥 Guardar `data/requerimientos_ajustados_por_potrero.csv`"):
        try:
            out_cols = ["potrero","cultivo","superficie_ha",
                        "N_req_aj_kg_ha","P2O5_req_aj_kg_ha","K2O_req_aj_kg_ha"]
            vista[out_cols].to_csv(REQ_AJUSTADOS_CSV, index=False, encoding="utf-8")
            st.success("Escrito `data/requerimientos_ajustados_por_potrero.csv` ✅")
        except Exception as e:
            st.error(f"No se pudo escribir la salida: {e}")

    st.info(_dedent("""
    **Notas prácticas**
    - Los valores de suelo son **kg/ha disponibles** (no ppm). Si tienes ppm, conviértelo antes (PASO 2 simple).
    - En el PASO 3 agregaremos conversiones desde ppm por método (Olsen/Bray, profundidad, densidad aparente, %eficiencia).
    - Si un potrero queda con requerimiento 0 en un nutriente, el modelo (cuando lo conectemos) no debería forzar ese nutriente.
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
# UX: Progreso "fantasma" por pasos (solo informativo)
# =============================
from pathlib import Path as _Path2  # alias para no chocar con otros imports

def _files_ok() -> dict:
    """Chequeo rápido de archivos base en data/."""
    paths = {
        "potreros": DATA_DIR / "potreros.csv",
        "requerimientos": DATA_DIR / "requerimientos.csv",
        "productos": DATA_DIR / "productos.csv",
        "suelo": DATA_DIR / "analisis_suelo.csv",
    }
    return {k: p.exists() for k, p in paths.items()}

def compute_progress(ctx: dict) -> tuple[int, int, list[str]]:
    """
    Devuelve (hechos, total_obligatorios, etiquetas_hechas) para la barrita de progreso.
    Contamos pasos obligatorios: 2 (carga 3 CSV), 3 (mapa/potreros.csv), 6 (parametrización lista),
    7 (ejecutado al menos un escenario).
    """
    files = _files_ok()
    hechos = []
    total = 4  # 2,3,6,7

    # Paso 2: Cargar datos (potreros, requerimientos y productos)
    if files["potreros"] and files["requerimientos"] and files["productos"]:
        hechos.append("2")

    # Paso 3: Mapa / existencia de potreros.csv
    if files["potreros"]:
        hechos.append("3")

    # Paso 6: Parámetros (los consideramos listos: hay defaults en la UI)
    hechos.append("6")

    # Paso 7: Ejecutar A/B (con que uno resulte)
    if bool(ctx.get("okA")) or bool(ctx.get("okB")):
        hechos.append("7")

    return len(set(hechos)), total, hechos


# Barra de progreso del flujo (no bloqueante)
#ctx_last = st.session_state.get("last_run", {}) or {}
#done, total, _labels = compute_progress(ctx_last)
#pct = int(round(100 * done / total)) if total else 0
#st.progress(pct, text=f"Progreso del flujo: {done} de {total} pasos obligatorios completados ✅")

#st.markdown("### 🧠 Flujo recomendado de trabajo")
# =============================
# FLUJO GUIADO PASO A PASO
# =============================


# Luego vienen los textos del flujo (1️⃣, 2️⃣, 3️⃣, etc)

#st.markdown("""
#🔵1️⃣ **Manual rápido 📖:** conoce los pasos y formatos.  
#🔵2️⃣ **Carga datos de entrada 📂:** potreros, requerimientos y productos.  
#🔵3️⃣ **Mapa de potreros 🌎.**  
#🔘4️⃣ **Análisis de suelo (opcional) 🧪.**  
#🔘5️⃣ **Configuración del análisis de suelo ⚙️.**  
#🔵6️⃣ **Parámetros de optimización 💻.**  
#🔵7️⃣ **Ejecutar escenarios 🚜.**  
#🔵8️⃣ **Exportar reportes 📊.**
#""")
# =============================
# Suelo: funciones base (NO modifican el flujo actual)
# =============================
from dataclasses import dataclass
import math

@dataclass
class SoilCreditParams:
    bd_g_cm3: float = 1.3
    depth_cm: float = 20.0
    use_ppm: bool = True
    fN: float = 0.4
    fP2O5: float = 0.4
    fK2O: float = 0.6

def _ppm_to_kg_ha(ppm: float, bd_g_cm3: float = 1.3, depth_cm: float = 20.0) -> float:
    if ppm is None or (isinstance(ppm, float) and math.isnan(ppm)):
        return 0.0
    return float(ppm) * bd_g_cm3 * depth_cm * 0.1

def _element_to_oxide_P(P_kg_ha: float) -> float:
    return float(P_kg_ha) * 2.29

def _element_to_oxide_K(K_kg_ha: float) -> float:
    return float(K_kg_ha) * 1.2

def normalize_soil_inputs(soil_row: dict, params: SoilCreditParams) -> dict:
    direct_N = soil_row.get("N_kg_ha")
    direct_P2O5 = soil_row.get("P2O5_kg_ha")
    direct_K2O = soil_row.get("K2O_kg_ha")
    if direct_N is not None or direct_P2O5 is not None or direct_K2O is not None:
        return {
            "N_credito_kg_ha": float(direct_N or 0.0),
            "P2O5_credito_kg_ha": float(direct_P2O5 or 0.0),
            "K2O_credito_kg_ha": float(direct_K2O or 0.0),
        }
    N_ppm = soil_row.get("NO3_ppm")
    if N_ppm is None:
        N_ppm = soil_row.get("N_ppm")
    P_ppm = soil_row.get("P_ppm")
    K_ppm = soil_row.get("K_ppm")

    N_kg_ha = _ppm_to_kg_ha(N_ppm or 0.0, params.bd_g_cm3, params.depth_cm) if params.use_ppm else float(N_ppm or 0.0)
    P_kg_ha = _ppm_to_kg_ha(P_ppm or 0.0, params.bd_g_cm3, params.depth_cm) if params.use_ppm else float(P_ppm or 0.0)
    K_kg_ha = _ppm_to_kg_ha(K_ppm or 0.0, params.bd_g_cm3, params.depth_cm) if params.use_ppm else float(K_ppm or 0.0)

    P2O5_kg_ha = _element_to_oxide_P(P_kg_ha)
    K2O_kg_ha  = _element_to_oxide_K(K_kg_ha)

    return {
        "N_credito_kg_ha": N_kg_ha,
        "P2O5_credito_kg_ha": P2O5_kg_ha,
        "K2O_credito_kg_ha": K2O_kg_ha,
    }

def apply_soil_credits_to_requirements(req_df: pd.DataFrame, soil_df_or_dict, params: SoilCreditParams) -> pd.DataFrame:
    out = req_df.copy()

    def _descontar(row, creditos):
        N_adj = max(0.0, float(row["N_req_kg_ha"])    - params.fN    * creditos["N_credito_kg_ha"])
        P_adj = max(0.0, float(row["P2O5_req_kg_ha"]) - params.fP2O5 * creditos["P2O5_credito_kg_ha"])
        K_adj = max(0.0, float(row["K2O_req_kg_ha"])  - params.fK2O  * creditos["K2O_credito_kg_ha"])
        return pd.Series({
            "N_req_aj_kg_ha": N_adj,
            "P2O5_req_aj_kg_ha": P_adj,
            "K2O_req_aj_kg_ha": K_adj
        })

    if isinstance(soil_df_or_dict, dict):
        cred_global = normalize_soil_inputs(soil_df_or_dict, params)
        aj = out.apply(lambda r: _descontar(r, cred_global), axis=1)
        for c in aj.columns:
            out[c] = aj[c]
        return out

    if isinstance(soil_df_or_dict, pd.DataFrame):
        if "potrero" not in out.columns:
            row_avg = {}
            for k in ["NO3_ppm","N_ppm","P_ppm","K_ppm","N_kg_ha","P2O5_kg_ha","K2O_kg_ha"]:
                if k in soil_df_or_dict.columns:
                    row_avg[k] = float(soil_df_or_dict[k].dropna().mean())
            cred = normalize_soil_inputs(row_avg, params)
            aj = out.apply(lambda r: _descontar(r, cred), axis=1)
            for c in aj.columns:
                out[c] = aj[c]
            return out
        else:
            soil_min = soil_df_or_dict.copy()
            keep_cols = [c for c in soil_min.columns if c in
                         ["potrero","NO3_ppm","N_ppm","P_ppm","K_ppm","N_kg_ha","P2O5_kg_ha","K2O_kg_ha"]]
            soil_min = soil_min[keep_cols]
            out = out.merge(soil_min, on="potrero", how="left")
            def _row_apply(r):
                soil_row = {k: r.get(k) for k in keep_cols if k != "potrero"}
                cred = normalize_soil_inputs(soil_row, params)
                return _descontar(r, cred)
            aj = out.apply(_row_apply, axis=1)
            for c in aj.columns:
                out[c] = aj[c]
            return out
    return out

def choose_requirements_for_solver(req_df: pd.DataFrame, use_adjusted: bool = True) -> pd.DataFrame:
    out = req_df.copy()
    def _pick(base, aj):
        return out[aj] if aj in out.columns else out[base]
    out["N_req_final_kg_ha"]    = _pick("N_req_kg_ha",    "N_req_aj_kg_ha")
    out["P2O5_req_final_kg_ha"] = _pick("P2O5_req_kg_ha", "P2O5_req_aj_kg_ha")
    out["K2O_req_final_kg_ha"]  = _pick("K2O_req_kg_ha",  "K2O_req_aj_kg_ha")
    return out

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
# 🔁 Toggle: usar análisis de suelo en el solver
# =============================
st.info("⚙️ Aquí decides si el optimizador debe usar los aportes del suelo. Puedes activar o desactivar este ajuste antes de ejecutar los escenarios.")

with st.expander("5️⃣ Configuración del análisis de suelo en el solver ⚙", expanded=False):
    st.markdown("""
    Puedes decidir si el **optimizador** usará los requerimientos ajustados según tu análisis de suelo.
    Si está activado, el modelo tomará el archivo:
    - `data/requerimientos_ajustados_por_potrero.csv` (si existe),
    en lugar de `data/requerimientos.csv`.

    Si no existe el archivo ajustado, usará el normal automáticamente.
    """)

    use_soil = st.checkbox(" Usar análisis de suelo en el solver", value=True, key="use_soil_toggle")

    # Detectar archivo que se usará realmente
    req_aj_path = DATA_DIR / "requerimientos_ajustados_por_potrero.csv"
    req_base_path = DATA_DIR / "requerimientos.csv"

    if use_soil and req_aj_path.exists():
        st.success("El solver usará requerimientos **ajustados por potrero** ✅")
        solver_req_path = req_aj_path
    else:
        st.info("El solver usará los requerimientos **base (sin ajuste)**.")
        solver_req_path = req_base_path

    # Guardar en sesión para el paso del solver
    st.session_state["solver_req_path"] = str(solver_req_path)


# =============================
# 5️⃣ Parámetros de optimización (Escenario A y B)
# =============================
st.info("📊 Define los límites de mezcla y nitrógeno para tus escenarios A y B. Puedes probar combinaciones distintas y comparar costos más adelante.")

with st.expander("6️⃣ Parámetros de optimización (Escenario A y B)⚙️", expanded=False):
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
# Ejecutar solver
# =============================
def run_solver(nmax: int, mixmax: int, tol_pct: float, costo_ap_ton: int, tag: str, req_path: Optional[Path] = None):
    csv_path = DATA_DIR / f"resultados_dosis_{tag}.csv"
    txt_path = DATA_DIR / f"_resumen_{tag}.txt"
    for p in (csv_path, txt_path):
        if p.exists():
            try: p.unlink()
            except Exception: pass

    # --- armar args base
    args = [
        sys.executable, str(SOLVER_PATH),
        "--nmax",   str(nmax),
        "--mixmax", str(mixmax),
        "--tol",    str(tol_pct/100.0),
        "--costoap",str(costo_ap_ton),
        "--tag",    tag,
    ]
    # --- si tenemos ruta de requerimientos, la pasamos
    if req_path is not None:
        args += ["--reqpath", str(req_path)]

    proc = subprocess.run(args, capture_output=True, text=True)
    ok = (proc.returncode == 0) and csv_path.exists() and txt_path.exists()
    return proc, csv_path, txt_path, ok


# =============================
# 6️⃣ Ejecutar escenarios A y B
# =============================
st.info("🚜 Aquí el sistema hace su magia: calcula las mezclas óptimas, muestra costos y genera el resumen agronómico. Solo presiona ejecutar y observa los resultados.")

with st.expander("7️⃣ Ejecutar escenarios A y B 🚜", expanded=False):
    if st.button("🚜 Ejecutar escenarios A y B", key="run_ab"):
        st.session_state["already_rendered"] = True
        # 👉 NUEVO: lee la ruta decidida por el toggle (o usa base si no está)
        req_path = Path(st.session_state.get("solver_req_path", str(DATA_DIR / "requerimientos.csv")))

        with st.spinner("Ejecutando optimizaciones A y B..."):
            # 👉 NUEVO: pasa req_path a ambos escenarios
            resA, csvA, txtA, okA = run_solver(nA, mixA, tolA, 0, "A", req_path=req_path)
            resB, csvB, txtB, okB = run_solver(nB, mixB, tolB, 0, "B", req_path=req_path)


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

        costoA = costo_total_desde_txt(txtA) if okA else None
        costoB = costo_total_desde_txt(txtB) if okB else None

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

        st.session_state["last_run"] = {
            "okA": okA, "okB": okB,
            "csvA": str(csvA) if okA else None,
            "txtA": str(txtA) if okA else None,
            "csvB": str(csvB) if okB else None,
            "txtB": str(txtB) if okB else None,
            "costoA": costoA if okA else None,
            "costoB": costoB if okB else None,
            "mixA": st.session_state["mixA"], "mixB": st.session_state["mixB"],
            "nA": st.session_state["nA"], "nB": st.session_state["nB"],
            "tolA": st.session_state["tolA"], "tolB": st.session_state["tolB"],
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
        if okA: resumen_agronomico("A", csvA, st.session_state["mixA"])
        if okB: resumen_agronomico("B", csvB, st.session_state["mixB"])

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

            st.download_button(
                "📥 Descargar comparación A/B (CSV)",
                data=pd.concat([dfA, dfB]).to_csv(index=False).encode("utf-8"),
                file_name="comparacion_AB.csv",
                mime="text/csv",
                key="dl_ab",
            )

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
# Render persistente (último resultado) — igual que antes
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

# =============================
# 7️⃣ Exportar reportes (todo junto)
# =============================
st.info("🧾 Descarga tus resultados en formatos CSV, Markdown o PDF. El informe **en chileno** explica todo en lenguaje simple y directo para tus registros o presentaciones.")

with st.expander("8️⃣ Exportar reportes", expanded=False):
    ctx = st.session_state.get("last_run", {}) or {}
    okA_ = bool(ctx.get("okA")); okB_ = bool(ctx.get("okB"))
    csvA_path = Path(ctx["csvA"]) if okA_ and ctx.get("csvA") else None
    csvB_path = Path(ctx["csvB"]) if okB_ and ctx.get("csvB") else None
    costoA_ = ctx.get("costoA"); costoB_ = ctx.get("costoB")

    if not (okA_ and okB_ and csvA_path and csvB_path and csvA_path.exists() and csvB_path.exists()):
        st.info("Corre ambos escenarios (A y B) para habilitar las exportaciones.")
    else:
        # Cargar datos desde disco para no depender del render previo
        dfA_ = pd.read_csv(csvA_path); dfA_["escenario"] = "A"
        dfB_ = pd.read_csv(csvB_path); dfB_["escenario"] = "B"
        dfAB_ = pd.concat([dfA_, dfB_], ignore_index=True)

        # Selector de potrero para los informes
        potreros_disp = sorted(dfAB_["potrero"].unique())
        pot_sel7 = st.selectbox("Potrero a destacar en el informe:", potreros_disp, key="pot_sel_export")

        # Totales y diferencias por potrero
        tot_por_pot_7 = (dfAB_.groupby(["potrero","escenario"])["kg_ha"]
                            .sum().unstack("escenario").fillna(0).sort_index())
        dif_pot_7 = (tot_por_pot_7.get("B",0) - tot_por_pot_7.get("A",0)).rename("dif")

        # Diferencias por producto en potrero elegido
        mix_pot_7 = (dfAB_[dfAB_["potrero"] == pot_sel7]
                        .pivot_table(index="producto", columns="escenario", values="kg_ha", aggfunc="sum")
                        .fillna(0).sort_index())
        diff_prod_7 = (mix_pot_7.get("B",0) - mix_pot_7.get("A",0)).rename("Diferencia (kg/ha)")

        # Botón 1: CSV comparación A/B
        st.download_button(
            "📥 Descargar comparación A/B (CSV)",
            data=dfAB_.to_csv(index=False).encode("utf-8"),
            file_name="comparacion_AB.csv",
            mime="text/csv",
            key="dl_ab_step7",
        )

        # Preparar textos comunes (robustos si faltan costos)
        if isinstance(costoA_, (int,float)) and isinstance(costoB_, (int,float)):
            dif_cost_7 = costoB_ - costoA_
            costoA_txt = formato_clp(costoA_)
            costoB_txt = formato_clp(costoB_)
            dif_cost_txt = formato_clp(dif_cost_7)
            caridad = 'B más caro 💸' if dif_cost_7>0 else 'B más barato 💰' if dif_cost_7<0 else 'igual 🤝'
        else:
            dif_cost_7 = 0
            costoA_txt = "s/d"
            costoB_txt = "s/d"
            dif_cost_txt = "s/d"
            caridad = "—"

        sube_txt_7 = f"{dif_pot_7.idxmax()} (+{dif_pot_7.max():.1f} kg/ha)" if len(dif_pot_7) else "—"
        baja_txt_7 = f"{dif_pot_7.idxmin()} ({dif_pot_7.min():.1f} kg/ha)" if len(dif_pot_7) else "—"
        p_up_7 = diff_prod_7.idxmax() if len(diff_prod_7)>0 else "—"
        p_dn_7 = diff_prod_7.idxmin() if len(diff_prod_7)>0 else "—"

        # Botón 2: Reporte en chileno (Markdown)
        resumen_txt_7 = f"""
# 🧾 Informe – Comparación A y B

## 💰 Costo total
A: **{costoA_txt}** · B: **{costoB_txt}** · Diferencia: **{dif_cost_txt}** → {caridad}.

## 🌾 Potreros
Mayor aumento: **{sube_txt_7}** · Mayor baja: **{baja_txt_7}**.

## 🧪 Mezclas y productos
En **{pot_sel7}**: sube más **{p_up_7 if len(diff_prod_7)>0 else '—'}**, baja más **{p_dn_7 if len(diff_prod_7)>0 else '—'}**.

## 🧠 Interpretación
Si B cuesta más, apretaste límites (N máx o mezcla) y el modelo usa productos más concentrados.
Si B es más barato, diste holgura (tolerancia/N máx) y encontró una mezcla más eficiente.

_Desarrollado por BData 🌾 – PuLP + Streamlit_
        """.strip()

        st.download_button(
            "📥 Descargar reporte en chileno (Markdown)",
            data=resumen_txt_7.encode("utf-8"),
            file_name="reporte_en_chileno.md",
            mime="text/markdown",
            key="dl_md_step7",
        )

        # Botón 3: Reporte PDF (usa la misma función ya definida)
        logo_path7 = DATA_DIR / "logo-bdata.png"
        pdf_bytes7 = build_pdf_reporte_chileno(
            logo_path=logo_path7 if logo_path7.exists() else None,
            costoA=(costoA_ or 0), costoB=(costoB_ or 0), dif_cost=(dif_cost_7 or 0),
            tot_por_pot=tot_por_pot_7,
            pot_mayor_sube=(dif_pot_7.idxmax() if len(dif_pot_7) else None),
            pot_mayor_baja=(dif_pot_7.idxmin() if len(dif_pot_7) else None),
            pot_sel=pot_sel7, diff_prod=diff_prod_7,
            dfAB_head=dfAB_.head(10).copy(),
        )
        st.download_button(
            "📥 Descargar informe fertilización BData (PDF)",
            data=pdf_bytes7,
            file_name="informe_fertilizacion_BData.pdf",
            mime="application/pdf",
            key="dl_pdf_step7",
        )

# Pie
st.caption("Desarrollado por BData 🌾 | Digitalizando el campo Chileno")
