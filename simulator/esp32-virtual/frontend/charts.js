"use strict";

((root, factory) => {
  if (typeof module === "object" && module.exports) module.exports = factory(require("./monitoring-data.js"));
  else root.ESP32Charts = factory(root.ESP32Monitoring);
})(globalThis, ({ MonitoringHistory }) => {
  const BLUE = "#2563EB";
  const RED = "#DC2626";
  const GREEN = "#16A34A";
  const GRAY = "#94A3B8";
  const timeFormat = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const numberFormat = new Intl.NumberFormat("es", { maximumFractionDigits: 1 });
  const timeLabel = (value) => timeFormat.format(new Date(value));

  function lineOptions(unit) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => items.length ? timeLabel(items[0].parsed.x) : "",
            label: (item) => `${item.dataset.label}: ${numberFormat.format(item.parsed.y)} ${unit}`,
          },
        },
      },
      scales: {
        x: { type: "linear", grid: { display: false }, ticks: { maxTicksLimit: 4, maxRotation: 0, callback: timeLabel }, border: { display: false } },
        y: { beginAtZero: true, grid: { color: "#EEF2F6" }, border: { display: false }, ticks: { maxTicksLimit: 5 } },
      },
    };
  }

  class MonitoringCharts {
    constructor(document, ChartClass, clock = () => ({ monotonicMs: performance.now(), wallMs: Date.now() })) {
      this.document = document;
      this.ChartClass = ChartClass;
      this.clock = clock;
      this.history = new MonitoringHistory();
      this.snapshot = null;
      this.selected = "";
      this.selectorKey = "";
      this.adcKey = "";
      this.trafficKey = "";
      this.statesKey = "";
      this.charts = null;
      this.selector = this.element("chart-device");
      this.selector.addEventListener("change", () => {
        this.selected = this.selector.value;
        this.renderAdc();
      });
      this.enabled = typeof ChartClass === "function";
      if (!this.enabled) {
        const error = this.element("charts-error");
        error.textContent = "No se pudo cargar Chart.js. La configuración y la tabla siguen disponibles; vuelve a cargar el panel para reintentar.";
        error.hidden = false;
      }
    }

    element(id) { return this.document.getElementById(id); }

    createCharts() {
      if (this.charts || !this.enabled) return;
      const adcOptions = lineOptions("ADC");
      adcOptions.scales.y.max = 4095;
      this.charts = {
        adc: new this.ChartClass(this.element("adc-chart"), {
          type: "line",
          data: { datasets: [
            { label: "Lectura", data: [], borderColor: BLUE, borderWidth: 2, pointRadius: 2, pointHoverRadius: 5, tension: 0 },
            { label: "Umbral actual", data: [], borderColor: RED, borderWidth: 1.5, borderDash: [5, 5], pointRadius: 0 },
          ] },
          options: adcOptions,
        }),
        traffic: new this.ChartClass(this.element("traffic-chart"), {
          type: "line",
          data: { datasets: [{ label: "Tráfico", data: [], borderColor: BLUE, backgroundColor: "rgba(37,99,235,0.07)", borderWidth: 2, fill: true, pointRadius: 0, pointHoverRadius: 4, spanGaps: false, tension: 0 }] },
          options: lineOptions("msg/s"),
        }),
        states: new this.ChartClass(this.element("states-chart"), {
          type: "doughnut",
          data: { labels: ["Normal", "Alarma", "Alerta Preventiva", "Sin lectura"], datasets: [{ data: [], backgroundColor: [GREEN, RED, "#b45309", GRAY], borderWidth: 0, hoverOffset: 2 }] },
          options: { responsive: true, maintainAspectRatio: false, animation: false, cutout: "76%", plugins: { legend: { display: false } } },
        }),
      };
    }

    update(snapshot, options = {}) {
      this.snapshot = snapshot;
      const clock = this.clock();
      this.history.ingest(snapshot, clock.monotonicMs, clock.wallMs, options);
      this.element("monitoring-status").textContent = snapshot.running ? "En vivo · cada segundo" : "Detenida · historial conservado";
      this.syncSelector();
      if (!this.enabled) return;
      this.createCharts();
      this.renderAdc();
      this.renderTraffic();
      this.renderStates();
    }

    syncSelector() {
      const nodes = this.snapshot.nodes;
      const key = JSON.stringify(nodes.map((node) => [node.device_id, node.ubicacion]));
      if (key !== this.selectorKey) {
        const options = nodes.map((node) => {
          const option = this.document.createElement("option");
          option.value = node.device_id;
          option.textContent = node.device_id;
          return option;
        });
        this.selector.replaceChildren(...options);
        this.selectorKey = key;
      }
      if (!nodes.some((node) => node.device_id === this.selected)) this.selected = nodes[0]?.device_id || "";
      this.selector.value = this.selected;
      this.selector.disabled = !nodes.length;
    }

    renderAdc() {
      if (!this.charts || !this.snapshot) return;
      const node = this.snapshot.nodes.find((item) => item.device_id === this.selected);
      const points = this.history.devices.get(this.selected)?.points || [];
      const mqtt = this.element("chart-mqtt");
      mqtt.textContent = !node ? "Sin dispositivo" : node.connected ? "MQTT conectado" : "MQTT desconectado";
      mqtt.className = `connection-state${node?.connected ? " is-connected" : ""}`;
      this.element("adc-empty").hidden = points.length > 0;
      this.element("adc-chart").hidden = !points.length;
      this.element("threshold-value").textContent = numberFormat.format(this.snapshot.alarm_threshold);
      this.element("adc-summary").textContent = points.length ? `${points.length} / 60 lecturas observadas` : "Sin lecturas de este dispositivo";
      this.element("adc-chart").setAttribute("aria-label", points.length ? `Lecturas ADC de ${this.selected}. Última: ${points.at(-1).y}. Umbral actual: ${this.snapshot.alarm_threshold}. ${mqtt.textContent}.` : "Sin lecturas ADC");
      const key = JSON.stringify([this.selected, points, this.snapshot.alarm_threshold]);
      if (key === this.adcKey) return;
      this.adcKey = key;
      const chart = this.charts.adc;
      chart.data.datasets[0].data = points;
      chart.data.datasets[0].pointBackgroundColor = points.map((point) => point.estado === "alarma" ? RED : point.estado === "alarma preventiva" ? "#b45309" : point.estado === "normal" ? GREEN : GRAY);
      const first = points[0]?.x;
      const last = points.at(-1)?.x;
      if (points.length) {
        const min = first === last ? first - 1000 : first;
        const max = first === last ? last + 1000 : last;
        chart.options.scales.x.min = min;
        chart.options.scales.x.max = max;
        chart.data.datasets[1].data = [{ x: min, y: this.snapshot.alarm_threshold }, { x: max, y: this.snapshot.alarm_threshold }];
      } else {
        chart.data.datasets[1].data = [];
        delete chart.options.scales.x.min;
        delete chart.options.scales.x.max;
      }
      chart.update("none");
    }

    renderTraffic() {
      const points = this.history.traffic;
      const hasData = points.some((point) => point.y !== null);
      this.element("traffic-empty").hidden = hasData;
      this.element("traffic-chart").hidden = !hasData;
      const rate = this.history.rate;
      this.element("traffic-rate").textContent = rate === null || !hasData ? "—" : `${numberFormat.format(rate)} msg/s`;
      this.element("traffic-chart").setAttribute("aria-label", hasData ? `Tráfico MQTT observado. ${this.element("traffic-rate").textContent}. Hasta 60 muestras.` : "Sin muestras de tráfico MQTT");
      const key = JSON.stringify(points);
      if (key === this.trafficKey) return;
      this.trafficKey = key;
      this.charts.traffic.data.datasets[0].data = points;
      this.charts.traffic.update("none");
    }

    renderStates() {
      const counts = this.history.states;
      const values = [counts.normal, counts.alarma, counts.alertaPreventiva || 0, counts.sinLectura];
      const total = values.reduce((sum, value) => sum + value, 0);
      this.element("states-normal").textContent = counts.normal;
      this.element("states-alarm").textContent = counts.alarma;
      this.element("states-preventive").textContent = counts.alertaPreventiva || 0;
      this.element("states-unread").textContent = counts.sinLectura;
      this.element("states-total").textContent = total;
      this.element("states-empty").hidden = total > 0;
      this.element("states-visual").hidden = total === 0;
      this.element("states-chart").setAttribute("aria-label", `${counts.normal} nodos normales, ${counts.alarma} en alarma, ${counts.alertaPreventiva || 0} en alerta preventiva y ${counts.sinLectura} sin lectura. Conectividad MQTT independiente.`);
      const key = JSON.stringify(values);
      if (key === this.statesKey) return;
      this.statesKey = key;
      this.charts.states.data.datasets[0].data = values;
      this.charts.states.update("none");
    }

    markOffline() {
      this.history.markGap();
      this.element("monitoring-status").textContent = "Sin conexión a la API · últimos datos";
      this.element("traffic-rate").textContent = "—";
    }
  }

  return { MonitoringCharts };
});
