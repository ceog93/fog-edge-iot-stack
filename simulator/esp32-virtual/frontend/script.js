"use strict";

(() => {
  const API_BASE = "/api";
  const byId = (id) => document.getElementById(id);
  const form = byId("simulation-form");
  const fields = byId("configuration-fields");
  const startButton = byId("start-button");
  const stopButton = byId("stop-button");
  const inputs = {
    node_count: byId("node-count"),
    interval_seconds: byId("interval"),
    alarm_threshold: byId("threshold"),
    alarm_probability: byId("probability"),
  };
  const formatNumber = new Intl.NumberFormat("es");
  const formatTime = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const rowCache = new Map();
  let rowOrder = "";
  let latest = null;
  let online = false;
  let busy = null;
  let dirty = false;
  let pollInFlight = false;
  let actionVersion = 0;
  let monitoring = null;

  function monitoringError() {
    const notice = byId("charts-error");
    notice.textContent = "No se pudo inicializar el monitoreo. La configuración y la tabla siguen disponibles; recarga el panel para reintentar.";
    notice.hidden = false;
    monitoring = null;
  }

  try {
    monitoring = new window.ESP32Charts.MonitoringCharts(document, window.Chart);
  } catch {
    monitoringError();
  }

  class ApiError extends Error {
    constructor(message, status = 0) {
      super(message);
      this.status = status;
    }
  }

  function feedback(message, isError = false) {
    const element = byId("action-feedback");
    element.textContent = message;
    element.classList.toggle("is-error", isError);
    element.hidden = !message;
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.method === "POST" ? 15000 : 4000);
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        ...options,
        signal: controller.signal,
        cache: "no-store",
        headers: { Accept: "application/json", ...options.headers },
      });
      let body;
      try {
        body = await response.json();
      } catch {
        const message = response.ok
          ? "La API devolvió una respuesta no válida."
          : `No se pudo comunicar con el backend (HTTP ${response.status}).`;
        throw new ApiError(message, response.status);
      }
      if (!response.ok) {
        let detail = typeof body.detail === "string" ? body.detail : "";
        if (response.status === 422) {
          detail = "Revisa los parámetros: nodos de 1 a 100, intervalo mayor que 0 y hasta 3600 s, umbral de 0 a 4094 y probabilidad de 0 a 100 %.";
        }
        throw new ApiError(detail || `No se pudo completar la solicitud (HTTP ${response.status}).`, response.status);
      }
      return body;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error.name === "AbortError") {
        throw new ApiError("La API tardó demasiado en responder. El estado se comprobará automáticamente.");
      }
      throw new ApiError("No se pudo conectar con la API. Comprueba que el backend esté disponible.");
    } finally {
      clearTimeout(timer);
    }
  }

  function setBadge(id, text, variant = "") {
    const element = byId(id);
    element.textContent = text;
    element.className = `badge${variant ? ` is-${variant}` : ""}`;
  }

  function updateControls() {
    const stopped = latest?.status === "stopped";
    const running = latest?.status === "running";
    fields.disabled = !online || !stopped || Boolean(busy);
    startButton.disabled = !online || !stopped || Boolean(busy);
    stopButton.disabled = !online || !running || Boolean(busy);
    startButton.textContent = busy === "start" ? "Iniciando…" : "▶  Iniciar simulación";
    stopButton.textContent = busy === "stop" ? "Deteniendo…" : "■  Detener";
    form.setAttribute("aria-busy", String(Boolean(busy)));
    byId("config-mode").textContent = !online ? "Sin conexión a la API" : busy ? "Procesando" : stopped ? "Editable" : "Bloqueada";
    byId("config-mode").classList.toggle("is-active", online && stopped && !busy);
    byId("config-help").textContent = !online
      ? "Los controles estarán disponibles cuando la API responda."
      : !stopped
        ? "Detén la simulación para modificar sus parámetros."
        : dirty
          ? "Cambios pendientes. Se aplicarán al iniciar la simulación."
          : "Los parámetros se aplican al iniciar. Los contadores se conservan.";
  }

  function syncInputs(data) {
    for (const [name, input] of Object.entries(inputs)) {
      input.value = name === "alarm_probability" ? Number((data[name] * 100).toFixed(8)) : data[name];
      input.setCustomValidity("");
    }
    dirty = false;
  }

  function updateRows(nodes) {
    const currentIds = new Set(nodes.map((node) => node.device_id));
    for (const id of rowCache.keys()) {
      if (!currentIds.has(id)) rowCache.delete(id);
    }
    for (const node of nodes) {
      let row = rowCache.get(node.device_id);
      if (!row) {
        const element = byId("device-row").content.firstElementChild.cloneNode(true);
        row = {
          element,
          id: element.querySelector(".device-id"),
          location: element.querySelector(".device-location"),
          adc: element.querySelector(".device-adc"),
          reading: element.querySelector(".reading-status"),
          connection: element.querySelector(".connection-state"),
        };
        rowCache.set(node.device_id, row);
      }
      row.id.textContent = node.device_id;
      row.location.textContent = node.ubicacion;
      row.adc.textContent = node.last_reading ? formatNumber.format(node.last_reading.adc) : "—";
      row.adc.title = node.last_reading ? `Generada: ${node.last_reading.timestamp}` : "Aún no hay lecturas";
      const readingState = node.last_reading?.estado;
      row.reading.textContent = readingState === "alarma" ? "Alarma" : readingState === "normal" ? "Normal" : "Sin lectura";
      row.reading.className = `badge reading-status${readingState === "alarma" ? " is-danger" : readingState === "normal" ? " is-success" : ""}`;
      row.connection.textContent = node.connected ? "Conectado" : "Desconectado";
      row.connection.className = `connection-state${node.connected ? " is-connected" : ""}`;
      row.connection.title = node.last_error || "";
    }
    const newOrder = JSON.stringify(nodes.map((node) => node.device_id));
    if (newOrder !== rowOrder) {
      byId("devices-body").replaceChildren(...nodes.map((node) => rowCache.get(node.device_id).element));
      rowOrder = newOrder;
    }
  }

  function render(data, forceSync = false) {
    if (!Array.isArray(data.nodes) || !["stopped", "starting", "running", "stopping"].includes(data.status)) {
      throw new ApiError("La API devolvió un estado no reconocido.");
    }
    latest = data;
    online = true;
    byId("connection-alert").hidden = true;
    const mqttNotice = byId("mqtt-notice");
    const missingConnections = data.status === "running" && data.connected_nodes < data.node_count;
    const mqttMessage = data.connected_nodes === 0
      ? "El generador está activo, pero aún no hay conexiones MQTT. El backend reintentará automáticamente; comprueba el broker si la situación persiste."
      : "Algunos nodos están desconectados del broker. El backend reintentará sus conexiones automáticamente.";
    if (mqttNotice.textContent !== mqttMessage) mqttNotice.textContent = mqttMessage;
    mqttNotice.hidden = !missingConnections;
    document.body.classList.remove("is-stale");
    const labels = { stopped: "Detenida", starting: "Iniciando", running: "En ejecución", stopping: "Deteniendo" };
    setBadge("run-status", labels[data.status], data.status === "stopped" ? "" : "active");
    if (data.connected_nodes === data.node_count) {
      setBadge("broker-status", "Conectado", "active");
    } else if (data.connected_nodes > 0) {
      setBadge("broker-status", `Parcial · ${data.connected_nodes}/${data.node_count}`);
    } else {
      setBadge("broker-status", data.status === "stopped" ? "Sin conexiones" : "Sin conexión");
    }
    byId("connected-count").textContent = formatNumber.format(data.connected_nodes);
    byId("total-count").textContent = `/ ${formatNumber.format(data.node_count)}`;
    byId("sent-count").textContent = formatNumber.format(data.messages_sent);
    byId("error-count").textContent = formatNumber.format(data.errors);
    byId("error-count").classList.toggle("has-errors", data.errors > 0);
    byId("device-count").textContent = data.node_count;
    byId("last-update").textContent = `Sincronizado a las ${formatTime.format(new Date())}`;
    if (forceSync || !dirty || data.status !== "stopped") syncInputs(data);
    updateRows(data.nodes);
    updateControls();
    if (monitoring) {
      try {
        // Mutation responses refresh the UI; traffic samples use GET polls only.
        monitoring.update(data, { sampleTraffic: !forceSync });
      } catch {
        monitoringError();
      }
    }
  }

  function showOffline(error) {
    online = false;
    monitoring?.markOffline();
    byId("mqtt-notice").hidden = true;
    const alert = byId("connection-alert");
    const message = `${error.message} Se reintentará automáticamente.${latest ? " Los datos visibles corresponden a la última sincronización." : ""}`;
    if (alert.textContent !== message) alert.textContent = message;
    alert.hidden = false;
    document.body.classList.add("is-stale");
    setBadge("run-status", "Sin datos actuales");
    setBadge("broker-status", "Sin datos");
    updateControls();
  }

  async function refreshStatus() {
    if (pollInFlight || busy) return;
    pollInFlight = true;
    const version = actionVersion;
    try {
      const data = await request("/status");
      if (version === actionVersion && !busy) render(data);
    } catch (error) {
      if (version === actionVersion && !busy) showOffline(error);
    } finally {
      pollInFlight = false;
    }
  }

  async function runAction(action, parameters) {
    if (busy || !online) return;
    busy = action;
    actionVersion += 1; // Ignore a poll that started before this mutation.
    feedback("");
    updateControls();
    try {
      const options = { method: "POST" };
      if (parameters) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(parameters);
      }
      const data = await request(`/simulation/${action}`, options);
      render(data, true);
      feedback(action === "start" ? "Simulación iniciada. Las conexiones MQTT se actualizarán automáticamente." : "Simulación detenida. Las últimas lecturas y los contadores se conservan.");
    } catch (error) {
      feedback(error.message, true);
      if (!error.status || error.status >= 500) showOffline(error);
    } finally {
      busy = null;
      updateControls();
      await refreshStatus();
    }
  }

  form.addEventListener("input", () => {
    dirty = true;
    inputs.interval_seconds.setCustomValidity("");
    feedback("");
    updateControls();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!online || busy || latest?.status !== "stopped") return;
    inputs.interval_seconds.setCustomValidity(Number(inputs.interval_seconds.value) > 0 ? "" : "El intervalo debe ser mayor que cero.");
    if (!form.reportValidity()) return;
    const parameters = Object.fromEntries(Object.entries(inputs).map(([name, input]) => [name, Number(input.value)]));
    parameters.alarm_probability /= 100;
    runAction("start", parameters);
  });
  stopButton.addEventListener("click", () => {
    if (latest?.status === "running") runAction("stop");
  });

  // Loading or refreshing this page only reads state. Never auto-start or stop.
  refreshStatus();
  setInterval(refreshStatus, 1000);
})();
