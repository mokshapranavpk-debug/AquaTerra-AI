
import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import date

# ---------------- PAGE SETUP ----------------
st.set_page_config(
    page_title="JAL-DRISHTI AI",
    page_icon="💧",
    layout="wide"
)

DATA_FILE = Path("field_data.csv")

COLUMNS = [
    "Sample ID", "Observation Date", "Location",
    "Latitude", "Longitude", "Soil Type",
    "Vegetation", "Slope", "Infiltration Rate (mm/hour)",
    "Rainfall Notes", "Additional Notes"
]

# ---------------- DATA STORAGE ----------------
def load_data():
    if DATA_FILE.exists():
        try:
            data = pd.read_csv(DATA_FILE)
            for col in COLUMNS:
                if col not in data.columns:
                    data[col] = None
            return data[COLUMNS]
        except (OSError, ValueError, pd.errors.ParserError):
            st.error(
                "Could not read field_data.csv. "
                "Back up the file before attempting repairs."
            )
            return pd.DataFrame(columns=COLUMNS)

    return pd.DataFrame(columns=COLUMNS)


# ---------------- HEADER ----------------
st.title("💧 JAL-DRISHTI AI")
st.subheader("Groundwater Recharge Research & Mapping")

st.write(
    "A field research platform for recording observations "
    "and investigating groundwater recharge potential."
)

st.info(
    "Research mode: predictions are not enabled yet. "
    "Enter only actual measurements and observations."
)

data = load_data()

# ---------------- OVERVIEW ----------------
a, b, c = st.columns(3)

a.metric("Recorded observations", len(data))
b.metric(
    "Unique sample IDs",
    data["Sample ID"].nunique() if not data.empty else 0
)
c.metric(
    "Locations with coordinates",
    (
        data[["Latitude", "Longitude"]].dropna().shape[0]
        if not data.empty else 0
    )
)

st.divider()

# ---------------- FIELD ENTRY ----------------
st.header("📋 Record Field Observations")

with st.form("field_form", clear_on_submit=True):
    sample_id = st.text_input(
        "Sample ID",
        placeholder="Example: JD-001"
    )

    observation_date = st.date_input(
        "Observation date",
        value=date.today(),
        max_value=date.today()
    )

    location = st.text_input(
        "Location / Site Name",
        placeholder="Give a site name or description"
    )

    st.caption(
        "Coordinates are optional. Enter verified site coordinates "
        "if available; do not guess them."
    )

    col1, col2 = st.columns(2)

    with col1:
        latitude = st.number_input(
            "Latitude",
            min_value=-90.0,
            max_value=90.0,
            value=0.0,
            format="%.6f"
        )

    with col2:
        longitude = st.number_input(
            "Longitude",
            min_value=-180.0,
            max_value=180.0,
            value=0.0,
            format="%.6f"
        )

    coordinates_available = st.checkbox(
        "I have verified these coordinates"
    )

    soil_type = st.selectbox(
        "Observed soil type",
        ["Not assessed", "Sandy", "Loamy", "Clayey",
         "Silty", "Gravelly", "Mixed", "Other"]
    )

    vegetation = st.selectbox(
        "Vegetation cover",
        ["Not assessed", "Sparse", "Moderate", "Dense"]
    )

    slope = st.selectbox(
        "Land slope",
        ["Not assessed", "Flat", "Gentle", "Moderate", "Steep"]
    )

    infiltration = st.number_input(
        "Measured infiltration rate (mm/hour)",
        min_value=0.0,
        value=0.0,
        step=0.5,
        help="Enter a measured value, not an estimate."
    )

    rainfall_notes = st.text_input(
        "Rainfall / recent weather notes"
    )

    notes = st.text_area(
        "Additional field notes",
        placeholder="Surface condition, method used, "
                    "date of measurement, or other observations"
    )

    submitted = st.form_submit_button(
        "Save Field Observation",
        type="primary"
    )

    if submitted:
        if not sample_id.strip() or not location.strip():
            st.error("Sample ID and location are required.")

        elif sample_id.strip() in data["Sample ID"].astype(str).values:
            st.error(
                "This Sample ID already exists. "
                "Use a unique ID for each record."
            )

        elif coordinates_available and latitude == 0 and longitude == 0:
            st.error(
                "Check the coordinates. Both values are zero; "
                "confirm the actual site coordinates before saving."
            )

        else:
            record = {
                "Sample ID": sample_id.strip(),
                "Observation Date": str(observation_date),
                "Location": location.strip(),
                "Latitude": latitude if coordinates_available else None,
                "Longitude": longitude if coordinates_available else None,
                "Soil Type": soil_type,
                "Vegetation": vegetation,
                "Slope": slope,
                "Infiltration Rate (mm/hour)": infiltration,
                "Rainfall Notes": rainfall_notes.strip(),
                "Additional Notes": notes.strip()
            }

            updated = pd.concat(
                [data, pd.DataFrame([record])],
                ignore_index=True
            )

            try:
                updated.to_csv(DATA_FILE, index=False)
                st.success(
                    f"Observation {sample_id.strip()} saved successfully!"
                )
                st.rerun()
            except OSError:
                st.error(
                    "Could not save the file. Check folder permissions "
                    "and make sure the file is not locked."
                )

