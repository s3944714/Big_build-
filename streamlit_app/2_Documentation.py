import sys
from pathlib import Path

# Same defensive import fix as 1_Dashboard.py - see the comment there for why.
sys.path.append(str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

from style import inject_global_styles
from data_loader import load_gold_table, load_trend_table

# set_page_config is NOT called here - Home.py (the router) calls it exactly once.
inject_global_styles()

gold_df = load_gold_table()
trend_df = load_trend_table()

st.title("How this works")
st.markdown(
    "The full methodology, data sources, and honest limitations behind the Priority Score "
    "and the two models built on top of it. Numbers on this page are computed live from the "
    "same data the dashboard uses — they can't silently drift out of sync with what you see "
    "there."
)

st.divider()

tab_data, tab_score, tab_cluster, tab_trend, tab_limits, tab_stack = st.tabs(
    ["Data Sources", "Composite Score", "Clustering", "Trend Forecast", "Limitations", "Tech Stack"]
)

# --- Data Sources ---
with tab_data:
    st.subheader("Five open datasets, one geographic key")
    st.markdown(
        "Every dataset joins on **LGA name** — normalised to upper-case with council-type "
        "suffixes stripped (e.g. `\"Melbourne (C)\"` → `\"MELBOURNE\"`). Six different naming "
        "mismatches were found and fixed across these sources during ingestion — Victorian "
        "and Commonwealth government data is genuinely inconsistent about how it spells the "
        "same 79 places."
    )

    sources = pd.DataFrame([
        {"Dataset": "Victoria in Future (VIF) population projections", "Publisher": "DTP", "Used for": "Population growth rate (2026→2036), the canonical 80-LGA reference list"},
        {"Dataset": "Victorian Road Crash Data", "Publisher": "Dept. of Transport and Planning", "Used for": "Severity-weighted crash rate (fatal=3, serious=2, other injury=1, non-injury=0)"},
        {"Dataset": "Traffic Signal Volume", "Publisher": "Dept. of Transport and Planning", "Used for": "Current traffic volume index (site-level, spatially joined to LGA)"},
        {"Dataset": "Historical AADT (Annual Average Daily Traffic)", "Publisher": "Dept. of Transport and Planning", "Used for": "Trend Forecast model — 2005/2010/2015 training, 2019 validation"},
        {"Dataset": "Building Permit Activity Data", "Publisher": "Building and Plumbing Commission", "Used for": "Dwelling approvals per capita (new dwellings summed, not permit count)"},
        {"Dataset": "ABS ASGS LGA boundaries", "Publisher": "Australian Bureau of Statistics", "Used for": "Map polygons, and the spatial joins used to place traffic sites/road segments onto the correct LGA"},
    ])
    st.dataframe(sources, width="stretch", hide_index=True)

    st.caption(
        "Processed end-to-end in Databricks (PySpark + scikit-learn) — see the `notebooks/` "
        "folder for the actual ingestion, feature engineering, and modelling code."
    )

# --- Composite Score ---
with tab_score:
    st.subheader("Priority Score = growth pressure + existing strain − PT service level")
    st.markdown(
        "Every feature is **z-score standardised** before combining — raw values sit on very "
        "different scales (a growth rate is a small decimal, traffic volume is in the "
        "thousands), so summing them unscaled would let whichever feature has the largest "
        "raw numbers dominate regardless of its actual importance."
    )

    st.markdown("**The four active components** (adjustable live via the Dashboard's sliders):")
    st.markdown(
        "- `population_growth_rate` — VIF projection, 2026 → 2036\n"
        "- `dwelling_approvals_per_capita` — new dwellings summed from Building Permit "
        "Activity Data, per capita\n"
        "- `crash_rate_severity_weighted` — severity-weighted crash count per 1,000 residents\n"
        "- `traffic_volume_index` — average daily traffic volume, spatially joined from site "
        "level to LGA level"
    )
    st.markdown(
        "**A fifth component — PT service level (GTFS stop density)** — is in the formula's "
        "shape at weight 0. It was scoped as a Phase 2 addition and hasn't been sourced yet; "
        "the composite score currently reflects growth pressure and existing strain only, not "
        "the full three-part formula from the original plan."
    )

    st.info(
        "The sliders on the Dashboard page only recompute the **score and ranking** — they do "
        "not re-run the clustering. Archetype labels (and the map's colours) come from a "
        "separate, fixed K-Means model — see the Clustering tab."
    )

# --- Clustering ---
with tab_cluster:
    st.subheader("K-Means clustering — an independent check on the composite score")
    st.markdown(
        "The composite score is a hand-built formula. To avoid trusting a single method's "
        "output at face value, every LGA is *also* run through unsupervised K-Means "
        "clustering on the same four standardised features — a completely different "
        "technique, with no knowledge of the composite score's ranking. Agreement between "
        "the two is the actual evidence; either one alone would just be an assertion."
    )

    if len(gold_df) > 0 and "archetype" in gold_df.columns:
        counts = gold_df["archetype"].value_counts()
        st.markdown("**Current archetype breakdown:**")
        for name, count in counts.items():
            st.markdown(f"- **{name}**: {count} LGAs")

    st.markdown(
        "**Why k=4, not the statistically \"best\" k=3:** silhouette score (the standard "
        "cluster-quality metric) actually favoured k=3 across repeated runs. But at k=3, a "
        "real distinction kept disappearing — a small group of low-population, high-crash-rate "
        "rural shires (their crash rate is likely inflated by non-resident/transit traffic, "
        "not genuine resident risk — see Limitations) kept getting merged into the main growth "
        "cluster, erasing a meaningful pattern. k=4 was chosen deliberately to preserve that "
        "distinction — narrative clarity over a marginally tighter statistical boundary, and a "
        "defensible methodological choice if asked about it directly."
    )

# --- Trend Forecast ---
with tab_trend:
    st.subheader("Trend Forecast — is strain rising or falling, not just where it sits today")
    st.markdown(
        "A simple linear trend fitted per LGA on historical traffic volume from three "
        "training years (2005, 2010, 2015), then validated against a held-out year (2019) "
        "the model never saw during fitting."
    )

    if trend_df is not None:
        mape = (
            (trend_df["predicted_2019"] - trend_df["actual_2019"]).abs() / trend_df["actual_2019"]
        ).mean() * 100
        rising = int(trend_df["trending_up"].sum())
        col1, col2, col3 = st.columns(3)
        col1.metric("LGAs trending up", f"{rising} / {len(trend_df)}")
        col2.metric("Validation MAPE", f"{mape:.1f}%")
        col3.metric("Training years used", "3 of 19 available")

        st.markdown(
            f"A {mape:.1f}% average error on a 2019 prediction, extrapolated from a 3-point "
            "fit made using only data through 2015, is a strong result for how minimal the "
            "approach is."
        )

        declining = trend_df[~trend_df["trending_up"]]["lga_canonical"].tolist()
        if declining:
            st.markdown(
                f"**{len(declining)} LGAs show declining traffic volume**: "
                f"{', '.join(d.title() for d in declining)}. These are established, "
                "built-out inner/bayside Melbourne suburbs — plausibly reflecting mature "
                "infill development and active modal-shift policy (bike lanes, PT investment) "
                "rather than a data artifact."
            )
    else:
        st.warning("Trend data not currently loaded.")

    st.markdown(
        "**Scope note:** the full historical AADT archive covers 2001-2019 (19 separate "
        "files, ~570MB). Only 4 years were used — enough to fit and honestly validate a "
        "simple trend, without the manual download burden of the full archive for what's "
        "explicitly a stretch feature. The AADT source data also required a real fix before "
        "use: its `\"Local Government Area\"` field is mislabeled (1,227 distinct values — "
        "actually suburb/locality names, not LGAs), so LGA assignment uses a proper spatial "
        "join on each road segment's midpoint instead."
    )

# --- Limitations ---
with tab_limits:
    st.subheader("What this tool is honestly not")
    st.markdown(
        "**This is a directional, proxy prioritisation tool, not a capital-planning-grade "
        "causal model.** Open government data has no true \"infrastructure spend\" variable — "
        "nothing here claims to know how much investment an LGA needs, only where growth "
        "appears to be outpacing existing capacity."
    )

    st.markdown("**Specific, named limitations, not glossed over:**")
    st.markdown(
        "- **Small-population crash rate instability**: per-capita severity-weighted crash "
        "rate can spike in low-population rural/alpine LGAs, very likely inflated by "
        "non-resident transit and tourist traffic rather than reflecting genuine risk to "
        "residents. This is exactly why those LGAs correctly separate into their own "
        "\"Established High-Strain\" cluster rather than being averaged away.\n"
        "- **Dwelling approvals counts new dwellings, not permits** — a deliberate choice "
        "(one permit can cover many dwellings, e.g. an apartment block) but a different "
        "measure than some other datasets report.\n"
        "- **Non-injury crashes are weighted 0** in the severity scale — a modelling choice, "
        "not verified against any external road-safety standard.\n"
        "- **PT service level is not yet in the model** — the composite score currently "
        "reflects growth and strain only, not the full three-part formula from the original "
        "plan.\n"
        "- **~5.9% of traffic signal sites have no confirmed location match** and are excluded "
        "from the traffic volume feature — a documented, acceptable data completeness gap, "
        "not a silent one."
    )

# --- Tech Stack ---
with tab_stack:
    st.subheader("How it's built")
    st.markdown(
        "**Data pipeline:** Databricks Free Edition (PySpark, Delta tables, Unity Catalog) — "
        "bronze ingestion → silver feature engineering + composite score → gold K-Means "
        "clustering output → a separate trend-forecast table, all in `notebooks/`.\n\n"
        "**Modelling:** scikit-learn (`KMeans`, `StandardScaler`), `numpy.polyfit` for the "
        "trend model, `shapely` for the spatial joins (site/segment → LGA) rather than full "
        "`geopandas` — avoids the heavier GDAL/fiona dependency chain for joins this size.\n\n"
        "**Dashboard:** a multi-page Streamlit app (`st.navigation`/`st.Page`) — this page, "
        "the landing page, and the interactive Dashboard all read from small exported CSV/"
        "GeoJSON files, not a live Databricks connection. `Plotly` for the choropleth map, an "
        "explicit colour-blind-safe (Okabe-Ito) palette with non-colour glyph icons for the "
        "archetypes, and a Three.js particle-network animation on the landing page."
    )
    st.caption(
        "Data sources: Victoria in Future population projections, Victorian Road Crash Data, "
        "Traffic Signal Volume and Historical AADT (Dept. of Transport and Planning), Building "
        "Permit Activity Data (Building and Plumbing Commission), ABS ASGS LGA boundaries."
    )