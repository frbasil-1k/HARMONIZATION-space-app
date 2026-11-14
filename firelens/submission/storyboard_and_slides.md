# FireLens — Storyboard & Slide Skeleton
> **Status:** DRAFT · R4 owner: Mohammed Zaidan Contractor · Last updated: 2026-11-14
> ⚠️ Verify Oct–Nov peak district against R2's (Mohammed Basil's) real Ludhiana plot before finalising.

---

## 30-Second Demo Storyboard

| Seconds | Screen | Subtitle (spoken / on screen) |
|---------|--------|-------------------------------|
| 0–5 | A raw hotspot count bar chart that jumps discontinuously when sensors change (Terra → Aqua → VIIRS) | *"Satellite fire records change with every new sensor."* |
| 5–15 | App: user picks **Punjab → Ludhiana** → the month × year heatmap appears, Oct–Nov band clearly darker | *"FireLens harmonizes MODIS and VIIRS into one burning calendar."* |
| 15–25 | Metric cards zoom in: this month vs median ratio, percentile rank, top-3 peak months; then the sensor-agreement validation chart | *"See if this month is unusual — backed by both sensors."* |
| 25–30 | CSV download button clicked; footer shows team names and data credits | *"Built with NASA MODIS and VIIRS fire data."* |

### Notes for recording
- Record at **1080p**, keep cursor movements slow and deliberate.
- Use **English subtitles** (burn them in or attach as .srt — confirm format from submission rules).
- Total runtime ≤ 30 seconds (confirm cap from submission rules).
- **District fallback:** if Ludhiana's Oct–Nov peak isn't visually obvious in the real data, switch to whichever Punjab district R2 recommends.

---

## Slide Skeleton (7 slides max)

### Slide 1 — Title, Team & Challenge
- **Title:** FireLens
- **Subtitle:** A harmonized burning-activity calendar for Northern India, 2016–2026
- **Challenge:** Harmonization of MODIS and VIIRS Hot Spots · NASA Space Apps 2026
- **Team:** COSMICBRO's — Lincoln Serrao · Shaikh Mohammed Basil · Mohammed Mubeen Kamalsha · Mohammed Zaidan Contractor
- _Visual: clean title card, map of Northern India in background_

---

### Slide 2 — The Problem: The Sensor Step
- Satellite fire data is inconsistent across sensors — MODIS Terra, Aqua, and VIIRS return different counts for the same fire events.
- A decade of records contains two major sensor transitions, making trend analysis unreliable.
- _Visual: bar chart showing raw hotspot counts with visible jumps at sensor changeover years_

---

### Slide 3 — Our Approach: The Pipeline
- **Input:** Daily MODIS (MOD14A1, MYD14A1) + VIIRS (VNP14A1) fire products via Google Earth Engine
- **Normalize:** Activity = fire pixels ÷ clear-view pixels (removes cloud-cover bias)
- **Anchor:** VIIRS Suomi-NPP as reference; MODIS scaled to it
- **Output:** `district_monthly.csv` — one consistent time-series per district, 2016–2026
- _Visual: simple pipeline diagram: EE → CSV → App_

```
Google Earth Engine
   MODIS Terra (MOD14A1)  ──┐
   MODIS Aqua (MYD14A1)   ──┼──► fire_pixel_days / clear_pixel_days ──► Harmonize ──► App
   VIIRS S-NPP (VNP14A1)  ──┘                                             (anchor: VIIRS)
```

---

### Slide 4 — Harmonization & Validation
- Activity metric removes cloud-cover and sensor-sensitivity bias.
- Sensor-agreement chart: VIIRS vs Aqua activity — high correlation (r ≈ ?) confirms both sensors see the same signal.
- Seasonal validation: paddy-stubble peak (Oct–Nov) and wheat-residue peak (Apr–May) visible every year.
- _Visual: R2's Plot 2 (sensor agreement scatter) + Plot 1 (Ludhiana seasonality) — insert when available_

---

### Slide 5 — The App
- Pick state → district → sensor → see a month × year heatmap.
- Metric cards: current month vs long-term median.
- Blank cells = no data (not zero) — honesty built in.
- CSV download for researchers.
- _Visual: 2–3 screenshots of the live Streamlit app — Ludhiana heatmap, metric cards, map_

---

### Slide 6 — Insights & Use Cases
- **Farmers & extension workers:** Is this harvest season unusually smoky?
- **Air-quality researchers:** A clean, long fire-activity time series to correlate with PM2.5.
- **Policymakers:** Which districts burn most, and is it improving?
- Key insight: _[fill in after R2's real data — e.g. "Ludhiana's Oct–Nov activity has declined X% since 2020" or similar]_
- _Visual: heatmap of a high-burning district highlighting the trend_

---

### Slide 7 — Limitations, Next Steps & Credits
**Limitations**
- Pixel aggregates, not individual fire counts
- GAUL boundaries (not official India boundaries)
- Data ends at latest processed satellite image

**Next steps**
- NOAA-20/21 VIIRS · Official boundaries · Record back to 2003 · Human-activity context panel

**Data credits**
- MOD14A1 v6.1, MYD14A1 v6.1, VNP14A1 v2 — NASA LP DAAC via Google Earth Engine
- GAUL Level 2 — FAO via Google Earth Engine

---

## Screenshots needed (Sunday)
- [ ] App home / district picker (sidebar visible)
- [ ] Ludhiana heatmap with Oct–Nov band visible
- [ ] Metric cards close-up
- [ ] Sensor-agreement chart (from R2's notebook)
- [ ] CSV download in action
- [ ] Map tab with district boundary

---

> **TODO before recording:**
> - [ ] Confirm video ≤ 30 s and subtitle format from submission rules (R4)
> - [ ] Confirm which district shows clearest Oct–Nov peak (R2 — Mohammed Basil)
> - [ ] Get live app URL from R3 (Mohammed Mubeen) for recording
> - [ ] Fill in sensor-agreement correlation value from R2's Plot 2
> - [ ] Fill in Slide 6 insight once real data is available