# ---------------- RECORDS ----------------
st.divider()
st.header("🗂️ Field Research Records")

data = load_data()

if data.empty:
    st.write(
        "No field observations have been saved yet. "
        "You can prepare the system now and enter actual records later."
    )
else:
    st.dataframe(data, use_container_width=True)

    csv_data = data.to_csv(index=False).encode("utf-8")

    st.download_button(
        "⬇️ Download Field Data (CSV)",
        data=csv_data,
        file_name="jal_drishti_field_data.csv",
        mime="text/csv"
    )
st.divider()
st.header("🧭 Upcoming Research Modules")

st.markdown("""
- **Data validation:** check field records for missing or inconsistent values.
- **Recharge assessment:** develop a documented method based on scientific evidence.
- **Site mapping:** plot verified coordinates on a map.
- **AI experimentation:** evaluate a model only when suitable, reliable data
  and an appropriate validation method are available.
""") import html
import hmac
from datetime import date
from functools import partial

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from supabase import create_client


# ======================================================
# CONFIGURATION
# ======================================================
st.set_page_config(
    page_title="JAL-DRISHTI AI",
    page_icon="💧",
    layout="wide",
)

TABLE_NAME = "field_observations"

SOIL_TYPES = [
    "Not assessed", "Sandy", "Loamy", "Clayey",
    "Silty", "Gravelly", "Mixed", "Other"
]

VEGETATION_TYPES = [
    "Not assessed", "Sparse", "Moderate", "Dense"
]

SLOPE_TYPES = [
    "Not assessed", "Flat", "Gentle", "Moderate", "Steep"
]


