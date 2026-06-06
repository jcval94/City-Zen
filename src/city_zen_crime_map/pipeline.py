from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd

LAT_COL = "latitud"
LON_COL = "longitud"
CP_COL_GEOJSON = "d_codigo"
DEFAULT_DATE_CANDIDATES = (
    "fecha_hechos",
    "FechaHechos",
    "fecha_inicio",
    "FechaInicio",
    "ao_hechos",
)
DEFAULT_CATEGORY_CANDIDATES = (
    "categoria_delito",
    "CategoriaDelito",
    "delito",
    "Delito",
    "tipo_delito",
    "TipoDelito",
)
CDMX_BBOX = {
    "lat_min": 19.00,
    "lat_max": 19.75,
    "lon_min": -99.45,
    "lon_max": -98.80,
}
INCIDENT_RULES: tuple[tuple[str, str], ...] = (
    ("Homicidio", r"\b(homicidio|feminicidio)\b"),
    ("Lesiones", r"\b(lesion|lesiones)\b"),
    ("Robo a transeúnte", r"\b(robo).*\b(transeunte|transeúnte|peaton|peatón|via publica|vía pública)\b"),
    ("Robo de vehículo", r"\b(robo).*\b(vehiculo|vehículo|automovil|automóvil|motocicleta|auto|moto)\b"),
    ("Robo a negocio", r"\b(robo).*\b(negocio|comercio|tienda|establecimiento)\b"),
    ("Robo a casa habitación", r"\b(robo).*\b(casa habitacion|casa habitación|domicilio|vivienda)\b"),
    ("Robo en transporte", r"\b(robo).*\b(transporte|metro|microbus|microbús|taxi|combi|autobus|autobús)\b"),
    ("Violencia familiar", r"\b(violencia familiar|violencia intrafamiliar)\b"),
    ("Delitos sexuales", r"\b(violacion|violación|abuso sexual|acoso sexual|hostigamiento sexual)\b"),
    ("Narcomenudeo", r"\b(narcomenudeo|posesion de droga|posesión de droga|contra la salud)\b"),
    ("Fraude y extorsión", r"\b(fraude|extorsion|extorsión)\b"),
    ("Daño a la propiedad", r"\b(daño|danio|daños|danios).*\b(propiedad|bien|bienes)\b"),
    ("Amenazas", r"\b(amenaza|amenazas)\b"),
    ("Secuestro", r"\b(secuestro|privacion de la libertad|privación de la libertad)\b"),
)


@dataclass(frozen=True)
class BuildResult:
    html_path: Path
    aggregated_path: Path
    assigned_path: Path | None
    missing_path: Path | None
    months: list[str]
    incident_types: list[str]


def _normalize_cp(series: pd.Series) -> pd.Series:
    return series.astype(str).str.extract(r"(\d{5})", expand=False).str.zfill(5)


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def refine_incident_type(row: pd.Series, candidates: Iterable[str] = DEFAULT_CATEGORY_CANDIDATES) -> str:
    """Map raw FGJ incident labels into stable dashboard buckets."""
    pieces = [_clean_text(row[col]) for col in candidates if col in row.index]
    raw = " | ".join(piece for piece in pieces if piece)
    if not raw:
        return "Sin tipificar"
    for label, pattern in INCIDENT_RULES:
        if re.search(pattern, raw, flags=re.IGNORECASE):
            return label
    if "robo" in raw:
        return "Otros robos"
    return "Otros incidentes"


def load_postal_polygons(path_geojson: str | Path, cp_col: str = CP_COL_GEOJSON) -> gpd.GeoDataFrame:
    gdf_cp = gpd.read_file(path_geojson)
    if cp_col not in gdf_cp.columns:
        raise ValueError(f"No existe la columna '{cp_col}'. Columnas disponibles: {list(gdf_cp.columns)}")
    gdf_cp["cp"] = _normalize_cp(gdf_cp[cp_col])
    gdf_cp = gdf_cp[
        gdf_cp["cp"].notna()
        & gdf_cp["cp"].str.match(r"^\d{5}$", na=False)
        & gdf_cp.geometry.notna()
    ].copy()
    if gdf_cp.crs is None:
        gdf_cp = gdf_cp.set_crs("EPSG:4326")
    gdf_cp = gdf_cp.to_crs("EPSG:4326")
    gdf_cp["geometry"] = gdf_cp.geometry.buffer(0)
    gdf_cp = gdf_cp[["cp", "geometry"]].dissolve(by="cp", as_index=False)
    return gdf_cp.set_crs("EPSG:4326", allow_override=True)


