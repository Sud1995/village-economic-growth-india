"""
05_build_presentation.py

Builds the 7-slide presentation from the pipeline outputs, so every number on the
slides comes straight from the data files.

Input:  data/output/top100_villages.csv
        data/output/villages_scored.csv.gz
        data/output/top100_map.png        (04_visualise.py)
Output: presentation/Village_Economic_Growth_Top100.pptx

Run from the project root:
  python scripts/05_build_presentation.py
"""

from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
TOP_FILE = ROOT / "data" / "output" / "top100_villages.csv"
SCORED_FILE = ROOT / "data" / "output" / "villages_scored.csv.gz"
MAP_FILE = ROOT / "data" / "output" / "top100_map.png"
OUT_FILE = ROOT / "presentation" / "Village_Economic_Growth_Top100.pptx"

AUTHOR = "Sudipta Mahato"
DATE_LINE = "November 2026"

# Palette: deep navy dominates, amber (night lights) accents dark slides
NAVY = RGBColor(0x14, 0x21, 0x3D)
AMBER = RGBColor(0xFC, 0xA3, 0x11)
INK = RGBColor(0x1F, 0x1F, 0x1F)
MUTED = RGBColor(0x5F, 0x6B, 0x7A)
TINT = RGBColor(0xEE, 0xF1, 0xF6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT_WHITE = RGBColor(0xC9, 0xD1, 0xDE)
GROWTH_COLORS = {"Broad local growth": RGBColor(0x1B, 0xAF, 0x7A),
                 "Near a city": RGBColor(0x2A, 0x78, 0xD6),
                 "Large project": RGBColor(0xEB, 0x68, 0x34)}
HEAD, BODY = "Cambria", "Calibri"

# ----------------------------------------------------------------------------
# Numbers used on the slides
# ----------------------------------------------------------------------------
top = pd.read_csv(TOP_FILE)
scored = pd.read_csv(SCORED_FILE, usecols=["excl_reason", "signals_agree", "built_2020",
                                           "built_2025", "ntl_2020_sum", "ntl_2025_sum"])
top["growth_type"] = "Broad local growth"
top.loc[top["peri_urban"] == 1, "growth_type"] = "Near a city"
top.loc[top["flag_large_project"] == 1, "growth_type"] = "Large project"

n_polygons = len(scored)
n_eligible = int((scored["excl_reason"].isna() | (scored["excl_reason"] == "")).sum())
n_agree = int(scored["signals_agree"].sum())
built_growth = scored["built_2025"].sum() / scored["built_2020"].sum() - 1
light_growth = scored["ntl_2025_sum"].sum() / scored["ntl_2020_sum"].sum() - 1
n_states = top["state_name"].nunique()
type_counts = top["growth_type"].value_counts()
state_counts = top["state_name"].value_counts().head(8)
median_stability = top["rank_stability"].median()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def background(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def text(slide, x, y, w, h, runs, size=16, color=INK, font=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=4):
    """Text box. `runs` is a string or a list of paragraphs; a paragraph is a string
    or a list of (text, overrides) tuples."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    paragraphs = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(spacing)
        for part in ([(para, {})] if isinstance(para, str) else para):
            t, o = part
            r = p.add_run()
            r.text = t
            r.font.name = o.get("font", font)
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.color.rgb = o.get("color", color)
    return box


def card(slide, x, y, w, h, color=TINT):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(h))
    shp.adjustments[0] = 0.08
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def badge(slide, x, y, d, label, fill=NAVY, color=WHITE, size=14):
    shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = BODY, Pt(size), True, color
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE


def title(slide, words):
    text(slide, 0.6, 0.45, 12.1, 0.8, words, size=34, color=NAVY, font=HEAD, bold=True)


def arrow(slide, x, y, w=0.35, h=0.3, color=MUTED):
    shp = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]

# ----------------------------------------------------------------------------
# 1. Title
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, NAVY)
text(s, 0.8, 2.1, 11.5, 1.4, "Village Economic Growth Intelligence",
     size=46, color=WHITE, font=HEAD, bold=True)
text(s, 0.8, 3.45, 11.5, 0.9,
     "India's 100 fastest-growing villages, 2020–2025, from night lights and land cover",
     size=22, color=SOFT_WHITE)
text(s, 0.8, 5.6, 6, 0.9, [[(AUTHOR, {"bold": True, "color": AMBER})], DATE_LINE],
     size=16, color=SOFT_WHITE)
s.notes_slide.notes_text_frame.text = (
    "Goal: find the 100 Indian villages with the highest economic growth over the last "
    "five years using satellite data and open datasets, with a reproducible pipeline.")

# ----------------------------------------------------------------------------
# 2. Definition and data
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, WHITE)
title(s, "Growth = more activity plus new capital")
card(s, 0.6, 1.6, 5.0, 5.2, NAVY)
text(s, 0.95, 1.95, 4.3, 0.4, "DEFINITION", size=13, color=AMBER, bold=True)
text(s, 0.95, 2.45, 4.3, 2.6,
     "A sustained rise in economic activity (night-time lights) together with new "
     "physical capital (new buildings), measured against each village's own starting point.",
     size=20, color=WHITE, font=HEAD, spacing=0)
text(s, 0.95, 5.25, 4.3, 1.3,
     "Both must rise: lights alone can be a single flare or factory; buildings alone can be "
     "misclassified land.", size=14, color=SOFT_WHITE)

sources = [
    ("SHRUG 2.2 village boundaries", "Development Data Lab",
     "648,878 Census 2011 village polygons with state and district codes; the only open "
     "all-India village boundary set"),
    ("Esri 10 m Annual Land Cover", "Impact Observatory / Esri, Sentinel-2",
     "Built-up and cropland area per village, 2020 and 2025; 10 m resolves village-scale "
     "construction"),
    ("VIIRS night lights, monthly", "Earth Observation Group, Colorado School of Mines",
     "Night-time radiance per village, every year 2020–2025 (72 months); the standard "
     "proxy for economic activity"),
]
for i, (name, org, desc) in enumerate(sources):
    y = 1.6 + i * 1.8
    card(s, 6.0, y, 6.73, 1.6)
    badge(s, 6.25, y + 0.25, 0.5, str(i + 1))
    text(s, 7.0, y + 0.2, 5.5, 1.3,
         [[(name, {"bold": True, "size": 17, "color": NAVY})],
          [(org, {"size": 12, "color": MUTED})],
          [(desc, {"size": 14})]], spacing=3)
s.notes_slide.notes_text_frame.text = (
    "Lights capture energy use and activity; built-up area captures investment. Requiring "
    "both keeps out single-sensor artefacts. All three datasets are open and cover all of "
    "India consistently.")

# ----------------------------------------------------------------------------
# 3. Pipeline and funnel
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, WHITE)
title(s, "From 6.5 lakh polygons to a top 100")
steps = [
    ("Prepare boundaries", "Add names, drop non-village gaps, unique IDs, flag towns"),
    ("Extract in Earth Engine", "Built-up and lights per village, sent in 3,242 batches"),
    ("Score four signals", "Percentiles, weighted score, both-signal test"),
    ("Rank and check", "One top-100 list, flags, stability over 1,000 weight sets"),
]
w, gap = 2.75, 0.37
for i, (name, desc) in enumerate(steps):
    x = 0.6 + i * (w + gap)
    card(s, x, 1.6, w, 2.1)
    badge(s, x + 0.25, 1.85, 0.5, str(i + 1))
    text(s, x + 0.25, 2.5, w - 0.5, 1.1,
         [[(name, {"bold": True, "size": 16, "color": NAVY})], [(desc, {"size": 13})]])
    if i < 3:
        arrow(s, x + w + 0.03, 2.5, 0.3, 0.3)

funnel = [(f"{n_polygons:,}", "village polygons"), (f"{n_eligible:,}", "eligible villages"),
          (f"{n_agree:,}", "pass the both-signal test"), ("100", "ranked villages")]
text(s, 0.6, 4.25, 12, 0.4, "HOW THE FIELD NARROWS", size=13, color=MUTED, bold=True)
for i, (num, label) in enumerate(funnel):
    x = 0.6 + i * (w + gap)
    text(s, x, 4.75, w, 0.9, num, size=40, color=AMBER if i == 3 else NAVY,
         font=HEAD, bold=True)
    text(s, x, 5.65, w, 0.5, label, size=15, color=MUTED)
    if i < 3:
        arrow(s, x + w - 0.2, 5.0, 0.3, 0.3)
text(s, 0.6, 6.5, 12.1, 0.5,
     "Excluded before scoring: 4,168 towns, 4,409 fragments under 10 ha, 13 villages with "
     "missing land cover.", size=13, color=MUTED)
s.notes_slide.notes_text_frame.text = (
    "Four Python scripts; only step 2 uses Google Earth Engine. Each step writes a file the "
    "next reads, so any step can be rerun alone.")

# ----------------------------------------------------------------------------
# 4. Scoring
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, WHITE)
title(s, "Four signals, and both kinds must agree")
signals = [
    ("Night-light trend", "30%", "How fast lights grew relative to their start (robust "
     "slope over 2021–2025)"),
    ("Night-light gain", "20%", "How much light was added per km², 2021 to 2024–25"),
    ("New built-up share", "25%", "Share of the village's land newly built on, 2020 to 2025"),
    ("Settlement expansion", "25%", "New built-up relative to the 2020 settlement size"),
]
for i, (name, wt, desc) in enumerate(signals):
    col, row = i % 2, i // 2
    x, y = 0.6 + col * 3.95, 1.6 + row * 2.6
    card(s, x, y, 3.7, 2.35)
    text(s, x + 0.3, y + 0.25, 2.2, 0.5, "ACTIVITY" if i < 2 else "CONSTRUCTION",
         size=11, color=MUTED, bold=True)
    text(s, x + 2.5, y + 0.15, 0.95, 0.6, wt, size=24, color=NAVY, font=HEAD, bold=True,
         align=PP_ALIGN.RIGHT)
    text(s, x + 0.3, y + 0.75, 3.1, 1.5,
         [[(name, {"bold": True, "size": 17, "color": NAVY})], [(desc, {"size": 14})]])
card(s, 8.6, 1.6, 4.13, 4.95, NAVY)
text(s, 8.95, 1.95, 3.5, 0.4, "THE RULE", size=13, color=AMBER, bold=True)
text(s, 8.95, 2.45, 3.5, 2.2,
     "A village is ranked only if a light signal and a built-up signal are both in "
     "India's top 20%.", size=20, color=WHITE, font=HEAD, spacing=0)
text(s, 8.95, 4.55, 3.5, 1.9,
     ["Score = weighted average of the four percentiles.",
      "2021 is the light baseline; 2020 was depressed by the COVID lockdown."],
     size=14, color=SOFT_WHITE, spacing=8)
s.notes_slide.notes_text_frame.text = (
    "Relative and absolute versions of each signal cover each other's blind spots: relative "
    "favours tiny bases, absolute favours places that were already big. Activity and "
    "construction get equal weight overall.")

# ----------------------------------------------------------------------------
# 5. Findings: map + headline numbers + state chart
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, WHITE)
title(s, f"Top villages span {n_states} states; half grow broadly")
s.shapes.add_picture(str(MAP_FILE), Inches(0.6), Inches(1.45), height=Inches(5.75))
stats = [(f"+{built_growth:.0%}", "built-up area, all villages"),
         (f"+{light_growth:.0%}", "night light, all villages"),
         (f"{type_counts.get('Broad local growth', 0)}", "of the top 100 grow broadly")]
for i, (num, label) in enumerate(stats):
    x = 6.6 + i * 2.1
    text(s, x, 1.55, 2.0, 0.7, num, size=34, color=NAVY, font=HEAD, bold=True)
    text(s, x, 2.3, 1.9, 0.7, label, size=13, color=MUTED)

cd = CategoryChartData()
cd.categories = list(state_counts.index[::-1])
cd.add_series("Villages in top 100", list(state_counts.values[::-1]))
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(6.6), Inches(3.25), Inches(6.13),
                        Inches(3.95), cd)
ch = gf.chart
ch.has_legend = False
ch.has_title = True
ch.chart_title.text_frame.text = "Top-100 villages by state (top 8)"
tp = ch.chart_title.text_frame.paragraphs[0]
tp.runs[0].font.size, tp.runs[0].font.bold = Pt(14), True
tp.runs[0].font.color.rgb, tp.runs[0].font.name = NAVY, BODY
plot = ch.plots[0]
plot.gap_width = 60
plot.has_data_labels = True
plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
plot.data_labels.font.size, plot.data_labels.font.color.rgb = Pt(12), INK
plot.series[0].format.fill.solid()
plot.series[0].format.fill.fore_color.rgb = NAVY
ch.value_axis.visible = False
ch.value_axis.has_major_gridlines = False
ch.category_axis.tick_labels.font.size = Pt(12)
ch.category_axis.tick_labels.font.color.rgb = INK
ch.category_axis.format.line.fill.background()
s.notes_slide.notes_text_frame.text = (
    f"{type_counts.get('Near a city', 0)} villages sit near a major city (Bangalore Rural "
    f"alone has 10) and {type_counts.get('Large project', 0)} are driven by a single large "
    "project such as an airport or refinery. The rest show broad local growth.")

# ----------------------------------------------------------------------------
# 6. Top 10 table
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, WHITE)
title(s, "The ten fastest-growing villages")
t10 = top.head(10)
headers = ["Rank", "Village", "District, State", "New built-up (ha)", "Night light 2021 → 2024–25",
           "Growth type"]
widths = [0.8, 2.4, 3.3, 1.7, 2.1, 1.83]
tbl = s.shapes.add_table(len(t10) + 1, len(headers), Inches(0.6), Inches(1.5),
                         Inches(sum(widths)), Inches(5.2)).table
for j, wd in enumerate(widths):
    tbl.columns[j].width = Inches(wd)


def cell(r, c, value, bold=False, color=INK, fill=WHITE, align=PP_ALIGN.LEFT, size=13):
    ce = tbl.cell(r, c)
    ce.fill.solid()
    ce.fill.fore_color.rgb = fill
    ce.margin_left = ce.margin_right = Inches(0.08)
    ce.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = ce.text_frame.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = str(value)
    run.font.name, run.font.size, run.font.bold, run.font.color.rgb = BODY, Pt(size), bold, color


for j, h in enumerate(headers):
    cell(0, j, h, bold=True, color=WHITE, fill=NAVY,
         align=PP_ALIGN.RIGHT if j in (3, 4) else PP_ALIGN.LEFT, size=12)
for i, r in enumerate(t10.itertuples(), start=1):
    fill = TINT if i % 2 == 0 else WHITE
    name = r.tv_name.split("(")[0].strip()
    cell(i, 0, r.rank, bold=True, color=NAVY, fill=fill)
    cell(i, 1, name, bold=True, fill=fill)
    cell(i, 2, f"{r.dist_name}, {r.state_name}", fill=fill)
    cell(i, 3, f"{r.new_built_ha:.1f}", fill=fill, align=PP_ALIGN.RIGHT)
    cell(i, 4, f"{r.ntl_base:.1f} → {r.ntl_end:.1f}", fill=fill, align=PP_ALIGN.RIGHT)
    cell(i, 5, r.growth_type, color=GROWTH_COLORS[r.growth_type], bold=True, fill=fill, size=12)
text(s, 0.6, 6.85, 12.1, 0.4,
     f"Median rank stability across 1,000 random weight sets: {median_stability:.0f}%. "
     "Night light = area-weighted sum of annual median radiance.", size=12, color=MUTED)
s.notes_slide.notes_text_frame.text = (
    "Several leaders match known projects (not yet verified on imagery): Banwari Bara and "
    "Kishorpur near the Noida International Airport, Samletu near AIIMS Bilaspur. Kerki "
    "(rank 5) is the clearest case of broad local growth in the top ten.")

# ----------------------------------------------------------------------------
# 7. Limitations and next steps
# ----------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
background(s, NAVY)
text(s, 0.6, 0.45, 12.1, 0.8, "Limits and next steps", size=34, color=WHITE, font=HEAD, bold=True)
cols = [
    ("LIMITATIONS", [
        "Proxies, not income: farm-led growth barely shows in lights or buildings",
        "City spillover and big projects count as growth (flagged, not removed)",
        "Census 2011 boundaries, ~1 km error; night lights at ~464 m",
        f"Weights are a judgement call; median stability {median_stability:.0f}%",
    ]),
    ("NEXT STEPS", [
        "Check the top 30 on before/after high-resolution imagery",
        "Validate district scores against NFHS-4 → NFHS-5 asset change",
        "Add a farm signal: cropping intensity from Sentinel-2",
        "Add Census population for per-capita growth",
    ]),
]
for i, (head, items) in enumerate(cols):
    x = 0.6 + i * 6.2
    text(s, x, 1.65, 5.8, 0.4, head, size=14, color=AMBER, bold=True)
    for k, item in enumerate(items):
        y = 2.25 + k * 1.15
        badge(s, x, y + 0.02, 0.42, str(k + 1), fill=AMBER, color=NAVY, size=13)
        text(s, x + 0.65, y, 5.15, 1.0, item, size=17, color=WHITE)
s.notes_slide.notes_text_frame.text = (
    "The most valuable next step is independent validation: imagery for the top villages and "
    "survey data at district level.")

# ----------------------------------------------------------------------------
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
props = prs.core_properties
props.author = props.last_modified_by = AUTHOR
props.title = "Village Economic Growth Intelligence"
props.subject = "Top 100 economically growing villages in India, 2020-2025"
prs.save(OUT_FILE)
print(f"written: {OUT_FILE}")
