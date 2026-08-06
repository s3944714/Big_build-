# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — K-Means Clustering (Model A)
# MAGIC **Project:** "Where Should Victoria Build Next?" — VIDA Data & IT Graduate Program demo
# MAGIC
# MAGIC **Purpose:** segment the 80 LGAs into data-driven priority archetypes, as an independent
# MAGIC sanity-check on the heuristic composite score from Process 2 — do LGAs the formula ranks
# MAGIC highest also fall into a "high growth / high strain" cluster on their own, without the score
# MAGIC telling them to?
# MAGIC
# MAGIC **Feature scope note:** `dwelling_approvals_per_capita` is null for all 80 LGAs right now
# MAGIC (statewide building permits not ingested yet) — excluded from clustering below rather than
# MAGIC imputed, since a fully-null column breaks standardisation outright and a placeholder value
# MAGIC would inject noise, not signal. Clustering runs on the 3 features that are actually
# MAGIC populated: `population_growth_rate`, `crash_rate_severity_weighted`, `traffic_volume_index`.
# MAGIC Re-running this notebook after the permits data lands picks up the 4th feature automatically.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Config + dependencies
# MAGIC Same pattern as Processes 1 and 2 - install before anything else depends on session state,
# MAGIC since this environment needs a restart after `%pip install` even for first-time installs.

# COMMAND ----------

dbutils.widgets.text("catalog", "workspace", "Catalog")
dbutils.widgets.text("schema", "vic_build", "Schema")

# COMMAND ----------

# MAGIC %pip install scikit-learn -q
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Load features
# MAGIC Pulled to pandas - only 80 rows, no need for Spark/MLlib at this scale. Matches the plan's
# MAGIC own recommendation (scikit-learn in a single-node notebook, MLlib only worth mentioning as
# MAGIC an alternative for the video, not actually needed here).

# COMMAND ----------

silver = spark.table(f"{catalog}.{schema}.silver_lga_features").toPandas()

CLUSTER_FEATURES = [
    "population_growth_rate",
    "dwelling_approvals_per_capita",
    "crash_rate_severity_weighted",
    "traffic_volume_index",
]

print(f"Loaded {len(silver)} LGAs")
for col in CLUSTER_FEATURES:
    nulls = silver[col].isna().sum()
    print(f"  {col}: {nulls} nulls")

# Traffic volume nulls (LGAs with zero matched SCATS sites) filled with 0 - a defensible proxy
# for "no measured signal volume", not a claim that traffic is literally zero. Worth a caveat
# in the video if this comes up. Rows with nulls on the other three features (should be near-zero
# now that the statewide permits data is in - only Unincorporated Vic isn't a real single place)
# are dropped rather than silently filled, since that would be a real data problem worth
# investigating, not a proxy assumption.
cluster_df = silver.dropna(
    subset=["population_growth_rate", "dwelling_approvals_per_capita", "crash_rate_severity_weighted"]
).copy()
cluster_df["traffic_volume_index"] = cluster_df["traffic_volume_index"].fillna(0)
print(f"\n{len(cluster_df)} LGAs going into clustering (dropped {len(silver) - len(cluster_df)} for missing core features)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Standardise
# MAGIC Z-score each feature so no single feature dominates the distance calculation just because
# MAGIC its raw numbers happen to be larger (traffic volume is in the thousands, population growth
# MAGIC rate is a small decimal).

# COMMAND ----------

scaler = StandardScaler()
X = scaler.fit_transform(cluster_df[CLUSTER_FEATURES])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Choose k via silhouette score
# MAGIC Try k = 3 through 7 (plan expects ~4-5), pick whichever separates the LGAs most cleanly -
# MAGIC not just the highest score in isolation, but one that's a clear step up from its neighbours
# MAGIC rather than a razor-thin, easily-arbitrary winner.

# COMMAND ----------

silhouette_scores = {}
for k in range(3, 8):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X)
    score = silhouette_score(X, labels)
    silhouette_scores[k] = score
    print(f"k={k}: silhouette={score:.4f}")

best_k = max(silhouette_scores, key=silhouette_scores.get)
print(f"\nHighest silhouette score: k={best_k} ({silhouette_scores[best_k]:.4f})")
print("Check the printed scores above before trusting this automatically - if the top two are")
print("close, prefer the smaller k (simpler, easier to name and explain archetypes for).")

# COMMAND ----------

# MAGIC %md
# MAGIC **Set `FINAL_K` explicitly below** once you've looked at the scores above - don't just take
# MAGIC `best_k` on faith. Defaults to `best_k` but override if a smaller, nearly-as-good k makes a
# MAGIC cleaner story.

# COMMAND ----------

FINAL_K = 4  #override with an int here if you disagree with the automatic pick