# ======================================================
# THEME
# ======================================================
st.markdown("""
<style>
.stApp {
    background: linear-gradient(145deg, #0b1220, #102b32);
    color: #edf7fa;
}
.block-container {
    max-width: 1250px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}
h1, h2, h3, h4 {
    color: #f2fafc !important;
}
[data-testid="stMetric"] {
    background: #172d3b;
    border: 1px solid #315361;
    border-radius: 14px;
    padding: 16px;
}
[data-testid="stMetricValue"] {
    color: #63e6d2 !important;
}
[data-testid="stForm"] {
    background: #142636;
    border: 1px solid #294653;
    border-radius: 15px;
    padding: 20px;
}
.stButton button, .stFormSubmitButton button,
.stDownloadButton button {
    border-radius: 10px;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)


# ======================================================
# LOGIN
# ======================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


def check_password():
    entered = st.session_state.get("password_input", "")
    expected = st.secrets.get("APP_PASSWORD", "")

    if expected and hmac.compare_digest(entered, expected):
        st.session_state.authenticated = True
        st.session_state.password_input = ""
    else:
        st.session_state.authenticated = False
        st.session_state.login_error = True


st.markdown("""
<div style="
    background:linear-gradient(120deg,#123441,#174d50);
    border:1px solid #30636a;
    border-radius:20px;
    padding:26px;
    margin-bottom:20px;
">
    <div style="color:#63e6d2;letter-spacing:3px;font-size:12px;">
        STUDENT SCIENTIFIC RESEARCH
    </div>
    <div style="font-size:38px;font-weight:800;color:#f2fafc;">
        💧 JAL-DRISHTI
    </div>
    <div style="font-size:17px;color:#c3e1e4;">
        Groundwater Recharge Research &amp; Mapping
    </div>
</div>
""", unsafe_allow_html=True)

if not st.secrets.get("APP_PASSWORD", ""):
    st.error(
        "APP_PASSWORD is missing from Streamlit Secrets. "
        "Configure it before continuing."
    )
    st.stop()

if not st.session_state.authenticated:
    st.subheader("🔐 Researcher Login")
    st.write("Enter your app password to access the research dashboard.")

    st.text_input(
        "App password",
        type="password",
        key="password_input",
        on_change=check_password,
    )

    if st.session_state.get("login_error", False):
        st.error("Incorrect password. Please try again.")

    if st.button("Unlock JAL-DRISHTI", use_container_width=True):
        check_password()
        if st.session_state.authenticated:
            st.rerun()
        else:
            st.error("Incorrect password.")

    st.caption(
        "Use a strong password and share it only with authorized users."
    )
    st.stop()


# ======================================================
# DATABASE CONNECTION
# ======================================================
@st.cache_resource
def get_database_client(url, key):
    return create_client(url, key)


try:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]

    if not supabase_url.startswith("https://"):
        raise ValueError("The Supabase URL must begin with https://")

    db = get_database_client(supabase_url, supabase_key)

except Exception:
    st.error(
        "Database configuration could not be loaded. "
        "Check SUPABASE_URL and SUPABASE_KEY in Streamlit Secrets."
    )
    st.stop()


# ======================================================
# DATABASE FUNCTIONS
# ======================================================
def fetch_records():
    response = (
        db.table(TABLE_NAME)
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def save_record(record):
    response = (
        db.table(TABLE_NAME)
        .insert(record)
        .execute()
    )
    return response.data


def connection_test():
    db.table(TABLE_NAME).select("sample_id").limit(1).execute()
    return True


def mapped_records(records):
    result = []

    for record in records:
        if not record.get("coordinates_verified"):
            continue

        try:
            lat = float(record["latitude"])
            lon = float(record["longitude"])
        except (TypeError, ValueError):
            continue

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        if lat == 0 and lon == 0:
            continue

        result.append(record)

    return result


def clean(value):
    if value is None or str(value).strip() == "":
        return "Not recorded"
    return str(value)


# ======================================================
# SIDEBAR
# ======================================================
with st.sidebar:
    st.markdown("## 💧 JAL-DRISHTI")
    st.caption("Groundwater research platform")

    st.markdown("---")

    if st.button("🔌 Test database connection", use_container_width=True):
        try:
            connection_test()
            st.success("Database connection successful!")
        except Exception:
            st.error(
                "Connection failed. Check the database settings, "
                "table name, permissions, and Secrets."
            )

    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.login_error = False
        st.rerun()


st.info(
    "Online database mode: observations are stored in Supabase. "
    "This application does not yet generate validated AI predictions."
)


# ======================================================
# LOAD RECORDS
# ======================================================
try:
    records = fetch_records()
except Exception:
    st.error(
        "Could not retrieve records from Supabase. "
        "Check the database connection and table permissions."
    )
    st.stop()

data = pd.DataFrame(records)


# ======================================================
# DASHBOARD
# ======================================================
st.header("📊 Research Overview")

mappable = mapped_records(records)

c1, c2, c3 = st.columns(3)

c1.metric("Saved Records", len(records))
c2.metric(
    "Unique Sample IDs",
    data["sample_id"].nunique() if not data.empty else 0,
)
c3.metric("Verified Mapped Sites", len(mappable))

st.divider()


# ======================================================
# FIELD OBSERVATION FORM
# ======================================================
st.header("📋 Enter Field Observations")

st.write(
    "Enter measurements from your actual field investigation. "
    "Do not enter estimated values as if they were measured."
)

with st.form("observation_form", clear_on_submit=True):
    sample_id = st.text_input(
        "Sample ID",
        placeholder="JD-001",
    )

    observation_date = st.date_input(
        "Observation Date",
        value=date.today(),
    )

    location = st.text_input(
        "Location / Site Name",
        placeholder="Research site name",
    )

    left, right = st.columns(2)

    with left:
        soil_type = st.selectbox("Soil Type", SOIL_TYPES)
        vegetation = st.selectbox(
            "Vegetation Cover", VEGETATION_TYPES
        )

    with right:
        slope = st.selectbox("Land Slope", SLOPE_TYPES)

        has_infiltration = st.checkbox(
            "I have a measured infiltration rate"
        )

        infiltration = st.number_input(
            "Infiltration Rate (mm/hour)",
            min_value=0.0,
            value=0.0,
            step=0.5,
            disabled=not has_infiltration,
        )

    st.subheader("📍 GPS Coordinates")

    coordinates_verified = st.checkbox(
        "I have verified these GPS coordinates"
    )

    gps_left, gps_right = st.columns(2)

    with gps_left:
        latitude = st.number_input(
            "Latitude",
            min_value=-90.0,
            max_value=90.0,
            value=0.0,
            format="%.6f",
            disabled=not coordinates_verified,
        )

    with gps_right:
        longitude = st.number_input(
            "Longitude",
            min_value=-180.0,
            max_value=180.0,
            value=0.0,
            format="%.6f",
            disabled=not coordinates_verified,
        )

    notes = st.text_area(
        "Field Notes",
        placeholder="Sampling conditions and observations...",
    )

    submitted = st.form_submit_button(
        "💾 Save Observation",
        use_container_width=True,
    )


# ======================================================
# VALIDATE AND SAVE
# ======================================================
if submitted:
    cleaned_id = sample_id.strip()
    cleaned_location = location.strip()

    if not cleaned_id or not cleaned_location:
        st.error("Sample ID and location are required.")

    elif coordinates_verified and latitude == 0 and longitude == 0:
        st.error("Please check your GPS coordinates.")

    else:
        record = {
            "sample_id": cleaned_id,
            "observation_date": observation_date.isoformat(),
            "location": cleaned_location,
            "soil_type": soil_type,
            "vegetation": vegetation,
            "slope": slope,
            "infiltration_rate_mm_hour": (
                float(infiltration) if has_infiltration else None
            ),
            "latitude": float(latitude) if coordinates_verified else None,
            "longitude": float(longitude) if coordinates_verified else None,
            "coordinates_verified": bool(coordinates_verified),
            "notes": notes.strip() or None,
        }

        try:
            save_record(record)
            st.success(
                f"Observation {cleaned_id} saved to the online database!"
            )
            st.rerun()

        except Exception as error:
            # Do not expose server responses or credentials in the UI.
            error_text = str(error).lower()

            if (
                "duplicate key" in error_text
                or "23505" in error_text
            ):
                st.error(
                    "That Sample ID already exists. "
                    "Please choose a unique ID."
                )
            else:
                st.error(
                    "The observation could not be saved. "
                    "Check the database connection, table columns, "
                    "and database permissions."
                )


st.divider()


# ======================================================
# SAVED RECORDS
# ======================================================
st.header("🗂️ Saved Field Records")

if not records:
    st.info("No observations saved yet.")

else:
    display_columns = {
        "sample_id": "Sample ID",
        "observation_date": "Date",
        "location": "Location",
        "soil_type": "Soil Type",
        "vegetation": "Vegetation",
        "slope": "Slope",
        "infiltration_rate_mm_hour": "Infiltration Rate (mm/hour)",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "coordinates_verified": "GPS Verified",
        "notes": "Notes",
    }

    display_data = data[
        [col for col in display_columns if col in data.columns]
    ].rename(columns=display_columns)

    st.dataframe(
        display_data,
        use_container_width=True,
        hide_index=True,
    )

    st.download_button(
        "⬇️ Download Field Records (CSV)",
        data=display_data.to_csv(index=False).encode("utf-8"),
        file_name="jal_drishti_field_data.csv",
        mime="text/csv",
    )


st.divider()


# ======================================================
# INTERACTIVE MAP
# ======================================================
st.header("🗺️ Interactive Groundwater Mapping")

if not mappable:
    st.info(
        "No verified GPS sites are available yet. "
        "Save an observation with verified coordinates to map it."
    )

else:
    center_lat = sum(
        float(r["latitude"]) for r in mappable
    ) / len(mappable)

    center_lon = sum(
        float(r["longitude"]) for r in mappable
    ) / len(mappable)

    research_map = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=14,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    for site in mappable:
        sample = html.escape(clean(site.get("sample_id")))
        location_name = html.escape(clean(site.get("location")))
        soil = html.escape(clean(site.get("soil_type")))
        vegetation = html.escape(clean(site.get("vegetation")))
        slope_value = html.escape(clean(site.get("slope")))

        rate = site.get("infiltration_rate_mm_hour")
        rate_text = (
            f"{float(rate):g} mm/hour"
            if rate is not None else "Not recorded"
        )

        popup = f"""
        <div style="font-family:Arial,sans-serif;width:230px;">
            <h3>💧 {sample}</h3>
            <b>Site:</b> {location_name}<br>
            <b>Soil:</b> {soil}<br>
            <b>Vegetation:</b> {vegetation}<br>
            <b>Slope:</b> {slope_value}<br>
            <b>Infiltration:</b> {rate_text}<br>
            <b>Latitude:</b> {float(site['latitude']):.6f}<br>
            <b>Longitude:</b> {float(site['longitude']):.6f}
        </div>
        """

        folium.Marker(
            location=[
                float(site["latitude"]),
                float(site["longitude"]),
            ],
            tooltip=f"Site: {sample}",
            popup=folium.Popup(popup, max_width=320),
            icon=folium.Icon(color="cadetblue", icon="tint"),
        ).add_to(research_map)

    st_folium(
        research_map,
        height=520,
        use_container_width=True,
        key="jal_drishti_map",
    )


st.divider()

st.caption(
    "JAL-DRISHTI | Supabase persistent storage | "
    "Field observations and mapping; AI predictions not yet validated."
)

st.caption(
    "Important: soil type, vegetation and slope alone do not establish "
    "groundwater recharge rates. This app currently records observations; "
    "it does not predict groundwater recharge."
)
