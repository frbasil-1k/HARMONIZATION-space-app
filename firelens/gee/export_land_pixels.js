// =====================================================================
// FireLens R1: land pixels per district (for R2's coverage_share)
// Paste into https://code.earthengine.google.com, click Run, then RUN the
// task "fl_land_pixels" in the Tasks tab. Download the CSV from Drive into
// data/raw/, then: python gee/supporting.py land
// Same districts and same ~1 km MODIS grid as gee/export_monthly.js, so
// land_pixels is directly comparable to clear_pixel_days / fire_pixel_days.
// =====================================================================

var STATES = ['Punjab', 'Haryana', 'Uttarakhand', 'Uttaranchal'];
var REGIONS = ee.FeatureCollection('FAO/GAUL/2015/level2')
    .filter(ee.Filter.eq('ADM0_NAME', 'India'))
    .filter(ee.Filter.inList('ADM1_NAME', STATES));
var PROJ = ee.ImageCollection('MODIS/061/MOD14A1').first().select('FireMask').projection();

// MCD12Q1 land/water band: 1 = land. 2020 is mid-period; the coastline doesn't move.
var land = ee.ImageCollection('MODIS/061/MCD12Q1').filterDate('2020-01-01', '2021-01-01')
    .first().select('LW').eq(1).rename('land_pixels');

// sum (not count) = same partial-pixel weighting as the fire/clear sums in the main table.
var table = land.reduceRegions({
  collection: REGIONS, reducer: ee.Reducer.sum(),
  crs: PROJ, scale: PROJ.nominalScale(), tileScale: 4
}).map(function (f) {
  return ee.Feature(null, {state: f.get('ADM1_NAME'), district: f.get('ADM2_NAME'),
                           land_pixels: f.get('sum')});  // 1-band image: EE names the result 'sum'
});

print('Districts (expect 49):', table.size());
print('First rows:', table.limit(5));
Export.table.toDrive({collection: table, description: 'fl_land_pixels',
  folder: 'firelens_exports', fileFormat: 'CSV', selectors: ['state', 'district', 'land_pixels']});
