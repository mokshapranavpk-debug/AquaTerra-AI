import hmac
import io
import json
import math
import tempfile
import zipfile
from pathlib import Path
from datetime import date, timedelta

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from folium.plugins import Fullscreen
from streamlit_folium import st_folium
from supabase import create_client

st.set_page_config(page_title="AquaTerra AI | Land & Water Intelligence", page_icon="💧", layout="wide")

def render_map_explorer():
    ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
    USER_AGENT = "JAL-DRISHTI-research-prototype/1.0"

    FIELD_COLUMNS = [
        "sample_id", "date", "latitude", "longitude", "soil_type",
        "vegetation_land_cover", "infiltration_mm_hr", "slope_notes",
        "rainfall_notes", "water_feature_notes", "observer_notes", "evidence_type",
    ]

    st.title("🗺️ Map Explorer & Land Advisor")
    st.subheader("Terrain, rainfall, GIS layers and land-screening tools")
    st.caption("Field evidence • Terrain screening • GIS layers • Transparent limitations")

    st.info(
        "This is a research and screening prototype. Terrain and rainfall do not "
        "independently prove groundwater presence or recharge. The Land Advisor provides "
        "explainable rule-based suggestions, not validated crop prescriptions or groundwater predictions."
    )

    # ------------------------- Session state -------------------------
    if "terrain_results" not in st.session_state:
        st.session_state.terrain_results = None
    if "field_records" not in st.session_state:
        st.session_state.field_records = pd.DataFrame(columns=FIELD_COLUMNS)
    if "rainfall_results" not in st.session_state:
        st.session_state.rainfall_results = None
    if "imported_layers" not in st.session_state:
        st.session_state.imported_layers = []

    # ------------------------- Sidebar -------------------------
    with st.sidebar:
        st.header("Study Area Settings")
        st.warning(
            "These are approximate starting coordinates. Verify the study-area centre "
            "and boundary before using outputs in research."
        )
        latitude = st.number_input(
            "Centre latitude", min_value=-90.0, max_value=90.0,
            value=11.0200, step=0.0001, format="%.6f",
        )
        longitude = st.number_input(
            "Centre longitude", min_value=-180.0, max_value=180.0,
            value=77.1200, step=0.0001, format="%.6f",
        )
        radius_m = st.select_slider(
            "Study area half-width",
            options=[500, 750, 1000, 1500, 2000],
            value=1500,
            format_func=lambda x: f"{x:,} metres",
        )
        grid_size = st.select_slider(
            "Terrain sample grid",
            options=[5, 7, 9],
            value=5,
            help="More points increase API requests but do not create a high-resolution terrain raster.",
        )
        st.markdown("---")
        st.caption(
            "Study area: Kangeyampalayam / Sulur region, Coimbatore, Tamil Nadu. "
            "Verify the exact site."
        )

    # ------------------------- Helpers -------------------------
    def offset_to_latlon(centre_lat, centre_lon, north_m, east_m):
        lat = centre_lat + north_m / 111320.0
        cos_lat = max(0.01, abs(math.cos(math.radians(centre_lat))))
        lon = centre_lon + east_m / (111320.0 * cos_lat)
        return lat, lon


    def fetch_elevation_grid(lat, lon, radius, n):
        offsets = np.linspace(-radius, radius, n)
        spacing = (2 * radius) / (n - 1)
        points = [
            offset_to_latlon(lat, lon, north, east)
            for north in offsets for east in offsets
        ]
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        elevations = []

        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT})
            # Chunk requests to keep URL lengths manageable.
            chunk_size = 35
            for start in range(0, len(points), chunk_size):
                chunk_lat = lats[start:start + chunk_size]
                chunk_lon = lons[start:start + chunk_size]
                response = session.get(
                    ELEVATION_URL,
                    params={
                        "latitude": ",".join(f"{v:.6f}" for v in chunk_lat),
                        "longitude": ",".join(f"{v:.6f}" for v in chunk_lon),
                    },
                    timeout=45,
                )
                response.raise_for_status()
                values = response.json().get("elevation")
                if not isinstance(values, list) or len(values) != len(chunk_lat):
                    raise ValueError("Elevation service returned an unexpected response.")
                elevations.extend(values)

        if len(elevations) != n * n or any(
            value is None or not np.isfinite(value) for value in elevations
        ):
            raise ValueError("Elevation data contains missing or invalid values.")

        grid = np.asarray(elevations, dtype=float).reshape(n, n)
        grad_north, grad_east = np.gradient(grid, spacing, spacing)
        slope = np.sqrt(grad_north ** 2 + grad_east ** 2) * 100

        records = []
        for i in range(n):
            for j in range(n):
                idx = i * n + j
                records.append({
                    "latitude": lats[idx],
                    "longitude": lons[idx],
                    "elevation_m": float(grid[i, j]),
                    "estimated_slope_percent": float(slope[i, j]),
                    "grid_row": i + 1,
                    "grid_column": j + 1,
                    "evidence_type": "Modelled elevation estimate / derived slope",
                })
        df = pd.DataFrame(records)

        lower_cut = df["estimated_slope_percent"].quantile(1 / 3)
        upper_cut = df["estimated_slope_percent"].quantile(2 / 3)

        def classify(value):
            if value <= lower_cut:
                return "Relatively lower slope"
            if value <= upper_cut:
                return "Intermediate relative slope"
            return "Relatively steeper slope"

        df["terrain_category"] = df["estimated_slope_percent"].apply(classify)
        return df, spacing


    def fetch_historical_rainfall(lat, lon, start_date, end_date):
        if start_date > end_date:
            raise ValueError("Start date must be on or before end date.")
        response = requests.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "precipitation_sum,rain_sum,precipitation_hours",
                "timezone": "Asia/Kolkata",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=45,
        )
        response.raise_for_status()
        daily = response.json().get("daily", {})
        if not daily.get("time"):
            raise ValueError("Rainfall service returned no daily records.")
        return pd.DataFrame({
            "date": daily.get("time", []),
            "precipitation_mm": daily.get("precipitation_sum", []),
            "rain_mm": daily.get("rain_sum", []),
            "precipitation_hours": daily.get("precipitation_hours", []),
        })


    def read_upload(upload):
        name = upload.name.lower()
        raw = upload.getvalue()

        if name.endswith(".csv"):
            return "csv", pd.read_csv(io.BytesIO(raw))

        if name.endswith(".geojson") or name.endswith(".json"):
            obj = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(obj, dict) or obj.get("type") not in (
                "FeatureCollection", "Feature", "GeometryCollection",
                "Point", "MultiPoint", "LineString", "MultiLineString",
                "Polygon", "MultiPolygon",
            ):
                raise ValueError("The JSON file does not appear to be valid GeoJSON.")
            return "geojson", obj

        if name.endswith(".zip"):
            if not zipfile.is_zipfile(io.BytesIO(raw)):
                raise ValueError("This file is not a valid ZIP archive.")
            try:
                import geopandas as gpd
            except ImportError as exc:
                raise ValueError(
                    "Shapefile support needs GeoPandas. Install it with "
                    "`pip install geopandas`, then restart the app."
                ) from exc

            # GeoPandas/Fiona can read a ZIP through a temporary file more reliably.
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / "uploaded_layer.zip"
                zip_path.write_bytes(raw)
                try:
                    gdf = gpd.read_file(f"zip://{zip_path}")
                except Exception as exc:
                    raise ValueError(
                        "Could not read the ZIP as a shapefile. Include .shp, .shx, "
                        ".dbf and preferably .prj files in the ZIP. "
                        f"Details: {exc}"
                    ) from exc
                if gdf.crs is None:
                    raise ValueError(
                        "The shapefile has no declared CRS. Add/confirm its CRS in a GIS "
                        "tool before importing to avoid misplaced map features."
                    )
                gdf = gdf.to_crs("EPSG:4326")
                return "geojson", json.loads(gdf.to_json())

        raise ValueError("Supported formats: CSV, GeoJSON/JSON, or zipped shapefile.")


    def add_csv_points(map_obj, frame, layer_name):
        lookup = {str(c).strip().lower(): c for c in frame.columns}
        lat_col = next((lookup[k] for k in ("latitude", "lat", "y") if k in lookup), None)
        lon_col = next((lookup[k] for k in ("longitude", "lon", "lng", "long", "x") if k in lookup), None)
        if lat_col is None or lon_col is None:
            st.warning(
                f"CSV layer '{layer_name}' was loaded for review but not mapped. "
                "It needs latitude/longitude columns (or lat/lon)."
            )
            return

        layer = folium.FeatureGroup(name=f"Imported CSV: {layer_name}", show=True)
        plotted = 0
        for _, row in frame.iterrows():
            try:
                lat, lon = float(row[lat_col]), float(row[lon_col])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue
                details = "<br>".join(
                    f"{str(k)}: {str(v)}" for k, v in row.items() if pd.notna(v)
                )
                folium.CircleMarker(
                    location=[lat, lon], radius=5, color="#6A3D9A",
                    fill=True, fill_opacity=0.85,
                    tooltip=f"{layer_name} — imported record",
                    popup=folium.Popup(details[:2500], max_width=350),
                ).add_to(layer)
                plotted += 1
            except (TypeError, ValueError):
                continue
        layer.add_to(map_obj)
        st.caption(f"CSV layer '{layer_name}': mapped {plotted} coordinate rows.")


    def add_geojson(map_obj, obj, layer_name):
        layer = folium.FeatureGroup(name=f"Imported GIS: {layer_name}", show=True)
        folium.GeoJson(
            obj,
            name=layer_name,
            style_function=lambda feature: {
                "color": "#6A3D9A",
                "weight": 2,
                "fillColor": "#9B7EBD",
                "fillOpacity": 0.25,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=list((obj.get("features") or [{}])[0].get("properties", {}).keys())[:4]
            ) if obj.get("type") == "FeatureCollection"
                 and (obj.get("features") or [])
                 and (obj["features"][0].get("properties") or {}) else None,
        ).add_to(layer)
        layer.add_to(map_obj)


    # ------------------------- Tabs -------------------------
    tab_map, tab_rain, tab_field, tab_imports, tab_advisor, tab_method = st.tabs([
        "🗺️ Map & terrain", "🌧️ Rainfall", "🧪 Field observations",
        "📂 Import GIS / CSV", "🌱 Land Advisor", "📘 Method & limitations",
    ])

    # ------------------------- Map / terrain -------------------------
    with tab_map:
        st.markdown("### Terrain baseline")
        st.write(
            "Fetch elevation estimates, derive a coarse slope estimate, and explore "
            "the terrain grid. Relative slope classes are calculated from this grid only."
        )
        if st.button("Fetch elevation & build map", type="primary", key="fetch_terrain"):
            try:
                with st.spinner("Fetching public elevation estimates..."):
                    terrain_df, spacing = fetch_elevation_grid(
                        latitude, longitude, radius_m, grid_size
                    )
                st.session_state.terrain_results = {
                    "data": terrain_df, "latitude": latitude, "longitude": longitude,
                    "radius_m": radius_m, "spacing_m": spacing, "grid_size": grid_size,
                }
                st.success("Terrain grid generated.")
            except Exception as exc:
                st.error("Elevation data could not be retrieved or processed.")
                st.caption(f"Technical details: {exc}")

        terrain_result = st.session_state.terrain_results
        if terrain_result is None:
            st.warning("Generate the terrain grid to view the terrain layer.")
        else:
            df = terrain_result["data"]
            centre_lat = terrain_result["latitude"]
            centre_lon = terrain_result["longitude"]
            radius = terrain_result["radius_m"]
            spacing = terrain_result["spacing_m"]
            n = terrain_result["grid_size"]

            c1, c2, c3 = st.columns(3)
            c1.metric("Grid locations", len(df))
            c2.metric("Minimum sampled elevation", f"{df['elevation_m'].min():.1f} m")
            c3.metric("Maximum sampled elevation", f"{df['elevation_m'].max():.1f} m")
            st.caption(
                f"Grid: {n} × {n}; nominal sample spacing about {spacing:.0f} m. "
                "This is not a terrain raster at that resolution."
            )

            show_terrain = st.checkbox("Show terrain / relative slope", value=True, key="show_terrain")
            show_centre = st.checkbox("Show study-area centre", value=True, key="show_centre")
            show_fields = st.checkbox(
                "Show saved field observations with coordinates", value=True, key="show_fields"
            )
            map_obj = folium.Map(
                location=[centre_lat, centre_lon], zoom_start=14,
                tiles="OpenStreetMap", control_scale=True,
            )
            Fullscreen(position="topright").add_to(map_obj)

            if show_terrain:
                terrain_layer = folium.FeatureGroup(name="Terrain / relative slope", show=True)
                half_cell = spacing / 2
                for _, row in df.iterrows():
                    category = row["terrain_category"]
                    colour = {
                        "Relatively lower slope": "#2E8B57",
                        "Intermediate relative slope": "#F2C94C",
                        "Relatively steeper slope": "#D9534F",
                    }[category]
                    grid_row = int(row["grid_row"]) - 1
                    grid_col = int(row["grid_column"]) - 1
                    north_offset = -radius + grid_row * spacing
                    east_offset = -radius + grid_col * spacing
                    south, west = offset_to_latlon(
                        centre_lat, centre_lon, north_offset - half_cell, east_offset - half_cell
                    )
                    north, east = offset_to_latlon(
                        centre_lat, centre_lon, north_offset + half_cell, east_offset + half_cell
                    )
                    popup = (
                        f"Elevation estimate: {row['elevation_m']:.1f} m<br>"
                        f"Estimated slope: {row['estimated_slope_percent']:.2f}%<br>"
                        f"Relative terrain class: {category}<br>"
                        "Evidence: modelled elevation / derived slope<br>"
                        "Not a groundwater prediction."
                    )
                    folium.Rectangle(
                        bounds=[[south, west], [north, east]], color=colour, weight=1,
                        fill=True, fill_color=colour, fill_opacity=0.40,
                        tooltip=category, popup=folium.Popup(popup, max_width=320),
                    ).add_to(terrain_layer)
                terrain_layer.add_to(map_obj)

            if show_centre:
                folium.Marker(
                    [centre_lat, centre_lon], tooltip="Selected study-area centre",
                    popup="Verify this point against the actual study boundary.",
                    icon=folium.Icon(color="blue", icon="info-sign"),
                ).add_to(map_obj)

            if show_fields and not st.session_state.field_records.empty:
                fields = st.session_state.field_records.dropna(subset=["latitude", "longitude"])
                field_layer = folium.FeatureGroup(name="Field observations (user-recorded)", show=True)
                for _, row in fields.iterrows():
                    try:
                        lat, lon = float(row["latitude"]), float(row["longitude"])
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            continue
                        details = "<br>".join(
                            f"{col}: {row[col]}" for col in fields.columns
                            if pd.notna(row[col]) and str(row[col]).strip()
                        )
                        folium.CircleMarker(
                            [lat, lon], radius=6, color="#1F78B4", fill=True, fill_opacity=0.9,
                            tooltip=f"Field sample: {row.get('sample_id', 'unnamed')}",
                            popup=folium.Popup(details, max_width=360),
                        ).add_to(field_layer)
                    except (TypeError, ValueError):
                        continue
                field_layer.add_to(map_obj)

            for item in st.session_state.imported_layers:
                try:
                    if item["kind"] == "csv":
                        add_csv_points(map_obj, item["data"], item["name"])
                    elif item["kind"] == "geojson":
                        add_geojson(map_obj, item["data"], item["name"])
                except Exception as exc:
                    st.warning(f"Could not display imported layer '{item['name']}': {exc}")

            folium.LayerControl(collapsed=False).add_to(map_obj)
            st_folium(map_obj, use_container_width=True, height=580, returned_objects=[])

            st.markdown("**Terrain legend**")
            st.markdown(
                "- 🟢 Relatively lower slope within this sampled grid  \n"
                "- 🟡 Intermediate relative slope  \n"
                "- 🔴 Relatively steeper slope  \n"
                "- 🔵 Field observations are user-recorded, not independently verified"
            )
            st.dataframe(df.round({
                "latitude": 6, "longitude": 6, "elevation_m": 2,
                "estimated_slope_percent": 2,
            }), use_container_width=True)
            st.download_button(
                "Download terrain grid CSV", data=df.to_csv(index=False).encode("utf-8"),
                file_name="aquaterra_terrain_grid.csv", mime="text/csv",
            )

    # ------------------------- Rainfall -------------------------
    with tab_rain:
        st.markdown("### Historical rainfall context")
        st.warning(
            "This is gridded historical weather/reanalysis data for the selected centre, "
            "not a direct campus rain-gauge observation. Rainfall is water input, not proof "
            "of groundwater recharge."
        )
        today = date.today()
        default_end = today - timedelta(days=6)
        default_start = default_end - timedelta(days=29)
        c1, c2 = st.columns(2)
        start_date = c1.date_input("Start date", value=default_start, key="rain_start")
        end_date = c2.date_input("End date", value=default_end, key="rain_end")

        if st.button("Fetch historical rainfall", key="fetch_rain"):
            try:
                with st.spinner("Fetching daily precipitation data..."):
                    rain_df = fetch_historical_rainfall(latitude, longitude, start_date, end_date)
                st.session_state.rainfall_results = {
                    "data": rain_df, "latitude": latitude, "longitude": longitude,
                    "start": start_date, "end": end_date,
                }
                st.success("Rainfall context retrieved.")
            except Exception as exc:
                st.error("Rainfall data could not be retrieved.")
                st.caption(f"Technical details: {exc}")

        rain_result = st.session_state.rainfall_results
        if rain_result is not None:
            rdf = rain_result["data"]
            total = pd.to_numeric(rdf["precipitation_mm"], errors="coerce").sum(min_count=1)
            c1, c2, c3 = st.columns(3)
            c1.metric("Days returned", len(rdf))
            c2.metric("Total precipitation", "—" if pd.isna(total) else f"{total:.1f} mm")
            c3.metric("Date range", f"{rain_result['start']} to {rain_result['end']}")
            chart_df = rdf.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            chart_df = chart_df.set_index("date")
            chart_cols = [col for col in ["precipitation_mm", "rain_mm"] if col in chart_df]
            if chart_cols:
                st.line_chart(chart_df[chart_cols])
            st.dataframe(rdf, use_container_width=True)
            st.download_button(
                "Download rainfall CSV", data=rdf.to_csv(index=False).encode("utf-8"),
                file_name="aquaterra_historical_rainfall.csv", mime="text/csv",
            )
            st.caption(
                "Source: Open-Meteo Historical Weather API. Data are model/reanalysis "
                "estimates at a much coarser spatial scale than a school campus."
            )

    # ------------------------- Field observations -------------------------
    with tab_field:
        st.markdown("### Record a field observation")
        st.write(
            "Use consistent methods, record units, and repeat measurements where practical. "
            "Do not enter guessed values as measurements."
        )
        with st.form("field_observation_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            sample_id = c1.text_input("Sample / observation ID", placeholder="e.g. JD-S01")
            obs_date = c2.date_input("Observation date", value=date.today())
            evidence_type = c3.selectbox(
                "Evidence type",
                ["Measured in field", "Visual observation", "Reported by another source"],
            )
            c1, c2 = st.columns(2)
            obs_lat = c1.number_input(
                "Latitude", min_value=-90.0, max_value=90.0,
                value=float(latitude), format="%.6f",
            )
            obs_lon = c2.number_input(
                "Longitude", min_value=-180.0, max_value=180.0,
                value=float(longitude), format="%.6f",
            )
            soil_type = st.selectbox(
                "Observed soil type",
                ["Not assessed", "Sand", "Sandy loam", "Loam", "Silt / silty soil",
                 "Clay / clayey soil", "Gravelly", "Rock / exposed bedrock", "Mixed / unknown"],
            )
            land_cover = st.selectbox(
                "Vegetation / land cover",
                ["Not assessed", "Built-up / paved", "Bare soil", "Grass", "Agriculture",
                 "Trees / dense vegetation", "Water body", "Mixed / other"],
            )
            infiltration = st.number_input(
                "Infiltration rate (mm/hour; use 0 if not measured)",
                min_value=0.0, max_value=10000.0, value=0.0, step=1.0,
            )
            slope_notes = st.text_input("Slope / surface notes")
            rainfall_notes = st.text_input("Rainfall / recent wetness notes")
            water_notes = st.text_input("Nearby drains, ponds, wells or water features")
            observer_notes = st.text_area("Method, units, uncertainty and other notes")
            submitted = st.form_submit_button("Save observation")

        if submitted:
            if not sample_id.strip():
                st.error("Please provide a sample / observation ID.")
            else:
                record = {
                    "sample_id": sample_id.strip(), "date": obs_date.isoformat(),
                    "latitude": float(obs_lat), "longitude": float(obs_lon),
                    "soil_type": soil_type, "vegetation_land_cover": land_cover,
                    "infiltration_mm_hr": float(infiltration) if infiltration > 0 else np.nan,
                    "slope_notes": slope_notes, "rainfall_notes": rainfall_notes,
                    "water_feature_notes": water_notes, "observer_notes": observer_notes,
                    "evidence_type": evidence_type,
                }
                st.session_state.field_records = pd.concat(
                    [st.session_state.field_records, pd.DataFrame([record])],
                    ignore_index=True,
                )
                st.success("Observation saved for this app session.")
                st.caption(
                    "Download the CSV to preserve the record outside this browser session. "
                    "Coordinates default to the study centre; change them to the actual site."
                )

        field_df = st.session_state.field_records
        st.markdown("#### Saved observations")
        if field_df.empty:
            st.info("No field observations recorded in this session yet.")
        else:
            st.dataframe(field_df, use_container_width=True)
            st.download_button(
                "Download field observations CSV",
                data=field_df.to_csv(index=False).encode("utf-8"),
                file_name="aquaterra_field_observations.csv", mime="text/csv",
            )

        st.markdown("#### Import previous field records")
        field_upload = st.file_uploader(
            "Upload field-observation CSV", type=["csv"], key="field_csv_upload"
        )
        if field_upload is not None:
            try:
                uploaded_df = pd.read_csv(field_upload)
                st.dataframe(uploaded_df.head(20), use_container_width=True)
                if st.button("Append imported rows to observations", key="append_field_csv"):
                    st.session_state.field_records = pd.concat(
                        [st.session_state.field_records, uploaded_df],
                        ignore_index=True, sort=False,
                    )
                    st.success("Rows appended. Review columns and units before analysis.")
            except Exception as exc:
                st.error(f"Could not read CSV: {exc}")

    # ------------------------- GIS / CSV imports -------------------------
    with tab_imports:
        st.markdown("### Import external data layers")
        st.write(
            "Supported: CSV point data, GeoJSON, and zipped shapefiles when GeoPandas "
            "and its dependencies are installed. GeoTIFF rasters are not rendered in this "
            "version; prepare them in a GIS tool before importing."
        )
        st.caption(
            "CSV mapping requires latitude/longitude columns (or lat/lon). Spatial files "
            "should use WGS84 / EPSG:4326 or have a known CRS that can be converted."
        )
        uploads = st.file_uploader(
            "Upload GIS / CSV files", type=["csv", "geojson", "json", "zip"],
            accept_multiple_files=True, key="gis_uploads",
        )
        if uploads and st.button("Load selected layers", key="load_gis"):
            loaded = 0
            for upload in uploads:
                try:
                    kind, data = read_upload(upload)
                    st.session_state.imported_layers.append({
                        "name": upload.name, "kind": kind, "data": data,
                    })
                    loaded += 1
                except Exception as exc:
                    st.error(f"{upload.name}: {exc}")
            if loaded:
                st.success(f"Loaded {loaded} layer(s) for this session.")

        if st.session_state.imported_layers:
            st.markdown("#### Layers loaded in this session")
            for i, layer in enumerate(st.session_state.imported_layers):
                st.write(f"{i + 1}. **{layer['name']}** — {layer['kind']}")
                if layer["kind"] == "csv":
                    st.dataframe(layer["data"].head(10), use_container_width=True)
                elif layer["kind"] == "geojson":
                    st.caption("GIS layer will appear in the map tab if its geometry is valid.")
            if st.button("Clear imported layers from this session", key="clear_layers"):
                st.session_state.imported_layers = []
                st.rerun()

    # ------------------------- Land Advisor -------------------------
    with tab_advisor:
        st.markdown("### 🌱 Land Improvement & Crop Advisory")
        st.write(
            "This transparent rule-based advisor turns user-entered observations into "
            "possible actions to discuss with a teacher or local agricultural extension officer. "
            "It is a screening guide, not an automated soil diagnosis or groundwater prediction."
        )
        st.info(
            "Use actual observations where available. If the field test has not yet been done, "
            "select 'Not measured'—do not enter zero as a measured infiltration rate."
        )

        with st.form("land_advisor_form"):
            a1, a2 = st.columns(2)
            advisor_soil = a1.selectbox(
                "Soil texture (observed or lab-confirmed)",
                ["Unknown / not assessed", "Sandy / coarse", "Loamy / mixed", "Clayey / fine", "Gravelly", "Rocky / shallow soil"],
            )
            advisor_land = a2.selectbox(
                "Current land use / cover",
                ["Unknown", "Bare soil", "Agriculture", "Grass / vegetation", "Built-up / paved", "Orchard / trees"],
            )
            a3, a4 = st.columns(2)
            infiltration_class = a3.selectbox(
                "Infiltration evidence",
                ["Not measured", "Slow in a repeatable field test", "Moderate in a repeatable field test", "Fast in a repeatable field test", "Visual impression only"],
            )
            surface_issue = a4.selectbox(
                "Main visible issue (if any)",
                ["Unknown / none confirmed", "Surface crusting", "Compaction suspected", "Runoff / erosion", "Waterlogging / ponding", "Very little soil / exposed rock"],
            )
            a5, a6 = st.columns(2)
            slope_class = a5.selectbox("Slope", ["Unknown", "Nearly flat / gentle", "Moderate", "Steep"])
            water_supply = a6.selectbox("Water availability", ["Unknown", "Rainfed / uncertain", "Limited irrigation", "Reliable irrigation available"])
            season = st.selectbox("Season for crop planning", ["Not decided", "Kharif / monsoon", "Rabi / post-monsoon", "Summer"])
            climate_note = st.selectbox("Rainfall / climate context", ["Not assessed", "Dry / irregular rainfall", "Seasonal monsoon rainfall", "Reliable rainfall or irrigation"])
            advisor_submitted = st.form_submit_button("Generate transparent recommendations", type="primary")

        if advisor_submitted:
            recs = []
            watchouts = []
            crop_candidates = []
            evidence_items = []

            # Soil and surface management rules: these are options to investigate, not prescriptions.
            if surface_issue == "Surface crusting":
                recs.append(("Reduce surface crusting", "Maintain suitable organic mulch or crop-residue cover where agronomically appropriate; avoid leaving soil bare for long periods. Check that the crust is truly the cause before changing management."))
                evidence_items.append("Surface crusting selected by user (not independently verified).")
            if surface_issue == "Compaction suspected":
                recs.append(("Investigate compaction", "Reduce unnecessary traffic and repeated trampling when soil is wet. Ask an agricultural adviser whether compaction is present before considering any loosening; unnecessary tillage can worsen soil structure."))
                watchouts.append("Compaction is only suspected. Confirm it before using mechanical treatment.")
            if surface_issue == "Runoff / erosion" or slope_class in ("Moderate", "Steep"):
                recs.append(("Manage runoff and erosion", "Keep soil covered with suitable vegetation or residue. Consider contour-aligned measures or vegetated strips only after a site-specific slope and drainage assessment with a qualified adviser."))
                watchouts.append("Do not build bunds, pits or barriers where they could divert water onto neighbouring land, buildings or roads.")
            if surface_issue == "Waterlogging / ponding":
                recs.append(("Investigate drainage and waterlogging", "Record where and how long ponding occurs. Check whether the cause is surface sealing, a low spot, blocked drainage or a high water table before proposing drainage works."))
                watchouts.append("Do not dig drainage channels or soak pits without permission and a site assessment.")
            if advisor_land == "Bare soil" or advisor_land == "Agriculture":
                recs.append(("Maintain protective soil cover", "Where compatible with the crop and local practice, retain clean crop residues or use a suitable cover crop to reduce raindrop impact, evaporation and erosion."))
            if advisor_soil == "Sandy / coarse":
                recs.append(("Manage water and nutrients on coarse soil", "Consider organic matter additions based on local agronomic guidance, split nutrient applications where recommended, and mulch to reduce evaporation. Coarse soils may drain quickly but can still have other limitations."))
            elif advisor_soil == "Clayey / fine":
                recs.append(("Protect structure in fine-textured soil", "Avoid traffic and heavy tillage when soil is wet. Maintain organic cover and verify drainage and compaction before selecting any intervention."))
            elif advisor_soil == "Rocky / shallow soil":
                recs.append(("Check soil depth and safe land use", "Map the extent of shallow soil and exposed rock. Choose vegetation suited to the available rooting depth; do not assume infiltration or recharge from appearance alone."))
            elif advisor_soil == "Unknown / not assessed":
                watchouts.append("Soil texture is unknown. A visual description or teacher-guided texture assessment is needed before soil-specific recommendations.")

            if infiltration_class == "Slow in a repeatable field test":
                recs.append(("Follow up on slow infiltration", "Repeat the same test on comparable undisturbed patches and record initial wetness, surface cover, water volume, test area and timing. Investigate crusting, compaction and texture before choosing a treatment."))
                watchouts.append("A simple ring-and-water trial is comparative unless the test area, water head, procedure and calculation are standardized; do not report it as a certified infiltration rate.")
            elif infiltration_class == "Fast in a repeatable field test":
                recs.append(("Protect against rapid drainage and leaching", "Maintain soil cover and follow local nutrient-management advice. Fast surface entry does not prove groundwater recharge or indicate that water is retained in the root zone."))
            elif infiltration_class in ("Not measured", "Visual impression only"):
                watchouts.append("Infiltration has not been measured reliably. Keep the result as 'not measured' or 'visual impression' and avoid a low/medium/high infiltration label.")

            # Candidate crop ideas are deliberately broad and require local confirmation.
            if water_supply in ("Rainfed / uncertain", "Limited irrigation") or climate_note == "Dry / irregular rainfall":
                crop_candidates.append(("Millets and locally adapted pulses", "Potential candidates for some rainfed settings because many varieties tolerate intermittent dry conditions; confirm species/variety, soil, sowing window and local recommendations with the Tamil Nadu agriculture extension service."))
                crop_candidates.append(("Cover crops / green-manure options", "Consider only where the species fits the season, available moisture and farm objective; some cover crops compete for water in dry periods."))
            if advisor_soil == "Sandy / coarse":
                crop_candidates.append(("Locally recommended crops for lighter soils", "Ask the local agriculture office to shortlist crops and varieties based on soil depth, nutrient status, season and irrigation. Do not select a crop from texture alone."))
            if advisor_soil == "Clayey / fine" and water_supply == "Reliable irrigation available":
                crop_candidates.append(("Crops adapted to the local soil and water regime", "Crop choice depends on drainage, salinity, season and reliable water supply. Do not infer that paddy or another water-demanding crop is suitable from clayey texture alone."))
            if advisor_land == "Built-up / paved":
                crop_candidates = []
                watchouts.append("For built-up or paved land, crop selection is not the main intervention. Prioritize safe runoff management and permitted green-space planning instead.")
            if not crop_candidates:
                crop_candidates.append(("Crop choice needs more evidence", "Obtain soil-test results if available, soil depth, pH/salinity where relevant, season, water availability and local extension advice before ranking crops."))

            st.markdown("#### 1. Suggested land actions")
            if recs:
                for title, detail in recs:
                    with st.expander(title, expanded=True):
                        st.write(detail)
            else:
                st.write("Not enough information for a specific action. Begin with site photos, soil observations, and a repeatable field test.")

            st.markdown("#### 2. Crop suitability: candidate ideas, not a crop prescription")
            for title, detail in crop_candidates:
                st.markdown(f"**{title}** — {detail}")

            st.markdown("#### 3. Water-management options")
            water_options = []
            if advisor_land in ("Bare soil", "Agriculture", "Grass / vegetation", "Orchard / trees"):
                water_options.append("Maintain soil cover and protect existing vegetation where appropriate.")
            if slope_class in ("Moderate", "Steep") or surface_issue == "Runoff / erosion":
                water_options.append("First map the runoff pathway; ask a qualified local adviser about contour measures or vegetated buffers. Avoid structures that redirect flow to others.")
            if surface_issue == "Waterlogging / ponding":
                water_options.append("Document ponding locations and duration, and check blocked drains and local drainage conditions before proposing changes.")
            if water_supply in ("Rainfed / uncertain", "Limited irrigation"):
                water_options.append("Consider water-efficient scheduling, mulching and locally approved rainwater-harvesting options after checking soil, slope, overflow and local rules.")
            if not water_options:
                water_options.append("Water availability and site conditions are not sufficiently known. Record rainfall, runoff and drainage before recommending structures.")
            for item in water_options:
                st.markdown(f"- {item}")

            st.markdown("#### 4. Evidence and confidence report")
            known = sum([
                advisor_soil != "Unknown / not assessed",
                advisor_land != "Unknown",
                infiltration_class not in ("Not measured", "Visual impression only"),
                surface_issue != "Unknown / none confirmed",
                slope_class != "Unknown",
                water_supply != "Unknown",
                season != "Not decided",
                climate_note != "Not assessed",
            ])
            coverage = int(100 * known / 8)
            st.progress(coverage, text=f"Input completeness: {known}/8 categories supplied ({coverage}%)")
            st.write("**Recommendation confidence: preliminary / low.** This is a rule-based checklist from your selections, not a statistically calibrated confidence score.")
            st.write("**Evidence used:**")
            st.markdown("- Soil: " + advisor_soil)
            st.markdown("- Land cover: " + advisor_land)
            st.markdown("- Infiltration evidence: " + infiltration_class)
            st.markdown("- Surface issue: " + surface_issue)
            st.markdown("- Slope: " + slope_class)
            st.markdown("- Water availability: " + water_supply)
            st.markdown("- Season / climate: " + season + " / " + climate_note)
            for item in watchouts:
                st.warning(item)
            st.caption("No groundwater prediction is produced. These recommendations do not replace soil testing, a site visit, or advice from the local agricultural extension service.")

            report = {
                "advisor_type": "Explainable rule-based screening; not a validated prediction",
                "soil": advisor_soil, "land_cover": advisor_land,
                "infiltration_evidence": infiltration_class, "surface_issue": surface_issue,
                "slope": slope_class, "water_availability": water_supply,
                "season": season, "climate_context": climate_note,
                "input_completeness_percent": coverage,
                "recommendations": [{"title": t, "detail": d} for t, d in recs],
                "crop_candidate_notes": [{"title": t, "detail": d} for t, d in crop_candidates],
                "water_management_options": water_options,
                "limitations": watchouts,
            }
            st.download_button(
                "Download advisor report (JSON)",
                data=json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name="aquaterra_land_advisor_report.json", mime="application/json",
            )

        st.markdown("#### Scientific guidance to consult")
        st.markdown(
            "- [FAO — Soil management and conservation](https://www.fao.org/soils-portal/soil-management/en/)\n"
            "- [Tamil Nadu Agricultural University](https://tnau.ac.in/) — local crop, soil and season guidance\n"
            "- [Central Ground Water Board](https://cgwb.gov.in/en/aquifer-mapping) — hydrogeological context"
        )

    # ------------------------- Method / limitations -------------------------
    with tab_method:
        st.markdown("### Evidence and interpretation")
        st.markdown(
            """
            | Layer | Evidence status | What it can support | What it cannot establish alone |
            |---|---|---|---|
            | Elevation | Modelled estimate from public API | Broad terrain context | Precise campus-level slope or aquifer location |
            | Slope | Derived from sparse elevation samples | Relative surface-gradient screening | Groundwater presence or recharge rate |
            | Historical rainfall | Gridded weather/reanalysis estimate | Rainfall context over a chosen period | Local rain-gauge totals or actual recharge |
            | Imported geology / geomorphology | Depends on source file | Regional geological context | Site-specific conditions without validation |
            | Land cover | Depends on source and date | Surface-cover context | Infiltration without soil and surface evidence |
            | Field observations | User-entered evidence | Local observations with method and units | Independent verification or a complete aquifer assessment |
            | Groundwater potential prediction | Not generated in this version | — | No validated prediction is claimed |
            """
        )
        st.markdown("### Suggested scientific workflow")
        st.markdown(
            """
            1. Verify the study boundary and coordinates.
            2. Record source, date, units, method and uncertainty for every dataset.
            3. Obtain geology/geomorphology, land-cover and drainage layers for the exact area.
            4. Collect repeatable field observations and compare with reliable well/aquifer records where feasible.
            5. Develop a documented multi-criteria method before considering machine learning.
            6. Validate any resulting map against independent observations and report limitations.
            """
        )
        st.markdown("### Data-source links")
        st.markdown(
            "- Elevation: [Open-Meteo Elevation API](https://open-meteo.com/en/docs/elevation-api)\n"
            "- Historical weather: [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)\n"
            "- Groundwater context: [ISRO Bhuvan-Bhujal](https://bhuvan-app1.nrsc.gov.in/gwis/)\n"
            "- Aquifer context: [Central Ground Water Board](https://cgwb.gov.in/en/aquifer-mapping)"
        )
        st.warning(
            "Do not describe map colours as confirmed high/medium/low groundwater potential. "
            "They currently describe terrain classes only. A defensible potential map requires "
            "appropriate hydrogeological evidence and an explicit method."
        )

    st.markdown("---")
    st.caption(
        "AquaTerra AI research prototype. Online data may be unavailable or revised. "
        "Session data and uploaded layers are not automatically saved permanently; download "
        "your CSV outputs to keep a copy."
    )


st.title("💧 AquaTerra AI")
st.caption("Land & Water Intelligence • Field evidence • Mapping • Exploratory analysis")

# ---------- Secure login and existing Supabase connection ----------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    APP_PASSWORD = str(st.secrets["APP_PASSWORD"])
except Exception:
    st.error("Configure SUPABASE_URL, SUPABASE_KEY and APP_PASSWORD in Streamlit Cloud → Settings → Secrets.")
    st.stop()
if not SUPABASE_URL or not SUPABASE_KEY or not APP_PASSWORD:
    st.error("One or more required secrets are empty.")
    st.stop()

@st.cache_resource
def get_database_client(url, key):
    return create_client(url, key)

try:
    db = get_database_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    st.error("Could not initialise Supabase. Check the URL and server-side key in Secrets.")
    st.stop()

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    st.markdown("### 🔐 Secure Research Login")
    with st.form("login_form"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Log in", use_container_width=True)
    if submitted:
        if hmac.compare_digest(password, APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()

with st.sidebar:
    st.title("💧 AquaTerra AI")
    page = st.radio("Workspace", ["Research Dashboard", "Map Explorer & Land Advisor"], key="aquaterra_page")
    st.divider()
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()
    if st.button("🔌 Test database connection", use_container_width=True):
        try:
            db.table("field_observations").select("sample_id").limit(1).execute()
            st.success("Supabase connection successful.")
        except Exception:
            st.error("Connection failed. Check Supabase permissions and Cloud logs.")
    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    st.caption("Use verified measurements for research conclusions.")

if page == "Map Explorer & Land Advisor":
    render_map_explorer()
    st.divider()
    st.caption("Terrain and rainfall layers are contextual estimates, not proof of groundwater presence or recharge.")
    st.stop()

# ---------- Dashboard: existing public.field_observations schema ----------
def load_observations():
    rows, start, page_size = [], 0, 1000
    while True:
        response = (db.table("field_observations").select("*")
                    .order("created_at", desc=True)
                    .range(start, start + page_size - 1).execute())
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows

try:
    records = load_observations()
    df = pd.DataFrame(records)
except Exception:
    st.error("Could not load observations. Check table permissions and Streamlit Cloud logs.")
    st.stop()

if not df.empty:
    if "observation_date" in df:
        df["observation_date"] = pd.to_datetime(df["observation_date"], errors="coerce")
    for col in ["infiltration_rate_mm_hour", "latitude", "longitude"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "coordinates_verified" in df:
        df["coordinates_verified"] = df["coordinates_verified"].fillna(False).astype(bool)

st.header("📊 Research Dashboard")
st.write("Your original Supabase-backed observations, charts, field map and CSV exports.")
analysis_df = df.copy()
if not analysis_df.empty:
    with st.expander("⚙️ Data filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            exclude_tests = st.checkbox("Exclude test samples (TEST-)", value=True)
        with c2:
            soils = sorted(analysis_df["soil_type"].dropna().astype(str).unique()) if "soil_type" in analysis_df else []
            selected_soils = st.multiselect("Soil types", soils, default=soils)
        with c3:
            slopes = sorted(analysis_df["slope"].dropna().astype(str).unique()) if "slope" in analysis_df else []
            selected_slopes = st.multiselect("Slopes", slopes, default=slopes)
    if exclude_tests and "sample_id" in analysis_df:
        analysis_df = analysis_df[~analysis_df["sample_id"].astype(str).str.upper().str.startswith("TEST-")]
    if "soil_type" in analysis_df:
        analysis_df = analysis_df[analysis_df["soil_type"].isin(selected_soils)] if selected_soils else analysis_df.iloc[0:0]
    if "slope" in analysis_df:
        analysis_df = analysis_df[analysis_df["slope"].isin(selected_slopes)] if selected_slopes else analysis_df.iloc[0:0]

measured = analysis_df["infiltration_rate_mm_hour"].dropna() if "infiltration_rate_mm_hour" in analysis_df else pd.Series(dtype=float)
verified = int(analysis_df["coordinates_verified"].fillna(False).astype(bool).sum()) if "coordinates_verified" in analysis_df else 0
m1, m2, m3, m4 = st.columns(4)
m1.metric("Observations", len(analysis_df))
m2.metric("Measured infiltration", len(measured))
m3.metric("Verified GPS sites", verified)
m4.metric("Mean infiltration (mm/h)", f"{measured[measured >= 0].mean():.2f}" if (measured >= 0).any() else "N/A")

ov, soil_tab, trend_tab, map_tab, data_tab, add_tab = st.tabs(["📈 Overview", "🪨 Soil & Infiltration", "📅 Trends & Statistics", "🗺️ Field Map", "📁 Data & Export", "➕ Add Observation"])
with ov:
    if analysis_df.empty:
        st.info("No records match the current filters yet. Add field observations in the last tab.")
    else:
        c1, c2 = st.columns(2)
        if "soil_type" in analysis_df:
            counts = analysis_df["soil_type"].fillna("Not recorded").value_counts().rename_axis("Soil type").reset_index(name="Observations")
            c1.plotly_chart(px.bar(counts, x="Soil type", y="Observations", title="Observations by Soil Type"), use_container_width=True)
        if "vegetation" in analysis_df:
            counts = analysis_df["vegetation"].fillna("Not recorded").value_counts().rename_axis("Vegetation").reset_index(name="Observations")
            c2.plotly_chart(px.pie(counts, names="Vegetation", values="Observations", title="Vegetation Cover", hole=0.35), use_container_width=True)
        if "slope" in analysis_df:
            counts = analysis_df["slope"].fillna("Not recorded").value_counts().rename_axis("Slope").reset_index(name="Observations")
            st.plotly_chart(px.bar(counts, x="Slope", y="Observations", title="Observations by Slope"), use_container_width=True)
with soil_tab:
    valid = analysis_df.dropna(subset=["infiltration_rate_mm_hour"]).copy() if "infiltration_rate_mm_hour" in analysis_df else pd.DataFrame()
    if not valid.empty:
        valid = valid[valid["infiltration_rate_mm_hour"] >= 0]
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.histogram(valid, x="infiltration_rate_mm_hour", nbins=15, title="Infiltration Rate Distribution"), use_container_width=True)
        if "soil_type" in valid:
            c2.plotly_chart(px.box(valid, x="soil_type", y="infiltration_rate_mm_hour", points="all", title="Infiltration by Soil Type"), use_container_width=True)
            summary = valid.groupby("soil_type", dropna=False)["infiltration_rate_mm_hour"].agg(["count", "mean", "median", "std", "min", "max"]).reset_index()
            st.dataframe(summary.round(3), use_container_width=True, hide_index=True)
        if "slope" in valid:
            st.plotly_chart(px.box(valid, x="slope", y="infiltration_rate_mm_hour", points="all", title="Infiltration by Slope"), use_container_width=True)
        if "vegetation" in valid:
            st.plotly_chart(px.box(valid, x="vegetation", y="infiltration_rate_mm_hour", points="all", title="Infiltration by Vegetation"), use_container_width=True)
    else:
        st.info("No valid infiltration measurements are available.")
with trend_tab:
    if not analysis_df.empty and "observation_date" in analysis_df and "infiltration_rate_mm_hour" in analysis_df:
        td = analysis_df.dropna(subset=["observation_date", "infiltration_rate_mm_hour"]).copy()
        td = td[td["infiltration_rate_mm_hour"] >= 0]
        if not td.empty:
            daily = td.groupby("observation_date")["infiltration_rate_mm_hour"].agg(["mean", "count"]).reset_index()
            st.plotly_chart(px.line(daily, x="observation_date", y="mean", markers=True, title="Mean Infiltration by Date"), use_container_width=True)
            st.dataframe(td.describe(include="all").T, use_container_width=True)
            nums = [x for x in ["infiltration_rate_mm_hour", "latitude", "longitude"] if x in td]
            if len(nums) >= 2 and len(td[nums].dropna()) >= 3:
                st.plotly_chart(px.imshow(td[nums].corr(method="spearman"), text_auto=".2f", zmin=-1, zmax=1, title="Exploratory Spearman Correlation"), use_container_width=True)
        else:
            st.info("Record dates and valid infiltration measurements to view trends.")
    else:
        st.info("Add dated field observations with measured infiltration values.")
with map_tab:
    if not analysis_df.empty and all(c in analysis_df for c in ["latitude", "longitude", "coordinates_verified"]):
        md = analysis_df[analysis_df["coordinates_verified"].fillna(False).astype(bool)].dropna(subset=["latitude", "longitude"]).copy()
        md = md[md["latitude"].between(-90, 90) & md["longitude"].between(-180, 180)]
        if not md.empty:
            fmap = folium.Map(location=[float(md.latitude.mean()), float(md.longitude.mean())], zoom_start=13, control_scale=True)
            for _, r in md.iterrows():
                sample = str(r.get("sample_id", "Unknown"))
                popup = f"Sample: {sample}<br>Location: {r.get('location', 'Unknown')}<br>Soil: {r.get('soil_type', 'Not recorded')}<br>Infiltration: {r.get('infiltration_rate_mm_hour', 'Not measured')}"
                folium.Marker([float(r.latitude), float(r.longitude)], tooltip=sample, popup=folium.Popup(popup, max_width=300)).add_to(fmap)
            st_folium(fmap, use_container_width=True, height=500, key="aquaterra_verified_field_map")
        else:
            st.info("No verified coordinates are available in the filtered data.")
    else:
        st.info("Verified GPS coordinates are needed to display sites.")
with data_tab:
    if not analysis_df.empty:
        st.dataframe(analysis_df, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download filtered observations (CSV)", analysis_df.to_csv(index=False).encode("utf-8"), "aquaterra_field_observations.csv", "text/csv")
    else:
        st.info("No data to export.")
with add_tab:
    st.caption("New records are saved to your existing public.field_observations table.")
    with st.form("new_observation_form", clear_on_submit=True):
        left, right = st.columns(2)
        with left:
            sample_id = st.text_input("Sample ID *").strip()
            obs_date = st.date_input("Observation date", value=date.today())
            location = st.text_input("Location / site name *").strip()
            soil_type = st.selectbox("Soil type", ["Not recorded", "Sandy", "Clayey", "Loamy", "Silty", "Gravelly", "Mixed", "Other"])
            vegetation = st.selectbox("Vegetation cover", ["Not recorded", "Bare ground", "Sparse", "Moderate", "Dense"])
        with right:
            slope = st.selectbox("Land slope", ["Not recorded", "Flat", "Gentle", "Moderate", "Steep"])
            infil_text = st.text_input("Infiltration rate (mm/hour)", placeholder="Leave blank if not measured")
            coords_verified = st.checkbox("I have verified these GPS coordinates", value=False)
            lat = st.number_input("Latitude", min_value=-90.0, max_value=90.0, value=0.0, step=0.000001, format="%.6f")
            lon = st.number_input("Longitude", min_value=-180.0, max_value=180.0, value=0.0, step=0.000001, format="%.6f")
        notes = st.text_area("Field notes / method / conditions")
        save = st.form_submit_button("💾 Save Observation", use_container_width=True)
    if save:
        valid, infil = True, None
        if not sample_id or not location:
            st.error("Sample ID and location are required."); valid = False
        if infil_text.strip():
            try:
                infil = float(infil_text)
                if not math.isfinite(infil) or infil < 0: raise ValueError
            except ValueError:
                st.error("Infiltration must be a finite, non-negative number."); valid = False
        if coords_verified and lat == 0 and lon == 0:
            st.error("Coordinates 0, 0 are not accepted as a verified field location."); valid = False
        if valid:
            record = {"sample_id": sample_id, "observation_date": obs_date.isoformat(), "location": location,
                      "soil_type": None if soil_type == "Not recorded" else soil_type,
                      "vegetation": None if vegetation == "Not recorded" else vegetation,
                      "slope": None if slope == "Not recorded" else slope,
                      "infiltration_rate_mm_hour": infil,
                      "latitude": lat if coords_verified else None, "longitude": lon if coords_verified else None,
                      "coordinates_verified": coords_verified, "notes": notes.strip() or None}
            try:
                db.table("field_observations").insert(record).execute()
                st.success(f"Observation {sample_id} saved."); st.rerun()
            except Exception:
                st.error("Could not save this observation. Check if the Sample ID already exists, table constraints and Cloud logs.")

st.divider()
st.caption("AquaTerra AI is an exploratory research tool. Terrain colours, rainfall estimates and statistical relationships are not proof of groundwater recharge. Validate findings in the field.")
