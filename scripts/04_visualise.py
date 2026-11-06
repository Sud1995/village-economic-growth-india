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
        data/output/top100_map.html   interactive map with a pop-up per village

Run from the project root:
  python scripts/04_visualise.py
"""

from pathlib import Path

import folium
import matplotlib.pyplot as plt
import pandas as pd
import pyogrio
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
TOP_FILE = ROOT / "data" / "output" / "top100_villages.csv"
STATE_FILE = ROOT / "data" / "raw" / "shrug_pc11_state" / "state.shp"
OUT_PNG = ROOT / "data" / "output" / "top100_map.png"
OUT_HTML = ROOT / "data" / "output" / "top100_map.html"

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

# ----------------------------------------------------------------------------
# Static map
# ----------------------------------------------------------------------------
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

# ----------------------------------------------------------------------------
# Interactive map
# ----------------------------------------------------------------------------
m = folium.Map(location=[22.5, 80], zoom_start=5, tiles="CartoDB positron")
for _, r in top.iterrows():
    color = GROWTH_TYPES[r["growth_type"]]["color"]
    popup = (f"<b>#{r['rank']} {r['tv_name']}</b><br>{r['dist_name']}, {r['state_name']}<br>"
             f"Score {r['score']:.1f} &middot; stability {r['rank_stability']:.0f}%<br>"
             f"New built-up {r['new_built_ha']:.1f} ha<br>"
             f"Total light {r['ntl_base']:.1f} &rarr; {r['ntl_end']:.1f}<br>"
             f"Type: {r['growth_type']}")
    folium.CircleMarker([r["lat"], r["lon"]], radius=6, color="white", weight=1,
                        fill=True, fill_color=color, fill_opacity=0.95,
                        tooltip=f"#{r['rank']} {r['tv_name']}",
                        popup=folium.Popup(popup, max_width=260)).add_to(m)

legend_rows = "".join(
    f"<div><span style='display:inline-block;width:10px;height:10px;border-radius:50%;"
    f"background:{s['color']};margin-right:6px'></span>{name} ({counts.get(name, 0)})</div>"
    for name, s in GROWTH_TYPES.items())
legend = (f"<div style='position:fixed;bottom:24px;left:24px;z-index:9999;background:white;"
          f"padding:10px 12px;border-radius:6px;font:13px Arial;color:{INK};"
          f"box-shadow:0 1px 4px rgba(0,0,0,.2)'><b>Top 100 villages by growth type</b>"
          f"{legend_rows}</div>")
m.get_root().html.add_child(folium.Element(legend))
m.save(OUT_HTML)
print(f"written: {OUT_HTML}")
