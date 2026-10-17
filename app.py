
import hmac
import math
from datetime import date

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium
from supabase import create_client


# ============================================================
# JAL-DRISHTI | ADVANCED SCIENTIFIC DASHBOARD
# Existing Supabase table: public.field_observations
# ============================================================

st.set_page_config(
    page_title="JAL-DRISHTI | Research Dashboard",
    page_icon="💧",
    layout="wide",
)

st.title("💧 JAL-DRISHTI")
st.subheader("Advanced Groundwater Recharge Research Dashboard")
st.caption(
    "AI-assisted mapping • Field observations • Statistical exploration"
)


# ============================================================
# SECRETS
# ============================================================

try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    APP_PASSWORD = str(st.secrets["APP_PASSWORD"])
except Exception:
    st.error(
        "Required secrets are missing. Configure SUPABASE_URL, "
        "SUPABASE_KEY and APP_PASSWORD in Streamlit Cloud → "
        "App settings → Secrets."
    )
    st.stop()

if not SUPABASE_URL or not SUPABASE_KEY or not APP_PASSWORD:
    st.error("One or more required secrets are empty.")
    st.stop()


# ============================================================
# DATABASE
# ============================================================

@st.cache_resource
def get_database_client(url, key):
    return create_client(url, key)


try:
    db = get_database_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    st.error(
        "Could not initialise Supabase. Check your project URL "
        "and private server-side key in Streamlit Secrets."
    )
    st.stop()


def load_observations():
    """Fetch all observations in pages rather than only the first page."""
    records = []
    page_size = 1000
    start = 0

    while True:
        response = (
            db.table("field_observations")
            .select("*")
            .order("created_at", desc=True)
            .range(start, start + page_size - 1)
            .execute()
        )

        batch = response.data or []
        records.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return records


