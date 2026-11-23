"use strict";

// Browser global + CommonJS export for dependency-free Node tests.
((root, factory) => {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ESP32Monitoring = api;
})(globalThis, () => {
  const HISTORY_LIMIT = 60;

  function appendLimited(list, item) {
    list.push(item);
    if (list.length > HISTORY_LIMIT) list.splice(0, list.length - HISTORY_LIMIT);
  }

  function countStates(nodes) {
    const counts = { normal: 0, alarma: 0, sinLectura: 0 };
    for (const node of nodes) {
      const state = node.last_reading?.estado;
      // Connectivity is deliberately independent of the last ADC state.
      if (state === "normal" || state === "alarma") counts[state] += 1;
      else counts.sinLectura += 1;
    }
    return counts;
  }

  class MonitoringHistory {
    constructor() {
      this.devices = new Map();
      this.traffic = [];
      this.baseline = null;
      this.rate = null;
      this.trafficGap = false;
      this.states = countStates([]);
    }

    ingest(snapshot, monotonicMs, wallMs, { sampleTraffic = true } = {}) {
      const activeIds = new Set(snapshot.nodes.map((node) => node.device_id));
      for (const id of this.devices.keys()) {
        if (!activeIds.has(id)) this.devices.delete(id);
      }
      for (const node of snapshot.nodes) {
        let history = this.devices.get(node.device_id);
        if (!history) {
          history = { points: [], lastTimestamp: -Infinity };
          this.devices.set(node.device_id, history);
        }
        const reading = node.last_reading;
        if (!reading) continue;
        const timestamp = Date.parse(reading.timestamp);
        if (!Number.isFinite(timestamp) || !Number.isInteger(reading.adc) || reading.adc < 0 || reading.adc > 4095) continue;
        // Ignore repeated snapshots and late/out-of-order readings.
        if (timestamp < history.lastTimestamp || history.points.some((point) => point.timestamp === reading.timestamp)) continue;
        appendLimited(history.points, { x: timestamp, y: reading.adc, estado: reading.estado, timestamp: reading.timestamp });
        history.lastTimestamp = timestamp;
      }
      this.states = countStates(snapshot.nodes);
      if (sampleTraffic) this.sampleTraffic(snapshot, monotonicMs, wallMs);
    }

    sampleTraffic(snapshot, monotonicMs, wallMs) {
      const count = snapshot.messages_sent;
      if (!Number.isFinite(count) || count < 0 || !Number.isFinite(monotonicMs) || !Number.isFinite(wallMs)) {
        this.markGap();
        return;
      }
      const previous = this.baseline;
      if (!previous) {
        this.baseline = { count, time: monotonicMs, running: snapshot.running };
        this.rate = null;
        return;
      }
      const elapsed = monotonicMs - previous.time;
      if (elapsed <= 0) return;
      this.baseline = { count, time: monotonicMs, running: snapshot.running };
      if (count < previous.count) {
        // Backend restart: start a new baseline instead of a negative rate.
        this.rate = null;
        this.trafficGap = true;
        return;
      }
      this.rate = (count - previous.count) * 1000 / elapsed;
      if (snapshot.running || previous.running || count > previous.count) {
        if (this.trafficGap && this.traffic.length) {
          appendLimited(this.traffic, { x: wallMs, y: null });
        }
        appendLimited(this.traffic, { x: wallMs, y: this.rate });
        this.trafficGap = false;
      }
      // A stopped, unchanged simulation keeps its chart instead of scrolling
      // the last measured traffic away with repeated zero samples.
    }

    markGap() {
      this.baseline = null;
      this.rate = null;
      this.trafficGap = true;
    }
  }

  return { HISTORY_LIMIT, MonitoringHistory, countStates };
});
