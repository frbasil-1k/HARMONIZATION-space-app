// =====================================================================
// FireLens: hotspots with land cover + night lights for ALL 49 districts
// (fire type and static sources in every district, not just the 19 that the
// FirePulse rectangles covered).
//
// Paste into https://code.earthengine.google.com, click Run, then RUN each task
// in the Tasks tab (33 tasks: 3 sensors x 11 years). Download the Drive folder
// `firelens_fire_context` into data/raw/fire_context/ and run, from firelens/:
//
//   python science/fire_types.py --input data/raw/fire_context --full-coverage
//
// Same hotspot rule and grid as export_hotspots.js (FireMask >= 8, native ~1 km
// grid, one row per pixel per day), so the counts add up to the calendar's
// fire_pixel_days; fire_types.py checks that and refuses to write if they don't.
// Same context layers as export_hotspots_context.js: MCD12Q1 LC_Type1 of the
// fire's year (latest year if not yet released) and VIIRS DNB monthly radiance.
// Columns match the FirePulse files, so fire_types.py reads both.
// =====================================================================

var STATES = ['Punjab', 'Haryana', 'Uttarakhand', 'Uttaranchal'];
var YEARS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
var DRIVE_FOLDER = 'firelens_fire_context';
var NODATA = -9999;
var SENSORS = {
  terra: {id: 'MODIS/061/MOD14A1', satellite: 'Terra', sensor: 'MODIS', frpScale: 0.1, dayBit: 2},
  aqua: {id: 'MODIS/061/MYD14A1', satellite: 'Aqua', sensor: 'MODIS', frpScale: 0.1, dayBit: 2},
  viirs_snpp: {id: 'NASA/VIIRS/002/VNP14A1', satellite: 'S-NPP', sensor: 'VIIRS', frpScale: 1, dayBit: 4}
};
var ONLY = {};  // re-run only some sensor-years, e.g. {terra: [2017]}; {} = all 33
var COLUMNS = ['sensor', 'satellite', 'acq_date', 'latitude', 'longitude', 'frp_mw',
               'confidence', 'daynight', 'land_cover_code', 'nightlight_rad'];
var CONF_NAMES = ee.List(['nominal', 'high']);  // FireMask 8, 9

var DISTRICTS = ee.FeatureCollection('FAO/GAUL/2015/level2')
    .filter(ee.Filter.eq('ADM0_NAME', 'India'))
    .filter(ee.Filter.inList('ADM1_NAME', STATES));
var REGION = DISTRICTS.geometry();

// ---------------- context layers (as in export_hotspots_context.js) ----------------
var LC = ee.ImageCollection('MODIS/061/MCD12Q1').select('LC_Type1');
var LC_LATEST = LC.sort('system:time_start', false).first();
var NTL = ee.ImageCollection('NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG').select('avg_rad');
var NTL_LAST = NTL.sort('system:time_start', false).first();

function contextBands(date) {
  var y = date.get('year');
  var lcYear = LC.filter(ee.Filter.calendarRange(y, y, 'year'));
  var lc = ee.Image(ee.Algorithms.If(lcYear.size().gt(0), lcYear.first(), LC_LATEST));
  var m0 = ee.Date.fromYMD(y, date.get('month'), 1);
  var ntlMonth = NTL.filterDate(m0, m0.advance(1, 'month'));
  var ntl = ee.Image(ee.Algorithms.If(ntlMonth.size().gt(0), ntlMonth.first(), NTL_LAST));
  // unmask so a missing context value never drops the fire pixel itself
  return lc.rename('land_cover_code').unmask(NODATA)
      .addBands(ntl.rename('nightlight_rad').unmask(NODATA));
}

// Hotspots of one sensor in [start, end), UTC dates as in the monthly table.
function hotspots(key, start, end, region) {
  var s = SENSORS[key];
  var proj = ee.ImageCollection(s.id).first().select('FireMask').projection();
  return ee.ImageCollection(s.id).filterDate(start, end).map(function (img) {
    var fm = img.select('FireMask');
    var date = img.date();
    var pixels = ee.Image.cat(
      fm.subtract(8).rename('conf_idx'),
      img.select('QA').rightShift(s.dayBit).bitwiseAnd(1).rename('is_day'),
      img.select('MaxFRP').multiply(s.frpScale).unmask(-1).rename('frp_mw'),
      ee.Image.pixelLonLat(),
      contextBands(date)
    ).updateMask(fm.gte(8));
    return pixels.sample({region: region || REGION, projection: proj, dropNulls: true,
                          geometries: false, tileScale: 4})
      .map(function (f) {
        return ee.Feature(null, {
          sensor: s.sensor,
          satellite: s.satellite,
          acq_date: date.format('YYYY-MM-dd'),
          latitude: f.get('latitude'),
          longitude: f.get('longitude'),
          frp_mw: f.get('frp_mw'),
          confidence: CONF_NAMES.get(f.getNumber('conf_idx')),
          daynight: ee.Algorithms.If(f.getNumber('is_day').eq(1), 'D', 'N'),
          land_cover_code: f.get('land_cover_code'),
          nightlight_rad: f.get('nightlight_rad')
        });
      });
  }).flatten();
}

// Preview: Ludhiana, VIIRS, Nov 2020. Expect a few hundred to ~1,000 rows, most with
// land_cover_code 12 (croplands).
var ludhiana = DISTRICTS.filter(ee.Filter.eq('ADM2_NAME', 'Ludhiana')).geometry();
var preview = hotspots('viirs_snpp', '2020-11-01', '2020-12-01', ludhiana);
print('Ludhiana VIIRS Nov 2020 hotspots:', preview.size());
print('First 5:', preview.limit(5));

Object.keys(SENSORS).forEach(function (key) {
  YEARS.forEach(function (year) {
    if (Object.keys(ONLY).length && (ONLY[key] || []).indexOf(year) < 0) return;
    Export.table.toDrive({
      collection: hotspots(key, year + '-01-01', (year + 1) + '-01-01'),
      description: 'fl_ctx_' + key + '_' + year,
      folder: DRIVE_FOLDER, fileFormat: 'CSV', selectors: COLUMNS
    });
  });
});

Map.centerObject(DISTRICTS, 6);
Map.addLayer(ee.Image().paint(DISTRICTS, 0, 2), {palette: ['00ffff']}, 'FireLens districts');
