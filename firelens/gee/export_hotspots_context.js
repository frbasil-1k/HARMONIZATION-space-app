// =====================================================================
// FirePulse India: active fire hotspots 2012-01-01 .. 2026-11-01
// MODIS Terra/Aqua + VIIRS S-NPP/NOAA-20, enriched with MCD12Q1 land
// cover and VIIRS DNB nighttime lights. See README.md.
// Paste into https://code.earthengine.google.com, Run, then start the
// yearly tasks in the Tasks tab.
// =====================================================================

// ---------------- CONFIG ----------------
var REGION_MODE = 'INDIA_STUDY_ZONES'; // 'INDIA_STUDY_ZONES' (fast, default) | 'ALL_INDIA'
var START_DATE = '2012-01-01';
var END_DATE = '2026-11-01';           // exclusive
var DRIVE_FOLDER = 'FirePulse_India_Data';
var NODATA = -9999;                    // written when land cover / nightlights have no value
var MAP_YEAR = 2024;                   // year shown on the map layer

var STUDY_ZONES = ee.FeatureCollection([
  ee.Feature(ee.Geometry.Rectangle([73.6, 14.8, 74.6, 15.8]), {zone: 'Western Ghats / Goa-Karnataka'}),
  ee.Feature(ee.Geometry.Rectangle([76.5, 21.5, 81.2, 23.8]), {zone: 'Central India Tiger Reserves'}),
  ee.Feature(ee.Geometry.Rectangle([78.0, 29.0, 80.5, 30.8]), {zone: 'Uttarakhand Himalayan Pine'}),
  ee.Feature(ee.Geometry.Rectangle([74.5, 29.5, 76.8, 31.8]), {zone: 'Punjab/Haryana Stubble Belt'})
]);
var INDIA = ee.FeatureCollection('USDOS/LSIB_SIMPLE/2017').filter(ee.Filter.eq('country_na', 'India'));

var AOI_FC = REGION_MODE === 'ALL_INDIA' ? INDIA : STUDY_ZONES;
var AOI = AOI_FC.geometry();

var COLUMNS = ['sensor', 'satellite', 'acq_date', 'latitude', 'longitude',
               'frp_mw', 'confidence', 'daynight', 'land_cover_code', 'nightlight_rad'];
var CONF_NAMES = ee.List(['low', 'nominal', 'high']);

// ---------------- CONTEXT LAYERS ----------------
var LC = ee.ImageCollection('MODIS/061/MCD12Q1').select('LC_Type1');
var LC_LATEST = LC.sort('system:time_start', false).first();
var NTL = ee.ImageCollection('NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG').select('avg_rad');
var NTL_FIRST = NTL.sort('system:time_start').first();         // 2014-01
var NTL_LAST = NTL.sort('system:time_start', false).first();

// Land cover of the fire's year (latest year if not yet released),
// nightlights of the fire's month (clamped to first/last available month).
function contextBands(date) {
  var y = date.get('year');
  var lcYear = LC.filter(ee.Filter.calendarRange(y, y, 'year'));
  var lc = ee.Image(ee.Algorithms.If(lcYear.size().gt(0), lcYear.first(), LC_LATEST));

  var m0 = ee.Date.fromYMD(y, date.get('month'), 1);
  var ntlMonth = NTL.filterDate(m0, m0.advance(1, 'month'));
  var ntl = ee.Image(ee.Algorithms.If(ntlMonth.size().gt(0), ntlMonth.first(),
      ee.Algorithms.If(date.millis().lt(NTL_FIRST.date().millis()), NTL_FIRST, NTL_LAST)));

  // unmask so a missing context value never drops the fire pixel itself
  return lc.rename('land_cover_code').unmask(NODATA)
      .addBands(ntl.rename('nightlight_rad').unmask(NODATA))
      .addBands(ee.Image.pixelLonLat().rename(['longitude', 'latitude']));
}

