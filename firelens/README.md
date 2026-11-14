🔥 FireLens

A harmonized burning-activity calendar for Northern India, 2016–2026

Built for the NASA Space Apps Challenge 2026, challenge: Harmonization of MODIS and VIIRS Hot Spots.

FireLens turns satellite fire detections from NASA's MODIS and VIIRS sensors into one consistent month-by-year calendar for any district in Northern India. Users can see when burning peaks, compare the current month with its historical median, and download the data.

Live app: add Streamlit link here · Demo: add video/slides link here

The problem

Satellites have recorded active-fire "hotspots" for more than two decades, but the record is split across sensors that see differently:

MODIS (Terra and Aqua satellites): about 1 km pixels; the long historical record
VIIRS (Suomi-NPP, NOAA-20, NOAA-21): 375–750 m pixels; more sensitive, and the sensor that continues the record

If the raw counts are combined, burning appears to change whenever a satellite is added or replaced. These jumps are sensor artefacts, not real changes. FireLens corrects for the sensor differences, so the calendar reflects changes in burning rather than changes in satellites.

What FireLens does
Burning calendar: a month × year heatmap per district (2016–2026), with a colour-blind-safe colour scale
This month vs history: the latest month compared with the median of the same month across all years, plus its percentile rank
Peak season: the months with the highest typical activity
Sensor comparison: monthly activity from each satellite, side by side
Anomaly view: each month's difference from its long-term median
Location search: jump to a district by latitude and longitude
Download: the district's monthly data as CSV


How it works

Data: daily 1 km fire products from Google Earth Engine:
MODIS/061/MOD14A1 (Terra MODIS)
MODIS/061/MYD14A1 (Aqua MODIS)
NASA/VIIRS/002/VNP14A1 (Suomi-NPP VIIRS)
Filtering: a pixel counts as fire when FireMask ≥ 8 (nominal or high confidence). It counts as clearly observed when FireMask is 5 (land, no fire) or ≥ 7 (fire). Cloud and missing data are excluded.
Aggregation: for each district, month and sensor, we sum fire pixel-days and clearly observed pixel-days.
Metric: activity = fire pixel-days ÷ clear pixel-days, the share of clearly observed land that was burning. Dividing by clear observations removes most of the bias from cloud cover (especially during the monsoon) and from differing overpass schedules.
Harmonization: Suomi-NPP VIIRS is the anchor sensor because it covers the whole period. MODIS is calibrated against it using the months both sensors observed. (In progress — see science/.)
Baselines: the median and spread of each calendar month across 2016–2025, used for the anomaly and "vs median" views.




Repository structure

firelens/
├── CLAUDE.md          # project rules and data contract (read by Claude Code)
├── README.md
├── requirements.txt
├── app/               # Streamlit web app (R3)
│   ├── app.py
│   └── make_mock.py   # generates mock data for development
├── gee/               # Google Earth Engine export scripts (R1)
├── science/           # quality checks, harmonization, validation (R2)
├── data/              # district_monthly.csv, districts.geojson (+ mock files)
├── docs/              # decisions.md, data-contract.md
└── submission/        # project page text, storyboard, screenshots (R4)



Running locally

bash
git clone <repo-url> && cd firelens
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python app/make_mock.py        # creates mock data (only needed until real data is in data/)
streamlit run app/app.py       # opens http://localhost:8501

The app loads data/district_monthly.csv automatically when that file exists. Otherwise it uses the mock files and shows a "MOCK data" banner.

Data contract

data/district_monthly.csv, one row per district × sensor × month:

Column	Type	Meaning
state	text	State name
district	text	District name
sensor	text	terra, aqua or viirs_snpp
year, month	int	2016–2026, 1–12
fire_pixel_days	float	1 km pixels flagged as fire, summed over the month
clear_pixel_days	float	1 km land pixels clearly observed, summed over the month
mean_frp_mw	float	Mean fire radiative power over fire pixels (MW)
n_images	int	Daily images available that month (0 = no data)

Changes to this format need the science lead's approval and an entry in docs/decisions.md.



Limitations

Hotspots are satellite detections, not confirmed individual fires. One fire can produce many detections, and fires that are small, short-lived or under cloud may be missed.
District boundaries come from FAO GAUL and are not official boundaries of India. They are used for orientation only.
The most recent months depend on when NASA publishes the data in Google Earth Engine.
NOAA-20 and NOAA-21 VIIRS are not yet part of the calendar.
Next steps
Add NOAA-20 and NOAA-21 VIIRS, normalized for their extra overpasses
Extend the calendar back to 2003 using MODIS and the 2016–2026 calibration
An equal-area grid, so any drawn area can be analysed
A context panel per area (land cover, protected areas, settlements, weather)
Data sources and credits
NASA LP DAAC: MOD14A1 and MYD14A1 v6.1 (Terra and Aqua MODIS Thermal Anomalies & Fire Daily L3 1 km); VNP14A1 (VIIRS Suomi-NPP Thermal Anomalies & Fire Daily L3 1 km)
NASA FIRMS (Fire Information for Resource Management System)
Google Earth Engine, for data access and processing
FAO GAUL, for administrative boundaries

We acknowledge the use of data from NASA's Land Processes Distributed Active Archive Center (LP DAAC) and Fire Information for Resource Management System (FIRMS), part of NASA's Earth Science Data and Information System (ESDIS).
