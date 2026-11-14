# FireLens — shared instructions for Claude Code

Changes to this file must be approved by R2.

## Directory ownership

| Path          | Contents                                   | Owner                         |
|---------------|--------------------------------------------|-------------------------------|
| `docs/`       | `decisions.md`, data contract              | R2                            |
| `gee/`        | Earth Engine scripts                       | R1                            |
| `science/`    | Notebooks, harmonization                   | R2                            |
| `data/`       | Final small CSVs only                      | R1 adds, R2 checks            |
| `app/`        | Streamlit app                              | App developer                 |
| `submission/` | Submission text, screenshots               | R4                            |


# FireLens — NASA Space Apps 2026
Harmonized burning-activity calendar for Northern India, 2016–2026,
from MODIS (Terra, Aqua) and VIIRS (Suomi-NPP) fire products via Google Earth Engine.

## Data contract (do not change without approval in docs/decisions.md)
data/district_monthly.csv columns:
state, district, sensor, year, month, fire_pixel_days, clear_pixel_days, mean_frp_mw
activity = fire_pixel_days / clear_pixel_days. Dates are IST.

## Folder ownership — only edit your own folder
gee/ = R1 · science/ + docs/ = R2 · app/ = R3 · submission/ = R4

## Rules
- Hotspots are detections, never "fires"; never sum satellites' raw counts.
- Never commit credentials or files over 20 MB.
- App: Streamlit + Plotly + folium; colour-blind-safe ramps; months with no data shown blank, not 0.
- Plan first, then code. Keep changes small.
