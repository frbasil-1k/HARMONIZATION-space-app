// =====================================================================
// FireLens R1: individual hotspot pixels, for the app's "hotspots CSV" download.
// Paste into https://code.earthengine.google.com, click Run, then RUN each task
// in the Tasks tab (33 sensor-year tasks + 1 district lookup).
// Then put the Drive folder under data/raw/ and run: python gee/merge_hotspots.py
//
// Same rules as export_monthly.js, so the list adds up to fire_pixel_days:
//   hotspot = FireMask >= 8 on the sensor's native ~1 km grid, one row per pixel per day.
// =====================================================================

var STATES = ['Punjab', 'Haryana', 'Uttarakhand', 'Uttaranchal'];
var YEARS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
var DRIVE_FOLDER = 'firelens_hotspots';
var SENSORS = {
  terra: 'MODIS/061/MOD14A1',
  aqua: 'MODIS/061/MYD14A1',
  viirs_snpp: 'NASA/VIIRS/002/VNP14A1'
};
var FRP_SCALE = {terra: 0.1, aqua: 0.1, viirs_snpp: 1};  // same as export_monthly.js
var ONLY = {};  // re-run only some sensor-years, e.g. {terra: [2016]}; {} = all 33
var COLUMNS = ['sensor', 'acq_date', 'latitude', 'longitude', 'frp_mw', 'fire_mask', 'adm2_code'];

var DISTRICTS = ee.FeatureCollection('FAO/GAUL/2015/level2')
    .filter(ee.Filter.eq('ADM0_NAME', 'India'))
    .filter(ee.Filter.inList('ADM1_NAME', STATES));
var REGION = DISTRICTS.geometry();
// District of each pixel centre; pixels whose centre is outside every district are dropped.
var DISTRICT_ID = ee.Image().int().paint(DISTRICTS, 'ADM2_CODE').rename('adm2_code');

// Hotspots of one sensor in [start, end), UTC dates as in the monthly table.
function hotspots(sensor, start, end) {
  var cid = SENSORS[sensor];
  var proj = ee.ImageCollection(cid).first().select('FireMask').projection();
  var col = ee.ImageCollection(cid).filterDate(start, end);
  return col.map(function (img) {
    var fm = img.select('FireMask');
    var pixels = ee.Image.cat(
      fm.rename('fire_mask'),
      // -1 = FRP missing on a fire pixel (kept, blanked by the merge), so no hotspot is dropped.
      img.select('MaxFRP').multiply(FRP_SCALE[sensor]).unmask(-1).rename('frp_mw'),
      ee.Image.pixelLonLat(),
      DISTRICT_ID
    ).updateMask(fm.gte(8));
    var date = img.date().format('YYYY-MM-dd');
    return pixels.sample({region: REGION, projection: proj, dropNulls: true,
                          geometries: false, tileScale: 4})
        .map(function (f) { return f.set({sensor: sensor, acq_date: date}); });
  }).flatten();
}

// Preview: Ludhiana, VIIRS, Nov 2020 (expect a few hundred to ~1,000 rows).
var ludhiana = DISTRICTS.filter(ee.Filter.eq('ADM2_NAME', 'Ludhiana'));
print('Ludhiana VIIRS Nov 2020 hotspots:', hotspots('viirs_snpp', '2020-11-01', '2020-12-01')
    .filter(ee.Filter.eq('adm2_code', ludhiana.first().get('ADM2_CODE'))).size());

Object.keys(SENSORS).forEach(function (sensor) {
  YEARS.forEach(function (year) {
    if (Object.keys(ONLY).length && (ONLY[sensor] || []).indexOf(year) < 0) return;
    Export.table.toDrive({collection: hotspots(sensor, year + '-01-01', (year + 1) + '-01-01'), description: 'fl_hot_' + sensor + '_' + year,
                          folder: DRIVE_FOLDER, fileFormat: 'CSV', selectors: COLUMNS});
  });
});

// adm2_code -> exact GAUL names, joined by the merge.
Export.table.toDrive({collection: DISTRICTS, description: 'fl_hotspot_districts', folder: DRIVE_FOLDER,
                      fileFormat: 'CSV', selectors: ['ADM2_CODE', 'ADM1_NAME', 'ADM2_NAME']});
