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

_(3 sentences — to be refined after R2 confirms real data)_

Satellite fire records for Northern India are inconsistent across sensors: MODIS Terra, MODIS Aqua, and VIIRS Suomi-NPP each produce different hotspot counts, making year-on-year comparison unreliable. FireLens harmonizes all three into a single burning-activity metric — fire pixels divided by clearly-observed pixels — anchored to VIIRS Suomi-NPP and covering every district in Northern India from 2016 to 2026. The result is a live, interactive calendar that lets farmers, researchers, and policymakers see whether this month's burning is unusually high or low, backed by a decade of consistent data.

---

## How we used NASA data

We used three NASA daily fire products, accessed via Google Earth Engine:

- **MODIS Terra** — MOD14A1 (Collection 6.1), 1 km, daily, 2016–2026
- **MODIS Aqua** — MYD14A1 (Collection 6.1), 1 km, daily, 2016–2026
- **VIIRS Suomi-NPP** — VNP14A1 (Collection 2), 375 m, daily, 2016–2026

For each district × month × sensor we computed:
- **fire_pixel_days** — sum of 1 km pixels flagged as fire (FireMask ≥ 8) across all daily images
- **clear_pixel_days** — sum of 1 km land pixels with a clear view (FireMask = 5 or ≥ 7)
- **mean_frp_mw** — mean fire radiative power over fire pixels, in megawatts

The NASA LP DAAC distributes all three products.

---

## Method (plain words)

Satellite fire records are notoriously difficult to compare over time because different instruments see different numbers of fires for the same piece of land. To solve this, FireLens uses a four-step harmonization process written for clarity and scientific rigor:

1. **Daily Pixel Extraction via Google Earth Engine:**  
   Across every district in Northern India (covering Punjab, Haryana, and Uttarakhand) from January 2016 to 2026, we query daily observations from MODIS Terra (morning pass), MODIS Aqua (afternoon pass), and Suomi-NPP VIIRS (afternoon pass). For each day, we classify every 1 km pixel into whether it is actively burning ($\text{FireMask} \ge 8$), clear cloud-free land ($\text{FireMask} = 5 \text{ or } \ge 7$), or obscured by clouds, smoke, or missing data.

2. **Cloud-Normalized Burning Activity:**  
   Raw fire counts are deceptive: during the heavy monsoon months (July–September), cloud cover obscures the ground, making it appear that burning has stopped when the satellites simply cannot see the land. FireLens computes a normalized activity ratio for each district, month, and sensor:
   $$\text{Burning Activity} = \frac{\text{fire\_pixel\_days}}{\text{clear\_pixel\_days}}$$
   This expresses fire as a fraction of what was *actually observable*, completely removing cloud-cover bias and unequal satellite overpass frequencies.

3. **Anchoring to Suomi-NPP VIIRS:**  
   Because Suomi-NPP VIIRS has a sharper 375 m spatial resolution and higher thermal sensitivity than MODIS (1 km), it detects smaller, cooler agricultural burns that MODIS frequently misses. We choose Suomi-NPP VIIRS as our **anchor sensor**. MODIS Terra and MODIS Aqua are statistically scaled to the VIIRS baseline across their overlapping decade of observations, ensuring a seamless, continuous record.

4. **Interactive Historical Context & Anomaly Detection:**  
   Instead of overwhelming users with complex raw tables, the harmonized data powers an interactive Streamlit calendar heatmap. Each district's current monthly burning is automatically compared against its 10-year historical calendar-month median and percentile rank. Months with insufficient or missing imagery are transparently shown as blank/hatched cells rather than deceptive zeros. Researchers and local officials can download the full harmonized dataset directly as a clean CSV for regional air quality planning.

---

## Limitations

- Fire detections are aggregates of 1 km pixels, not counts of individual fires.
- District boundaries use the GAUL Level 2 dataset (FAO, 2015), which is not India's official boundary layer.
- Data availability ends at the latest processed image for each sensor; months after that appear blank, not zero.
- Phase 1 covers harmonization display; the statistical cross-sensor scaling (Phase 2) is in progress.

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

- **Live app:** _(waiting for R3 / Mohammed Mubeen to deploy)_
- **Demo video / slides:** _(add link once recorded — will be uploaded to Drive `slides/` or `video/`)_
- **GitHub repo:** https://github.com/frbasil-1k/HARMONIZATION-space-app
- **Drive folder (public):** https://drive.google.com/drive/folders/10Ux8snPZ6pcc6l9GhDaxWkgh4WRp14Ag?usp=sharing

---

> **TODO before submission:**
> - [ ] Confirm exact close time and required fields from Space Apps submission guide (R4)
> - [ ] Add live app URL from R3 (Mohammed Mubeen)
> - [ ] Confirm Oct–Nov peak wording matches R2's real Ludhiana plot (Mohammed Basil)
> - [x] Add Drive folder public link (Done: https://drive.google.com/drive/folders/10Ux8snPZ6pcc6l9GhDaxWkgh4WRp14Ag?usp=sharing)
> - [ ] Add demo video / slides link