def prepare_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[LAT_COL] = pd.to_numeric(df[LAT_COL], errors="coerce")
    df[LON_COL] = pd.to_numeric(df[LON_COL], errors="coerce")
    df["coord_status"] = "OK"
    df.loc[df[LAT_COL].isna() | df[LON_COL].isna(), "coord_status"] = "NULL_COORDS"
    df.loc[(df[LAT_COL] == 0) & (df[LON_COL] == 0), "coord_status"] = "ZERO_ZERO"
    mask_not_null = df[LAT_COL].notna() & df[LON_COL].notna()
    mask_not_zero = ~((df[LAT_COL] == 0) & (df[LON_COL] == 0))
    mask_outside = (
        mask_not_null
        & mask_not_zero
        & (
            ~df[LAT_COL].between(CDMX_BBOX["lat_min"], CDMX_BBOX["lat_max"])
            | ~df[LON_COL].between(CDMX_BBOX["lon_min"], CDMX_BBOX["lon_max"])
        )
    )
    df.loc[mask_outside, "coord_status"] = "OUTSIDE_CDMX_BBOX"
    df["coords_validas_cdmx"] = df["coord_status"].eq("OK")
    return df


def assign_cp_to_dataframe(df: pd.DataFrame, gdf_cp: gpd.GeoDataFrame, existing_cp_col: str | None = None) -> pd.DataFrame:
    df = prepare_coordinates(df)
    if existing_cp_col and existing_cp_col in df.columns:
        df["cp"] = _normalize_cp(df[existing_cp_col])
        df["cp_match_method"] = df["cp"].notna().map({True: "existing_cp", False: None})
    else:
        df["cp"] = pd.NA
        df["cp_match_method"] = None

    needs_spatial = df["coords_validas_cdmx"] & df["cp"].isna()
    df_valid = df[needs_spatial].copy()
    if df_valid.empty:
        df.loc[df["cp"].isna(), "cp_match_method"] = df.loc[df["cp"].isna(), "coord_status"]
        return df

    gdf_points = gpd.GeoDataFrame(
        df_valid,
        geometry=gpd.points_from_xy(df_valid[LON_COL], df_valid[LAT_COL]),
        crs="EPSG:4326",
    )
    gdf_cp = gdf_cp.to_crs("EPSG:4326")
    joined = gpd.sjoin(gdf_points, gdf_cp[["cp", "geometry"]], how="left", predicate="within", rsuffix="poly")
    right_cp_col = "cp_poly" if "cp_poly" in joined.columns else "cp_right"
    if right_cp_col in joined.columns:
        joined["cp_spatial"] = joined[right_cp_col]
    else:
        joined["cp_spatial"] = joined["cp"]
    joined["method_spatial"] = joined["cp_spatial"].notna().map({True: "within", False: None})
    missing_idx = joined[joined["cp_spatial"].isna()].index.unique()
    if len(missing_idx) > 0:
        joined_intersects = gpd.sjoin(
            gdf_points.loc[missing_idx],
            gdf_cp[["cp", "geometry"]],
            how="left",
            predicate="intersects",
            rsuffix="poly",
        )
        joined_intersects = joined_intersects[~joined_intersects.index.duplicated(keep="first")]
        inter_cp_col = "cp_poly" if "cp_poly" in joined_intersects.columns else "cp_right"
        if inter_cp_col not in joined_intersects.columns:
            inter_cp_col = "cp"
        for idx, cp_val in joined_intersects[inter_cp_col].items():
            if pd.notna(cp_val):
                joined.loc[idx, "cp_spatial"] = cp_val
                joined.loc[idx, "method_spatial"] = "intersects"

    for idx, row in joined.iterrows():
        if pd.notna(row["cp_spatial"]):
            df.loc[idx, "cp"] = row["cp_spatial"]
            df.loc[idx, "cp_match_method"] = row["method_spatial"]
    df.loc[df["cp"].isna(), "cp_match_method"] = df.loc[df["cp"].isna(), "coord_status"]
    return df


