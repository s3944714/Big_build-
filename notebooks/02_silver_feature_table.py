# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver Feature Table + Composite Score
# MAGIC **Project:** "Where Should Victoria Build Next?" — VIDA Data & IT Graduate Program demo
# MAGIC
# MAGIC **Purpose:** join the bronze tables from `01_bronze_ingestion` onto a single LGA-level
# MAGIC feature table, and compute the composite Priority Score from the plan.
# MAGIC
# MAGIC **Phase 1 scope note:** the plan's full formula is
# MAGIC `Priority Score = growth_pressure + existing_strain - existing_pt_service`. GTFS (the PT
# MAGIC service-level input) is explicitly Phase 2 in the roadmap — not sourced yet — so this
# MAGIC notebook computes `growth_pressure + existing_strain` only, with the PT term wired into the
# MAGIC formula at weight 0 so Phase 2 is a config change, not a rewrite.
# MAGIC
# MAGIC **What's ready vs. blocked coming in:**
# MAGIC - ✅ Road Crash Data → severity-weighted crash rate
# MAGIC - ✅ VIF population → growth rate + per-capita denominator
# MAGIC - ✅ Traffic Signal Volume + site locations → spatial join to LGA, needs the LGA boundary
# MAGIC   GeoJSON uploaded to the volume first (see step 3)
# MAGIC - ⬜ Building permits (statewide) → still waiting on the VBA `.xlsb` file; feature computes
# MAGIC   as null until that's ingested, rest of the pipeline runs regardless

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Config
# MAGIC Same widgets as Process 1 - this notebook reads bronze tables via `catalog`/`schema`, and
# MAGIC reads the LGA boundary GeoJSON from the same volume.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Catalog")
dbutils.widgets.text("schema", "vic_build", "Schema")
dbutils.widgets.text("volume", "raw_data", "Volume (raw files land here)")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
raw_path = f"/Volumes/{catalog}/{schema}/{volume}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Install dependencies
# MAGIC `shapely` only - not full `geopandas`. At ~4,731 sites x 80 LGA polygons, a plain
# MAGIC point-in-polygon loop is fast enough without spatial indexing, and avoids GDAL/fiona, which
# MAGIC are heavier and more prone to install friction. Installed early, before anything else
# MAGIC depends on session state, same reasoning as Process 1's step 3.

# COMMAND ----------

# MAGIC %pip install shapely -q
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
raw_path = f"/Volumes/{catalog}/{schema}/{volume}"

from pyspark.sql import functions as F
from pyspark.sql import types as T

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Canonical LGA list + name normalisation
# MAGIC VIF is the cleanest source of the actual 80 LGAs (79 + Unincorporated Vic), so it's the
# MAGIC canonical list everything else joins onto. Normalise to crash data's style (upper case, no
# MAGIC suffix) since that's already the simplest format in play:
# MAGIC - VIF: `"Alpine (S)"` → strip the `" (X)"` suffix, upper case → `"ALPINE"`
# MAGIC - **Some VIF names have a *double* suffix** — `"Kingston (C) (Vic.)"`, `"Latrobe (C) (Vic.)"`
# MAGIC   — because those LGA names also exist in other states, so VIF disambiguates with a second
# MAGIC   `(Vic.)` tag. A single-group regex misses this entirely (and the period in `"Vic."` breaks
# MAGIC   a letters-only pattern too) - fixed below to strip repeated trailing groups.
# MAGIC - Crash: already `"ALPINE"` — used as-is, but rows with the 7 alpine-resort values or a
# MAGIC   null `LGA_NAME` are dropped here (per the Process 1 QA decision) since they can't join to
# MAGIC   a real LGA.

# COMMAND ----------

bronze_vif = spark.table(f"{catalog}.{schema}.bronze_vif_population")

lga_lookup = (
    bronze_vif
    .withColumn("lga_canonical", F.upper(F.trim(F.regexp_replace("LGA", r"(\s*\([A-Za-z.]+\))+$", ""))))
    .select("lga_canonical", "LGA", "LGA_code", "2021", "2026", "2031", "2036")
)
print(f"Canonical LGA list: {lga_lookup.count()} rows (expect 80)")
lga_lookup.display()

# COMMAND ----------

ALPINE_RESORT_AREAS = [
    "(FALLS CREEK)", "(FRENCH ISLAND)", "(LAKE MOUNTAIN)", "(MOUNT BAW BAW)",
    "(MOUNT BULLER)", "(MOUNT HOTHAM)", "(MOUNT STIRLING)",
]

