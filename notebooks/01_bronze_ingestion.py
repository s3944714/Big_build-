# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze Ingestion
# MAGIC **Project:** "Where Should Victoria Build Next?" — VIDA Data & IT Graduate Program demo
# MAGIC
# MAGIC **Purpose:** land the four Phase 1 MVP source files as governed Delta tables in Unity Catalog,
# MAGIC tagged with ingestion metadata, so the feature-table/composite-score notebook has a stable
# MAGIC bronze layer to build on.
# MAGIC
# MAGIC **Sources (Phase 1):**
# MAGIC 1. Victorian Road Crash Data (flat file) — opendata.transport.vic.gov.au
# MAGIC 2. VIF2023 LGA Population/Household/Dwelling Projections to 2036 — data.vic.gov.au
# MAGIC 3. Traffic Signal Volume — data.vic.gov.au
# MAGIC 4. Building permit approvals — data.vic.gov.au
# MAGIC
# MAGIC **Read before running:**
# MAGIC 1. Databricks Free Edition restricts outbound internet access from the compute, so these
# MAGIC    files can't be pulled with `requests`/`urllib` from inside the notebook. Download them
# MAGIC    to your laptop first, then upload via the workspace UI: **Catalog → your catalog →
# MAGIC    default schema → Volumes → Create volume → Upload files**. (`databricks fs cp` also
# MAGIC    works if you have the CLI set up locally.)
# MAGIC 2. Free Edition is Unity-Catalog-only — DBFS/FileStore is disabled — so raw files must land
# MAGIC    in a UC **Volume**, not `dbfs:/FileStore/...`.
# MAGIC 3. The VIF projections file ships as **.xlsx**, not CSV — handled separately below with pandas.
# MAGIC 4. Only the crash dataset has a ready-made `LGA_NAME` column. Traffic Signal Volume and
# MAGIC    Building Permits may key on something else (SCATS site ID + lat/long, or council name in
# MAGIC    a different format) — confirm this once you've opened the actual files, since it affects
# MAGIC    whether you need a spatial join to get everything onto the LGA grain.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Config

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Catalog")
dbutils.widgets.text("schema", "vic_build", "Schema")
dbutils.widgets.text("volume", "raw_data", "Volume (raw files land here)")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

