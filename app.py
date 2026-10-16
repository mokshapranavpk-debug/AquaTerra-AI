
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
""")

st.caption(
    "Important: soil type, vegetation and slope alone do not establish "
    "groundwater recharge rates. This app currently records observations; "
    "it does not predict groundwater recharge."
)
