# 🔥 FireLens

**A harmonized burning-activity calendar for Northern India, 2016–2026**

Built for the NASA Space Apps Challenge 2026, challenge: *Harmonization of MODIS and VIIRS Hot Spots*.

FireLens turns satellite fire detections from NASA's MODIS and VIIRS sensors into one consistent month-by-year calendar for any district in Northern India. Users can see when burning peaks, compare the current month with its historical median, and download the data.

**Live app:** add Streamlit link here · **Demo:** add video/slides link here

## The problem

Satellites have recorded active-fire "hotspots" for more than two decades, but the record is split across sensors that see differently:

- **MODIS** (Terra and Aqua satellites): about 1 km pixels; the long historical record
- **VIIRS** (Suomi-NPP, NOAA-20, NOAA-21): 375–750 m pixels; more sensitive, and the sensor that continues the record

If the raw counts are combined, burning appears to change whenever a satellite is added or replaced. These jumps are sensor artefacts, not real changes. FireLens corrects for the sensor differences, so the calendar reflects changes in burning rather than changes in satellites.

## What FireLens does

- **Harmonized series:** one MODIS + VIIRS record per district, on the VIIRS scale; each sensor is also available on its own
- **Burning calendar:** a month × year heatmap per district (2016–2026), with a colour-blind-safe colour scale, coloured by activity or by hotspot count
- **Date range:** limit every view, metric and download to any span of months
- **This month vs history:** the latest month with at least half its daily images, compared with the median of the same month across the selected years, plus its percentile rank (a month still in progress is named, and shown in the calendar)
- **Peak season:** the months with the highest typical activity
- **Yearly view:** mean monthly activity per year, to compare years
- **Anomaly view:** each month's difference from the median of the same calendar month
- **Trend:** per season (Oct–Nov, Apr–May or the whole year), a Mann-Kendall test and Sen's slope for the district, a trend map of all 49 districts, and a caution where a trend crosses the 2022–23 detection shift
- **Uncertainty:** every harmonized value carries the range of the three sensors, how many sensors it rests on and how much of the district was clearly seen; shown as a band, error bars and in the hover text
- **Fire type:** hotspots split by land cover (cropland, forest, woodland and grass) and static heat sources such as flares and furnaces flagged, for the 19 districts the land-cover export covers so far
- **Sensor comparison:** monthly activity from each satellite, as recorded and after harmonization
- **Location search:** jump to a district by latitude and longitude
- **District map:** all 49 districts coloured by the latest month against each district's own median for that month; click a district to open it
- **MODIS-only check:** the calendar rebuilt from MODIS alone, overlaid on what VIIRS saw, to show the harmonization works before VIIRS existed
- **Download:** the district's harmonized and per-sensor monthly data, and the individual hotspot detections (date, location, FRP, sensor) for the selected dates, as CSV (the hotspot list needs `data/hotspots.csv.gz`, see `gee/README.md` step 8–9); the trend table for all districts; everything in one ZIP with the data dictionary; every chart as PNG
- **Citation:** a "How to cite" panel with the DOI of each NASA product, a `CITATION.cff`, and a data dictionary (`data/README.md`)

## How it works

- **Data:** daily 1 km fire products from Google Earth Engine:
  - `MODIS/061/MOD14A1` (Terra MODIS)
  - `MODIS/061/MYD14A1` (Aqua MODIS)
  - `NASA/VIIRS/002/VNP14A1` (Suomi-NPP VIIRS)
- **Filtering:** a pixel counts as fire when FireMask ≥ 8 (nominal or high confidence). It counts as clearly observed when FireMask is 5 (land, no fire) or ≥ 7 (fire). Cloud and missing data are excluded.
- **Aggregation:** for each district, month and sensor, we sum fire pixel-days and clearly observed pixel-days.
- **Metric:** activity = fire pixel-days ÷ clear pixel-days, the share of clearly observed land that was burning. Dividing by clear observations removes most of the bias from cloud cover (especially during the monsoon) and from differing overpass schedules.
- **Harmonization:** Suomi-NPP VIIRS is the anchor sensor because it covers the whole period. Terra and Aqua MODIS are scaled to it with **one ratio per state and calendar month** (VIIRS ÷ MODIS, summed over 2016–2022), because Terra's morning pass misses far more of the afternoon crop burning in Oct–Nov than in quiet months. The harmonized value blends VIIRS with each scaled MODIS sensor, weighted by how well it predicted VIIRS in years it never saw. Only months before each MODIS orbit **drifted** (Terra from Oct 2022, Aqua from Feb 2023) are used; after that, MODIS only fills months VIIRS could not see, and those are flagged. Leave-one-year-out on 2016–2022: Terra r = 0.91 and Aqua r = 0.98 against VIIRS, both within 4% of VIIRS's total burning in the peak months; the MODIS-only reconstruction reaches r = 0.97 with a 2% bias. Details in `science/validation.md`.
- **Baselines:** the median of each calendar month across the selected dates (at least 3 years), used for the anomaly and "vs median" views.

## Repository structure

```
firelens/
├── CLAUDE.md          # project rules and data contract (read by Claude Code)
├── README.md
├── app/               # Streamlit web app (R3)
│   ├── app.py
│   ├── trends.py      # Mann-Kendall test and Sen's slope
│   ├── make_mock.py   # generates mock data for development
│   └── requirements.txt
├── gee/               # Google Earth Engine export scripts (R1)
├── science/           # quality checks, harmonization, validation (R2)
├── data/              # the tables the app reads; README.md is the data dictionary
├── docs/              # decisions.md, data-contract.md
├── submission/        # project page text, storyboard, screenshots (R4)
└── tests/             # pytest: trend maths, data contract, reproducibility, app
```

