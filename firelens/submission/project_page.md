# FireLens — Project Page Draft
> **Status:** DRAFT · R4 owner: Mohammed Zaidan Contractor · Last updated: 2026-11-14

---

## Team

**Team Name:** COSMICBRO's

| Role | Name |
|------|------|
| R1 — Data & Earth Engine | Lincoln Serrao |
| R2 — Science Lead | Shaikh Mohammed Basil |
| R3 — App | Mohammed Mubeen Kamalsha |
| R4 — Product & Pitch | Mohammed Zaidan Contractor |

---

## Challenge

**Harmonization of MODIS and VIIRS Hot Spots**

---

## One-liner

> A harmonized burning-activity calendar for Northern India, 2016–2026.

---

## Summary

Satellite fire records for Northern India are inconsistent across sensors: MODIS Terra, MODIS Aqua, and VIIRS Suomi-NPP each produce different hotspot counts, making year-on-year comparison unreliable. FireLens harmonizes all three into a single burning-activity metric — fire pixels divided by clearly-observed pixels — anchored to VIIRS Suomi-NPP and covering 49 districts of Punjab, Haryana and Uttarakhand from 2016 to 2026. The result is a live, interactive calendar that lets farmers, researchers, and policymakers see whether this month's burning is unusually high or low, backed by a decade of consistent data.

---

## How we used NASA data

We used three NASA daily fire products, accessed via Google Earth Engine:

- **MODIS Terra** — MOD14A1 (Collection 6.1), 1 km, daily, 2016–2026
- **MODIS Aqua** — MYD14A1 (Collection 6.1), 1 km, daily, 2016–2026
- **VIIRS Suomi-NPP** — VNP14A1 (Collection 2), 1 km, daily, 2016–2026

For each district × month × sensor we computed:
- **fire_pixel_days** — sum of 1 km pixels flagged as fire (FireMask ≥ 8) across all daily images
- **clear_pixel_days** — sum of 1 km land pixels with a clear view (FireMask = 5 or ≥ 7)
- **mean_frp_mw** — mean fire radiative power over fire pixels, in megawatts

The NASA LP DAAC distributes all three products.

---

## Method (plain words)

1. **Collect** — For each of 49 districts in Punjab, Haryana and Uttarakhand, each month from January 2016, we count how many 1 km pixels were flagged as burning, and how many pixels had a clear view that month.
2. **Normalize** — Burning activity = fire pixels ÷ clear-view pixels. This removes the cloud-cover bias that makes monsoon months look fire-free when they are simply unobserved.
3. **Harmonize** — VIIRS Suomi-NPP is our reference sensor: it covers the whole period and is the sensor that continues the record. MODIS Terra and Aqua are scaled to it with one ratio per state and sensor (the median VIIRS ÷ MODIS activity over 2016–2022), and the harmonized value is the mean of the sensors that saw the district clearly that month. Tested blind on 2023–2025, the scaled MODIS agrees with VIIRS at r = 0.70 (Aqua 0.83, Terra 0.57), and the seasonal peaks survive: Ludhiana's Oct–Nov paddy burning is 4.2× its yearly average, Naini Tal's Apr–May forest fires 4.0×.
4. **Display** — A Streamlit app lets any user pick a district (or search by latitude/longitude), a date range, and the harmonized series or any single sensor, then see a month × year calendar, yearly averages, anomalies against the monthly median and a sensor comparison. Metric cards show how the latest month compares to its historical median and percentile, and the harmonized and per-sensor data download as CSV.

---

## Limitations

- Fire detections are aggregates of 1 km pixels, not counts of individual fires.
- District boundaries use the GAUL Level 2 dataset (FAO, 2015), which is not India's official boundary layer.
- Data availability ends at the latest processed image for each sensor; months after that appear blank, not zero.
- Harmonization uses one ratio per state and sensor; Terra is the weakest match to VIIRS (r = 0.57 on the blind years), so it adds the most noise to the harmonized average.

---

## Next steps

- Add NOAA-20 and NOAA-21 VIIRS to extend the record forward
- Replace GAUL boundaries with official Survey of India district shapefiles
- Extend the MODIS record back to 2003
- Add a human-activity context panel (crop calendars, air-quality index)
- Equal-area grid option for users who don't want district aggregation

---

## Data credits

| Source | Product | Provider |
|--------|---------|----------|
| MODIS Terra Daily Fire | MOD14A1 v6.1 | NASA LP DAAC via Google Earth Engine |
| MODIS Aqua Daily Fire | MYD14A1 v6.1 | NASA LP DAAC via Google Earth Engine |
| VIIRS Suomi-NPP Daily Fire | VNP14A1 v2 | NASA LP DAAC via Google Earth Engine |
| District boundaries | GAUL Level 2 (2015) | FAO via Google Earth Engine |

---

## Links

- **Live app:** _(add link once R3 / Mohammed Mubeen deploys)_
- **Demo video / slides:** _(add link once recorded — goes in Drive `slides/` or `video/`)_
- **GitHub repo:** https://github.com/frbasil-1k/HARMONIZATION-space-app
- **Drive folder (public):** https://drive.google.com/drive/folders/10Ux8snPZ6pcc6l9GhDaxWkgh4WRp14Ag?usp=sharing

---

> **TODO before submission:**
> - [ ] Confirm exact close time and required fields from Space Apps submission guide (R4)
> - [ ] Add live app URL from R3 (Mohammed Mubeen)
> - [x] Confirm Oct–Nov peak wording matches R2's real Ludhiana plot (Mohammed Basil): confirmed, VIIRS peaks in November and harmonized Oct–Nov is 4.2× the yearly average
> - [x] Add Drive folder public link
> - [ ] Add demo video / slides link

