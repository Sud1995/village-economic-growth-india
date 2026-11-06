"""
02_extract_gee.py

Village-level zonal statistics from Google Earth Engine (GEE), reading the village
polygons straight from the local project folder (no GEE asset upload, no Drive export).

How it works:
  The local shapefile is split into small batches (~BATCH_SIZE villages, ordered by
  state/district so each batch is spatially compact). Each batch is sent to GEE as an
  in-memory FeatureCollection, GEE computes the statistics, and the results come back
  directly and are saved as one CSV per batch in data/interim/gee_batches/.
  Batches run in parallel on GEE's high-volume endpoint. Finished batches are skipped
  on re-run, so the script can be stopped and resumed at any time.

Statistics per village:
  A. Esri 10 m Annual LULC (Impact Observatory)  -> class areas (ha) for
     START_YEAR and END_YEAR, plus persistent new built-up and crop->built area
  B. VIIRS DNB monthly nightlights (VCMSLCFG)    -> annual sum and mean radiance
     for every year START_YEAR..END_YEAR (cheap at ~464 m, allows a trend later)

Data sources:
  Esri LULC:  projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS
              (GEE Community Catalog; Karra et al. 2021, Impact Observatory/Esri)
  VIIRS:      NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG
              (Earth Observation Group, Payne Institute, Colorado School of Mines)
  Villages:   SHRUG 2.2 PC11 village polygons (Development Data Lab), prepared by
              01_prepare_gee_upload.py -> data/interim/gee_upload/villages_gee.shp

Setup (once):
  pip install earthengine-api
  earthengine authenticate

Run from the project root:
  python scripts/02_extract_gee.py --project <gcp-project-id>
Quick test on N random villages (separate output, nothing else is touched):
  python scripts/02_extract_gee.py --project <gcp-project-id> --test 10

Output:
  data/interim/gee_batches/batch_XXXXX.csv    (one per batch, used for resuming)
  data/interim/village_gee_stats.csv          (all villages, written when every batch is done)
"""

import argparse
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ee
import pandas as pd
import pyogrio

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
parser.add_argument("--project", required=True, help="Cloud project registered for Earth Engine")
parser.add_argument("--test", type=int, metavar="N",
                    help="run on N random villages only, writing to *_test outputs")
parser.add_argument("--workers", type=int, default=10,
                    help="parallel requests (lower to 2-3 if the project is in restricted mode)")
ARGS = parser.parse_args()

ROOT = Path(__file__).resolve().parents[1]
VILLAGES_FILE = ROOT / "data" / "interim" / "gee_upload" / "villages_gee.shp"
BATCH_DIR = ROOT / "data" / "interim" / "gee_batches"
OUT_FILE = ROOT / "data" / "interim" / "village_gee_stats.csv"
if ARGS.test:
    BATCH_DIR = BATCH_DIR.with_name("gee_batches_test")
    OUT_FILE = OUT_FILE.with_name("village_gee_stats_test.csv")

START_YEAR = 2020
END_YEAR = 2025

NTL_MIN_CF_CVG = 2       # drop monthly pixels with fewer cloud-free observations
NTL_NOISE_FLOOR = 0.5    # nW/cm2/sr; annual medians below this are set to 0 (background noise)

LULC_SCALE = 10          # native Esri LULC resolution (m)
NTL_SCALE = 463.83       # native VIIRS DNB resolution (m)
TILE_SCALE = 4           # higher = less memory per request, slower

BATCH_SIZE = 200         # villages per request; failed batches are split automatically
WORKERS = ARGS.workers   # parallel requests to GEE
MAX_RETRIES = 5
COORD_PRECISION = 1e-5   # round coordinates to ~1 m to keep request payloads small

ID_COLS = ["uid", "pc11_s_id", "state_name", "pc11_d_id", "dist_name",
           "pc11_sd_id", "pc11_tv_id", "tv_name", "is_town", "chunk"]

# Esri LULC original class values (band b1) -> short names used in output columns
LULC_CLASSES = {
    1: "water",
    2: "trees",
    4: "flood",      # flooded vegetation
    5: "crops",
    7: "built",
    8: "bare",
    9: "snow",
    10: "cloud",     # no-data due to persistent cloud; useful as a quality flag
    11: "range",     # rangeland (grass + scrub)
}
BUILT, CROPS = 7, 5

