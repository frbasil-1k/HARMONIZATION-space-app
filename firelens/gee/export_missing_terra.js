// =====================================================================
// FireLens R1: re-export ONLY the 4 missing Terra years (V1 fix, PR #6)
// Paste into https://code.earthengine.google.com, click Run, then RUN the
// 4 tasks in the Tasks tab. Files land in Drive folder firelens_exports_terra.
// Same logic as gee/export_monthly.js (keep the two in sync).
// =====================================================================

var STATES = ['Punjab', 'Haryana', 'Uttarakhand', 'Uttaranchal'];
var MISSING_YEARS = [2016, 2017, 2018, 2021];
var CID = 'MODIS/061/MOD14A1';
var FRP_SCALE = 0.1;
var BANDS = ['fire', 'clear', 'frp'];

var REGIONS = ee.FeatureCollection('FAO/GAUL/2015/level2')
    .filter(ee.Filter.eq('ADM0_NAME', 'India'))
    .filter(ee.Filter.inList('ADM1_NAME', STATES))
    .select(['ADM1_NAME', 'ADM2_NAME']);
var PROJ = ee.ImageCollection(CID).first().select('FireMask').projection();

function daily(img) {
  var fm = img.select('FireMask');
  var fire = fm.gte(8);
  var clear = fm.eq(5).or(fm.gte(7));
  var frp = img.select('MaxFRP').unmask(0).multiply(FRP_SCALE).multiply(fire);
  return ee.Image.cat(fire, clear, frp).rename(BANDS).toFloat();
}

function monthTable(year, month) {
  var start = ee.Date.fromYMD(year, month, 1);
  var col = ee.ImageCollection(CID).filterDate(start, start.advance(1, 'month'));
  var zeros = ee.Image.constant([0, 0, 0]).rename(BANDS).toFloat();
  var img = ee.Image(ee.Algorithms.If(col.size().gt(0), col.map(daily).sum(), zeros));
  return img.reduceRegions({
    collection: REGIONS, reducer: ee.Reducer.sum(),
    crs: PROJ, scale: PROJ.nominalScale(), tileScale: 4
  }).map(function (f) {
    return f.set({sensor: 'terra', year: year, month: month, n_images: col.size()});
  });
}

print('Districts (expect 49):', REGIONS.size());

MISSING_YEARS.forEach(function (year) {
  var months = [];
  for (var m = 1; m <= 12; m++) months.push(monthTable(year, m));
  Export.table.toDrive({
    collection: ee.FeatureCollection(months).flatten(),
    description: 'fl_terra_' + year,
    folder: 'firelens_exports_terra',
    fileFormat: 'CSV',
    selectors: ['ADM1_NAME', 'ADM2_NAME', 'sensor', 'year', 'month', 'fire', 'clear', 'frp', 'n_images']
  });
});
