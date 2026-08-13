import sys
from pathlib import Path

# Defensive: guarantees style.py/data_loader.py/scoring.py resolve as imports regardless of
# exactly how Streamlit invokes this page script. This file lives directly in streamlit_app/
# (not nested in a pages/ subfolder), same directory as the modules being imported - so this
# is likely unnecessary in practice, but costs nothing and removes any doubt.
sys.path.append(str(Path(__file__).resolve().parent))

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from style import inject_global_styles
from data_loader import (
    load_gold_table, load_lga_boundaries, load_lga_centroids, load_trend_table,
)
from scoring import compute_priority_score, DEFAULT_WEIGHTS

# set_page_config is NOT called here - under st.navigation (Home.py is the router), it's
# called exactly once in the router before pg.run(). Calling it again here would raise
# StreamlitAPIException: set_page_config() can only be called once per app.
inject_global_styles()

# Explicit, semantically intuitive colours - not Plotly's default (which just assigns colour
# by the order labels first appear in the data, with no meaning attached - this previously put
# "Growth Hotspot" in blue and "Low-Pressure Stable" in red, backwards from what a reviewer
# skimming quickly would instinctively read). Warm = urgent/high priority, cool = calm/stable.
#
# Palette is the Okabe-Ito colour-blind-safe set (Okabe & Ito, 2008 - the standard reference
# palette for figures that need to survive deuteranopia/protanopia, the two most common forms
# of colour vision deficiency). The original red/orange/green/blue put a saturated red right
# next to a saturated green - the single most common confusion pair - so red and green have
# both been swapped out for vermillion and a blue-shifted teal, which stay distinguishable
# under both conditions while keeping the same warm-to-cool urgency ordering.
ARCHETYPE_COLORS = {
    "Growth Hotspot – High Strain": "#D55E00",           # vermillion - highest urgency
    "Established High-Strain": "#E69F00",                 # orange - elevated concern
    "Emerging Growth – Low Strain (so far)": "#009E73",   # blue-green (teal) - watch, not yet urgent
    "Low-Pressure Stable": "#0072B2",                     # blue - calm, low priority
}
DEFAULT_ARCHETYPE_ORDER = list(ARCHETYPE_COLORS.keys())

ARCHETYPE_ICONS = {
    "Growth Hotspot – High Strain": "▲▲",
    "Established High-Strain": "▲",
    "Emerging Growth – Low Strain (so far)": "△",
    "Low-Pressure Stable": "●",
}
ARCHETYPE_DISPLAY_LABELS = {name: f"{icon} {name}" for name, icon in ARCHETYPE_ICONS.items()}
ARCHETYPE_DISPLAY_TO_PLAIN = {display: name for name, display in ARCHETYPE_DISPLAY_LABELS.items()}
ARCHETYPE_COLORS_DISPLAY = {
    ARCHETYPE_DISPLAY_LABELS[name]: color for name, color in ARCHETYPE_COLORS.items()
}
DEFAULT_ARCHETYPE_ORDER_DISPLAY = [ARCHETYPE_DISPLAY_LABELS[name] for name in DEFAULT_ARCHETYPE_ORDER]

st.title("Where Should Victoria Build Next?")
st.markdown(
    "A data-driven infrastructure investment priority model across Victoria's Local Government "
    "Areas, built from open Victorian and Commonwealth government data. This is a directional, "
    "proxy prioritisation tool - open data has no true \"infrastructure spend\" variable, so it "
    "surfaces where growth is outpacing capacity, not a capital-planning-grade causal model."
)

gold_df = load_gold_table()
boundaries = load_lga_boundaries()
centroids = load_lga_centroids()
trend_df = load_trend_table()

