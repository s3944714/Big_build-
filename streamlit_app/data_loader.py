"""
Data loading for the dashboard. This app reads exported flat files, not a live Databricks
connection - see the architecture note in CLAUDE.md. Nothing here talks to Databricks.
"""
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parent / "data"
GOLD_TABLE_PATH = DATA_DIR / "gold_lga_priority.csv"
BOUNDARIES_PATH = DATA_DIR / "vic_lga_boundaries.geojson"


def _normalize_lga_name(raw_name: str) -> str:
    """Same normalisation used throughout the Databricks pipeline (02_silver_feature_table.py,
    03_clustering.py): strip a trailing council-type suffix group, upper case. Kept as its own
    small function here rather than imported from the notebooks, since this app has no
    dependency on the Databricks code at runtime."""
    name = re.sub(r"(\s*\([A-Za-z.]+\))+$", "", str(raw_name)).strip().upper()
    return BOUNDARY_NAME_OVERRIDES.get(name, name)


# Confirmed by inspecting the actual downloaded GeoJSON: this ABS boundary file spells
# Colac-Otway with a space, not a hyphen - VIF (the canonical source) uses the hyphen. Same
# class of issue as the crash-data naming mismatches fixed in Process 2 - an explicit override
# rather than a cleverer regex, since it's a genuinely arbitrary difference between two
# separate government/statistical agencies, not a systematic pattern.
BOUNDARY_NAME_OVERRIDES = {
    "COLAC OTWAY": "COLAC-OTWAY",
}


@st.cache_data
def load_gold_table() -> pd.DataFrame:
    if not GOLD_TABLE_PATH.exists():
        st.error(
            f"Missing `{GOLD_TABLE_PATH.relative_to(DATA_DIR.parent)}`.\n\n"
            "Export it from Databricks: run "
            "`spark.table(f\"{catalog}.{schema}.gold_lga_priority\").toPandas()` "
            "in `03_clustering.py`, use the cell output's Download button (CSV), and save it "
            "at that path."
        )
        st.stop()
    df = pd.read_csv(GOLD_TABLE_PATH)
    # CSV round-trips (export from Databricks, download, re-save) can introduce stray leading/
    # trailing whitespace on string columns - cheap to strip defensively rather than have it
    # silently break an exact-match lookup like the archetype -> colour map in app.py.
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()
    return df


@st.cache_data
def load_lga_boundaries() -> dict | None:
    """Loads the ABS ASGS LGA boundary GeoJSON (same file used for the Process 2 spatial join)
    and adds a normalised `lga_canonical` property to every feature, so the map can key off the
    exact same join column the rest of the pipeline uses - the raw file's `lga_name_2023`
    property isn't normalised on its own."""
    if not BOUNDARIES_PATH.exists():
        st.warning(
            f"Missing `{BOUNDARIES_PATH.relative_to(DATA_DIR.parent)}` - map will be unavailable, "
            "table view still works. Same file already used in Process 2 - copy it here."
        )
        return None
    with open(BOUNDARIES_PATH) as f:
        geojson = json.load(f)

    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        raw_name = props.get("lga_name_2023", "")
        props["lga_canonical"] = _normalize_lga_name(raw_name)
        feature["properties"] = props

    return geojson


@st.cache_data
def load_lga_centroids() -> dict[str, tuple[float, float]]:
    """lga_canonical -> (lat, lon) centroid, computed from the same boundary polygons as the
    map. Used to drop a pin when someone searches for an LGA - e.g. to visually confirm
    whether a gray patch on the map is a real LGA with a name-matching bug, or genuinely just
    water (Bass Strait, Port Phillip Bay) with no polygon at all."""
    from shapely.geometry import shape

    boundaries = load_lga_boundaries()
    if boundaries is None:
        return {}

    centroids = {}
    for feature in boundaries.get("features", []):
        if feature.get("geometry") is None:
            continue
        name = feature["properties"]["lga_canonical"]
        centroid = shape(feature["geometry"]).centroid
        centroids[name] = (centroid.y, centroid.x)  # (lat, lon)
    return centroids
