const { test } = require("node:test");
const assert = require("node:assert/strict");
const { MonitoringCharts } = require("../charts.js");

function fixture(available = true) {
  const elements = new Map();
  function element() {
    return {
      hidden: false, textContent: "", value: "", children: [], attributes: {}, listeners: {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
      replaceChildren(...children) { this.children = children; },
      setAttribute(name, value) { this.attributes[name] = value; },
    };
  }
  const document = {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement() { return element(); },
  };
  const created = [];
  class FakeChart {
    constructor(canvas, config) {
      this.canvas = canvas; this.data = config.data; this.options = config.options; this.type = config.type; this.updates = [];
      created.push(this);
    }
    update(mode) { this.updates.push(mode); }
  }
  let time = 0;
  const dashboard = new MonitoringCharts(document, available ? FakeChart : undefined, () => ({ monotonicMs: time += 1000, wallMs: 1794830400000 + time }));
  const node = (id, adc, connected = true) => ({ device_id: id, ubicacion: "laboratorio", connected, last_reading: adc === null ? null : { adc, estado: adc > 1500 ? "alarma" : "normal", timestamp: "2026-11-16T12:00:00Z" } });
  const snapshot = (nodes, running = true, count = 0) => ({ nodes, running, messages_sent: count, alarm_threshold: 1500 });
  return { dashboard, document, created, node, snapshot, get: (id) => document.getElementById(id) };
}

test("charts are created once and ADC/state plots do not redraw repeated data", () => {
  const f = fixture();
  f.dashboard.update(f.snapshot([f.node("a", 1700)]));
  const [adc, traffic, states] = f.created;
  const adcUpdates = adc.updates.length;
  const stateUpdates = states.updates.length;
  f.dashboard.update(f.snapshot([f.node("a", 1700)], true, 10));
  assert.equal(f.created.length, 3);
  assert.equal(adc.updates.length, adcUpdates);
  assert.equal(states.updates.length, stateUpdates);
  assert.equal(traffic.data.datasets[0].data.at(-1).y, 10);
  assert.ok(f.created.every((chart) => chart.options.animation === false));
  assert.ok(f.created.every((chart) => chart.updates.every((mode) => mode === "none")));
});

test("device selection uses each device's observed history and preserves selection", () => {
  const f = fixture();
  const data = f.snapshot([f.node("a", 600), f.node("b", 1900)]);
  f.dashboard.update(data);
  const selector = f.get("chart-device");
  selector.value = "b";
  selector.listeners.change();
  assert.equal(f.created[0].data.datasets[0].data[0].y, 1900);
  f.dashboard.update(data);
  assert.equal(selector.value, "b");
  f.dashboard.update(f.snapshot([f.node("a", 600)]));
  assert.equal(selector.value, "a");
});

test("threshold line uses the current threshold without inventing ADC samples", () => {
  const f = fixture();
  f.dashboard.update(f.snapshot([f.node("a", 600)]));
  const chart = f.created[0];
  assert.equal(chart.data.datasets[0].data.length, 1);
  assert.deepEqual(chart.data.datasets[1].data.map((point) => point.y), [1500, 1500]);
  f.dashboard.update({ ...f.snapshot([f.node("a", 600)]), alarm_threshold: 2200 });
  assert.deepEqual(chart.data.datasets[1].data.map((point) => point.y), [2200, 2200]);
  assert.equal(chart.data.datasets[0].data.length, 1);
});

test("disconnecting or stopping retains the last ADC and its alarm state", () => {
  const f = fixture();
  f.dashboard.update(f.snapshot([f.node("a", 1700)]));
  f.dashboard.update(f.snapshot([f.node("a", 1700, false)], false));
  assert.equal(f.created[0].data.datasets[0].data[0].y, 1700);
  assert.deepEqual(f.created[2].data.datasets[0].data, [0, 1, 0]);
  assert.equal(f.get("chart-mqtt").textContent, "MQTT desconectado");
  assert.match(f.get("monitoring-status").textContent, /historial conservado/);
});

test("empty plots show explicit placeholders, not fabricated numerical data", () => {
  const f = fixture();
  f.dashboard.update(f.snapshot([f.node("a", null)], false));
  assert.equal(f.get("adc-empty").hidden, false);
  assert.equal(f.get("traffic-empty").hidden, false);
  assert.equal(f.get("adc-chart").hidden, true);
  assert.deepEqual(f.created[0].data.datasets[0].data, []);
  assert.deepEqual(f.created[1].data.datasets[0].data, []);
  assert.deepEqual(f.created[2].data.datasets[0].data, [0, 0, 1]);
  f.dashboard.update(f.snapshot([], false));
  assert.equal(f.get("states-empty").hidden, false);
  assert.equal(f.get("chart-device").disabled, true);
});

test("API failure leaves charts intact but marks current traffic as unknown", () => {
  const f = fixture();
  f.dashboard.update(f.snapshot([f.node("a", 600)]));
  f.dashboard.markOffline();
  assert.equal(f.get("traffic-rate").textContent, "—");
  assert.match(f.get("monitoring-status").textContent, /Sin conexión/);
  assert.equal(f.created[0].data.datasets[0].data.length, 1);
});

test("missing Chart.js reports a monitoring error without throwing on API updates", () => {
  const f = fixture(false);
  assert.equal(f.get("charts-error").hidden, false);
  assert.match(f.get("charts-error").textContent, /Chart.js/);
  assert.doesNotThrow(() => f.dashboard.update(f.snapshot([f.node("a", 600)])));
});
