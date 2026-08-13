import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    load_gold_table, load_lga_boundaries, load_lga_centroids, load_trend_table,
)
from scoring import compute_priority_score, DEFAULT_WEIGHTS

st.set_page_config(page_title="Where Should Victoria Build Next?", layout="wide")

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

# Non-colour reinforcement for the archetype categories: a colour-coded table cell or map
# region is a "graphical object" under WCAG 1.4.11 (3:1 contrast is enough there), but relying
# on hue alone for someone with a colour vision deficiency to tell four categories apart *at a
# glance* is still asking a lot even with a colour-blind-safe palette picked carefully - a
# shape/weight cue that doesn't depend on colour perception at all is worth adding on top, same
# principle as the existing ↑/↓ Traffic trend column already uses. Glyph weight tracks urgency
# (filled, doubled triangle down to a plain dot for the stable tier) so it reads as an ordering
# even without knowing what the symbols mean specifically.
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
# st.markdown, not st.caption - this framing paragraph is the abstract a reviewer needs to
# actually read before the map means anything; caption's smaller, greyed-out styling was
# de-emphasising it right next to genuinely secondary text like the data-source citation.
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

# --- Sidebar: search ---
# Bordered container instead of a flat header - groups the search control and its result
# message visually as one unit, so the sidebar reads as sections rather than a stacked list of
# unrelated widgets. Same treatment applied to the weight sliders below.
with st.sidebar.container(border=True):
    st.header("Find an LGA")
    st.caption(
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
    search_choice = st.selectbox("Search LGA", search_options, index=0)

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
                # No manual emoji prefix any more - st.success's own colour/border is already
                # the signal. A hand-typed checkmark on top of it was exactly the "mixed
                # iconography" problem: a flat emoji sitting next to the page's actual semantic
                # colour/icon system. Same reasoning applies to the st.warning branches below.
                st.success(f"{search_choice} — has data and a map polygon.")
            else:
                # Row and polygon both exist, but the archetype string doesn't match any known
                # colour key - renders as an unstyled white/gray shape despite everything else
                # being present. repr() deliberately shown, not str() - this is exactly the check
                # that would catch a stray/mismatched character (e.g. an en dash "–" mangled into
                # a plain hyphen "-" by a CSV round-trip) that a normal print wouldn't reveal.
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

# --- Sidebar: weight sliders ---
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

# Left join, not inner - a missing trend row shouldn't drop an LGA from the ranking, it should
# just show as "—" (no trend data) same as any other optional overlay in this app. trend_slope
# is joined in too (not just trending_up) so the map hover can show the actual magnitude, not
# just the up/down direction.
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

# --- Top insight callout ---
# A bordered container instead of st.info: this isn't a warning or a notice, it's the single
# most important number on the page, and burying it in the same blue alert-box styling used for
# routine explanatory asides elsewhere undersold it. Reserving st.info/warning/error for genuine
# warnings and errors also means the warnings further down (missing files, mismatched
# archetypes) stand out more, since they're no longer one alert box among several look-alikes.
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
st.header("Explore the map & rankings")

col_map, col_table = st.columns([3, 2])
# Streamlit auto-stacks columns to full width below roughly 640px of container width (default
# behaviour since ~1.32), so the 3:2 split should degrade to a normal vertical layout on narrow
# screens rather than squeezing both panels into unreadable slivers - worth actually checking at
# a real narrow browser width before the demo video though, since the exact breakpoint is
# version-dependent and isn't something verifiable from here.

with col_map:
    st.subheader("Priority map")
    st.caption(
        "Colour = cluster archetype (from Process 3's K-Means model). Full data is available "
        "in the ranked table alongside and via CSV download below - the map is a visual "
        "summary, not the only way to get at this data."
    )
    if boundaries is not None and len(scored_df) > 0:
        # A separate copy for the map only - archetype_display (icon + name, for the legend) is
        # a presentation-only column and must not leak into scored_df, which is what the CSV
        # download button further down exports.
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
                    # No pin emoji here any more - the marker itself is already the visual
                    # indicator, and a bold label next to it reads as deliberate typography
                    # rather than a mismatched pictographic icon dropped next to the rest of the
                    # page's plain geometric icon language (▲▲ ▲ △ ● / ↑ ↓).
                    text=[search_choice],
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

    def _trend_label(val):
        # val is None for the whole column when trend_df wasn't loaded, and NaN per-row for
        # any LGA the left join didn't find a match for - both should render the same "no
        # trend data" placeholder rather than crashing on a NaN != True/False comparison.
        if val is None or val != val:
            return "—"
        return "↑ Rising" if val else "↓ Declining"

    display_cols = ["LGA", "archetype", "priority_score"]
    table_df = scored_df[display_cols].head(20).copy()
    table_df["Traffic trend"] = scored_df["trending_up"].head(20).map(_trend_label)

    # Icon + name for display only, same reasoning as archetype_display on the map above - the
    # underlying scored_df (and therefore the CSV export) keeps the plain archetype name. Falls
    # back to the original value for anything not in the lookup (a mismatched archetype string,
    # same edge case the sidebar search warns about) rather than going blank.
    plain_archetype = table_df["archetype"]
    table_df["archetype"] = plain_archetype.map(ARCHETYPE_DISPLAY_LABELS).fillna(plain_archetype)

    def _archetype_cell_style(display_val):
        # Coloured background stays as a decorative/secondary cue (the icon prefix above is the
        # actual non-colour signal), but the text itself is now a fixed near-black rather than
        # the archetype's own hue - colouring text the same hue as its own translucent
        # background can't reliably clear the 4.5:1 contrast ratio WCAG 1.4.3 requires for text,
        # no matter how the opacity is tuned, since both ends of the blend share a hue. A fixed
        # dark neutral text colour on a light tinted background clears that easily.
        plain_val = ARCHETYPE_DISPLAY_TO_PLAIN.get(display_val, display_val)
        color = ARCHETYPE_COLORS.get(plain_val, "#888888")
        return f"background-color: {color}22; color: #1a1a1a; font-weight: 600"

    st.dataframe(
        table_df.style.format({"priority_score": "{:.2f}"}).map(
            _archetype_cell_style, subset=["archetype"]
        ),
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

st.divider()
st.header("Cluster summary")

if len(scored_df) > 0:
    archetype_summary = (
        scored_df.groupby("archetype")
        .agg(lga_count=("LGA", "count"), avg_priority_score=("priority_score", "mean"))
        .sort_values("avg_priority_score", ascending=False)
        .reset_index()
    )
    # Same display-only icon prefix as the map legend and ranked table - grouping itself still
    # happens on the plain archetype column above, this only relabels the result for rendering.
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

# Computed from the full trend_df, not the (possibly archetype-filtered) scored_df - this is a
# model-validation statement about Process 4 itself, so it shouldn't wobble depending on which
# archetypes happen to be selected in the sidebar filter. st.markdown, not st.caption - this is
# the evidentiary number backing the "trending up/down" claims made elsewhere on the page, not
# a footnote.
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