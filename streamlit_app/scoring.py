"""
Composite Priority Score - mirrors the z-score + weighted sum in 02_silver_feature_table.py
exactly. If the weighting formula changes, change it in both places (see CLAUDE.md's
Workflow note) - this file existing separately from app.py is specifically so Process 5
doesn't quietly drift from the Databricks model.
"""
import pandas as pd

FEATURE_COLUMNS = [
    "population_growth_rate",
    "dwelling_approvals_per_capita",
    "crash_rate_severity_weighted",
    "traffic_volume_index",
]

DEFAULT_WEIGHTS = {
    "population_growth_rate": 1.0,
    "dwelling_approvals_per_capita": 1.0,
    "crash_rate_severity_weighted": 1.0,
    "traffic_volume_index": 1.0,
    "pt_stops_per_capita": 0.0,  # Phase 2 - GTFS not sourced yet, weight 0 keeps formula shape intact
}


def compute_priority_score(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """Recompute the composite score from raw features + weights - pure pandas at this scale
    (79 rows), no Spark needed. Cluster/archetype labels are NOT recomputed here - those come
    from Process 3's K-Means run and stay fixed; only the score and ranking respond to the
    sliders, matching what the plan actually promises ("watch the ranking change live"), not a
    live re-clustering."""
    scored = df.copy()
    for col in FEATURE_COLUMNS:
        mean = scored[col].mean()
        std = scored[col].std()
        scored[f"{col}_z"] = (scored[col] - mean) / std if std else 0.0

    scored["priority_score"] = sum(
        scored[f"{col}_z"].fillna(0) * weights.get(col, 0.0) for col in FEATURE_COLUMNS
    )
    return scored