# High-volume endpoint is meant for many parallel small requests like these
ee.Initialize(project=ARGS.project, opt_url="https://earthengine-highvolume.googleapis.com")

lulc_ic = ee.ImageCollection("projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS")
ntl_ic = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
ha = ee.Image.pixelArea().divide(1e4)  # pixel area in hectares


# ----------------------------------------------------------------------------
# A. LULC image: one band per (class, year) in hectares, plus change bands
# ----------------------------------------------------------------------------
def lulc_year(year):
    """Esri LULC map for one year: mosaic of all UTM tiles, single band 'b1'."""
    return (lulc_ic.filterDate(f"{year}-01-01", f"{year + 1}-01-01")
            .mosaic().select("b1"))


def lulc_area_bands(year):
    lc = lulc_year(year)
    bands = [ha.updateMask(lc.eq(v)).rename(f"{name}_{year}")
             for v, name in LULC_CLASSES.items()]
    return ee.Image.cat(bands)


lc_start = lulc_year(START_YEAR)
lc_end = lulc_year(END_YEAR)
lc_end_prev = lulc_year(END_YEAR - 1)

# New built-up = not built at START and built in BOTH of the last two years.
# Requiring two consecutive years suppresses single-year class flicker.
built_end_persistent = lc_end.eq(BUILT).And(lc_end_prev.eq(BUILT))
new_built = lc_start.neq(BUILT).And(built_end_persistent)
crop_to_built = lc_start.eq(CROPS).And(built_end_persistent)

lulc_img = ee.Image.cat([
    ha.rename("area_ha"),
    lulc_area_bands(START_YEAR),
    lulc_area_bands(END_YEAR),
    ha.updateMask(new_built).rename("new_built_ha"),
    ha.updateMask(crop_to_built).rename("crop_to_built_ha"),
]).unmask(0)

LULC_BANDS = (["area_ha"]
              + [f"{n}_{y}" for y in (START_YEAR, END_YEAR) for n in LULC_CLASSES.values()]
              + ["new_built_ha", "crop_to_built_ha"])


# ----------------------------------------------------------------------------
# B. Nightlights image: one annual composite band per year
# ----------------------------------------------------------------------------
def ntl_year(year):
    """Annual median of monthly avg_rad, using only months with enough cloud-free
    observations; the median also suppresses short-lived lights (fires, festivals)."""
    monthly = (ntl_ic.filterDate(f"{year}-01-01", f"{year + 1}-01-01")
               .map(lambda im: im.select("avg_rad")
                    .updateMask(im.select("cf_cvg").gte(NTL_MIN_CF_CVG))))
    med = monthly.median()
    return med.where(med.lt(NTL_NOISE_FLOOR), 0).rename(f"ntl_{year}")


NTL_YEARS = list(range(START_YEAR, END_YEAR + 1))
ntl_img = ee.Image.cat([ntl_year(y) for y in NTL_YEARS]).unmask(0)

# sum = radiance summed over the village (area-weighted, "sum of lights");
# mean = average radiance per pixel. Output columns: ntl_<year>_sum, ntl_<year>_mean
ntl_reducer = ee.Reducer.sum().combine(ee.Reducer.mean(), sharedInputs=True)
NTL_BANDS = [f"ntl_{y}_{s}" for y in NTL_YEARS for s in ("sum", "mean")]

STAT_COLS = ["uid"] + LULC_BANDS + NTL_BANDS


# ----------------------------------------------------------------------------
# Local village polygons
# ----------------------------------------------------------------------------
def load_villages():
    """Read village polygons (uid + geometry only), repair invalid shapes and round
    coordinates. Sorted by uid (state_district_subdistrict_village) so that each
    batch covers a compact area."""
    gdf = pyogrio.read_dataframe(VILLAGES_FILE, columns=["uid"])
    invalid = ~gdf.is_valid
    gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)
    gdf["geometry"] = gdf.geometry.set_precision(COORD_PRECISION)
    empty = gdf.geometry.is_empty
    if empty.any():
        print(f"skipping {empty.sum()} villages with empty geometry: "
              f"{gdf.loc[empty, 'uid'].head(10).tolist()}")
    print(f"repaired {invalid.sum()} invalid geometries")
    return gdf[~empty].sort_values("uid").reset_index(drop=True)