with st.sidebar.container(border=True):
    st.header("Find an LGA")
    st.caption(
        "Search any LGA to drop a pin on the map - useful for checking whether a gray area is a "
        "real gap in the data (name-matching issue) or genuinely just water (Bass Strait, Port "
        "Phillip Bay) with no LGA polygon there at all."
    )

    name_lookup = {row["lga_canonical"]: row["LGA"] for _, row in gold_df.iterrows()}
    all_names = sorted(set(gold_df["lga_canonical"]) | set(centroids.keys()))
    search_options = ["(none)"] + [name_lookup.get(n, n.title()) for n in all_names]
    search_choice = st.selectbox("Search LGA", search_options, index=0)

    search_pin = None
    if search_choice != "(none)":
        reverse_lookup = {v: k for k, v in name_lookup.items()}
        search_canonical = reverse_lookup.get(search_choice, search_choice.upper())

        has_data = search_canonical in set(gold_df["lga_canonical"])
        has_geometry = search_canonical in centroids

        if has_data and has_geometry:
            row_archetype = gold_df.loc[gold_df["lga_canonical"] == search_canonical, "archetype"].iloc[0]
            if row_archetype in ARCHETYPE_COLORS:
                st.success(f"{search_choice} — has data and a map polygon.")
            else:
                st.warning(
                    f"{search_choice} has data and a polygon, but its archetype value "
                    f"doesn't match any known colour: {row_archetype!r}. It'll render as an "
                    f"unstyled white shape. Known values: {list(ARCHETYPE_COLORS.keys())}"
                )
        elif has_geometry and not has_data:
            st.warning(
                f"{search_choice} has a map polygon but no data row — it'll render as an "
                "unstyled gray shape. This is a real gap worth investigating."
            )
        elif has_data and not has_geometry:
            st.warning(
                f"{search_choice} has data but no matching polygon — it won't appear on the "
                "map at all, only in the table."
            )

        if has_geometry:
            search_pin = centroids[search_canonical]

st.sidebar.divider()

with st.sidebar.container(border=True):
    st.header("Score weights")
    st.caption(
        "Adjust how much each factor contributes to the Priority Score. Cluster archetypes (the map "
        "colours) come from a separate K-Means model and don't change with these sliders - only the "
        "ranking does."
    )

    weights = {
        "population_growth_rate": st.slider(
            "Population growth", 0.0, 2.0, DEFAULT_WEIGHTS["population_growth_rate"], 0.1
        ),
        "dwelling_approvals_per_capita": st.slider(
            "Dwelling approvals", 0.0, 2.0, DEFAULT_WEIGHTS["dwelling_approvals_per_capita"], 0.1
        ),
        "crash_rate_severity_weighted": st.slider(
            "Crash severity rate", 0.0, 2.0, DEFAULT_WEIGHTS["crash_rate_severity_weighted"], 0.1
        ),
        "traffic_volume_index": st.slider(
            "Traffic volume", 0.0, 2.0, DEFAULT_WEIGHTS["traffic_volume_index"], 0.1
        ),
    }
    st.caption("Public transport service level (GTFS) is Phase 2 - not yet in the model.")

    if st.button("Reset to defaults"):
        st.rerun()

st.sidebar.divider()

archetypes = sorted(gold_df["archetype"].dropna().unique().tolist())
selected_archetypes = st.sidebar.multiselect("Filter by archetype", archetypes, default=archetypes)

scored_df = compute_priority_score(gold_df, weights)
scored_df = scored_df[scored_df["archetype"].isin(selected_archetypes)]

if trend_df is not None:
    scored_df = scored_df.merge(
        trend_df[["lga_canonical", "trend_slope", "trending_up"]],
        on="lga_canonical",
        how="left",
    )
else:
    scored_df["trend_slope"] = None
    scored_df["trending_up"] = None

scored_df = scored_df.sort_values("priority_score", ascending=False).reset_index(drop=True)

if len(scored_df) > 0:
    top_lga = scored_df.iloc[0]
    with st.container(border=True):
        st.markdown("##### Highest current priority")
        st.markdown(
            f"**{top_lga['LGA']}** — archetype: *{top_lga['archetype']}*, "
            f"score: **{top_lga['priority_score']:.2f}**"
        )
        st.caption("Adjust the weights in the sidebar to see how the ranking responds.")
else:
    st.warning("No LGAs match the current archetype filter.")

st.divider()