// ---------------- FIRE IMAGE -> POINTS ----------------
function toPoints(img, fireMask, frp, confIdx, isDay, sensor, satellite) {
  var date = img.date();
  var stack = frp.rename('frp_mw').toFloat()
      .addBands(confIdx.rename('conf_idx').toInt())
      .addBands(isDay.rename('is_day').toInt())
      .addBands(contextBands(date))
      .updateMask(fireMask);

  var pts = stack.sample({
    region: AOI,
    projection: img.select(0).projection(), // native fire grid, no resampling
    geometries: false,
    dropNulls: true,
    tileScale: 4
  });

  return pts.map(function (f) {
    return ee.Feature(null, {
      sensor: sensor,
      satellite: satellite,
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
}

// FireMask >= 7 and QA bits 0-1 == 2 (confirmed land; drops water/coast glint).
function fireMaskOf(img) {
  return img.select('FireMask').gte(7).and(img.select('QA').bitwiseAnd(3).eq(2));
}

// MOD14A1 / MYD14A1 / VNP14A1. Day/night QA bit: MODIS = 2, VNP14A1 = 4.
function fireMaskProduct(sensor, satellite, frpScale, dayBit) {
  return function (img) {
    var fm = img.select('FireMask');
    return toPoints(img, fireMaskOf(img),
        img.select('MaxFRP').multiply(frpScale),
        fm.subtract(7),                                  // 7/8/9 -> low/nominal/high
        img.select('QA').rightShift(dayBit).bitwiseAnd(1),
        sensor, satellite);
  };
}

// NOAA-20 LANCE NRT (data from 2023-10-08): confidence 0/1/2, DayNight 1=day.
function noaa20(img) {
  var conf = img.select('confidence');
  return toPoints(img, conf.gte(1), img.select('frp'), conf, img.select('DayNight'),
      'VIIRS', 'NOAA-20');
}

var FM_BANDS = ['FireMask', 'MaxFRP', 'QA'];
var SOURCES = [
  {id: 'MODIS/061/MOD14A1',          bands: FM_BANDS, fn: fireMaskProduct('MODIS', 'Terra', 0.1, 2)},
  {id: 'MODIS/061/MYD14A1',          bands: FM_BANDS, fn: fireMaskProduct('MODIS', 'Aqua', 0.1, 2)},
  {id: 'NASA/VIIRS/002/VNP14A1',     bands: FM_BANDS, fn: fireMaskProduct('VIIRS', 'S-NPP', 1, 4)}, // unscaled per spec
  {id: 'NASA/LANCE/NOAA20_VIIRS/C2', bands: ['Bright_ti4', 'frp', 'confidence', 'DayNight'], fn: noaa20}
];

function collection(s, start, end) {
  return ee.ImageCollection(s.id).select(s.bands).filterDate(start, end).filterBounds(AOI);
}

function hotspots(start, end) {
  var out = ee.FeatureCollection([]);
  SOURCES.forEach(function (s) {
    out = out.merge(ee.FeatureCollection(collection(s, start, end).map(s.fn)).flatten());
  });
  return out;
}

// ---------------- EXPORT (one CSV per year) ----------------
var startYear = parseInt(START_DATE.slice(0, 4), 10);
var endYear = parseInt(END_DATE.slice(0, 4), 10);
for (var y = startYear; y <= endYear; y++) {
  var s = ee.Date(y === startYear ? START_DATE : y + '-01-01');
  var e = ee.Date(y === endYear ? END_DATE : (y + 1) + '-01-01');
  var tag = 'FirePulse_India_' + REGION_MODE + '_' + y;
  Export.table.toDrive({
    collection: hotspots(s, e),
    description: tag,
    folder: DRIVE_FOLDER,
    fileNamePrefix: tag,
    fileFormat: 'CSV',
    selectors: COLUMNS
  });
}

// ---------------- MAP ----------------
Map.centerObject(AOI_FC, REGION_MODE === 'ALL_INDIA' ? 5 : 6);
Map.addLayer(ee.Image().paint(AOI_FC, 0, 2), {palette: ['00ffff']}, 'AOI (' + REGION_MODE + ')');

// Fire-day count per pixel for MAP_YEAR, all three FireMask products combined.
var mapStart = ee.Date.fromYMD(MAP_YEAR, 1, 1), mapEnd = mapStart.advance(1, 'year');
var fireDays = ee.ImageCollection(SOURCES.slice(0, 3).map(function (src) {
  return collection(src, mapStart, mapEnd).map(function (img) {
    return fireMaskOf(img).selfMask().rename('fire').toInt();
  }).sum().rename('fire');
})).sum().selfMask().clip(AOI);
Map.addLayer(fireDays, {min: 1, max: 15, palette: ['ffff00', 'ff8800', 'ff0000', '800000']},
    'Fire-day count ' + MAP_YEAR + ' (MODIS+VIIRS)');

// NOAA-20 375 m max FRP for the same year (available from late 2023).
var n20 = collection(SOURCES[3], mapStart, mapEnd).map(function (img) {
  return img.select('frp').updateMask(img.select('confidence').gte(1));
}).max().clip(AOI);
Map.addLayer(n20, {min: 0, max: 100, palette: ['ff00ff', 'ffffff']}, 'NOAA-20 max FRP ' + MAP_YEAR, false);

// ---------------- QUICK CHECK ----------------
print('Preview Nov 2024 hotspots (first 10):',
    hotspots(ee.Date('2024-11-01'), ee.Date('2024-11-08')).limit(10));
