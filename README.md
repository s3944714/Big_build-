# Where Should Victoria Build Next?

**A data-driven infrastructure investment priority model across Victoria's 79 Local
Government Areas** — combining population growth, crash severity, traffic volume, and
dwelling approvals into a single, explainable score, cross-validated with unsupervised
clustering and a traffic trend forecast.

Built as a portfolio project for Victoria's Big Build (VIDA) Data & IT Graduate Program
application.



**🔗 Live demo:** [_add the Streamlit Community Cloud URL here once deployed_](https://s3944714-big-build--streamlit-apphome-4t6vat.streamlit.app/)

---

## What this actually does

Most infrastructure-priority tools either hide their logic in a black-box model or reduce a
genuinely multi-dimensional problem to one number nobody can interrogate. This project does
neither: every LGA's Priority Score is a **transparent, adjustable sum of measurable
factors**, and the same ranking is **cross-checked against a completely independent
unsupervised clustering model** — two different methods, checked against each other, not
just asserted.

**This is a directional, proxy prioritisation tool, not a capital-planning-grade causal
model.** Open government data has no true "infrastructure spend" variable, so it surfaces
where growth appears to be outpacing capacity — it doesn't claim to know how much investment
any LGA needs. Every limitation of that approach is named explicitly in the app's own
Documentation page, not glossed over.

## Key findings

- **Melbourne, Mitchell, Port Phillip, and Melton form a distinct extreme-growth cluster** —
  roughly 10x the growth intensity of the broader growth corridor, via two different
  mechanisms: Mitchell's population boom (nearly triples by 2036) vs. Melbourne/Port
  Phillip's high-density infill (40 and 26 new dwellings per capita — far above anyone else).
- **The composite score and an independent K-Means model agree** on the same top-priority
  LGAs, without either being told the other's answer.
- **A traffic trend model (linear fit, 2005-2015, validated against 2019)** predicts held-out
  actuals within **3.2% average error**, and correctly flags Melbourne's established,
  built-out inner/bayside suburbs (Bayside, Boroondara, Glen Eira, Port Phillip) as the only
  LGAs with declining traffic volume — a real, explainable pattern, not a data artifact.
- A known model limitation — small rural/alpine LGAs showing an inflated per-capita crash
  rate, very likely from non-resident transit traffic rather than genuine resident risk — is
  named explicitly rather than patched away, and is exactly why it separates into its own
  cluster archetype instead of distorting the growth-corridor ranking.

Full methodology, every data source, and the complete list of honest limitations are in the
app's own **"How it works"** page — this README stays high-level on purpose.

## Architecture

```
Victorian & Commonwealth open data (CSV / GeoJSON / XLSB)
        │
        ▼
Databricks Free Edition (PySpark, Delta tables, Unity Catalog)
  01  bronze ingestion        — 5 raw sources landed as governed Delta tables
  02  silver feature table    — LGA-name reconciliation, feature engineering, composite score
  03  gold clustering         — K-Means, priority archetypes, cross-validated against 02
  04  trend forecast          — historical AADT spatial join, linear trend, validated on 2019
        │
        ▼  (manual CSV/GeoJSON export)
streamlit_app/data/            — small, already-aggregated outputs (committed to the repo -
                                  the deployed app has no other way to read this data)
        │
        ▼
Streamlit multi-page app (st.navigation)
  Home.py            — landing page, live-computed key stats
  1_Dashboard.py      — interactive map, ranked table, weight sliders, LGA search
  2_Documentation.py  — full methodology, data sources, limitations
```

Data flows one direction only: Databricks → exported flat files → Streamlit. The deployed
app never talks to Databricks directly.

## Data sources

| Dataset | Publisher | Used for |
|---|---|---|
| Victoria in Future (VIF) population projections | Dept. of Transport and Planning | Population growth rate; the canonical 80-LGA reference list |
| Victorian Road Crash Data | Dept. of Transport and Planning | Severity-weighted crash rate |
| Traffic Signal Volume | Dept. of Transport and Planning | Current traffic volume index |
| Historical AADT (Annual Average Daily Traffic) | Dept. of Transport and Planning | Trend forecast model — 2005/2010/2015 training, 2019 validation |
| Building Permit Activity Data | Building and Plumbing Commission | Dwelling approvals per capita |
| ABS ASGS LGA boundaries | Australian Bureau of Statistics | Map polygons and spatial joins |

All sources are open Victorian and Commonwealth government data. See the in-app
Documentation page for exact dataset URLs and the (non-trivial) name-reconciliation work
needed to join six sources that spell the same 79 places differently.

## Tech stack

- **Data pipeline:** Databricks Free Edition (PySpark, Delta Lake, Unity Catalog)
- **Modelling:** scikit-learn (`KMeans`, `StandardScaler`), NumPy (linear trend fit),
  Shapely (spatial joins — deliberately not full GeoPandas, to avoid the heavier GDAL/fiona
  dependency chain for joins at this scale)
- **Dashboard:** Streamlit (multi-page, `st.navigation`/`st.Page`), Plotly (choropleth map),
  Three.js (landing page hero animation)
- **Design:** an explicit, colour-blind-safe (Okabe-Ito) palette with non-colour glyph icons
  for every category — not relying on hue alone anywhere in the app

## Project structure

```
big_build/
├── notebooks/                  Databricks source-format notebooks
│   ├── 01_bronze_ingestion.py
│   ├── 02_silver_feature_table.py
│   ├── 03_clustering.py
│   └── 04_trend_forecast.py
├── streamlit_app/
│   ├── Home.py                 Run this — landing page + navigation router
│   ├── 1_Dashboard.py          Interactive map, table, sliders, LGA search
│   ├── 2_Documentation.py      Full methodology & data sources
│   ├── style.py                Shared typography/CSS
│   ├── data_loader.py          Reads exported CSVs/GeoJSON, no live Databricks connection
│   ├── scoring.py               Composite score logic - kept in sync with 02's PySpark version
│   └── data/                   Small exported outputs (committed - see note below)
├── requirements.txt
└── CLAUDE.md                   Architecture/context notes for AI coding assistants
```

**Two things worth knowing if you're exploring this repo:**
1. `streamlit_app/1_Dashboard.py` lives flat, not in a `pages/` subfolder — a deliberate
   choice after hitting confirmed bugs in Streamlit's older `pages/`-folder navigation
   mechanism (see `CLAUDE.md` for the full story).
2. `streamlit_app/data/` is **committed on purpose**, unlike a typical `/data` folder — the
   deployed app has no access to Databricks or a local machine, so its data has to ship with
   the code.

## Running it locally

The Databricks notebooks require a Databricks workspace (Free Edition works) and can't run
standalone — they're included for transparency and to show the actual pipeline, not as a
"clone and run" step.

**The Streamlit app runs standalone**, reading the pre-exported data already committed in
`streamlit_app/data/`:

```bash
pip install -r requirements.txt
streamlit run streamlit_app/Home.py
```

To regenerate the underlying data yourself, you'd need a Databricks workspace, the open
datasets listed above, and to run the four notebooks in order — see `CLAUDE.md` for the full
ingestion and environment notes.

## Limitations

Stated plainly, not just once in fine print:

- Directional/proxy model — no true "infrastructure spend" ground truth exists in open data.
- The composite score currently reflects growth pressure and existing strain only; public
  transport service level is wired into the formula's shape at weight 0 but not yet sourced.
- Small-population rural/alpine LGAs can show volatile per-capita crash rates, plausibly
  inflated by non-resident traffic — a named, not hidden, limitation.
- The trend forecast uses 4 of 19 available AADT years (a deliberate scope choice, not a
  data-access limitation) and is a 3-point linear extrapolation, not a robust statistical model.

## About this project

Built by Rob — Master of AI student at RMIT, with prior experience in data analysis, API
development, and DevOps — as a portfolio piece for the Victoria's Big Build (VIDA) Data & IT
Graduate Program application.
