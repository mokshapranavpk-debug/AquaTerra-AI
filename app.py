
import hmac
from datetime import date

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from supabase import create_client


# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------
st.set_page_config(
    page_title="JAL-DRISHTI",
    page_icon="💧",
    layout="wide",
)

st.title("💧 JAL-DRISHTI")
st.subheader("AI-Assisted Mapping of Groundwater Recharge")
st.caption("Groundwater field observation and data management system")

# --------------------------------------------------
# LOAD PRIVATE SETTINGS
# --------------------------------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
except Exception:
    st.error(
        "App configuration is incomplete. "
        "Check SUPABASE_URL, SUPABASE_KEY and APP_PASSWORD "
        "in Streamlit Cloud → App settings → Secrets."
    )
    st.stop()

if not SUPABASE_URL or not SUPABASE_KEY or not APP_PASSWORD:
    st.error("One or more required secrets are empty.")
    st.stop()


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------
@st.cache_resource
def get_database_client(url, key):
    return create_client(url, key)


try:
    db = get_database_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    st.error(
        "Could not initialise the database client. "
        "Check your Supabase URL and private server-side key."
    )
    st.stop()


# --------------------------------------------------
# PASSWORD GATE
# --------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("### 🔐 Secure Login")
    st.write("Enter the app password to access field observations.")

    with st.form("login_form"):
        entered_password = st.text_input(
            "App password",
            type="password",
        )
        login_clicked = st.form_submit_button(
            "Log in",
            use_container_width=True,
        )

    if login_clicked:
        if hmac.compare_digest(
            entered_password,
            str(APP_PASSWORD),
        ):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")

    st.stop()


# --------------------------------------------------
# DATABASE HELPERS
# --------------------------------------------------
TABLE_NAME = "field_observations"


def load_observations():
    response = (
        db.table(TABLE_NAME)
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------
with st.sidebar:
    st.header("JAL-DRISHTI")
    st.write("Groundwater Research Dashboard")
    st.divider()

    if st.button("🔌 Test database connection", use_container_width=True):
        try:
            db.table(TABLE_NAME).select("sample_id").limit(1).execute()
            st.success("Database connection successful!")
        except Exception:
            st.error(
                "Connection test failed. Check your Streamlit Cloud "
                "logs and Supabase table permissions."
            )

    if st.button("Log out", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.caption("Store only verified field measurements.")


# --------------------------------------------------
# NEW FIELD OBSERVATION
# --------------------------------------------------
st.header("🧪 Add Field Observation")

with st.form("observation_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        sample_id = st.text_input(
            "Sample ID *",
            placeholder="e.g. JD-001",
        ).strip()

        observation_date = st.date_input(
            "Observation date",
            value=date.today(),
        )

        location = st.text_input(
            "Location / Site name *",
            placeholder="Enter your field site",
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

    with col2:
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

    notes = st.text_area(
        "Field notes",
        placeholder="Describe the site, sampling method, weather, "
                    "or other relevant observations.",
    )

    save_clicked = st.form_submit_button(
        "💾 Save Observation",
        use_container_width=True,
    )


# --------------------------------------------------
# VALIDATE AND SAVE
# --------------------------------------------------
if save_clicked:
    if not sample_id or not location:
        st.error("Please enter both a Sample ID and a Location.")
    else:
        infiltration_rate = None
        valid_input = True

        if infiltration_text.strip():
            try:
                infiltration_rate = float(infiltration_text)

                if (
                    not pd.notna(infiltration_rate)
                    or infiltration_rate < 0
                    or infiltration_rate == float("inf")
                    or infiltration_rate == float("-inf")
                ):
                    raise ValueError

            except ValueError:
                st.error(
                    "Infiltration rate must be a valid non-negative number."
                )
                valid_input = False

        if coordinates_verified and latitude == 0 and longitude == 0:
            st.error(
                "The coordinates are 0, 0. Enter the actual verified "
                "coordinates or untick the verification box."
            )
            valid_input = False

        if valid_input:
            record = {
                "sample_id": sample_id,
                "observation_date": observation_date.isoformat(),
                "location": location,
                "soil_type": (
                    None if soil_type == "Not recorded" else soil_type
                ),
                "vegetation": (
                    None if vegetation == "Not recorded" else vegetation
                ),
                "slope": (
                    None if slope == "Not recorded" else slope
                ),
                "infiltration_rate_mm_hour": infiltration_rate,
                "latitude": latitude if coordinates_verified else None,
                "longitude": longitude if coordinates_verified else None,
                "coordinates_verified": coordinates_verified,
                "notes": notes.strip() or None,
            }

            try:
                db.table(TABLE_NAME).insert(record).execute()
                st.success(
                    f"Observation {sample_id} saved successfully!"
                )
                st.rerun()

            except Exception:
                st.error(
                    "The observation could not be saved. The Sample ID "
                    "may already exist, or the database may be unavailable. "
                    "Check the Streamlit Cloud logs for details."
                )


# --------------------------------------------------
# VIEW STORED OBSERVATIONS
# --------------------------------------------------
st.divider()
st.header("📊 Stored Field Observations")

try:
    observations = load_observations()
except Exception:
    st.error(
        "Could not load observations. Check your database connection "
        "and table permissions."
    )
    observations = []

if observations:
    df = pd.DataFrame(observations)

    metric1, metric2, metric3 = st.columns(3)

    metric1.metric("Total observations", len(df))

    metric2.metric(
        "Verified GPS sites",
        int(
            df["coordinates_verified"].fillna(False).astype(bool).sum()
        ),
    )

    metric3.metric(
        "Measured infiltration rates",
        int(df["infiltration_rate_mm_hour"].notna().sum()),
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
    )

    csv_data = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "⬇️ Download observations as CSV",
        data=csv_data,
        file_name="jal_drishti_observations.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # --------------------------------------------------
    # VERIFIED LOCATION MAP
    # --------------------------------------------------
    st.subheader("🗺️ Verified Field Locations")

    if "coordinates_verified" in df.columns:
        map_df = df[
            df["coordinates_verified"].fillna(False).astype(bool)
        ].copy()

        if not map_df.empty:
            map_df = map_df.dropna(
                subset=["latitude", "longitude"]
            )

            map_df = map_df[
                map_df["latitude"].between(-90, 90)
                & map_df["longitude"].between(-180, 180)
            ]

        if not map_df.empty:
            center_lat = float(map_df["latitude"].mean())
            center_lon = float(map_df["longitude"].mean())

            field_map = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=12,
            )

            for _, row in map_df.iterrows():
                popup_text = (
                    f"Sample: {row['sample_id']} | "
                    f"Location: {row['location']}"
                )

                folium.Marker(
                    location=[
                        float(row["latitude"]),
                        float(row["longitude"]),
                    ],
                    popup=popup_text,
                    tooltip=str(row["sample_id"]),
                ).add_to(field_map)

            st_folium(
                field_map,
                use_container_width=True,
                height=450,
            )
        else:
            st.info(
                "No verified GPS locations are available yet. "
                "Verify coordinates when recording a field observation."
            )

else:
    st.info(
        "No observations have been saved yet. Add your first field "
        "observation above to begin building your dataset."
    )

st.divider()
st.caption(
    "JAL-DRISHTI | Research observations should be measured, "
    "recorded accurately and verified before analysis."
)