# --- Map: full width, its own row - this is the primary visual, everything else is detail ---
st.header("Priority map")
st.caption(
    "Colour = cluster archetype (from Process 3's K-Means model). Full data is available "
    "in the ranked table below and via CSV download - the map is a visual summary, not the "
    "only way to get at this data."
)
if boundaries is not None and len(scored_df) > 0:
    map_df = scored_df.copy()
    map_df["archetype_display"] = map_df["archetype"].map(ARCHETYPE_DISPLAY_LABELS)

    fig = px.choropleth_map(
        map_df,
        geojson=boundaries,
        locations="lga_canonical",
        featureidkey="properties.lga_canonical",
        color="archetype_display",
        color_discrete_map=ARCHETYPE_COLORS_DISPLAY,
        category_orders={"archetype_display": DEFAULT_ARCHETYPE_ORDER_DISPLAY},
        hover_name="LGA",
        hover_data={
            "priority_score": ":.2f",
            "population_growth_rate": ":.2%",
            "trend_slope": ":.0f",
            "lga_canonical": False,
            "archetype_display": False,
        },
        map_style="carto-positron",
        center={"lat": search_pin[0], "lon": search_pin[1]} if search_pin else {"lat": -36.9, "lon": 145.0},
        zoom=8.5 if search_pin else 6.1,
        opacity=0.82,
    )
    if search_pin:
        fig.add_trace(
            go.Scattermap(
                lat=[search_pin[0]],
                lon=[search_pin[1]],
                mode="markers+text",
                marker=dict(size=18, color="black", symbol="circle"),
                text=[search_choice],
                textposition="top center",
                textfont=dict(size=14, color="black"),
                showlegend=False,
                hoverinfo="skip",
            )
        )
    # Full-width now (was sharing a column with the table) - height bumped again (780 -> 860)
    # since it has much more width to fill proportionally. Legend moved to bottom-right: with
    # Victoria's coastline, that corner of the map is reliably open water (Bass Strait) at
    # this zoom/center, so the legend can never overlap a real LGA's colour - it used to sit
    # top-left, which did overlap western Victoria LGAs.
    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=860,
        legend=dict(
            yanchor="bottom", y=0.02, xanchor="right", x=0.99,
            bgcolor="rgba(255,255,255,0.9)", bordercolor="rgba(0,0,0,0.15)", borderwidth=1,
        ),
    )
    st.plotly_chart(fig, width="stretch")
elif boundaries is None:
    st.warning("Map unavailable — LGA boundary file not found (see sidebar/console note).")

st.divider()

# --- Ranked table: full width below the map now, not squeezed into a side column - this is
# what actually fixes the "Traffic trend" column getting truncated in the old 5:3 split.
st.header("Ranked LGAs")
st.caption("Top 20 by Priority Score. Full ranking available via the download button.")

def _trend_label(val):
    if val is None or val != val:
        return "—"
    return "↑ Rising" if val else "↓ Declining"

display_cols = ["LGA", "archetype", "priority_score"]
table_df = scored_df[display_cols].head(20).copy()
table_df["Traffic trend"] = scored_df["trending_up"].head(20).map(_trend_label)

plain_archetype = table_df["archetype"]
table_df["archetype"] = plain_archetype.map(ARCHETYPE_DISPLAY_LABELS).fillna(plain_archetype)

def _archetype_cell_style(display_val):
    plain_val = ARCHETYPE_DISPLAY_TO_PLAIN.get(display_val, display_val)
    color = ARCHETYPE_COLORS.get(plain_val, "#888888")
    return f"background-color: {color}22; color: #1a1a1a; font-weight: 600"

st.dataframe(
    table_df.style.format({"priority_score": "{:.2f}"}).map(
        _archetype_cell_style, subset=["archetype"]
    ),
    width="stretch",
    height=460,
    hide_index=True,
)

st.download_button(
    "Download ranked LGAs (CSV)",
    data=scored_df.sort_values("priority_score", ascending=False).to_csv(index=False),
    file_name="vic_lga_priority_ranking.csv",
    mime="text/csv",
)

st.divider()
st.header("Cluster summary")

if len(scored_df) > 0:
    archetype_summary = (
        scored_df.groupby("archetype")
        .agg(lga_count=("LGA", "count"), avg_priority_score=("priority_score", "mean"))
        .sort_values("avg_priority_score", ascending=False)
        .reset_index()
    )
    plain_summary_archetype = archetype_summary["archetype"]
    archetype_summary["archetype"] = plain_summary_archetype.map(ARCHETYPE_DISPLAY_LABELS).fillna(
        plain_summary_archetype
    )
    st.dataframe(
        archetype_summary.style.format({"avg_priority_score": "{:.2f}"}).map(
            _archetype_cell_style, subset=["archetype"]
        ),
        width="stretch",
        hide_index=True,
    )

if trend_df is not None:
    mape = (
        (trend_df["predicted_2019"] - trend_df["actual_2019"]).abs() / trend_df["actual_2019"]
    ).mean() * 100
    rising_count = int(trend_df["trending_up"].sum())
    st.markdown(
        f"**Traffic trend model (Process 4):** {rising_count} of {len(trend_df)} LGAs show "
        f"rising traffic volume (2005–2019). The linear trend's 2019 predictions were within "
        f"**{mape:.1f}%** of actual on average — a directional validation check, not a causal "
        "forecast."
    )

st.divider()
st.header("Methodology & data sources")
st.caption(
    "Data sources: Victoria in Future population projections, Victorian Road Crash Data, "
    "Traffic Signal Volume (Dept. of Transport and Planning), Building Permit Activity Data "
    "(Building and Plumbing Commission), ABS ASGS LGA boundaries. "
    "Processed in Databricks (PySpark, scikit-learn) — see the `notebooks/` folder."
)