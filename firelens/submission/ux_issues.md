# FireLens — UX Issues Log
> **R4 owner:** Mohammed Zaidan Contractor  
> **Testing Session:** Saturday 23:30 IST  
> **Instructions:** Open the live app (or local run) as a first-time user in an incognito window. Log every moment of confusion, friction, visual glitch, or unexpected behavior. Mubeen will address priority fixes tomorrow morning.

---

## App Under Test

- **Live URL:** _(waiting for Mubeen to paste deployed share.streamlit.io link, or run locally: `streamlit run app/app.py`)_
- **Tested at:** 23:30 IST (Nov 14, 2026)
- **Tester:** Mohammed Zaidan Contractor (R4)

---

## Issue Log

| # | Screen / Step | What happened | Why it's confusing / Broken | Priority | Status / Mubeen Fix |
|---|--------------|---------------|----------------------------|----------|---------------------|
| 1 | | | | High / Med / Low | Open |
| 2 | | | | High / Med / Low | Open |
| 3 | | | | High / Med / Low | Open |
| 4 | | | | High / Med / Low | Open |

_(Add rows as you encounter issues during testing)_

---

## First-Time User Flow Checklist (Run at 23:30)

Walk through this sequence in an **Incognito / Private tab**:

1. **Initial Impression:** When the app loads, is the title, purpose, and one-liner immediately obvious?
2. **State & District Picker:** Select **Punjab → Ludhiana**. Are the dropdowns intuitive, alphabetical, and responsive?
3. **Sensor Selector:** Switch between **Suomi-NPP VIIRS**, **Terra MODIS**, and **Aqua MODIS**. Does the heatmap update smoothly?
4. **Heatmap Inspection:**
   - Look at October–November across years. Is the autumn stubble-burning band clearly visible?
   - Look at July–September. Are cloudy / no-data months rendered as blank / grey cells rather than false 0s?
   - Hover over cells. Does the tooltip show Year, Month, Activity value, and pixel counts clearly?
5. **Metric Cards:**
   - Ratio vs. median, percentile rank, and top 3 peak months.
   - Are the numbers easy to interpret without a statistics background?
6. **Data Download:** Click the **"Download CSV"** button for the selected district. Does it download a valid, clean CSV file?
7. **Disclaimers & Credits:** Check the footer for NASA LP DAAC data credits and GAUL boundary disclaimer.

---

## Screenshots to Capture for Sunday Slides

During your 23:30 test, take clean screenshots for Sunday's 7-slide deck and demo:
- [ ] Screenshot 1: Full app dashboard with Punjab → Ludhiana selected
- [ ] Screenshot 2: Close-up of the October–November fire peak on the heatmap
- [ ] Screenshot 3: Metric cards display
- [ ] Screenshot 4: Hover tooltip showing normalized activity value
- [ ] Screenshot 5: Side-by-side or toggled view showing sensor differences

---

## Summary for R3

_(fill in after testing — a 2–3 sentence summary of the biggest issues to fix)_