bronze_crash = spark.table(f"{catalog}.{schema}.bronze_road_crash")
crash_clean = bronze_crash.filter(
    F.col("LGA_NAME").isNotNull() & ~F.col("LGA_NAME").isin(ALPINE_RESORT_AREAS)
)
dropped = bronze_crash.count() - crash_clean.count()
print(f"Crash rows dropped (alpine resort areas + null LGA_NAME): {dropped:,} of {bronze_crash.count():,}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Crash data → severity-weighted rate per LGA
# MAGIC Weighting: fatal=3, serious injury=2, other injury=1, non-injury=0 (non-injury crashes
# MAGIC don't represent the same "strain" signal as injury crashes - worth a one-line justification
# MAGIC in the video if asked). Normalised per capita using 2026 VIF population (nearest actual/
# MAGIC current-year figure to today).

# COMMAND ----------

SEVERITY_WEIGHTS = {
    "Fatal accident": 3,
    "Serious injury accident": 2,
    "Other injury accident": 1,
    "Non injury accident": 0,
}

severity_case = F.create_map([F.lit(x) for pair in SEVERITY_WEIGHTS.items() for x in pair])

crash_weighted = crash_clean.withColumn("severity_weight", severity_case[F.col("SEVERITY")])

crash_by_lga = (
    crash_weighted
    .groupBy("LGA_NAME")
    .agg(
        F.sum("severity_weight").alias("crash_severity_sum"),
        F.count("*").alias("crash_count"),
    )
    .withColumnRenamed("LGA_NAME", "lga_canonical")
)

# Confirmed naming mismatches between crash data and VIF - crash data drops "Greater" from
# regional city names, and uses a space instead of a hyphen for Colac-Otway. Not a systematic
# pattern worth a general regex for; these are genuinely arbitrary differences between two
# separate government datasets, so an explicit small crosswalk is the honest fix. Unincorporated
# Vic deliberately has no entry here - it's a scattered statistical catch-all, not a single
# place, and stays null/excluded from ranking by design rather than forced to a value.
CRASH_LGA_NAME_OVERRIDES = {
    "SHEPPARTON": "GREATER SHEPPARTON",
    "GEELONG": "GREATER GEELONG",
    "DANDENONG": "GREATER DANDENONG",
    "BENDIGO": "GREATER BENDIGO",
    "COLAC OTWAY": "COLAC-OTWAY",
}
override_map = F.create_map([F.lit(x) for pair in CRASH_LGA_NAME_OVERRIDES.items() for x in pair])
crash_by_lga = crash_by_lga.withColumn(
    "lga_canonical", F.coalesce(override_map[F.col("lga_canonical")], F.col("lga_canonical"))
)

crash_features = (
    crash_by_lga
    .join(lga_lookup.select("lga_canonical", F.col("2026").alias("population_2026")), "lga_canonical", "left")
    .withColumn(
        "crash_rate_severity_weighted",
        F.col("crash_severity_sum") / F.col("population_2026") * 1000,  # per 1,000 residents
    )
)
crash_features.orderBy(F.desc("crash_rate_severity_weighted")).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Traffic Signal Volume → spatial join → LGA
# MAGIC **Needs `vic_lga_boundaries.geojson` uploaded to the volume first.** Source: ABS's ASGS2023
# MAGIC LGA layer (Esri ArcGIS REST FeatureServer, standard/well-documented API, confirmed live and
# MAGIC confirmed field names via its own metadata endpoint) - covers all of Australia, so filtered
# MAGIC to Victoria only:
# MAGIC `https://geo.abs.gov.au/arcgis/rest/services/ASGS2023/LGA/FeatureServer/0/query?where=state_name_2021='Victoria'&outFields=lga_code_2023,lga_name_2023,state_name_2021&f=geojson`
# MAGIC Open that in a browser, save the response as `vic_lga_boundaries.geojson`, upload it like
# MAGIC every other raw file. This cell will fail with a clear file-not-found error until that's in
# MAGIC place — everything above it (crash, and VIF above that) doesn't depend on it.
# MAGIC
# MAGIC **LGA name property confirmed as `lga_name_2023`** (from ABS's own layer metadata, not a
# MAGIC guess this time) — but the print statement below still shows the actual property keys as a
# MAGIC sanity check before it's used, in case the field set changes.

# COMMAND ----------

import json
import re
from shapely.geometry import shape, Point

boundary_file = "vic_lga_boundaries.geojson"
boundary_local_path = f"{raw_path}/{boundary_file}"

with open(boundary_local_path) as f:
    lga_geojson = json.load(f)

print(f"Loaded {len(lga_geojson['features'])} LGA polygon features (expect ~79-80 for Victoria)")
print(f"Property keys on first feature: {list(lga_geojson['features'][0]['properties'].keys())}")

# COMMAND ----------

LGA_NAME_PROPERTY = "lga_name_2023"


def normalize_lga_name(raw_name: str) -> str:
    """Same normalisation as the VIF join in step 3 (including the double-suffix fix for
    names like 'Kingston (C) (Vic.)'): strip trailing ' (X)' council-type suffix group(s),
    upper case. ABS LGA names likely carry the same suffix style as VIF - applying it here
    too rather than assuming ABS's format matches crash data as-is."""
    return re.sub(r"(\s*\([A-Za-z.]+\))+$", "", str(raw_name)).strip().upper()


lga_polygons = [
    (normalize_lga_name((feat.get("properties") or {}).get(LGA_NAME_PROPERTY, "")), shape(feat["geometry"]))
    for feat in lga_geojson["features"]
    if feat.get("geometry") is not None
]

# COMMAND ----------

# Collect site coordinates to the driver (small - ~5,000 rows) and do the point-in-polygon
# match locally, then broadcast the resulting site->LGA mapping back into Spark.
sites_pdf = (
    spark.table(f"{catalog}.{schema}.bronze_traffic_signal_sites")
    .select("SITE_NO", "LATITUDE", "LONGITUDE")
    .toPandas()
)

def find_lga(lat, lon):
    point = Point(lon, lat)  # GeoJSON order is (x=lon, y=lat)
    for lga_name, polygon in lga_polygons:
        if polygon.contains(point):
            return lga_name
    return None

sites_pdf["lga_canonical"] = sites_pdf.apply(lambda r: find_lga(r["LATITUDE"], r["LONGITUDE"]), axis=1)
matched = sites_pdf["lga_canonical"].notna().sum()
print(f"Sites matched to an LGA polygon: {matched:,} of {len(sites_pdf):,}")

site_to_lga = spark.createDataFrame(sites_pdf[["SITE_NO", "lga_canonical"]])

# COMMAND ----------

bronze_traffic = spark.table(f"{catalog}.{schema}.bronze_traffic_signal_volume")

traffic_with_lga = bronze_traffic.join(
    site_to_lga, bronze_traffic.NB_SCATS_SITE == site_to_lga.SITE_NO, "inner"
)

traffic_features = (
    traffic_with_lga
    .groupBy("lga_canonical")
    .agg(F.avg("QT_VOLUME_24HOUR").alias("traffic_volume_index"))
)
traffic_features.orderBy(F.desc("traffic_volume_index")).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Building permits (statewide)
# MAGIC `bronze_building_permits_vic` now exists (VBA 2025 calendar year, 100,710 rows). Confirmed
# MAGIC by opening the actual file - two things worth knowing:
# MAGIC - **Join key is `Municipal_Full_Name`, not `Site_Municipality`.** `Site_Municipality`
# MAGIC   truncates some names (e.g. `"Mornington"` where the real LGA is `"Mornington Peninsula"`),
# MAGIC   which would silently mis-join. `Municipal_Full_Name` is formatted like
# MAGIC   `"Wangaratta, Rural City of"` - splitting on the first comma gives a name that actually
# MAGIC   matches VIF's official naming, including Kingston/Latrobe (no `(Vic.)` disambiguator
# MAGIC   needed in this file - confirmed by checking the actual values).
# MAGIC - **Summing `Number_of_New_Dwellings__c` per LGA, not counting permit rows** - a single
# MAGIC   permit can cover many dwellings (an apartment block), so a row count would understate
# MAGIC   exactly the dense-growth areas this project cares about most. Nulls in that field are
# MAGIC   treated as 0 (permit exists but doesn't add a new dwelling - e.g. a renovation), not
# MAGIC   dropped.

# COMMAND ----------

permits_table = f"{catalog}.{schema}.bronze_building_permits_vic"
if spark.catalog.tableExists(permits_table):
    bronze_permits_vic = spark.table(permits_table)

    permits_by_lga = (
        bronze_permits_vic
        .withColumn("lga_canonical", F.upper(F.trim(F.split(F.col("Municipal_Full_Name"), ",")[0])))
        .groupBy("lga_canonical")
        .agg(F.sum(F.coalesce(F.col("Number_of_New_Dwellings__c"), F.lit(0))).alias("new_dwellings"))
    )

    permits_features = (
        permits_by_lga
        .join(
            lga_lookup.select("lga_canonical", F.col("2026").alias("population_2026_permits")),
            "lga_canonical", "left",
        )
        .withColumn(
            "dwelling_approvals_per_capita",
            F.col("new_dwellings") / F.col("population_2026_permits") * 1000,
        )
        .select("lga_canonical", "dwelling_approvals_per_capita")
    )
    print(f"Permits aggregated to {permits_features.count()} LGAs")
    permits_features.orderBy(F.desc("dwelling_approvals_per_capita")).display()
else:
    print(f"{permits_table} doesn't exist yet - dwelling_approvals_per_capita will be null.")
    permits_features = lga_lookup.select("lga_canonical").withColumn(
        "dwelling_approvals_per_capita", F.lit(None).cast("double")
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Assemble the feature table
# MAGIC Population growth rate: simple growth from 2026 (current) to 2036 (end of projection
# MAGIC horizon) - a forward-looking "how much more pressure is coming" figure, matching the plan's
# MAGIC growth-pressure framing.

# COMMAND ----------

vif_features = lga_lookup.withColumn(
    "population_growth_rate", (F.col("2036") - F.col("2026")) / F.col("2026")
).select("lga_canonical", "LGA", "population_growth_rate", F.col("2026").alias("population_2026"))

feature_table = (
    vif_features
    .join(crash_features.select("lga_canonical", "crash_rate_severity_weighted"), "lga_canonical", "left")
    .join(traffic_features, "lga_canonical", "left")
    .join(permits_features.select("lga_canonical", "dwelling_approvals_per_capita"), "lga_canonical", "left")
)

print(f"Feature table: {feature_table.count()} rows (expect 80)")
feature_table.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Composite Priority Score
# MAGIC Z-score standardise before combining - the raw features are on very different scales
# MAGIC (a growth rate is a small decimal, traffic volume index is in the thousands), so summing raw
# MAGIC values would let whichever feature has the largest numbers dominate regardless of its actual
# MAGIC importance. Weights are exposed as a dict now specifically so the dashboard sliders (Process
# MAGIC 5) can reuse this exact function later.

# COMMAND ----------

def zscore(df, col: str):
    stats = df.agg(F.mean(col).alias("mean"), F.stddev(col).alias("std")).first()
    return df.withColumn(f"{col}_z", (F.col(col) - stats["mean"]) / stats["std"])

WEIGHTS = {
    "population_growth_rate": 1.0,
    "dwelling_approvals_per_capita": 1.0,
    "crash_rate_severity_weighted": 1.0,
    "traffic_volume_index": 1.0,
    "pt_stops_per_capita": 0.0,  # Phase 2 - GTFS not sourced yet, weight 0 keeps formula shape intact
}

scored = feature_table
for col in ["population_growth_rate", "dwelling_approvals_per_capita", "crash_rate_severity_weighted", "traffic_volume_index"]:
    scored = zscore(scored, col)

scored = scored.withColumn(
    "priority_score",
    F.coalesce(F.col("population_growth_rate_z"), F.lit(0)) * WEIGHTS["population_growth_rate"]
    + F.coalesce(F.col("dwelling_approvals_per_capita_z"), F.lit(0)) * WEIGHTS["dwelling_approvals_per_capita"]
    + F.coalesce(F.col("crash_rate_severity_weighted_z"), F.lit(0)) * WEIGHTS["crash_rate_severity_weighted"]
    + F.coalesce(F.col("traffic_volume_index_z"), F.lit(0)) * WEIGHTS["traffic_volume_index"],
)

scored.orderBy(F.desc("priority_score")).select(
    "LGA", "population_growth_rate", "dwelling_approvals_per_capita",
    "crash_rate_severity_weighted", "traffic_volume_index", "priority_score",
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Write silver table

# COMMAND ----------

full_table = f"{catalog}.{schema}.silver_lga_features"
(
    scored.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(full_table)
)
print(f"{full_table}: {scored.count():,} rows, {len(scored.columns)} columns written")

# COMMAND ----------



# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. QA
# MAGIC Null counts per feature - expect some nulls in `dwelling_approvals_per_capita` (not sourced
# MAGIC yet) and possibly `traffic_volume_index` if any LGA had zero matched sites. Anything else
# MAGIC null is worth investigating before Process 3.

# COMMAND ----------

for col in ["population_growth_rate", "crash_rate_severity_weighted", "traffic_volume_index", "dwelling_approvals_per_capita"]:
    null_count = scored.filter(F.col(col).isNull()).count()
    print(f"{col}: {null_count} nulls of {scored.count()} rows")