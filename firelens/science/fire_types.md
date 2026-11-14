# FireLens — fire types and static sources

**Generated:** 2026-11-14 by `science/fire_types.py` · every number below is computed.
**Input:** hotspot pixel-days with land cover and night lights (499,706 rows kept: three
calendar sensors, FireMask ≥ 8, 2016 onwards) · **Outputs:** `data/district_fire_types.csv`
(7,410 rows), `data/static_sources.csv` (17 pixels)

## 1. Coverage

The hotspot export sampled two rectangles, not whole states. A district is reported only
when at least 95% of its area lies inside them: **19 of 49 districts**.

Reported: Kaithal (Haryana), Bathinda (Punjab), Faridkot (Punjab), Fatehgarh Sahib (Punjab), Jalandhar (Punjab), Kapurthala (Punjab), Ludhiana (Punjab), Mansa (Punjab), Moga (Punjab), Nawan Shehar (Punjab), Rupnagar (Punjab), Sangrur (Punjab), Almora (Uttarakhand), Bageshwar (Uttarakhand), Champawat (Uttarakhand), Naini Tal (Uttarakhand), Pauri Garhwal (Uttarakhand), Rudra Prayag (Uttarakhand), Tehri Garhwal (Uttarakhand).

Not reported (share of area sampled): Ambala 20%, Bhiwani 0%, Faridabad 0%, Fatehabad 73%, Gurgaon 0%, Hisar 2%, Jhajjar 0%, Jind 35%, Karnal 31%, Kurukshetra 45%, Mahendragarh 0%, Panchkula 3%, Panipat 0%, Rewari 0%, Rohtak 0%, Sirsa 68%, Sonepat 0%, Yamuna Nagar 0%, Amritsar 89%, Firozpur 33%, Gurdaspur 16%, Hoshiarpur 73%, Muktsar 60%, Patiala 92%, Chamoli 82%, Dehra Dun 38%, Haridwar 45%, Pithoragarh 74%, Udham Singh Nagar 55%, Uttarkashi 23%.
Re-running the export over the district boundaries (see `gee/README.md`) fills these in.

## 2. Check against the calendar

The hotspot list and `district_monthly.csv` come from the same products and fire rule, so
their counts must agree for the reported districts. The list counts whole pixels by centre
and drops pixels the product flags as water or coast; the calendar is area-weighted, so
small differences are expected.

| Sensor | District-months | Hotspots ÷ fire_pixel_days | Pearson r |
|---|---|---|---|
| aqua | 2,470 | 0.995 | 1.000 |
| terra | 2,470 | 0.996 | 1.000 |
| viirs_snpp | 2,470 | 0.996 | 1.000 |

## 3. What burns (Suomi-NPP VIIRS, reported districts, whole record)

Land cover is MCD12Q1 (IGBP) for the year of the detection: cropland = classes 12 and 14;
forest = 1–5; woodland and grass = 6–10 (shrubland, savanna, grassland; much open
Himalayan pine forest falls here); other = everything else, including built-up. LP DAAC
advises caution with MCD12Q1 v6.1 classes for 2021 onwards, so treat recent small shifts
between classes as uncertain.

| State | Districts | Hotspot pixel-days | Cropland | Forest | Woodland & grass | Other | Static sources |
|---|---|---|---|---|---|---|---|
| Haryana | 1 | 3,305 | 99.4% | 0.0% | 0.2% | 0.5% | 0.0% |
| Punjab | 11 | 124,143 | 99.1% | 0.0% | 0.1% | 0.4% | 0.3% |
| Uttarakhand | 7 | 13,049 | 3.7% | 32.6% | 63.7% | 0.0% | 0.0% |

## 4. Static sources

A pixel is static when it has hotspots in at least 8 of the 12 calendar months
and in at least 12 different months of the record (all years and sensors pooled). **17 pixels** qualify, out of 72,210 that ever had a hotspot.
Independent evidence that they are not vegetation fires: their median night-light radiance
is **167** nW/cm²/sr against **1.0** for all other
hotspot pixels, and **64%** of their detections are at night against
**45%**.

Static sources are **3.5%** of VIIRS hotspot pixel-days outside the two
burning seasons (Apr–May, Oct–Nov) and **0.09%** inside them: negligible for the
seasonal peaks, but visible in the quiet-month baseline. Districts with the largest share:
Bathinda 1.7%, Kapurthala 0.9%, Sangrur 0.0%, Faridkot 0.0%, Kaithal 0.0%.

The calendar (`district_monthly.csv`) still includes these pixels; removing them needs a
re-export and a decision-log entry. The rule is conservative: seasonal fixed sources
(brick kilns) are not caught.

| State | District | Lat | Lon | Detections | Months | Calendar months | At night | Night light |
|---|---|---|---|---|---|---|---|---|
| Punjab | Kapurthala | 31.3125 | 75.3452 | 73 | 57 | 12 | 32% | 14.8 |
| Punjab | Kapurthala | 31.3125 | 75.3354 | 79 | 52 | 11 | 35% | 12.6 |
| Punjab | Bathinda | 29.9125 | 74.9559 | 251 | 50 | 12 | 76% | 1222.0 |
| Punjab | Bathinda | 29.9125 | 74.9462 | 249 | 45 | 12 | 81% | 605.7 |
| Punjab | Bathinda | 29.9042 | 74.9496 | 207 | 40 | 12 | 71% | 2257.4 |
| Haryana | Sirsa | 29.9042 | 74.9400 | 129 | 28 | 12 | 72% | 1104.5 |
| Punjab | Kapurthala | 31.3042 | 75.3385 | 40 | 28 | 10 | 2% | 10.5 |
| Punjab | Bathinda | 29.9042 | 74.9592 | 103 | 24 | 11 | 67% | 465.1 |
| Haryana | Sirsa | 29.9125 | 74.9366 | 96 | 22 | 10 | 71% | 166.7 |
| Punjab | Bathinda | 29.9208 | 74.9525 | 67 | 22 | 11 | 84% | 265.0 |
| Punjab | Bathinda | 29.9125 | 74.9655 | 87 | 20 | 10 | 76% | 134.8 |
| Punjab | Sangrur | 30.4292 | 75.8814 | 19 | 18 | 9 | 63% | 8.8 |
| Uttarakhand | Udham Singh Nagar | 29.2042 | 79.0910 | 19 | 18 | 8 | 37% | 5.1 |
| Punjab | Bathinda | 29.9208 | 74.9621 | 47 | 17 | 10 | 83% | 176.3 |
| Haryana | Sirsa | 29.9208 | 74.9333 | 22 | 15 | 9 | 73% | 42.7 |
| Haryana | Sirsa | 29.9125 | 74.9270 | 38 | 15 | 8 | 74% | 64.6 |
| Punjab | Bathinda | 29.9208 | 74.9429 | 41 | 15 | 10 | 83% | 238.0 |
