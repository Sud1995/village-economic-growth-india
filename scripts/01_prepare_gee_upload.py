"""
01_prepare_gee_upload.py

Prepares the named village polygons for upload to Google Earth Engine (GEE).

Steps:
  1. Drop the placeholder record (pc11_tv_id == "000000", no village).
  2. Build a unique polygon id `uid` = state_district_subdistrict_townvillage
     codes, and flag towns (`is_town`, PC11 codes 8xxxxx).
  3. Assign each village to a processing `chunk` of whole districts
     (~CHUNK_SIZE villages each) so GEE exports stay within memory/time limits.
  4. Lightly simplify geometries (SHRUG boundaries already carry ~0-1 km error,
     so ~11 m simplification loses nothing and makes the upload much smaller).
  5. Write the shapefile read by 02_extract_gee.py (plus a zip, only needed if
     you prefer to upload it as a GEE table asset instead).

Input:  data/interim/villages_pc11_named.shp   (from 00_add_admin_names.py)
Output: data/interim/gee_upload/villages_gee.shp  and  villages_gee.zip

Run from the project root:
  python scripts/01_prepare_gee_upload.py
"""

import zipfile
from pathlib import Path

import pyogrio

ROOT = Path(__file__).resolve().parents[1]
IN_FILE = ROOT / "data" / "interim" / "villages_pc11_named.shp"
OUT_DIR = ROOT / "data" / "interim" / "gee_upload"
OUT_FILE = OUT_DIR / "villages_gee.shp"

CHUNK_SIZE = 20_000          # target villages per GEE export task
SIMPLIFY_TOL_DEG = 0.0001    # ~11 m at the equator

villages = pyogrio.read_dataframe(IN_FILE)
print(f"input villages: {len(villages):,}")

# 1. Drop the all-zero placeholder record
villages = villages[villages["pc11_tv_id"] != "000000"].copy()

# 2. Unique id. state + town/village code alone is NOT unique: a few towns (and
#    some villages) are split across subdistricts/districts into several polygons,
#    so the full code path is used.
villages["uid"] = (villages["pc11_s_id"] + "_" + villages["pc11_d_id"] + "_"
                   + villages["pc11_sd_id"] + "_" + villages["pc11_tv_id"])
assert villages["uid"].is_unique, "uid is not unique"

# PC11 statutory/census town codes are 8xxxxx; villages are below 800000
villages["is_town"] = villages["pc11_tv_id"].str.startswith("8").astype(int)
print(f"towns: {villages['is_town'].sum():,}  villages: {(1 - villages['is_town']).sum():,}")

# 3. Chunks of whole districts, in state/district order, ~CHUNK_SIZE villages each
dist_counts = (villages.groupby(["pc11_s_id", "pc11_d_id"]).size()
               .reset_index(name="n").sort_values(["pc11_s_id", "pc11_d_id"]))
chunk, running, chunk_ids = 0, 0, []
for n in dist_counts["n"]:
    if running and running + n > CHUNK_SIZE:
        chunk, running = chunk + 1, 0
    chunk_ids.append(chunk)
    running += n
dist_counts["chunk"] = chunk_ids
villages = villages.merge(dist_counts[["pc11_s_id", "pc11_d_id", "chunk"]],
                          on=["pc11_s_id", "pc11_d_id"], how="left")
print(f"chunks: {villages['chunk'].nunique()}  "
      f"(largest: {villages['chunk'].value_counts().max():,} villages)")

# 4. Simplify geometry, keeping topology so polygons stay valid
villages["geometry"] = villages.geometry.simplify(SIMPLIFY_TOL_DEG, preserve_topology=True)
n_empty = villages.geometry.is_empty.sum()
print(f"empty geometries after simplify: {n_empty}")

# 5. Write shapefile (field names <= 10 chars) and zip it for upload
cols = ["uid", "pc11_s_id", "state_name", "pc11_d_id", "dist_name",
        "pc11_sd_id", "pc11_tv_id", "tv_name", "is_town", "chunk", "geometry"]
OUT_DIR.mkdir(parents=True, exist_ok=True)
pyogrio.write_dataframe(villages[cols], OUT_FILE, encoding="UTF-8")

zip_path = OUT_DIR / "villages_gee.zip"
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        f = OUT_FILE.with_suffix(ext)
        zf.write(f, f.name)
print(f"written: {OUT_FILE}")
print(f"zip for GEE upload: {zip_path} ({zip_path.stat().st_size / 1e6:.0f} MB)")
