"""
03_score_villages.py

Cleans the village-level GEE statistics, builds growth signals, scores every
village and selects the top 100 economically growing villages.

Definition used ("economic growth"):
  A sustained increase in observable economic ACTIVITY (night-time lights) together
  with new physical CAPITAL (persistent new built-up area) between the baseline and
  end period, measured relative to each village's own starting point.

Signals (each converted to a 0-100 percentile among eligible villages):
  p_ntl_trend        Theil-Sen slope of log(1 + light sum) over NTL_TREND_YEARS
                     -> relative, outlier-robust growth in activity
  p_ntl_gain         increase in light sum per km2 (end avg - base avg)
                     -> absolute intensity gain; stops tiny 0 -> 0.5 flickers dominating
  p_built_share      new built-up area / village area
                     -> how much of the village was newly built on
  p_built_expansion  new built-up area / (2020 built-up area + 1 ha)
                     -> growth of the settlement relative to its own size
  (new built-up = not built in 2020 AND built in both 2024 and 2025, from 02_extract_gee.py)

Score = weighted mean of the percentiles (WEIGHTS). A village can enter the ranking
only if BOTH an activity signal and a construction signal are >= AGREE_PCT
(multi-signal agreement), which filters single-sensor artefacts.

Exclusions: towns, slivers < MIN_AREA_HA, villages with missing/cloudy Esri LULC.
All remaining villages are ranked in ONE list. Villages within PERI_URBAN_KM of a
major town are marked `peri_urban = 1` as an attribute, not ranked separately.

Input:  data/interim/village_gee_stats.csv          (02_extract_gee.py)
        data/interim/gee_upload/villages_gee.shp     (01_prepare_gee_upload.py)
Output: data/output/villages_scored.csv.gz all villages, signals, score, exclusion reason
        data/output/top100_villages.csv    final ranked top 100

Run from the project root:
  python scripts/03_score_villages.py
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

ROOT = Path(__file__).resolve().parents[1]
STATS_FILE = ROOT / "data" / "interim" / "village_gee_stats.csv"
VILLAGES_FILE = ROOT / "data" / "interim" / "gee_upload" / "villages_gee.shp"
OUT_DIR = ROOT / "data" / "output"

# ----------------------------------------------------------------------------
# Analyst decisions: review and justify each of these in the write-up
# ----------------------------------------------------------------------------
NTL_BASE_YEARS = [2021]                  # 2020 skipped: COVID lockdown depresses lights nationwide
NTL_END_YEARS = [2024, 2025]             # 2-year average dampens single-year noise
NTL_TREND_YEARS = [2021, 2022, 2023, 2024, 2025]

WEIGHTS = {                              # must match the signal columns built below
    "p_ntl_trend": 0.30,
    "p_ntl_gain": 0.20,
    "p_built_share": 0.25,
    "p_built_expansion": 0.25,
}
ACTIVITY = ["p_ntl_trend", "p_ntl_gain"]
CONSTRUCTION = ["p_built_share", "p_built_expansion"]

AGREE_PCT = 80             # both an activity and a construction signal must reach this percentile
MIN_NEW_BUILT_HA = 1.0     # construction signal counts only with >= 1 ha (100 Esri pixels) of new built-up
MIN_END_NTL_SUM = 1.0      # activity signal counts only if the village is actually lit at the end
MIN_AREA_HA = 10           # drop slivers (split-polygon fragments)
MAX_CLOUD_FRAC = 0.10      # drop villages where Esri LULC is >10% cloud in either year

N_MAJOR_TOWNS = 500        # brightest towns at baseline ~ Census class-I cities (pop > 1 lakh)
PERI_URBAN_KM = 10         # villages within this distance of a major town are flagged peri-urban

# Large-project flag (kept in the ranking, marked for review): change too big or too
# abrupt to be organic village growth, e.g. airports, refineries, plants, highways
PROJECT_NEW_BUILT_HA = 100     # >= 100 ha of new built-up in ~4 years
PROJECT_SHARE_NEW = 0.30       # >= 30% of the village newly built ...
PROJECT_SHARE_BASE_HA = 25     # ... starting from < 25 ha of built-up in 2020 ...
PROJECT_SHARE_MIN_HA = 15      # ... and at least 15 ha new (so tiny villages are not flagged)
PROJECT_LIGHT_X = 15           # lights end/(base+1) >= 15x ...
PROJECT_LIGHT_END = 100        # ... reaching a substantial light sum

TOP_N = 100
N_WEIGHT_DRAWS = 1000      # random weight sets for the rank-stability check
SEED = 42
DIST_CRS = "EPSG:7755"     # WGS 84 / India NSF LCC, metres; suitable for distances across India

LULC_CLASSES = ["water", "trees", "flood", "crops", "built", "bare", "snow", "cloud", "range"]
CODE_COLS = {"pc11_s_id": str, "pc11_d_id": str, "pc11_sd_id": str, "pc11_tv_id": str}


def theil_sen_slope(y, t):
    """Row-wise Theil-Sen slope: median of all pairwise slopes (robust to one bad year)."""
    t = np.asarray(t, dtype=float)
    i, j = np.triu_indices(len(t), k=1)
    slopes = (y[:, j] - y[:, i]) / (t[j] - t[i])
    return np.median(slopes, axis=1)


# ----------------------------------------------------------------------------
# 1. Load
# ----------------------------------------------------------------------------
df = pd.read_csv(STATS_FILE, dtype=CODE_COLS)
print(f"loaded {len(df):,} polygons")

# Village location (representative point always falls inside the polygon) and
# distance to the nearest major town, both from the local polygons
geo = pyogrio.read_dataframe(VILLAGES_FILE, columns=["uid"])
pts = geo.representative_point()
geo["lon"], geo["lat"] = pts.x, pts.y
geo = geo.to_crs(DIST_CRS)

# ----------------------------------------------------------------------------
# 2. Quality filters (first matching reason is recorded)
# ----------------------------------------------------------------------------
for y in (2020, 2025):
    df[f"lulc_cover_{y}"] = df[[f"{c}_{y}" for c in LULC_CLASSES]].sum(axis=1) / df["area_ha"]
cloud_frac = np.maximum(df["cloud_2020"], df["cloud_2025"]) / df["area_ha"]

df["excl_reason"] = ""


def exclude(mask, reason):
    df.loc[mask & (df["excl_reason"] == ""), "excl_reason"] = reason


exclude(df["is_town"] == 1, "town")
exclude(df["area_ha"] < MIN_AREA_HA, f"area < {MIN_AREA_HA} ha")
exclude(((df["lulc_cover_2020"] - 1).abs() > 0.01) | ((df["lulc_cover_2025"] - 1).abs() > 0.01),
        "Esri LULC missing")
exclude(cloud_frac > MAX_CLOUD_FRAC, "Esri LULC cloudy")
df[[c for c in df.columns if c.startswith("ntl_") and c.endswith("_mean")]] = (
    df.filter(regex=r"^ntl_\d{4}_mean$").fillna(0))  # empty only for slivers with no pixel centre

print("excluded:", df.loc[df["excl_reason"] != "", "excl_reason"].value_counts().to_dict())

# ----------------------------------------------------------------------------
# 3. Peri-urban flag: distance to the nearest major town
#    Major towns = the N brightest towns at baseline (light sum ~ town size),
#    split towns are summed across their polygon pieces first.
# ----------------------------------------------------------------------------
base_col = f"ntl_{NTL_BASE_YEARS[0]}_sum"
town_light = df[df["is_town"] == 1].groupby("pc11_tv_id")[base_col].sum()
major_codes = town_light.nlargest(N_MAJOR_TOWNS).index
major_uids = df.loc[(df["is_town"] == 1) & df["pc11_tv_id"].isin(major_codes), "uid"]
major_towns = geo.loc[geo["uid"].isin(major_uids), ["geometry"]]

village_pts = gpd.GeoDataFrame(geo[["uid"]], geometry=geo.representative_point(), crs=DIST_CRS)
near = gpd.sjoin_nearest(village_pts, major_towns, how="left", distance_col="dist_m")
near = near.drop_duplicates("uid")  # equidistant ties return several rows
df = df.merge(geo[["uid", "lat", "lon"]], on="uid").merge(near[["uid", "dist_m"]], on="uid")
df["dist_major_town_km"] = df.pop("dist_m") / 1000
df["peri_urban"] = (df["dist_major_town_km"] <= PERI_URBAN_KM).astype(int)

# ----------------------------------------------------------------------------
# 4. Growth signals
# ----------------------------------------------------------------------------
def light_avg(years):
    return df[[f"ntl_{y}_sum" for y in years]].mean(axis=1)


df["ntl_base"] = light_avg(NTL_BASE_YEARS)
df["ntl_end"] = light_avg(NTL_END_YEARS)
trend_matrix = np.log1p(df[[f"ntl_{y}_sum" for y in NTL_TREND_YEARS]].to_numpy())
df["ntl_trend"] = theil_sen_slope(trend_matrix, NTL_TREND_YEARS)
df["ntl_gain_per_km2"] = (df["ntl_end"] - df["ntl_base"]) / (df["area_ha"] / 100)
df["built_share_new"] = df["new_built_ha"] / df["area_ha"]
df["built_expansion"] = df["new_built_ha"] / (df["built_2020"] + 1.0)

# Review flags (not exclusions): land-cover changes that often are NOT economic growth
df["flag_bare_gain"] = ((df["bare_2025"] - df["bare_2020"]) / df["area_ha"] > 0.10).astype(int)
# cropland lost to something other than new built-up (e.g. crop<->rangeland misclassification)
df["flag_crop_loss"] = ((df["crops_2020"] - df["crops_2025"] - df["crop_to_built_ha"])
                        / df["area_ha"] > 0.30).astype(int)
df["flag_water_change"] = ((df["water_2025"] - df["water_2020"]).abs() / df["area_ha"] > 0.10).astype(int)
light_x = df["ntl_end"] / (df["ntl_base"] + 1)
df["flag_large_project"] = (
    (df["new_built_ha"] >= PROJECT_NEW_BUILT_HA)
    | ((df["built_share_new"] >= PROJECT_SHARE_NEW) & (df["built_2020"] < PROJECT_SHARE_BASE_HA)
       & (df["new_built_ha"] >= PROJECT_SHARE_MIN_HA))
    | ((light_x >= PROJECT_LIGHT_X) & (df["ntl_end"] >= PROJECT_LIGHT_END))
).astype(int)

# ----------------------------------------------------------------------------
# 5. Percentiles, composite score, agreement filter (eligible villages only)
# ----------------------------------------------------------------------------
eligible = df["excl_reason"] == ""
signal_src = {
    "p_ntl_trend": "ntl_trend",
    "p_ntl_gain": "ntl_gain_per_km2",
    "p_built_share": "built_share_new",
    "p_built_expansion": "built_expansion",
}
for p_col, src in signal_src.items():
    df.loc[eligible, p_col] = df.loc[eligible, src].rank(pct=True) * 100

w = pd.Series(WEIGHTS)
df["score"] = (df[list(w.index)] * w).sum(axis=1, min_count=len(w)) / w.sum()

activity_pass = (df[ACTIVITY].max(axis=1) >= AGREE_PCT) & (df["ntl_end"] >= MIN_END_NTL_SUM)
construction_pass = ((df[CONSTRUCTION].max(axis=1) >= AGREE_PCT)
                     & (df["new_built_ha"] >= MIN_NEW_BUILT_HA))
df["signals_agree"] = (eligible & activity_pass & construction_pass).astype(int)


# ----------------------------------------------------------------------------
# 6. Ranking + rank stability under random weights
# ----------------------------------------------------------------------------
def rank_pool(pool):
    """Rank a candidate pool by score; add top-N membership share under random weights."""
    pool = pool.sort_values("score", ascending=False).copy()
    P = pool[list(w.index)].to_numpy()
    n_top = min(TOP_N, len(pool))
    counts = np.zeros(len(pool))
    rng = np.random.default_rng(SEED)
    for W in np.array_split(rng.dirichlet(np.ones(len(w)), N_WEIGHT_DRAWS), 10):
        S = P @ W.T                                         # (villages, draws)
        top_idx = np.argpartition(-S, n_top - 1, axis=0)[:n_top]
        np.add.at(counts, top_idx.ravel(), 1)
    pool["rank_stability"] = counts / N_WEIGHT_DRAWS * 100  # % of weight sets keeping it in top N
    pool = pool.head(TOP_N)
    pool.insert(0, "rank", np.arange(1, len(pool) + 1))
    return pool


candidates = df[df["signals_agree"] == 1]
top = rank_pool(candidates)

# ----------------------------------------------------------------------------
# 7. Outputs
# ----------------------------------------------------------------------------
OUT_COLS = [
    "rank", "score", "rank_stability",
    "tv_name", "dist_name", "state_name", "uid", "pc11_tv_id", "lat", "lon",
    "area_ha", "dist_major_town_km", "peri_urban",
    "built_2020", "built_2025", "new_built_ha", "crop_to_built_ha",
    "ntl_base", "ntl_end", "ntl_trend", "ntl_gain_per_km2",
    "built_share_new", "built_expansion",
    *signal_src.keys(),
    "flag_large_project", "flag_bare_gain", "flag_crop_loss", "flag_water_change",
]
OUT_DIR.mkdir(parents=True, exist_ok=True)
top[OUT_COLS].round(4).to_csv(OUT_DIR / "top100_villages.csv", index=False)

scored_cols = [c for c in OUT_COLS if c not in ("rank", "rank_stability")]
scored_cols += ["is_town", "signals_agree", "excl_reason",
                *[f"ntl_{y}_sum" for y in range(2020, 2026)]]
df[scored_cols].round(4).to_csv(OUT_DIR / "villages_scored.csv.gz", index=False)

# ----------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------
print(f"eligible villages: {eligible.sum():,}")
print(f"pass multi-signal agreement: {len(candidates):,}")
print(f"top {len(top)}: score {top['score'].min():.1f}-{top['score'].max():.1f}, "
      f"median rank stability {top['rank_stability'].median():.0f}%, "
      f"peri-urban {int(top['peri_urban'].sum())}")
print("top 100 by state:", top["state_name"].value_counts().head(10).to_dict())
print("top 100 review flags:", {f: int(top[f].sum()) for f in
                                ("flag_large_project", "flag_bare_gain", "flag_crop_loss", "flag_water_change")})
print(top[["rank", "tv_name", "dist_name", "state_name", "score", "rank_stability",
           "new_built_ha", "ntl_base", "ntl_end"]].head(15).round(2).to_string(index=False))
print(f"written to {OUT_DIR}")