kmeans = KMeans(n_clusters=FINAL_K, random_state=42, n_init=10)
cluster_df["cluster"] = kmeans.fit_predict(X)

print(f"Cluster sizes (k={FINAL_K}):")
print(cluster_df["cluster"].value_counts().sort_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Name the clusters
# MAGIC Rule-based, not hand-picked: for each cluster, compare its mean z-score on a growth axis and
# MAGIC a strain axis against the overall mean (0, since the data's standardised). This is
# MAGIC reproducible and defensible under questioning - "the algorithm decided," not "I eyeballed
# MAGIC the centroids and picked names that sounded right."

# COMMAND ----------

cluster_df["growth_z"] = (
    X[:, CLUSTER_FEATURES.index("population_growth_rate")]
    + X[:, CLUSTER_FEATURES.index("dwelling_approvals_per_capita")]
) / 2
cluster_df["strain_z"] = (
    X[:, CLUSTER_FEATURES.index("crash_rate_severity_weighted")]
    + X[:, CLUSTER_FEATURES.index("traffic_volume_index")]
) / 2

cluster_summary = cluster_df.groupby("cluster")[["growth_z", "strain_z", "priority_score"]].mean()
print(cluster_summary)

ARCHETYPE_NAMES = {
    (True, True): "Growth Hotspot – High Strain",
    (True, False): "Emerging Growth – Low Strain (so far)",
    (False, True): "Established High-Strain",
    (False, False): "Low-Pressure Stable",
}

def archetype_for_cluster(cluster_id: int) -> str:
    row = cluster_summary.loc[cluster_id]
    high_growth = row["growth_z"] > 0
    high_strain = row["strain_z"] > 0
    return ARCHETYPE_NAMES[(high_growth, high_strain)]

cluster_names = {c: archetype_for_cluster(c) for c in cluster_summary.index}
cluster_df["archetype"] = cluster_df["cluster"].map(cluster_names)

for c, name in cluster_names.items():
    print(f"Cluster {c}: {name}")

# COMMAND ----------

# MAGIC %md
# MAGIC **If two clusters land on the same quadrant** (e.g. two different "Growth Hotspot" clusters
# MAGIC at different intensities), that's not a bug — it means the algorithm found a real
# MAGIC distinction the 2x2 framing doesn't capture. Worth a one-line note in the video rather than
# MAGIC forcing a fifth made-up name; check the cell above's printed sizes/names before writing
# MAGIC anything down as fact.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Sanity check: known growth-corridor LGAs
# MAGIC Wyndham, Melton, Casey, Whittlesea are well-known outer-Melbourne growth areas. If the model
# MAGIC is behaving sensibly, they should cluster together in a high-growth archetype.

# COMMAND ----------

KNOWN_GROWTH_LGAS = ["WYNDHAM", "MELTON", "CASEY", "WHITTLESEA"]

check = cluster_df[cluster_df["lga_canonical"].isin(KNOWN_GROWTH_LGAS)][
    ["lga_canonical", "cluster", "archetype", "priority_score"]
]
print(check.to_string(index=False))

if check["archetype"].nunique() == 1 and "Growth" in check["archetype"].iloc[0]:
    print("\nAll four known growth LGAs landed in the same growth-flagged archetype - good sign.")
else:
    print("\nMixed or non-growth archetypes for known growth LGAs - worth investigating before trusting this clustering.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Cross-check against the composite score
# MAGIC Two independent methods (a hand-built formula, and unsupervised clustering) agreeing is a
# MAGIC much stronger result than either alone - this is the comparison that earns that claim.

# COMMAND ----------

print("Mean priority_score by cluster (should roughly track growth/strain archetype order):")
print(cluster_summary.sort_values("priority_score", ascending=False))

print("\nTop 10 LGAs by composite score, with their cluster archetype:")
top10 = cluster_df.sort_values("priority_score", ascending=False).head(10)
print(top10[["lga_canonical", "priority_score", "archetype"]].to_string(index=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Write gold table

# COMMAND ----------

gold_spark = spark.createDataFrame(
    cluster_df.drop(columns=["growth_z", "strain_z"])
)

full_table = f"{catalog}.{schema}.gold_lga_priority"
(
    gold_spark.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(full_table)
)
print(f"{full_table}: {gold_spark.count():,} rows, {len(gold_spark.columns)} columns written")
gold_spark.orderBy("priority_score", ascending=False).display()

# COMMAND ----------

import os

pdf = spark.table(f"{catalog}.{schema}.gold_lga_priority").toPandas()

# Save into the same Workspace folder this notebook lives in
notebook_path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
workspace_dir = "/Workspace" + os.path.dirname(notebook_path)
local_path = f"{workspace_dir}/gold_lga_priority.csv"

pdf.to_csv(local_path, index=False)
print(f"Saved to: {local_path}")