raw_path = f"/Volumes/{catalog}/{schema}/{volume}"
print(f"Raw files expected under: {raw_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Make sure the schema + volume exist
# MAGIC Free Edition users have CREATE privileges on the workspace catalog's default schema out of
# MAGIC the box, so this should just work without extra admin setup.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.{volume}")
print(f"Ready: {catalog}.{schema}, volume '{volume}'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Install dependencies (once, up front)
# MAGIC `openpyxl` (VIF `.xlsx`) and `pyxlsb` (VBA building permits `.xlsb`, Process 2) aren't in
# MAGIC Free Edition's default environment. Installing them here — before anything else depends on
# MAGIC session state — means the restart this environment requires only costs the two lines below,
# MAGIC not the widgets, config, or helper function that come after it.
# MAGIC
# MAGIC `dbutils.widgets` values survive a Python restart (they're notebook-level, not interpreter
# MAGIC state), so `catalog`/`schema`/`volume`/`raw_path` just get re-read from the widgets
# MAGIC immediately below rather than lost.

# COMMAND ----------

# MAGIC %pip install openpyxl pyxlsb -q
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Re-read config after the restart above - dbutils.widgets persisted, plain Python variables didn't.
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
raw_path = f"/Volumes/{catalog}/{schema}/{volume}"
print(f"Raw files expected under: {raw_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Generic bronze-CSV loader
# MAGIC One helper, reused for every CSV source, so ingestion metadata and write behaviour stay
# MAGIC consistent across tables.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql import DataFrame


def load_bronze_csv(
    file_name: str,
    table_name: str,
    header: bool = True,
    sep: str = ",",
    extra_options: dict | None = None,
) -> DataFrame:
    """
    Read a raw CSV from the UC volume, tag it with ingestion metadata,
    and write it out as a managed Delta bronze table.
    """
    file_path = f"{raw_path}/{file_name}"

    reader = (
        spark.read.format("csv")
        .option("header", header)
        .option("sep", sep)
        .option("inferSchema", "true")
        .option("multiLine", "true")
        .option("escape", '"')
    )
    if extra_options:
        for key, value in extra_options.items():
            reader = reader.option(key, value)

    df = reader.load(file_path)
    # input_file_name() is blocked under Unity Catalog governed compute
    # (UC_COMMAND_NOT_SUPPORTED). _metadata.file_name is the UC-safe equivalent, and still
    # tags each row with the specific file it came from for wildcard loads like "VSDATA_*.csv".
    df = df.withColumn("_source_file", F.col("_metadata.file_name")).withColumn(
        "_ingested_at", F.current_timestamp()
    )

    full_table = f"{catalog}.{schema}.{table_name}"
    (
        df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(full_table)
    )

    print(f"{full_table}: {df.count():,} rows, {len(df.columns)} columns  <-  {file_name}")
    return df

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Road Crash Data
# MAGIC Uses the single flat file (`victorian_road_crash_data.csv`), not the multi-table relational
# MAGIC export — the flat file already carries `LGA_NAME`, so it's the right choice for this project's
# MAGIC LGA grain. Confirmed columns (via the Transport Vic open data catalog) include:
# MAGIC `ACCIDENT_NO, ACCIDENT_DATE, ACCIDENT_TIME, ACCIDENT_TYPE, DAY_OF_WEEK, SEVERITY, SPEED_ZONE,
# MAGIC ROAD_NAME, ROAD_TYPE, LGA_NAME, DTP_REGION, LATITUDE, LONGITUDE, TOTAL_PERSONS, FATALITY,
# MAGIC SERIOUSINJURY, OTHERINJURY, NO_OF_VEHICLES, ...` (plus person/vehicle/road-condition counts).

# COMMAND ----------

bronze_crash = load_bronze_csv(
    file_name="victorian_road_crash_data.csv",
    table_name="bronze_road_crash",
)

bronze_crash.select(
    "ACCIDENT_NO", "ACCIDENT_DATE", "SEVERITY", "LGA_NAME", "DTP_REGION",
    "SPEED_ZONE", "NO_OF_VEHICLES", "FATALITY", "SERIOUSINJURY", "OTHERINJURY",
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC **`SEVERITY` values confirmed** against the actual file — exactly four categories:
# MAGIC `"Fatal accident"`, `"Serious injury accident"`, `"Other injury accident"`,
# MAGIC `"Non injury accident"`. Safe to hardcode these in the fatal=3/serious=2/minor=1 `CASE WHEN`
# MAGIC in Process 2.
# MAGIC
# MAGIC **`LGA_NAME` has 88 distinct values in Spark, not the 80 expected** (79 LGAs +
# MAGIC Unincorporated Vic). Two separate issues bundled into that number: 7 are alpine resort
# MAGIC areas that aren't LGAs in their own right — `(FALLS CREEK)`, `(FRENCH ISLAND)`,
# MAGIC `(LAKE MOUNTAIN)`, `(MOUNT BAW BAW)`, `(MOUNT BULLER)`, `(MOUNT HOTHAM)`,
# MAGIC `(MOUNT STIRLING)` — and 1 is an actual `NULL` (some crash records have no LGA at all;
# MAGIC `distinct().count()` in Spark counts `NULL` as a value, unlike pandas' `nunique()`, which is
# MAGIC why an earlier pandas-side check said 87). VIF won't have matching rows for the alpine areas,
# MAGIC and the null rows can't be placed on the LGA grid at all — Process 2 needs a decision on both
# MAGIC (fold alpine areas into their enclosing LGA or drop them; drop the nulls after checking how
# MAGIC many there are, below).

# COMMAND ----------

bronze_crash.select("SEVERITY").distinct().display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. VIF population projections (LGA-level, to 2036)
# MAGIC Confirmed structure (opened the actual workbook): 7 sheets —
# MAGIC `Contents, Explanatory Notes, Total_Population, Total_Dwellings, Total_Households,
# MAGIC Dwellings_and_Households, Households_by_Type`. This project needs `Total_Population`.
# MAGIC Header row is Excel row 10 (`LGA code, LGA, 2021, 2026, 2031, 2036`), preceded by 9 title/
# MAGIC contact rows. Row 11 is a `"Victoria"` statewide total (no LGA code) — drop it, we only want
# MAGIC LGA rows. Data ends at `"Unincorporated Vic"` (LGA code 29399), followed by blank rows.
# MAGIC
# MAGIC **LGA naming confirmed:** Title Case with a council-type suffix, e.g. `"Alpine (S)"`,
# MAGIC `"Ararat (RC)"`, `"Ballarat (C)"` — S=Shire, C=City, RC=Rural City. This does **not** match
# MAGIC the crash data's `"ALPINE"` / `"ARARAT"` / `"BALLARAT"` (upper case, no suffix) — confirmed
# MAGIC mismatch, so Process 2 needs a normalisation step (strip the `" (X)"` suffix, uppercase).
# MAGIC
# MAGIC **Column name quirk:** the source header has `"LGA  code"` with a double space, which Delta
# MAGIC rejects outright (`DELTA_INVALID_CHARACTERS_IN_COLUMN_NAMES`) — sanitised below before the
# MAGIC Spark conversion.
# MAGIC
# MAGIC `openpyxl` was already installed in step 3 - no extra install needed here.

# COMMAND ----------

import pandas as pd

vif_file = "VIF2023_LGA_Pop_Hhold_Dwelling_Projections_to_2036.xlsx"
vif_local_path = f"{raw_path}/{vif_file}"

import re

vif_pdf = pd.read_excel(vif_local_path, sheet_name="Total_Population", header=9)
# Delta rejects spaces (and other characters) in column names - the source header has
# "LGA  code" (double space), which fails outright. Collapse any whitespace run to a
# single underscore rather than hand-fixing just this one column, in case other VIF
# sheets have the same quirk when this gets reused for Total_Dwellings later.
vif_pdf.columns = [re.sub(r"\s+", "_", str(c).strip()) for c in vif_pdf.columns]
vif_pdf = vif_pdf[vif_pdf["LGA"].notna() & (vif_pdf["LGA"] != "Victoria")].reset_index(drop=True)

vif_df = spark.createDataFrame(vif_pdf)
vif_df = vif_df.withColumn("_source_file", F.lit(vif_file)).withColumn(
    "_ingested_at", F.current_timestamp()
)

full_table = f"{catalog}.{schema}.bronze_vif_population"
(
    vif_df.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(full_table)
)
print(f"{full_table}: {vif_df.count():,} rows, {len(vif_df.columns)} columns (expect 80: 79 LGAs + Unincorporated Vic)")
vif_df.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Traffic Signal Volume
# MAGIC Confirmed structure: daily files named `VSDATA_YYYYMMDD.csv`, one row per SCATS site +
# MAGIC detector, columns `NB_SCATS_SITE, QT_INTERVAL_COUNT (actually the date, oddly named),
# MAGIC NB_DETECTOR, V00...V95 (96 x 15-min volumes for the day), NM_REGION, CT_RECORDS,
# MAGIC QT_VOLUME_24HOUR, CT_ALARM_24HOUR`. No `LGA_NAME`, no lat/long, and `NM_REGION` is a coarse
# MAGIC DTP region code — not LGA-level.
# MAGIC
# MAGIC **Scope decision:** ingesting the full history (annual ZIPs of 1.1-1.8 GB back to 2014) is
# MAGIC unnecessary for a composite score that reflects *current* strain — using the ~27 days of
# MAGIC July 2026 uploaded as a representative snapshot. If you add more days later, this cell's
# MAGIC wildcard picks them up automatically.
# MAGIC
# MAGIC **LGA mapping:** don't rely on `NM_REGION`. Instead this loads the separate **Victorian
# MAGIC Traffic Signals** reference file (`SITE_NO, SITE_NAME, TYPE, MUNICIPALITY, LATITUDE,
# MAGIC LONGITUDE`) as its own bronze table now. `MUNICIPALITY` here is a 3-letter DTP council code
# MAGIC (e.g. `WTH`, `KIN`, `YRG`) with no verified public decode table, so the silver-layer join
# MAGIC (Process 2) uses `LATITUDE`/`LONGITUDE` with a proper spatial join against an authoritative
# MAGIC LGA boundary polygon (Vicmap Admin LGA Polygon, or the Geoscape LGA GeoJSON on data.gov.au)
# MAGIC rather than guessing what the codes mean.

# COMMAND ----------

# One row per site+detector+day across all uploaded VSDATA files - wildcard read.
bronze_traffic = load_bronze_csv(
    file_name="VSDATA_*.csv",
    table_name="bronze_traffic_signal_volume",
)
bronze_traffic.select(
    "NB_SCATS_SITE", "QT_INTERVAL_COUNT", "NB_DETECTOR", "NM_REGION", "QT_VOLUME_24HOUR",
).display()

# COMMAND ----------

# Site reference file: NB_SCATS_SITE (volume data) joins to SITE_NO (this file) in Process 2.
bronze_traffic_sites = load_bronze_csv(
    file_name="victorian_traffic_signals.csv",
    table_name="bronze_traffic_signal_sites",
)
bronze_traffic_sites.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Building permit approvals
# MAGIC **The uploaded `building-permits.csv` is not the statewide dataset.** Checked the actual
# MAGIC file: columns are `council_ref, permit_number, issue_date, address, desc_of_works,
# MAGIC estimated_cost_of_works, rbs_number, commence_by_date, completed_by_date,
# MAGIC permit_certificate_type` — no LGA/municipality column, and every address resolves to one of
# MAGIC 14 suburbs (Carlton, Docklands, East Melbourne, Kensington, Melbourne, North Melbourne,
# MAGIC Parkville, Port Melbourne, South Wharf, South Yarra, Southbank, West Melbourne, Flemington,
# MAGIC Carlton North) — all inner-Melbourne. This matches the **City of Melbourne's own open data
# MAGIC portal** ("Building Permits", data.melbourne.vic.gov.au), not a statewide feed. Used as-is,
# MAGIC every other LGA in Victoria would get a null `dwelling_approvals_per_capita` — the feature
# MAGIC would only ever surface Melbourne.
# MAGIC
# MAGIC **The dataset the plan actually needs** is the VBA/Building and Plumbing Commission's
# MAGIC **"Building Permit Activity Data"** (discover.data.vic.gov.au / vba.vic.gov.au/about/data) —
# MAGIC one file per year, and per its own description it "can be sliced by: region, municipality,
# MAGIC suburb, postcode and street name." It ships as **`.xlsb`** (Excel binary) — `pyxlsb` was
# MAGIC already installed in step 3, so `pd.read_excel(..., engine="pyxlsb")` will work once
# MAGIC downloaded. Grab one recent year (2024 or 2025) rather than the full 2009-2024 run; a single
# MAGIC year of approvals is plenty to represent "near-term development intensity" per the plan, and
# MAGIC each year's file is small (~9-13 MB).
# MAGIC
# MAGIC **Confirmed by opening the actual file:** two sheets, `Disclaimer` and `Sheet1` - the real
# MAGIC data (100,710 rows, 36 columns) is in `Sheet1`. Pandas defaults to the *first* sheet when
# MAGIC none is specified, which would have silently ingested the disclaimer text instead - explicit
# MAGIC `sheet_name="Sheet1"` below, not left to the default.
# MAGIC
# MAGIC Full 2025 calendar year, downloaded and confirmed via direct fetch:
# MAGIC `https://www.vba.vic.gov.au/__data/assets/file/0008/190295/20260079-Rawdata-December-2025.xlsb`
# MAGIC — save as `vba_building_permits_2025.xlsb` and upload to the volume. Data dictionary:
# MAGIC `https://www.vba.vic.gov.au/__data/assets/excel_doc/0007/99628/VBA-building-supplementary-information.xlsx`
# MAGIC
# MAGIC The City of Melbourne file ingests below for now (it's real, useful data) — just don't wire
# MAGIC it into the statewide feature table until the VBA file is in place alongside it.

# COMMAND ----------

bronze_permits_com = load_bronze_csv(
    file_name="building-permits.csv",
    table_name="bronze_building_permits_city_of_melbourne",
)
bronze_permits_com.printSchema()
bronze_permits_com.limit(5).display()

# COMMAND ----------

vba_file = "vba_building_permits_2025.xlsb"
vba_local_path = f"{raw_path}/{vba_file}"

vba_pdf = pd.read_excel(vba_local_path, engine="pyxlsb", sheet_name="Sheet1")
# Sanitise column names the same way as VIF in case this sheet has similar whitespace quirks.
vba_pdf.columns = [re.sub(r"\s+", "_", str(c).strip()) for c in vba_pdf.columns]

# Object-dtype columns from pyxlsb often mix real strings with NaN (a float) for missing
# values in the same column - Arrow can't infer one type for a part-string, part-float
# column and throws PySparkTypeError. Normalise: missing -> clean None, everything else -> str.
for col in vba_pdf.columns:
    if vba_pdf[col].dtype == object:
        vba_pdf[col] = vba_pdf[col].apply(lambda x: str(x) if pd.notna(x) else None)

print(f"Columns: {vba_pdf.columns.tolist()}")
print(f"Rows: {len(vba_pdf):,}")

vba_df = spark.createDataFrame(vba_pdf)
vba_df = vba_df.withColumn("_source_file", F.lit(vba_file)).withColumn(
    "_ingested_at", F.current_timestamp()
)

full_table = f"{catalog}.{schema}.bronze_building_permits_vic"
(
    vba_df.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(full_table)
)
print(f"{full_table}: {vba_df.count():,} rows, {len(vba_df.columns)} columns written")
vba_df.limit(5).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Bronze layer QA
# MAGIC Row/column counts for whatever has been ingested so far, plus an LGA-name coverage check
# MAGIC against Victoria's 79 LGAs (+ unincorporated Victoria) — this is where naming mismatches
# MAGIC between datasets usually surface (e.g. `"MELBOURNE"` vs `"City of Melbourne"` vs
# MAGIC `"Melbourne (C)"|"Melbourne (S)"|"Melbourne (RC)"` council/shire/rural-city suffixes). Worth
# MAGIC building a small LGA name-normalisation lookup once you see how each source actually spells it.

# COMMAND ----------

bronze_tables = [
    "bronze_road_crash",
    "bronze_vif_population",
    "bronze_traffic_signal_volume",
    "bronze_traffic_signal_sites",
    "bronze_building_permits_city_of_melbourne",
    "bronze_building_permits_vic",  # statewide VBA data
]

for t in bronze_tables:
    full = f"{catalog}.{schema}.{t}"
    if spark.catalog.tableExists(full):
        df = spark.table(full)
        print(f"{full}: {df.count():,} rows, {len(df.columns)} columns")
    else:
        print(f"{full}: not yet ingested")

# COMMAND ----------

# LGA name spot-check on the tables that are ready
crash_lga_count = bronze_crash.select("LGA_NAME").distinct().count()
print(f"Distinct LGA_NAME values in crash data: {crash_lga_count} (Victoria has 79 LGAs + unincorporated Vic)")

bronze_crash.select("LGA_NAME").distinct().orderBy("LGA_NAME").display()

# COMMAND ----------

# How many crash rows actually have no LGA at all? Small vs. large changes whether Process 2
# just drops them quietly or needs to investigate (e.g. cross-referencing LATITUDE/LONGITUDE
# against LGA boundaries instead of relying on the LGA_NAME field for those specific rows).
null_lga_count = bronze_crash.filter(F.col("LGA_NAME").isNull()).count()
total_crash_count = bronze_crash.count()
print(f"Crash rows with null LGA_NAME: {null_lga_count:,} of {total_crash_count:,} ({null_lga_count / total_crash_count:.2%})")

# COMMAND ----------

# Sanity check: does every NB_SCATS_SITE in the volume data have a matching SITE_NO in the
# site-location file? Sites without a match can't be placed on the LGA grain in Process 2.
volume_sites = bronze_traffic.select("NB_SCATS_SITE").distinct()
known_sites = bronze_traffic_sites.select("SITE_NO").distinct()
unmatched = volume_sites.join(known_sites, volume_sites.NB_SCATS_SITE == known_sites.SITE_NO, "left_anti")
print(f"Traffic volume sites with no location match: {unmatched.count():,} of {volume_sites.count():,}")