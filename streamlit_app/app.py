import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import load_gold_table, load_lga_boundaries, load_lga_centroids
from scoring import compute_priority_score, DEFAULT_WEIGHTS

st.set_page_config(page_title="Where Should Victoria Build Next?", layout="wide")

# Explicit, semantically intuitive colours - not Plotly's default (which just assigns colour
# by the order labels first appear in the data, with no meaning attached - this previously put
# "Growth Hotspot" in blue and "Low-Pressure Stable" in red, backwards from what a reviewer
# skimming quickly would instinctively read). Warm = urgent/high priority, cool = calm/stable.
ARCHETYPE_COLORS = {
    "Growth Hotspot – High Strain": "#d62728",       # red - highest urgency
    "Established High-Strain": "#ff7f0e",             # orange - elevated concern
    "Emerging Growth – Low Strain (so far)": "#2ca02c",  # green - watch, not yet urgent
    "Low-Pressure Stable": "#1f77b4",                 # blue - calm, low priority
}
DEFAULT_ARCHETYPE_ORDER = list(ARCHETYPE_COLORS.keys())

st.title("Where Should Victoria Build Next?")
st.caption(
    "A data-driven infrastructure investment priority model across Victoria's Local Government "
    "Areas, built from open Victorian and Commonwealth government data. This is a directional, "
    "proxy prioritisation tool - open data has no true \"infrastructure spend\" variable, so it "
    "surfaces where growth is outpacing capacity, not a capital-planning-grade causal model."
)

gold_df = load_gold_table()
boundaries = load_lga_boundaries()
centroids = load_lga_centroids()

# --- Sidebar: search ---
st.sidebar.header("Find an LGA")
st.sidebar.caption(
    "Search any LGA to drop a pin on the map - useful for checking whether a gray area is a "
    "real gap in the data (name-matching issue) or genuinely just water (Bass Strait, Port "
    "Phillip Bay) with no LGA polygon there at all."
)

# Union of names from both sources, not just gold_df - a name present in the boundary file but
# missing from the data (or vice versa) is exactly the kind of mismatch worth being able to
# search for directly, not just the "happy path" LGAs that already have everything.
name_lookup = {row["lga_canonical"]: row["LGA"] for _, row in gold_df.iterrows()}
all_names = sorted(set(gold_df["lga_canonical"]) | set(centroids.keys()))
search_options = ["(none)"] + [name_lookup.get(n, n.title()) for n in all_names]
search_choice = st.sidebar.selectbox("Search LGA", search_options, index=0)

search_pin = None
if search_choice != "(none)":
    # Map the display label back to the canonical key.
    reverse_lookup = {v: k for k, v in name_lookup.items()}
    search_canonical = reverse_lookup.get(search_choice, search_choice.upper())

    has_data = search_canonical in set(gold_df["lga_canonical"])
    has_geometry = search_canonical in centroids

    if has_data and has_geometry:
        row_archetype = gold_df.loc[gold_df["lga_canonical"] == search_canonical, "archetype"].iloc[0]
        if row_archetype in ARCHETYPE_COLORS:
            st.sidebar.success(f"✅ {search_choice} — has data and a map polygon.")
        else:
            # Row and polygon both exist, but the archetype string doesn't match any known
            # colour key - renders as an unstyled white/gray shape despite everything else
            # being present. repr() deliberately shown, not str() - this is exactly the check
            # that would catch a stray/mismatched character (e.g. an en dash "–" mangled into
            # a plain hyphen "-" by a CSV round-trip) that a normal print wouldn't reveal.
            st.sidebar.warning(
                f"⚠️ {search_choice} has data and a polygon, but its archetype value "
                f"doesn't match any known colour: {row_archetype!r}. It'll render as an "
                f"unstyled white shape. Known values: {list(ARCHETYPE_COLORS.keys())}"
            )
    elif has_geometry and not has_data:
        st.sidebar.warning(
            f"⚠️ {search_choice} has a map polygon but no data row — it'll render as an "
            "unstyled gray shape. This is a real gap worth investigating."
        )
    elif has_data and not has_geometry:
        st.sidebar.warning(
            f"⚠️ {search_choice} has data but no matching polygon — it won't appear on the "
            "map at all, only in the table."
        )

    if has_geometry:
        search_pin = centroids[search_canonical]

st.sidebar.divider()

# --- Sidebar: weight sliders ---
st.sidebar.header("Score weights")
st.sidebar.caption(
    "Adjust how much each factor contributes to the Priority Score. Cluster archetypes (the map "
    "colours) come from a separate K-Means model and don't change with these sliders - only the "
    "ranking does."
)

