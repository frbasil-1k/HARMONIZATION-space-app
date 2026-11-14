// =====================================================================
// FireLens R1: district x month x sensor fire table (playbook section 3)
// Paste into https://code.earthengine.google.com and click Run.
//   Console: smoke test, exact GAUL state names, Ludhiana 2020 chart.
//   Map:     chosen districts + Punjab 2020 VIIRS fire-days.
//   Tasks:   Punjab test CSV, 33 yearly exports, district GeoJSON.
// Then download the Drive folder and run: python gee/merge_exports.py
// =====================================================================

// ---------------- CONFIG ----------------
// Final list decided by R2. Uttarakhand is listed under both names because GAUL
// may use the old one; the name that doesn't exist matches 0 districts (harmless).
var STATES = ['Punjab', 'Haryana', 'Uttarakhand', 'Uttaranchal'];
var YEARS = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
var DRIVE_FOLDER = 'firelens_exports';
var SENSORS = {
  terra: 'MODIS/061/MOD14A1',
  aqua: 'MODIS/061/MYD14A1',
  viirs_snpp: 'NASA/VIIRS/002/VNP14A1'
};
// MaxFRP -> MW. MODIS stored x10. Unscaled VNP14A1 already matched MODIS in our
// hotspot run (median 11 vs 16 MW); playbook says 0.1 for all. Confirm with R2.
var FRP_SCALE = {terra: 0.1, aqua: 0.1, viirs_snpp: 1};

// Which tasks to create (each still needs Run in the Tasks tab).
var MAKE_TEST_TASK = false;       // step 2 (done: handoff 1 sent): data/test_punjab_2020_viirs.csv
var MAKE_FULL_TASKS = true;       // step 3: 33 tasks fl_<sensor>_<year>
var MAKE_BOUNDARY_TASK = false;   // step 4: fl_districts.geojson (done)
// Re-run only these sensor-years (empty {} = all 33). Missing from the first export run.
var ONLY = {terra: [2016, 2017, 2018, 2021]};

var BANDS = ['fire', 'clear', 'frp'];
var CONTRACT = ['state', 'district', 'sensor', 'year', 'month',
                'fire_pixel_days', 'clear_pixel_days', 'mean_frp_mw', 'n_images'];

// ---------------- CORE ----------------
var GAUL_INDIA = ee.FeatureCollection('FAO/GAUL/2015/level2')
    .filter(ee.Filter.eq('ADM0_NAME', 'India'));

function districts(states) {
  return GAUL_INDIA.filter(ee.Filter.inList('ADM1_NAME', states))
      .select(['ADM1_NAME', 'ADM2_NAME']);
}

function monthTable(sensor, year, month, regions) {
  var cid = SENSORS[sensor];
  var scale = FRP_SCALE[sensor];
  var start = ee.Date.fromYMD(year, month, 1);
  var col = ee.ImageCollection(cid).filterDate(start, start.advance(1, 'month'));

  var daily = function (img) {
    var fm = img.select('FireMask');
    var fire = fm.gte(8);                     // nominal + high confidence
    var clear = fm.eq(5).or(fm.gte(7));       // land seen clearly (no fire, or fire)
    var frp = img.select('MaxFRP').unmask(0).multiply(scale).multiply(fire);
    return ee.Image.cat(fire, clear, frp).rename(BANDS).toFloat();
  };

  // Empty month (after latest image) -> zeros, not blanks; n_images = 0 flags it.
  var zeros = ee.Image.constant([0, 0, 0]).rename(BANDS).toFloat();
  var img = ee.Image(ee.Algorithms.If(col.size().gt(0), col.map(daily).sum(), zeros));

  // Reduce on the sensor's native ~1 km grid, not a resampled one.
  var proj = ee.ImageCollection(cid).first().select('FireMask').projection();
  return img.reduceRegions({
    collection: regions,
    reducer: ee.Reducer.sum(),
    crs: proj,
    scale: proj.nominalScale(),
    tileScale: 4
  }).map(function (f) {
    return f.set({sensor: sensor, year: year, month: month, n_images: col.size()});
  });
}

