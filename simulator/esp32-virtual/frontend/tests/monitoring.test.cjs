const { test } = require("node:test");
const assert = require("node:assert/strict");
const { MonitoringHistory, countStates, HISTORY_LIMIT } = require("../monitoring-data.js");

const origin = Date.parse("2026-11-16T12:00:00Z");
function node(id = "virtual-001", adc = 1000, timestamp = new Date(origin).toISOString(), connected = true, estado = "normal") {
  return { device_id: id, connected, last_reading: adc === null ? null : { adc, timestamp, estado } };
}
function snapshot(nodes = [node()], count = 0, running = true) {
  return { nodes, messages_sent: count, running, alarm_threshold: 1500 };
}

test("empty snapshots create no fictitious readings or traffic", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node("a", null)], 0, false), 1000, origin);
  history.ingest(snapshot([node("a", null)], 0, false), 2000, origin + 1000);
  assert.equal(history.devices.get("a").points.length, 0);
  assert.deepEqual(history.traffic, []);
  assert.deepEqual(history.states, { normal: 0, alarma: 0, sinLectura: 1 });
});

test("repeated timestamps are ignored even when values change", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node()]), 1000, origin);
  history.ingest(snapshot([node("virtual-001", 2000)]), 2000, origin + 1000);
  assert.equal(history.devices.get("virtual-001").points.length, 1);
  assert.equal(history.devices.get("virtual-001").points[0].y, 1000);
});

test("distinct microsecond timestamps in the same millisecond remain distinct", () => {
  const history = new MonitoringHistory();
  for (const timestamp of ["2026-11-16T12:00:00.000001Z", "2026-11-16T12:00:00.000002Z", "2026-11-16T12:00:00.000001Z"]) {
    history.ingest(snapshot([node("a", 1000, timestamp)]), 1000, origin);
  }
  assert.equal(history.devices.get("a").points.length, 2);
});

test("ADC and traffic history remain bounded to sixty points", () => {
  const history = new MonitoringHistory();
  for (let i = 0; i < 200; i++) {
    history.ingest(snapshot([node("a", i, new Date(origin + i * 1000).toISOString())], i * 10), i * 1000, origin + i * 1000);
  }
  assert.equal(history.devices.get("a").points.length, HISTORY_LIMIT);
  assert.equal(history.devices.get("a").points[0].y, 140);
  assert.equal(history.traffic.length, HISTORY_LIMIT);
  assert.equal(history.traffic.at(-1).y, 10);
});

test("each device has an independent history; retired IDs do not accumulate", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node("a", 10), node("b", 20)]), 0, origin);
  assert.equal(history.devices.get("a").points[0].y, 10);
  assert.equal(history.devices.get("b").points[0].y, 20);
  history.ingest(snapshot([node("b", 20)]), 1000, origin + 1000);
  assert.equal(history.devices.has("a"), false);
  assert.equal(history.devices.get("b").points.length, 1);
});

test("invalid ADC values, timestamps and late readings are ignored", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node("a", 12, new Date(origin + 5000).toISOString())]), 0, origin);
  for (const reading of [node("a", -1), node("a", 4096), node("a", 1.5), node("a", 100, "invalid"), node("a", 100)]) {
    history.ingest(snapshot([reading]), 1000, origin + 1000);
  }
  assert.equal(history.devices.get("a").points.length, 1);
  assert.equal(history.devices.get("a").points[0].y, 12);
});

test("traffic uses counter delta and actual monotonic elapsed time", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([], 100), 500, origin);
  assert.equal(history.rate, null);
  history.ingest(snapshot([], 112), 2000, origin + 9000);
  assert.equal(history.rate, 8); // 12 / 1.5, independent of wall clock.
  history.ingest(snapshot([], 112), 3000, origin + 10000);
  assert.equal(history.rate, 0); // A real unchanged-counter observation.
});

test("mutation responses do not create traffic samples or replace the baseline", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([], 0), 1000, origin);
  history.ingest(snapshot([], 2), 1100, origin + 100, { sampleTraffic: false });
  assert.equal(history.traffic.length, 0);
  history.ingest(snapshot([], 10), 2000, origin + 1000);
  assert.equal(history.rate, 10);
});

test("zero or backwards elapsed time cannot create invalid traffic", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([], 10), 1000, origin);
  history.ingest(snapshot([], 20), 1000, origin);
  history.ingest(snapshot([], 20), 500, origin);
  assert.equal(history.traffic.length, 0);
  history.ingest(snapshot([], 20), 2000, origin + 1000);
  assert.equal(history.rate, 10);
});

test("counter reset starts a baseline and leaves an explicit gap", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([], 100), 0, origin);
  history.ingest(snapshot([], 110), 1000, origin + 1000);
  history.ingest(snapshot([], 0), 2000, origin + 2000);
  assert.equal(history.rate, null);
  history.ingest(snapshot([], 5), 3000, origin + 3000);
  assert.equal(history.rate, 5);
  assert.deepEqual(history.traffic.map((point) => point.y), [10, null, 5]);
});

test("API outages preserve history and do not average traffic over missing time", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node()], 0), 0, origin);
  history.ingest(snapshot([node()], 10), 1000, origin + 1000);
  history.markGap();
  history.ingest(snapshot([node()], 100), 11000, origin + 11000);
  assert.equal(history.rate, null);
  history.ingest(snapshot([node()], 103), 12000, origin + 12000);
  assert.equal(history.rate, 3);
  assert.equal(history.devices.get("virtual-001").points.length, 1);
  assert.deepEqual(history.traffic.map((point) => point.y), [10, null, 3]);
});

test("stopping preserves ADC and freezes stored traffic after the final sample", () => {
  const history = new MonitoringHistory();
  history.ingest(snapshot([node()], 0), 0, origin);
  history.ingest(snapshot([node()], 10), 1000, origin + 1000);
  history.ingest(snapshot([node()], 15, false), 2000, origin + 2000);
  const traffic = JSON.stringify(history.traffic);
  for (let i = 3; i < 100; i++) history.ingest(snapshot([node()], 15, false), i * 1000, origin + i * 1000);
  assert.equal(JSON.stringify(history.traffic), traffic);
  assert.equal(history.devices.get("virtual-001").points.length, 1);
  assert.equal(history.rate, 0);
});

test("the doughnut describes ADC state independently of MQTT connectivity", () => {
  assert.deepEqual(countStates([
    node("a", 1800, new Date(origin).toISOString(), false, "alarma"),
    node("b", 700, new Date(origin).toISOString(), false, "normal"),
    node("c", null, undefined, true),
  ]), { normal: 1, alarma: 1, sinLectura: 1 });
});

test("the vendored distribution exports the verified Chart.js version", () => {
  assert.equal(require("../vendor/chart.umd.min.js").version, "4.6.1");
});