weights = {
    "population_growth_rate": st.sidebar.slider(
        "Population growth", 0.0, 2.0, DEFAULT_WEIGHTS["population_growth_rate"], 0.1
    ),
    "dwelling_approvals_per_capita": st.sidebar.slider(
        "Dwelling approvals", 0.0, 2.0, DEFAULT_WEIGHTS["dwelling_approvals_per_capita"], 0.1
    ),
    "crash_rate_severity_weighted": st.sidebar.slider(
        "Crash severity rate", 0.0, 2.0, DEFAULT_WEIGHTS["crash_rate_severity_weighted"], 0.1
    ),
    "traffic_volume_index": st.sidebar.slider(
        "Traffic volume", 0.0, 2.0, DEFAULT_WEIGHTS["traffic_volume_index"], 0.1
    ),
}
st.sidebar.caption("Public transport service level (GTFS) is Phase 2 - not yet in the model.")

if st.sidebar.button("Reset to defaults"):
    st.rerun()

archetypes = sorted(gold_df["archetype"].dropna().unique().tolist())
selected_archetypes = st.sidebar.multiselect("Filter by archetype", archetypes, default=archetypes)

scored_df = compute_priority_score(gold_df, weights)
scored_df = scored_df[scored_df["archetype"].isin(selected_archetypes)]
scored_df = scored_df.sort_values("priority_score", ascending=False).reset_index(drop=True)

# --- Top insight callout ---
if len(scored_df) > 0:
    top_lga = scored_df.iloc[0]
    st.info(
        f"**Highest current priority: {top_lga['LGA']}** "
        f"(archetype: *{top_lga['archetype']}*, score: {top_lga['priority_score']:.2f}) — "
        "adjust the weights in the sidebar to see how the ranking responds."
    )
else:
    st.warning("No LGAs match the current archetype filter.")

col_map, col_table = st.columns([3, 2])

with col_map:
    st.subheader("Priority map")
    st.caption("Colour = cluster archetype (from Process 3's K-Means model)")
    if boundaries is not None and len(scored_df) > 0:
        fig = px.choropleth_map(
            scored_df,
            geojson=boundaries,
            locations="lga_canonical",
            featureidkey="properties.lga_canonical",
            color="archetype",
            color_discrete_map=ARCHETYPE_COLORS,
            category_orders={"archetype": DEFAULT_ARCHETYPE_ORDER},
            hover_name="LGA",
            hover_data={
                "priority_score": ":.2f",
                "population_growth_rate": ":.2%",
                "lga_canonical": False,
            },
            map_style="carto-positron",
            center={"lat": search_pin[0], "lon": search_pin[1]} if search_pin else {"lat": -36.9, "lon": 145.0},
            zoom=8.5 if search_pin else 5.8,
            opacity=0.8,
        )
        if search_pin:
            fig.add_trace(
                go.Scattermap(
                    lat=[search_pin[0]],
                    lon=[search_pin[1]],
                    mode="markers+text",
                    marker=dict(size=18, color="black", symbol="circle"),
                    text=[f"📍 {search_choice}"],
                    textposition="top center",
                    textfont=dict(size=14, color="black"),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=550)
        st.plotly_chart(fig, width="stretch")
    elif boundaries is None:
        st.warning("Map unavailable — LGA boundary file not found (see sidebar/console note).")

with col_table:
    st.subheader("Ranked LGAs")
    display_cols = ["LGA", "archetype", "priority_score"]
    table_df = scored_df[display_cols].head(20)

    def _archetype_bg(val):
        color = ARCHETYPE_COLORS.get(val, "#888888")
        return f"background-color: {color}22; color: {color}; font-weight: 600"

    st.dataframe(
        table_df.style.format({"priority_score": "{:.2f}"}).map(_archetype_bg, subset=["archetype"]),
        width="stretch",
        height=550,
        hide_index=True,
    )

    st.download_button(
        "Download ranked LGAs (CSV)",
        data=scored_df.sort_values("priority_score", ascending=False).to_csv(index=False),
        file_name="vic_lga_priority_ranking.csv",
        mime="text/csv",
    )

st.subheader("Cluster archetypes")
if len(scored_df) > 0:
    archetype_summary = (
        scored_df.groupby("archetype")
        .agg(lga_count=("LGA", "count"), avg_priority_score=("priority_score", "mean"))
        .sort_values("avg_priority_score", ascending=False)
        .reset_index()
    )
    st.dataframe(
        archetype_summary.style.format({"avg_priority_score": "{:.2f}"}).map(
            _archetype_bg, subset=["archetype"]
        ),
        width="stretch",
        hide_index=True,
    )

st.caption(
    "Data sources: Victoria in Future population projections, Victorian Road Crash Data, "
    "Traffic Signal Volume (Dept. of Transport and Planning), Building Permit Activity Data "
    "(Building and Plumbing Commission), ABS ASGS LGA boundaries. "
    "Processed in Databricks (PySpark, scikit-learn) — see the `notebooks/` folder."
)