`LICENSE`, `CITATION.cff` and the CI workflow (`.github/workflows/ci.yml`) are at the repository root.

## Running locally

```bash
git clone https://github.com/frbasil-1k/HARMONIZATION-space-app.git
cd HARMONIZATION-space-app/firelens
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r app/requirements.txt
streamlit run app/app.py                            # opens http://localhost:8501
```

If Windows blocks `streamlit.exe`, use `python -m streamlit run app/app.py`.

The real data is in `data/`, so the app needs no other setup. If `data/district_monthly.csv` is missing, the app falls back to mock files made by `python app/make_mock.py` and shows a "MOCK data" banner.

## Data contract

`data/district_monthly.csv`, one row per district × sensor × month:

| Column | Type | Meaning |
|---|---|---|
| `state` | text | State name |
| `district` | text | District name |
| `sensor` | text | `terra`, `aqua` or `viirs_snpp` |
| `year`, `month` | int | 2016–2026, 1–12 |
| `fire_pixel_days` | float | 1 km pixels flagged as fire, summed over the month |
| `clear_pixel_days` | float | 1 km land pixels clearly observed, summed over the month |
| `mean_frp_mw` | float | Mean fire radiative power over fire pixels (MW) |
| `n_images` | int | Daily images available that month (0 = no data) |

Changes to this format need the science lead's approval and an entry in `docs/decisions.md`. Every table and column is described in `data/README.md`.

## Tests

```bash
pip install -r app/requirements.txt -r science/requirements.txt -r tests/requirements.txt
python -m pytest tests -q        # about a minute
```

The tests check the trend maths against scipy, the data files against the contract, that `science/harmonize.py` rebuilds the committed harmonized file from the committed input, and that every district and view of the app renders. GitHub Actions runs them, with the 8 data-quality rules, on every pull request.

## Limitations

- Hotspots are satellite detections, not confirmed individual fires. One fire can produce many detections, and fires that are small, short-lived or under cloud may be missed.
- District boundaries come from FAO GAUL and are not official boundaries of India. They are used for orientation only.
- The most recent months depend on when NASA publishes the data in Google Earth Engine.
- NOAA-20 and NOAA-21 VIIRS are not yet part of the calendar. This now matters: a NASA Earthdata notice says delivery of Suomi-NPP products ends on 1 November 2026 and points users to NOAA-20 and NOAA-21, so the anchor record stops there (the file has 2 VIIRS images for November 2026). Check the current notice before quoting it.
- Fire type and static sources cover 19 of the 49 districts, because the land-cover hotspot export sampled two rectangles rather than whole states. The calendar still includes the static sources (0.09% of VIIRS detections in the burning seasons, 3.5% outside them).
- A trend is a statement about detections. Seasons from 2023 on fall in the period when burning appears to have moved later in the day, so a decline may be partly a detection effect; the app says so next to every such trend. With 49 districts tested at p < 0.05, two or three can look significant by chance.
- The sensor range is a measure of how far the satellites disagree, not a confidence interval.
- The calendar covers 2016–2026, the decade in which all three sensors overlap, not yet the early 2000s.
- Areas are the 49 districts of Punjab, Haryana and Uttarakhand; drawing a custom area is not yet supported.
- Since 2024, VIIRS records far fewer Punjab hotspots than Aqua MODIS (Nov 2025: 487 vs 4,288 pixel-days, against near-equal counts before 2023). Aqua's orbit has drifted to a later afternoon overpass (past 13:45 from Feb 2023, about 15:30 by mid-2026) while burning has also moved later in the day, so Aqua now sees fires that VIIRS's 13:30 pass misses. FireLens therefore stops blending drifted MODIS; the recent decline in the harmonized series is VIIRS's, and part of it may be a detection effect rather than less burning.
- New months arrive by re-running the Earth Engine exports; there is no automatic near-real-time refresh yet.
- VIIRS is used at 1 km (VNP14A1) so that all sensors share one grid; its 375 m detail is not used.

## Next steps

- Add NOAA-20 and NOAA-21 VIIRS, normalized for their extra overpasses, so the record continues after Suomi-NPP
- Re-run the land-cover hotspot export over the district boundaries, so fire type covers all 49 districts, then remove static sources from the calendar itself
- Extend the calendar back to 2001 (Terra) and 2003 (Aqua) using MODIS and the 2016–2026 calibration
- Use the VIIRS 375 m (VNP14IMG / FIRMS) detections for the hotspot list and counts
- Model the post-drift MODIS overpass time explicitly, so drifted MODIS can be used again
- An equal-area grid, so any drawn area can be analysed
- More context per area (protected areas, settlements, weather)

## Data sources and credits

- NASA LP DAAC: MOD14A1 and MYD14A1 v6.1 (Terra and Aqua MODIS Thermal Anomalies & Fire Daily L3 1 km); VNP14A1 (VIIRS Suomi-NPP Thermal Anomalies & Fire Daily L3 1 km)
- NASA FIRMS (Fire Information for Resource Management System)
- NASA LP DAAC: MCD12Q1 v6.1 (MODIS land cover), for the fire-type view; VIIRS Day/Night Band monthly composites (Earth Observation Group), for the static-source check
- Google Earth Engine, for data access and processing
- FAO GAUL, for administrative boundaries

DOIs and full citations are in `CITATION.cff` and in the app's "How to cite" panel.

We acknowledge the use of data from NASA's Land Processes Distributed Active Archive Center (LP DAAC) and Fire Information for Resource Management System (FIRMS), part of NASA's Earth Science Data and Information System (ESDIS).

## Licence

Code: MIT. Derived data tables: CC BY 4.0. The district boundaries stay under FAO's GAUL 2015 data licence (non-commercial) and are not relicensed. See `LICENSE` at the repository root.
