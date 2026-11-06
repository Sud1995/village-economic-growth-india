"""
04_visualise.py

Maps the final top 100 villages.

Each village is placed in one growth type, in this order:
  Large project      flag_large_project = 1 (airport, refinery, plant, highway ...)
  Near a city        peri_urban = 1 (within 10 km of a major town)
  Broad local growth neither of the above

Input:  data/output/top100_villages.csv          (03_score_villages.py)
        data/raw/shrug_pc11_state/state.shp       (SHRUG 2.2 state polygons)
Output: data/output/top100_map.png    static map (presentation, README)

Run from the project root:
  python scripts/04_visualise.py
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import pyogrio
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
TOP_FILE = ROOT / "data" / "output" / "top100_villages.csv"
STATE_FILE = ROOT / "data" / "raw" / "shrug_pc11_state" / "state.shp"
OUT_PNG = ROOT / "data" / "output" / "top100_map.png"

# Colour-blind-safe categorical colours; marker shape is a second cue
GROWTH_TYPES = {
    "Broad local growth": {"color": "#1baf7a", "marker": "o"},
    "Near a city": {"color": "#2a78d6", "marker": "s"},
    "Large project": {"color": "#eb6834", "marker": "^"},
}
INK, MUTED, LAND, BORDER = "#0b0b0b", "#52514e", "#f0efec", "#c3c2b7"

top = pd.read_csv(TOP_FILE)
top["growth_type"] = "Broad local growth"
top.loc[top["peri_urban"] == 1, "growth_type"] = "Near a city"
top.loc[top["flag_large_project"] == 1, "growth_type"] = "Large project"
counts = top["growth_type"].value_counts()
print(counts.to_dict())

states = pyogrio.read_dataframe(STATE_FILE)
states["geometry"] = states.geometry.simplify(0.02, preserve_topology=True)

fig, ax = plt.subplots(figsize=(6.4, 7.0), dpi=200)
states.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.5)
for name, style in GROWTH_TYPES.items():
    pts = top[top["growth_type"] == name]
    ax.scatter(pts["lon"], pts["lat"], s=34, c=style["color"], marker=style["marker"],
               edgecolors="white", linewidths=0.8, zorder=3)

handles = [Line2D([], [], linestyle="", marker=s["marker"], markersize=8,
                  markerfacecolor=s["color"], markeredgecolor="white",
                  label=f"{name} ({counts.get(name, 0)})")
           for name, s in GROWTH_TYPES.items()]
ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9,
          labelcolor=INK, handletextpad=0.4, borderaxespad=0.2)
ax.set_axis_off()
ax.set_aspect("equal")
ax.text(0.0, 0.0, "Boundaries: SHRUG 2.2 (Census 2011 states)", fontsize=7, color=MUTED,
        transform=ax.transAxes)
fig.savefig(OUT_PNG, bbox_inches="tight", facecolor="white")
print(f"written: {OUT_PNG}")