function yearTable(sensor, year, regions) {
  var months = [];
  for (var m = 1; m <= 12; m++) months.push(monthTable(sensor, year, m, regions));
  return ee.FeatureCollection(months).flatten();
}

// Raw export columns -> data-contract columns (same as merge_exports.to_contract).
function toContract(f) {
  var fire = f.getNumber('fire');
  return ee.Feature(null, {
    state: f.get('ADM1_NAME'),
    district: f.get('ADM2_NAME'),
    sensor: f.get('sensor'),
    year: f.get('year'),
    month: f.get('month'),
    fire_pixel_days: fire,
    clear_pixel_days: f.get('clear'),
    mean_frp_mw: ee.Algorithms.If(fire.gt(0), f.getNumber('frp').divide(fire), null),
    n_images: f.get('n_images')
  });
}

// ---------------- STEP 1: smoke test + names ----------------
print('VNP14A1 Oct-Nov 2020 images (daily, expect ~61):',
    ee.ImageCollection(SENSORS.viirs_snpp).filterDate('2020-10-01', '2020-12-01').size());
print('GAUL India state names:', GAUL_INDIA.aggregate_array('ADM1_NAME').distinct().sort());
STATES.forEach(function (s) {
  print('Districts in "' + s + '":', districts([s]).size());
});

print('Total districts (expect Punjab + Haryana + Uttarakhand ~ 36 + 13):', districts(STATES).size());

// ---------------- STEP 2: Punjab 2020 VIIRS test ----------------
var punjabTest = yearTable('viirs_snpp', 2020, districts(['Punjab'])).map(toContract);
var ludhiana = punjabTest.filter(ee.Filter.eq('district', 'Ludhiana'));
print(ui.Chart.feature.byFeature(ludhiana, 'month', ['fire_pixel_days'])
    .setChartType('ColumnChart')
    .setOptions({title: 'Ludhiana 2020 VIIRS fire_pixel_days (expect Oct-Nov peak)'}));
if (MAKE_TEST_TASK) {
  Export.table.toDrive({
    collection: punjabTest, description: 'test_punjab_2020_viirs',
    folder: DRIVE_FOLDER, fileFormat: 'CSV', selectors: CONTRACT
  });
}

// ---------------- STEP 3: all exports (one task per sensor x year) ----------------
var REGIONS = districts(STATES);
if (MAKE_FULL_TASKS) {
  Object.keys(SENSORS).forEach(function (sensor) {
    YEARS.forEach(function (year) {
      if (Object.keys(ONLY).length && (ONLY[sensor] || []).indexOf(year) < 0) return;
      Export.table.toDrive({
        collection: yearTable(sensor, year, REGIONS),
        description: 'fl_' + sensor + '_' + year,
        folder: DRIVE_FOLDER + '_' + sensor,   // one Drive folder per sensor (11 files), fits Drive's 30-file zip
        fileFormat: 'CSV',
        selectors: ['ADM1_NAME', 'ADM2_NAME', 'sensor', 'year', 'month', 'fire', 'clear', 'frp', 'n_images']
      });
    });
  });
}

// ---------------- STEP 4: district boundaries ----------------
if (MAKE_BOUNDARY_TASK) {
  Export.table.toDrive({
    collection: REGIONS.map(function (f) {
      return ee.Feature(f.geometry().simplify({maxError: 500}),
          {state: f.get('ADM1_NAME'), district: f.get('ADM2_NAME')});
    }),
    description: 'fl_districts', folder: DRIVE_FOLDER, fileFormat: 'GeoJSON'
  });
}

// ---------------- MAP ----------------
Map.centerObject(REGIONS, 6);
Map.addLayer(ee.Image().paint(REGIONS, 0, 1), {palette: ['00ffff']}, 'Districts (' + STATES.join(', ') + ')');
var fireDays2020 = ee.ImageCollection(SENSORS.viirs_snpp).filterDate('2020-01-01', '2021-01-01')
    .map(function (img) { return img.select('FireMask').gte(8); })
    .sum().selfMask().clip(REGIONS);
Map.addLayer(fireDays2020, {min: 1, max: 10, palette: ['ffff00', 'ff8800', 'ff0000']},
    'VIIRS fire-days 2020 (FireMask >= 8)');
