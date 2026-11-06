"""
00_add_admin_names.py

Adds state and district names to the SHRUG PC11 village polygons.

Inputs (SHRUG 2.2 "Pakora", Development Data Lab, CC BY-NC-SA 4.0,
https://www.devdatalab.org/shrug_download/):
  data/raw/shrug_pc11_village/village_modified.shp   - village/town polygons
  data/raw/shrug_pc11_district/district.shp          - district names (d_name)
  data/raw/shrug_pc11_state/state.shp                - state names (s_name)

Output:
  data/interim/villages_pc11_named.shp  - village polygons + state_name, dist_name

The join is an attribute join on Census 2011 codes (not a spatial join):
  district key = pc11_s_id + pc11_d_id
  state key    = pc11_s_id

Run from the project root:
  python scripts/00_add_admin_names.py
"""

from pathlib import Path

import pyogrio

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "interim"
OUT_FILE = OUT_DIR / "villages_pc11_named.shp"

# Read village polygons (with geometry) and the two name tables (attributes only)
villages = pyogrio.read_dataframe(RAW / "shrug_pc11_village" / "village_modified.shp")
districts = pyogrio.read_dataframe(
    RAW / "shrug_pc11_district" / "district.shp", read_geometry=False
)
states = pyogrio.read_dataframe(
    RAW / "shrug_pc11_state" / "state.shp", read_geometry=False
)
print(f"villages: {len(villages):,}  districts: {len(districts)}  states: {len(states)}")

# Lookup tables must be unique on their keys, otherwise the merge would duplicate villages
assert not districts.duplicated(["pc11_s_id", "pc11_d_id"]).any(), "duplicate district keys"
assert not states.duplicated(["pc11_s_id"]).any(), "duplicate state keys"

districts = districts.rename(columns={"d_name": "dist_name"})
states = states.rename(columns={"s_name": "state_name"})

n_before = len(villages)
villages = villages.merge(districts, on=["pc11_s_id", "pc11_d_id"], how="left")
villages = villages.merge(states, on="pc11_s_id", how="left")
assert len(villages) == n_before, "merge changed the number of villages"

# Report villages that did not get a name (e.g. the all-zero placeholder record)
missing = villages[villages["state_name"].isna() | villages["dist_name"].isna()]
print(f"rows missing state or district name: {len(missing):,}")
if len(missing):
    print(missing[["pc11_s_id", "pc11_d_id", "pc11_tv_id", "tv_name"]].head(20).to_string())

# Column order: ids, names, then the rest; shapefile field names must be <= 10 chars
cols = ["pc11_s_id", "state_name", "pc11_d_id", "dist_name",
        "pc11_sd_id", "pc11_tv_id", "tv_name", "mdds_og", "geometry"]
villages = villages[cols]

OUT_DIR.mkdir(parents=True, exist_ok=True)
pyogrio.write_dataframe(villages, OUT_FILE, encoding="UTF-8")
print(f"written: {OUT_FILE}")