def resolve_date_column(df: pd.DataFrame, preferred: str | None = None) -> str:
    candidates = [preferred] if preferred else []
    candidates += [c for c in DEFAULT_DATE_CANDIDATES if c not in candidates]
    for col in candidates:
        if col and col in df.columns:
            return col
    raise ValueError(f"No encontré columna de fecha. Candidatas: {DEFAULT_DATE_CANDIDATES}. Columnas: {list(df.columns)}")


def filter_recent_months(df: pd.DataFrame, date_col: str, months: int = 6) -> pd.DataFrame:
    df = df.copy()
    df["fecha_evento"] = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False)
    df = df[df["fecha_evento"].notna()].copy()
    if df.empty:
        raise ValueError("No hay fechas válidas después de parsear la columna seleccionada.")
    df["month"] = df["fecha_evento"].dt.to_period("M").astype(str)
    latest_months = sorted(df["month"].dropna().unique())[-months:]
    return df[df["month"].isin(latest_months)].copy()


def aggregate_events(df: pd.DataFrame, gdf_cp: gpd.GeoDataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    working = df[df["cp"].notna()].copy()
    working["cp"] = _normalize_cp(working["cp"])
    working["incident_type"] = working.apply(refine_incident_type, axis=1)
    months = sorted(working["month"].unique())
    incident_types = ["Todos"] + sorted(working["incident_type"].dropna().unique())
    rows = []
    cp_list = sorted(set(gdf_cp["cp"]) | set(working["cp"]))
    for month in months:
        month_df = working[working["month"] == month]
        for incident_type in incident_types:
            type_df = month_df if incident_type == "Todos" else month_df[month_df["incident_type"] == incident_type]
            total = len(type_df)
            counts = type_df.groupby("cp").size().to_dict()
            for cp in cp_list:
                count = int(counts.get(cp, 0))
                rows.append({
                    "month": month,
                    "incident_type": incident_type,
                    "cp": cp,
                    "count": count,
                    "pct_total": round((count / total * 100), 4) if total else 0.0,
                })
    return pd.DataFrame(rows), months, incident_types


def _geojson_for_dashboard(gdf_cp: gpd.GeoDataFrame, cp_values: Iterable[str]) -> dict:
    gdf = gdf_cp[gdf_cp["cp"].isin(set(cp_values))].copy().to_crs("EPSG:4326")
    gdf["geometry"] = gdf.geometry.simplify(0.00015, preserve_topology=True)
    return json.loads(gdf[["cp", "geometry"]].to_json())


def _html_template(geojson: dict, records: list[dict], months: list[str], incident_types: list[str], title: str) -> str:
    payload = {
        "geojson": geojson,
        "records": records,
        "months": months,
        "incidentTypes": incident_types,
        "title": title,
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang=\"es\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" crossorigin=\"\" />
  <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\" crossorigin=\"\"></script>
  <style>
    :root {{ --bg:#0f172a; --panel:#111827; --muted:#94a3b8; --text:#e5e7eb; --accent:#38bdf8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:var(--bg); color:var(--text); }}
    .shell {{ display:grid; grid-template-columns: 360px 1fr; min-height:100vh; }}
    aside {{ padding:22px; background:linear-gradient(180deg,#111827,#0b1220); border-right:1px solid rgba(148,163,184,.2); }}
    h1 {{ margin:0 0 8px; font-size:24px; line-height:1.15; }}
    p {{ color:var(--muted); line-height:1.45; }}
    label {{ display:block; margin:18px 0 8px; font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:#cbd5e1; }}
    select, input[type=range] {{ width:100%; }}
    select {{ background:#020617; color:var(--text); border:1px solid rgba(148,163,184,.35); border-radius:10px; padding:10px; }}
    button {{ cursor:pointer; border:0; border-radius:999px; padding:10px 16px; margin-right:8px; font-weight:800; color:#00111d; background:var(--accent); }}
    button.secondary {{ color:var(--text); background:#334155; }}
    #map {{ width:100%; height:100vh; }}
    .metric-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:18px 0; }}
    .metric {{ background:rgba(15,23,42,.9); border:1px solid rgba(148,163,184,.22); border-radius:16px; padding:14px; }}
    .metric strong {{ display:block; font-size:26px; color:white; }}
    .metric span {{ color:var(--muted); font-size:12px; }}
    .month {{ font-size:34px; font-weight:900; margin:8px 0; }}
    .legend {{ position:absolute; right:20px; bottom:24px; z-index:700; background:rgba(2,6,23,.9); padding:12px; border-radius:14px; border:1px solid rgba(148,163,184,.25); color:#e2e8f0; }}
    .legend i {{ display:inline-block; width:18px; height:12px; margin-right:6px; }}
    .leaflet-popup-content-wrapper, .leaflet-popup-tip {{ background:#020617; color:#e5e7eb; }}
    @media (max-width: 900px) {{ .shell {{ grid-template-columns:1fr; }} aside {{ order:2; }} #map {{ height:70vh; }} }}
  </style>
</head>
<body>
  <div class=\"shell\">
    <aside>
      <h1>{title}</h1>
      <p>Mapa coroplético por código postal con los 6 meses más recientes disponibles. Cambia entre conteo absoluto del mes y porcentaje relativo del total mensual filtrado.</p>
      <label for=\"incident\">Tipo de incidente</label>
      <select id=\"incident\"></select>
      <label for=\"mode\">Métrica</label>
      <select id=\"mode\"><option value=\"count\">Absoluta: eventos del mes</option><option value=\"pct_total\">Relativa: % del total mensual</option></select>
      <label for=\"monthRange\">Mes</label>
      <div class=\"month\" id=\"monthLabel\"></div>
      <input id=\"monthRange\" type=\"range\" min=\"0\" max=\"0\" value=\"0\" step=\"1\" />
      <div style=\"margin-top:14px\"><button id=\"play\">▶ Reproducir</button><button id=\"pause\" class=\"secondary\">Pausar</button></div>
      <div class=\"metric-grid\"><div class=\"metric\"><strong id=\"totalMetric\">0</strong><span>Total mensual filtrado</span></div><div class=\"metric\"><strong id=\"maxMetric\">0</strong><span>Máximo en un CP</span></div></div>
      <p><b>Tipificación refinada:</b> agrupa etiquetas crudas de FGJ en categorías comparables como robo a transeúnte, robo de vehículo, violencia familiar, delitos sexuales, homicidio y otros.</p>
    </aside>
    <main style=\"position:relative\"><div id=\"map\"></div><div class=\"legend\" id=\"legend\"></div></main>
  </div>
  <script>window.CITY_ZEN_PAYLOAD = {payload_json};</script>
  <script>
    const payload = window.CITY_ZEN_PAYLOAD;
    const months = payload.months;
    const incidentTypes = payload.incidentTypes;
    const byKey = new Map(payload.records.map(r => [`${{r.month}}|${{r.incident_type}}|${{r.cp}}`, r]));
    const map = L.map('map', {{ zoomControl:true }}).setView([19.4326, -99.1332], 11);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom:18, attribution:'&copy; OpenStreetMap contributors' }}).addTo(map);
    const colors = ['#f8fafc','#dbeafe','#93c5fd','#38bdf8','#facc15','#fb923c','#ef4444','#7f1d1d'];
    const incidentSelect = document.getElementById('incident');
    const modeSelect = document.getElementById('mode');
    const range = document.getElementById('monthRange');
    const label = document.getElementById('monthLabel');
    const totalMetric = document.getElementById('totalMetric');
    const maxMetric = document.getElementById('maxMetric');
    incidentTypes.forEach(t => incidentSelect.appendChild(new Option(t, t)));
    range.max = Math.max(months.length - 1, 0);
    range.value = Math.max(months.length - 1, 0);
    function fmt(v, mode) {{ return mode === 'pct_total' ? `${{v.toFixed(2)}}%` : v.toLocaleString('es-MX'); }}
    function valueFor(cp, month, incident, mode) {{ const r = byKey.get(`${{month}}|${{incident}}|${{cp}}`); return r ? Number(r[mode] || 0) : 0; }}
    function valuesFor(month, incident, mode) {{ return payload.geojson.features.map(f => valueFor(f.properties.cp, month, incident, mode)); }}
    function colorFor(v, max) {{ if (!v || max <= 0) return colors[0]; const ratio = v / max; const idx = Math.min(colors.length - 1, Math.max(1, Math.ceil(ratio * (colors.length - 1)))); return colors[idx]; }}
    function updateLegend(max, mode) {{ const steps = [0,.15,.3,.45,.6,.8,1]; document.getElementById('legend').innerHTML = '<b>Intensidad</b><br>' + steps.map(s => `<div><i style=\"background:${{colorFor(max*s,max)}}\"></i>${{fmt(max*s, mode)}}</div>`).join(''); }}
    const layer = L.geoJSON(payload.geojson, {{ style: () => ({{ color:'#334155', weight:1, fillOpacity:.78, fillColor:colors[0] }}), onEachFeature: (feature, lyr) => lyr.on('mouseover', () => lyr.openPopup()) }}).addTo(map);
    map.fitBounds(layer.getBounds(), {{ padding:[20,20] }});
    function redraw() {{
      const month = months[Number(range.value)] || months[months.length - 1] || '';
      const incident = incidentSelect.value || 'Todos';
      const mode = modeSelect.value;
      const vals = valuesFor(month, incident, mode);
      const max = Math.max(...vals, 0);
      const totalCount = payload.geojson.features.reduce((sum, f) => sum + valueFor(f.properties.cp, month, incident, 'count'), 0);
      label.textContent = month || 'Sin datos'; totalMetric.textContent = totalCount.toLocaleString('es-MX'); maxMetric.textContent = fmt(max, mode); updateLegend(max, mode);
      layer.eachLayer(lyr => {{ const cp = lyr.feature.properties.cp; const v = valueFor(cp, month, incident, mode); const count = valueFor(cp, month, incident, 'count'); const pct = valueFor(cp, month, incident, 'pct_total'); lyr.setStyle({{ fillColor: colorFor(v, max) }}); lyr.bindPopup(`<b>CP ${{cp}}</b><br>Mes: ${{month}}<br>Incidente: ${{incident}}<br>Eventos: ${{count.toLocaleString('es-MX')}}<br>% del total: ${{pct.toFixed(2)}}%`); }});
    }}
    let timer = null;
    document.getElementById('play').onclick = () => {{ clearInterval(timer); timer = setInterval(() => {{ range.value = (Number(range.value) + 1) % months.length; redraw(); }}, 1100); }};
    document.getElementById('pause').onclick = () => clearInterval(timer);
    [incidentSelect, modeSelect, range].forEach(el => el.addEventListener('input', redraw));
    redraw();
  </script>
</body>
</html>"""


def write_dashboard(aggregated: pd.DataFrame, gdf_cp: gpd.GeoDataFrame, html_path: str | Path, title: str) -> Path:
    html_path = Path(html_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    months = sorted(aggregated["month"].unique())
    incident_types = ["Todos"] + sorted(t for t in aggregated["incident_type"].unique() if t != "Todos")
    geojson = _geojson_for_dashboard(gdf_cp, aggregated["cp"].unique())
    html = _html_template(geojson, aggregated.to_dict("records"), months, incident_types, title)
    html_path.write_text(html, encoding="utf-8")
    return html_path


def build_dashboard(
    input_file: str | Path,
    cp_geojson_file: str | Path,
    output_html: str | Path = "outputs/cdmx_crime_heatmap.html",
    output_dir: str | Path = "outputs",
    date_col: str | None = None,
    existing_cp_col: str | None = None,
    months: int = 6,
    title: str = "Mapa de calor criminal CDMX por código postal",
) -> BuildResult:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gdf_cp = load_postal_polygons(cp_geojson_file)
    df = pd.read_csv(input_file, low_memory=False)
    date_col = resolve_date_column(df, date_col)
    assigned = assign_cp_to_dataframe(df, gdf_cp, existing_cp_col=existing_cp_col)
    recent = filter_recent_months(assigned, date_col, months=months)
    aggregated, selected_months, incident_types = aggregate_events(recent, gdf_cp)
    assigned_path = output_dir / "carpetas_fgj_cdmx_con_cp.csv"
    missing_path = output_dir / "carpetas_sin_cp.csv"
    aggregated_path = output_dir / "crime_aggregated_cp_month_incident.csv"
    assigned.to_csv(assigned_path, index=False, encoding="utf-8-sig")
    assigned[assigned["cp"].isna()].to_csv(missing_path, index=False, encoding="utf-8-sig")
    aggregated.to_csv(aggregated_path, index=False, encoding="utf-8-sig")
    html_path = write_dashboard(aggregated, gdf_cp, output_html, title)
    return BuildResult(html_path, aggregated_path, assigned_path, missing_path, selected_months, incident_types)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera dashboard HTML de carpetas FGJ CDMX por CP.")
    parser.add_argument("--input", required=True, help="CSV de carpetas de investigación FGJ CDMX.")
    parser.add_argument("--cp-geojson", required=True, help="GeoJSON de códigos postales CDMX con columna d_codigo.")
    parser.add_argument("--output-html", default="outputs/cdmx_crime_heatmap.html", help="Ruta del HTML final.")
    parser.add_argument("--output-dir", default="outputs", help="Directorio para CSV intermedios.")
    parser.add_argument("--date-col", default=None, help="Columna de fecha si se desea forzar una específica.")
    parser.add_argument("--existing-cp-col", default=None, help="Columna de CP existente para usar antes del cruce espacial.")
    parser.add_argument("--months", type=int, default=6, help="Número de meses recientes a incluir.")
    parser.add_argument("--title", default="Mapa de calor criminal CDMX por código postal", help="Título del dashboard.")
    return parser


def _is_interactive_kernel() -> bool:
    try:
        get_ipython
    except NameError:
        return False
    return get_ipython() is not None


def _has_required_cli_args(argv: list[str]) -> bool:
    has_input = any(arg == "--input" or arg.startswith("--input=") for arg in argv)
    has_cp_geojson = any(arg == "--cp-geojson" or arg.startswith("--cp-geojson=") for arg in argv)
    return has_input and has_cp_geojson


def _args_from_notebook_config(
    parser: argparse.ArgumentParser, config: dict[str, object] | None = None
) -> argparse.Namespace | None:
    config = config or globals()
    input_file = config.get("INPUT_FILE")
    cp_geojson_file = config.get("CP_GEOJSON_FILE")
    if input_file is None or cp_geojson_file is None:
        return None

    argv = ["--input", str(input_file), "--cp-geojson", str(cp_geojson_file)]
    optional_config = (
        ("OUTPUT_HTML", "--output-html"),
        ("OUTPUT_DIR", "--output-dir"),
        ("DATE_COL", "--date-col"),
        ("EXISTING_CP_COL", "--existing-cp-col"),
        ("MONTHS", "--months"),
        ("TITLE", "--title"),
    )
    for variable_name, flag in optional_config:
        value = config.get(variable_name)
        if value is not None:
            argv.extend([flag, str(value)])
    return parser.parse_args(argv)


def parse_args(
    argv: list[str] | None = None, notebook_config: dict[str, object] | None = None
) -> argparse.Namespace:
    parser = _build_arg_parser()
    cli_argv = list(argv) if argv is not None else None
    if cli_argv is None and _is_interactive_kernel():
        import sys

        kernel_argv = sys.argv[1:]
        if not _has_required_cli_args(kernel_argv):
            notebook_args = _args_from_notebook_config(parser, notebook_config)
            if notebook_args is not None:
                return notebook_args
            raise ValueError(
                "main() necesita --input y --cp-geojson. "
                "En notebooks/Colab define INPUT_FILE y CP_GEOJSON_FILE antes de llamar main(), "
                "o llama build_dashboard(input_file=..., cp_geojson_file=...)."
            )
    return parser.parse_args(cli_argv)


def main(argv: list[str] | None = None) -> BuildResult:
    import inspect

    frame = inspect.currentframe()
    caller_globals = frame.f_back.f_globals if frame and frame.f_back else None
    args = parse_args(argv, notebook_config=caller_globals)
    result = build_dashboard(
        input_file=args.input,
        cp_geojson_file=args.cp_geojson,
        output_html=args.output_html,
        output_dir=args.output_dir,
        date_col=args.date_col,
        existing_cp_col=args.existing_cp_col,
        months=args.months,
        title=args.title,
    )
    print(f"HTML generado: {result.html_path}")
    print(f"Agregado generado: {result.aggregated_path}")
    print(f"Meses incluidos: {', '.join(result.months)}")
    print(f"Tipos de incidente: {', '.join(result.incident_types)}")
    return result


if __name__ == "__main__":
    main()