# ============================================================
# PASSWORD PROTECTION
# ============================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("### 🔐 Secure Research Login")

    with st.form("login_form"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button(
            "Log in",
            use_container_width=True,
        )

    if submitted:
        if hmac.compare_digest(password, APP_PASSWORD):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    st.stop()


# ============================================================
# SIDEBAR CONTROLS
# ============================================================

with st.sidebar:
    st.title("💧 JAL-DRISHTI")
    st.caption("Scientific research workspace")
    st.divider()

    if st.button("🔄 Refresh database", use_container_width=True):
        st.rerun()

    if st.button("🔌 Test database connection", use_container_width=True):
        try:
            db.table("field_observations").select("sample_id").limit(1).execute()
            st.success("Supabase connection successful.")
        except Exception:
            st.error(
                "Connection failed. Check Streamlit Cloud logs "
                "and Supabase permissions."
            )

    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.divider()
    st.caption("Only use verified measurements for research conclusions.")


# ============================================================
# LOAD DATA
# ============================================================

try:
    records = load_observations()
except Exception:
    st.error(
        "Could not retrieve observations from Supabase. "
        "Check your connection, table permissions and Cloud logs."
    )
    st.stop()

if not records:
    st.info(
        "Your database is connected, but no observations have been saved. "
        "Add field observations below to populate the dashboard."
    )
    df = pd.DataFrame()
else:
    df = pd.DataFrame(records)

    # Normalise columns without changing the database schema.
    if "observation_date" in df.columns:
        df["observation_date"] = pd.to_datetime(
            df["observation_date"], errors="coerce"
        )

    numeric_columns = [
        "infiltration_rate_mm_hour",
        "latitude",
        "longitude",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "coordinates_verified" in df.columns:
        df["coordinates_verified"] = (
            df["coordinates_verified"].fillna(False).astype(bool)
        )


# ============================================================
# FILTERS
# ============================================================

st.header("📊 Research Overview")

analysis_df = df.copy()

if not analysis_df.empty:
    with st.expander("⚙️ Data filters", expanded=True):
        filter1, filter2, filter3 = st.columns(3)

        with filter1:
            exclude_tests = st.checkbox(
                "Exclude test samples (IDs beginning TEST-)",
                value=True,
            )

        with filter2:
            soil_values = sorted(
                analysis_df["soil_type"].dropna().astype(str).unique()
            ) if "soil_type" in analysis_df else []

            selected_soils = st.multiselect(
                "Soil types",
                options=soil_values,
                default=soil_values,
            )

        with filter3:
            slope_values = sorted(
                analysis_df["slope"].dropna().astype(str).unique()
            ) if "slope" in analysis_df else []

            selected_slopes = st.multiselect(
                "Slopes",
                options=slope_values,
                default=slope_values,
            )

    if exclude_tests and "sample_id" in analysis_df.columns:
        test_mask = analysis_df["sample_id"].astype(str).str.upper().str.startswith("TEST-")
        analysis_df = analysis_df[~test_mask]

    if "soil_type" in analysis_df.columns:
        if selected_soils:
            analysis_df = analysis_df[
                analysis_df["soil_type"].isin(selected_soils)
            ]
        else:
            analysis_df = analysis_df.iloc[0:0]

    if "slope" in analysis_df.columns:
        if selected_slopes:
            analysis_df = analysis_df[
                analysis_df["slope"].isin(selected_slopes)
            ]
        else:
            analysis_df = analysis_df.iloc[0:0]


# ============================================================
# METRICS
# ============================================================

if not analysis_df.empty:
    measured = analysis_df[
        "infiltration_rate_mm_hour"
    ].dropna() if "infiltration_rate_mm_hour" in analysis_df else pd.Series(dtype=float)

    verified_sites = (
        analysis_df["coordinates_verified"].fillna(False).astype(bool).sum()
        if "coordinates_verified" in analysis_df
        else 0
    )

    m1, m2, m3, m4 = st.columns(4)

    m1.metric("Observations", len(analysis_df))
    m2.metric("Measured infiltration", len(measured))
    m3.metric("Verified GPS sites", int(verified_sites))
    m4.metric(
        "Mean infiltration (mm/h)",
        f"{measured.mean():.2f}" if len(measured) else "N/A",
    )

    st.caption(
        "Metrics reflect the current filters. Missing measurements are "
        "excluded from infiltration calculations."
    )
else:
    st.warning(
        "No observations match the current filters. Change the filters "
        "or save additional observations."
    )


# ============================================================
# ANALYTICS TABS
# ============================================================

overview_tab, soil_tab, trends_tab, stats_tab, map_tab, data_tab = st.tabs(
    [
        "📈 Overview",
        "🪨 Soil & Infiltration",
        "📅 Trends",
        "🧮 Statistics",
        "🗺️ Field Map",
        "📁 Data & Export",
    ]
)


# ------------------------------------------------------------
# OVERVIEW
# ------------------------------------------------------------

with overview_tab:
    st.subheader("Observation Composition")

    if analysis_df.empty:
        st.info("Save observations to generate graphs.")
    else:
        chart1, chart2 = st.columns(2)

        with chart1:
            if "soil_type" in analysis_df.columns:
                soil_counts = (
                    analysis_df["soil_type"]
                    .fillna("Not recorded")
                    .value_counts()
                    .rename_axis("Soil type")
                    .reset_index(name="Observations")
                )

                fig = px.bar(
                    soil_counts,
                    x="Soil type",
                    y="Observations",
                    title="Observations by Soil Type",
                    text="Observations",
                )
                fig.update_layout(xaxis_title="", yaxis_title="Count")
                st.plotly_chart(fig, use_container_width=True)

        with chart2:
            if "vegetation" in analysis_df.columns:
                vegetation_counts = (
                    analysis_df["vegetation"]
                    .fillna("Not recorded")
                    .value_counts()
                    .rename_axis("Vegetation")
                    .reset_index(name="Observations")
                )

                fig = px.pie(
                    vegetation_counts,
                    names="Vegetation",
                    values="Observations",
                    title="Vegetation Cover Distribution",
                    hole=0.35,
                )
                st.plotly_chart(fig, use_container_width=True)

        if "slope" in analysis_df.columns:
            slope_counts = (
                analysis_df["slope"]
                .fillna("Not recorded")
                .value_counts()
                .rename_axis("Slope")
                .reset_index(name="Observations")
            )

            fig = px.bar(
                slope_counts,
                x="Slope",
                y="Observations",
                title="Observations by Land Slope",
                color="Slope",
            )
            st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------
# SOIL AND INFILTRATION
# ------------------------------------------------------------

with soil_tab:
    st.subheader("Soil and Infiltration Analysis")

    if "infiltration_rate_mm_hour" not in analysis_df.columns:
        st.info("No infiltration measurements are available.")
    else:
        infiltration_df = analysis_df.dropna(
            subset=["infiltration_rate_mm_hour"]
        ).copy()

        infiltration_df = infiltration_df[
            infiltration_df["infiltration_rate_mm_hour"] >= 0
        ]

        if infiltration_df.empty:
            st.info(
                "No valid infiltration measurements match the current filters."
            )
        else:
            c1, c2 = st.columns(2)

            with c1:
                fig = px.histogram(
                    infiltration_df,
                    x="infiltration_rate_mm_hour",
                    nbins=15,
                    title="Distribution of Infiltration Rates",
                    labels={
                        "infiltration_rate_mm_hour": "Infiltration (mm/hour)"
                    },
                )
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                if "soil_type" in infiltration_df.columns:
                    fig = px.box(
                        infiltration_df,
                        x="soil_type",
                        y="infiltration_rate_mm_hour",
                        points="all",
                        title="Infiltration Rate by Soil Type",
                        labels={
                            "soil_type": "Soil type",
                            "infiltration_rate_mm_hour": "Infiltration (mm/hour)",
                        },
                    )
                    st.plotly_chart(fig, use_container_width=True)

            if "soil_type" in infiltration_df.columns:
                soil_summary = (
                    infiltration_df.groupby("soil_type", dropna=False)
                    ["infiltration_rate_mm_hour"]
                    .agg(["count", "mean", "median", "std", "min", "max"])
                    .reset_index()
                    .rename(
                        columns={
                            "soil_type": "Soil type",
                            "count": "Sample count",
                            "mean": "Mean (mm/h)",
                            "median": "Median (mm/h)",
                            "std": "Standard deviation",
                            "min": "Minimum (mm/h)",
                            "max": "Maximum (mm/h)",
                        }
                    )
                )

                st.markdown("#### Group Summary")
                st.dataframe(
                    soil_summary.round(3),
                    use_container_width=True,
                    hide_index=True,
                )

            if "slope" in infiltration_df.columns:
                fig = px.box(
                    infiltration_df,
                    x="slope",
                    y="infiltration_rate_mm_hour",
                    points="all",
                    title="Infiltration Rate by Slope Category",
                    labels={
                        "slope": "Slope",
                        "infiltration_rate_mm_hour": "Infiltration (mm/hour)",
                    },
                )
                st.plotly_chart(fig, use_container_width=True)

            if "vegetation" in infiltration_df.columns:
                fig = px.box(
                    infiltration_df,
                    x="vegetation",
                    y="infiltration_rate_mm_hour",
                    points="all",
                    title="Infiltration Rate by Vegetation Cover",
                    labels={
                        "vegetation": "Vegetation cover",
                        "infiltration_rate_mm_hour": "Infiltration (mm/hour)",
                    },
                )
                st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------
# TRENDS
# ------------------------------------------------------------

with trends_tab:
    st.subheader("Observation Trends")

    if (
        not analysis_df.empty
        and "observation_date" in analysis_df.columns
        and "infiltration_rate_mm_hour" in analysis_df.columns
    ):
        trend_df = analysis_df.dropna(
            subset=["observation_date", "infiltration_rate_mm_hour"]
        ).copy()

        trend_df = trend_df[
            trend_df["infiltration_rate_mm_hour"] >= 0
        ]

        if trend_df.empty:
            st.info(
                "Record dates and infiltration measurements to view trends."
            )
        else:
            daily = (
                trend_df.groupby("observation_date")
                ["infiltration_rate_mm_hour"]
                .agg(["mean", "count"])
                .reset_index()
            )

            fig = px.line(
                daily,
                x="observation_date",
                y="mean",
                markers=True,
                title="Mean Infiltration Rate by Observation Date",
                labels={
                    "observation_date": "Observation date",
                    "mean": "Mean infiltration (mm/hour)",
                },
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "Dates with multiple measurements show the daily mean. "
                "This is not a groundwater-level or recharge-rate time series."
            )

            if "sample_id" in trend_df.columns:
                fig = px.scatter(
                    trend_df,
                    x="observation_date",
                    y="infiltration_rate_mm_hour",
                    color="soil_type" if "soil_type" in trend_df else None,
                    hover_name="sample_id",
                    title="Individual Infiltration Measurements Over Time",
                    labels={
                        "observation_date": "Observation date",
                        "infiltration_rate_mm_hour": "Infiltration (mm/hour)",
                        "soil_type": "Soil type",
                    },
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Add dated field observations with infiltration measurements.")


# ------------------------------------------------------------
# STATISTICS AND CORRELATIONS
# ------------------------------------------------------------

with stats_tab:
    st.subheader("Descriptive Statistics")

    numeric_for_stats = [
        column
        for column in [
            "infiltration_rate_mm_hour",
            "latitude",
            "longitude",
        ]
        if column in analysis_df.columns
    ]

    if not analysis_df.empty and numeric_for_stats:
        stats_df = analysis_df[numeric_for_stats].copy()

        if "infiltration_rate_mm_hour" in stats_df:
            stats_df.loc[
                stats_df["infiltration_rate_mm_hour"] < 0,
                "infiltration_rate_mm_hour",
            ] = float("nan")

        summary = stats_df.describe().T.reset_index()
        summary = summary.rename(columns={"index": "Variable"})

        st.dataframe(
            summary.round(4),
            use_container_width=True,
            hide_index=True,
        )

        if "infiltration_rate_mm_hour" in stats_df.columns:
            values = stats_df["infiltration_rate_mm_hour"].dropna()

            if len(values) >= 2:
                st.markdown("#### Infiltration Distribution")

                q1 = values.quantile(0.25)
                q3 = values.quantile(0.75)

                a, b, c, d = st.columns(4)
                a.metric("Median (mm/h)", f"{values.median():.2f}")
                b.metric("Standard deviation", f"{values.std():.2f}")
                c.metric("25th percentile", f"{q1:.2f}")
                d.metric("75th percentile", f"{q3:.2f}")

        # Correlations are exploratory and require enough paired observations.
        corr_columns = [
            column
            for column in [
                "infiltration_rate_mm_hour",
                "latitude",
                "longitude",
            ]
            if column in stats_df.columns
        ]

        if len(corr_columns) >= 2:
            corr_data = stats_df[corr_columns].dropna()

            if len(corr_data) >= 3:
                correlation = corr_data.corr(method="spearman")

                fig = px.imshow(
                    correlation,
                    text_auto=".2f",
                    zmin=-1,
                    zmax=1,
                    color_continuous_scale="RdBu",
                    title="Spearman Rank Correlation (Exploratory)",
                    aspect="auto",
                )
                st.plotly_chart(fig, use_container_width=True)

                st.caption(
                    "Correlation ranges from -1 to +1. Correlation does not "
                    "establish causation. Spatial correlations can be "
                    "misleading when there are few sites or clustered samples."
                )
            else:
                st.info(
                    "At least three complete paired observations are needed "
                    "for the exploratory correlation chart."
                )

        st.markdown("#### Sample Size Warnings")

        if "infiltration_rate_mm_hour" in analysis_df.columns:
            valid_n = analysis_df[
                "infiltration_rate_mm_hour"
            ].notna().sum()

            if valid_n < 5:
                st.warning(
                    f"Only {valid_n} infiltration measurement(s) are available. "
                    "Treat all patterns as preliminary; collect more samples."
                )
            else:
                st.write(
                    f"{valid_n} infiltration measurements are available. "
                    "Interpret results in light of the sampling method, "
                    "site variation and measurement uncertainty."
                )
    else:
        st.info("Numeric field data are needed for statistical analysis.")


# ------------------------------------------------------------
# VERIFIED FIELD MAP
# ------------------------------------------------------------

with map_tab:
    st.subheader("Verified Field-Site Map")

    if (
        not analysis_df.empty
        and "coordinates_verified" in analysis_df.columns
        and "latitude" in analysis_df.columns
        and "longitude" in analysis_df.columns
    ):
        map_df = analysis_df[
            analysis_df["coordinates_verified"].fillna(False).astype(bool)
        ].copy()

        map_df = map_df.dropna(subset=["latitude", "longitude"])

        map_df = map_df[
            map_df["latitude"].between(-90, 90)
            & map_df["longitude"].between(-180, 180)
        ]

        if not map_df.empty:
            center_lat = float(map_df["latitude"].mean())
            center_lon = float(map_df["longitude"].mean())

            field_map = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=11,
                control_scale=True,
            )

            for _, row in map_df.iterrows():
                sample = str(row.get("sample_id", "Unknown"))
                location = str(row.get("location", "Unknown"))
                soil = str(row.get("soil_type") or "Not recorded")
                infiltration = row.get("infiltration_rate_mm_hour")

                infiltration_label = (
                    f"{infiltration:.2f} mm/hour"
                    if pd.notna(infiltration)
                    else "Not measured"
                )

                popup_html = (
                    f"<b>Sample:</b> {sample}<br>"
                    f"<b>Location:</b> {location}<br>"
                    f"<b>Soil:</b> {soil}<br>"
                    f"<b>Infiltration:</b> {infiltration_label}"
                )

                folium.Marker(
                    [float(row["latitude"]), float(row["longitude"])],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=sample,
                ).add_to(field_map)

            st_folium(
                field_map,
                use_container_width=True,
                height=500,
                key="jal_drishti_field_map",
            )

            st.caption(
                "Only observations marked as coordinate-verified are shown. "
                "Check every location against the original field record."
            )
        else:
            st.info(
                "No verified coordinates are available in the filtered data."
            )
    else:
        st.info("Save observations with verified coordinates to create a map.")


# ------------------------------------------------------------
# DATA TABLE AND EXPORT
# ------------------------------------------------------------

with data_tab:
    st.subheader("Research Dataset")

    if not analysis_df.empty:
        st.dataframe(
            analysis_df,
            use_container_width=True,
            hide_index=True,
        )

        csv_bytes = analysis_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "⬇️ Download filtered dataset (CSV)",
            data=csv_bytes,
            file_name="jal_drishti_field_observations.csv",
            mime="text/csv",
            use_container_width=True,
        )

        if "infiltration_rate_mm_hour" in analysis_df.columns:
            measured = analysis_df.dropna(
                subset=["infiltration_rate_mm_hour"]
            )

            if not measured.empty and "soil_type" in measured.columns:
                report = (
                    measured.groupby("soil_type", dropna=False)
                    ["infiltration_rate_mm_hour"]
                    .agg(["count", "mean", "median", "std", "min", "max"])
                    .reset_index()
                )

                st.download_button(
                    "⬇️ Download soil summary (CSV)",
                    data=report.to_csv(index=False).encode("utf-8"),
                    file_name="jal_drishti_soil_summary.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    else:
        st.info("There are no observations to export with the current filters.")


# ============================================================
# ADD OBSERVATION FORM
# ============================================================

st.divider()
st.header("🧪 Add a Field Observation")
st.caption("New records are saved directly to your existing Supabase table.")

with st.form("new_observation_form", clear_on_submit=True):
    left, right = st.columns(2)

    with left:
        sample_id = st.text_input(
            "Sample ID *",
            placeholder="e.g. JD-001",
        ).strip()

        observation_date = st.date_input(
            "Observation date",
            value=date.today(),
        )

        location = st.text_input(
            "Location / site name *",
        ).strip()

        soil_type = st.selectbox(
            "Soil type",
            [
                "Not recorded",
                "Sandy",
                "Clayey",
                "Loamy",
                "Silty",
                "Gravelly",
                "Mixed",
                "Other",
            ],
        )

        vegetation = st.selectbox(
            "Vegetation cover",
            [
                "Not recorded",
                "Bare ground",
                "Sparse",
                "Moderate",
                "Dense",
            ],
        )

    with right:
        slope = st.selectbox(
            "Land slope",
            [
                "Not recorded",
                "Flat",
                "Gentle",
                "Moderate",
                "Steep",
            ],
        )

        infiltration_text = st.text_input(
            "Infiltration rate (mm/hour)",
            placeholder="Leave blank if not measured",
        )

        coordinates_verified = st.checkbox(
            "I have verified these GPS coordinates",
            value=False,
        )

        latitude = st.number_input(
            "Latitude",
            min_value=-90.0,
            max_value=90.0,
            value=0.0,
            step=0.000001,
            format="%.6f",
        )

        longitude = st.number_input(
            "Longitude",
            min_value=-180.0,
            max_value=180.0,
            value=0.0,
            step=0.000001,
            format="%.6f",
        )

    notes = st.text_area("Field notes / method / conditions")

    save_clicked = st.form_submit_button(
        "💾 Save Observation",
        use_container_width=True,
    )


if save_clicked:
    valid_input = True
    infiltration_rate = None

    if not sample_id or not location:
        st.error("Sample ID and location are required.")
        valid_input = False

    if infiltration_text.strip():
        try:
            infiltration_rate = float(infiltration_text)

            if (
                not math.isfinite(infiltration_rate)
                or infiltration_rate < 0
            ):
                raise ValueError

        except ValueError:
            st.error("Infiltration must be a finite, non-negative number.")
            valid_input = False

    if coordinates_verified and latitude == 0 and longitude == 0:
        st.error(
            "Coordinates 0, 0 are not accepted as a verified field location."
        )
        valid_input = False

    if valid_input:
        record = {
            "sample_id": sample_id,
            "observation_date": observation_date.isoformat(),
            "location": location,
            "soil_type": None if soil_type == "Not recorded" else soil_type,
            "vegetation": None if vegetation == "Not recorded" else vegetation,
            "slope": None if slope == "Not recorded" else slope,
            "infiltration_rate_mm_hour": infiltration_rate,
            "latitude": latitude if coordinates_verified else None,
            "longitude": longitude if coordinates_verified else None,
            "coordinates_verified": coordinates_verified,
            "notes": notes.strip() or None,
        }

        try:
            db.table("field_observations").insert(record).execute()
            st.success(f"Observation {sample_id} saved successfully.")
            st.rerun()
        except Exception:
            st.error(
                "Could not save this observation. The Sample ID may already "
                "exist, or the database may be unavailable. Check the "
                "Streamlit Cloud logs for the detailed error."
            )


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.caption(
    "JAL-DRISHTI | Exploratory research tool. Statistical patterns are "
    "not proof of groundwater recharge. Use verified measurements, "
    "document methods and validate findings in the field."
)