# ----------------------------------------------------------------------------
# One GEE request per batch
# ----------------------------------------------------------------------------
def fetch_stats(batch):
    """Send one batch of polygons to GEE and return its statistics as a DataFrame."""
    fc = ee.FeatureCollection(json.loads(batch.to_json(drop_id=True)))
    stats = lulc_img.reduceRegions(
        collection=fc, reducer=ee.Reducer.sum(),
        scale=LULC_SCALE, tileScale=TILE_SCALE)
    stats = ntl_img.reduceRegions(
        collection=stats, reducer=ntl_reducer,
        scale=NTL_SCALE, tileScale=TILE_SCALE)
    # keep properties only; returning geometry would waste bandwidth
    result = stats.select(STAT_COLS, None, False).getInfo()
    return pd.DataFrame([f["properties"] for f in result["features"]], columns=STAT_COLS)


def run_batch(batch):
    """fetch_stats with retries. Batches that are too heavy for one request
    (timeout / memory / payload) are split in half and retried."""
    for attempt in range(MAX_RETRIES):
        try:
            return fetch_stats(batch)
        except ee.EEException as e:
            msg = str(e).lower()
            too_big = any(k in msg for k in
                          ("timed out", "memory", "payload", "too large", "too many vertices"))
            if too_big and len(batch) > 1:
                half = len(batch) // 2
                return pd.concat([run_batch(batch.iloc[:half]), run_batch(batch.iloc[half:])])
            if attempt == MAX_RETRIES - 1:
                raise
        except Exception:  # network hiccups, rate limiting (HTTP 429), etc.
            if attempt == MAX_RETRIES - 1:
                raise
        time.sleep(5 * 2 ** attempt)


def process(batch_id, batch):
    out = BATCH_DIR / f"batch_{batch_id:05d}.csv"
    df = run_batch(batch)
    tmp = out.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(out)  # write-then-rename so a crash never leaves a half-written batch
    return batch_id


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    if ARGS.test:
        shutil.rmtree(BATCH_DIR, ignore_errors=True)  # test runs always start fresh
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    villages = load_villages()
    if ARGS.test:
        villages = villages.sample(ARGS.test, random_state=42).sort_values("uid")
        print(f"TEST MODE: {len(villages)} random villages -> {OUT_FILE.name}")

    batches = {i: villages.iloc[s:s + BATCH_SIZE]
               for i, s in enumerate(range(0, len(villages), BATCH_SIZE))}
    todo = {i: b for i, b in batches.items()
            if not (BATCH_DIR / f"batch_{i:05d}.csv").exists()}
    print(f"{len(villages):,} villages, {len(batches)} batches, {len(todo)} to run")

    failed, done, t0 = [], 0, time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(process, i, b): i for i, b in todo.items()}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                fut.result()
                done += 1
            except Exception as e:
                failed.append(i)
                print(f"batch {i} failed: {str(e)[:200]}")
            if done % 50 == 0 or done == len(todo):
                rate = done / max(time.time() - t0, 1)
                eta_min = (len(todo) - done - len(failed)) / max(rate, 1e-9) / 60
                print(f"{done}/{len(todo)} batches done, ~{eta_min:.0f} min left")

    if failed:
        print(f"{len(failed)} batches failed: {sorted(failed)[:20]} ... re-run the script to retry them.")
        return

    # All batches present: merge them and attach the village attributes
    stats = pd.concat([pd.read_csv(BATCH_DIR / f"batch_{i:05d}.csv") for i in batches],
                      ignore_index=True)
    attrs = pyogrio.read_dataframe(VILLAGES_FILE, read_geometry=False)[ID_COLS]
    merged = attrs.merge(stats, on="uid", how="inner")
    assert merged["uid"].is_unique, "duplicate uid in merged output"
    merged.to_csv(OUT_FILE, index=False)
    print(f"written: {OUT_FILE} ({len(merged):,} villages)")


if __name__ == "__main__":
    main()
