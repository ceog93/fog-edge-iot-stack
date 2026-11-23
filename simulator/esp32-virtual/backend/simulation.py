"""Independent MQTT clients with a nonblocking simulation lifecycle."""

import asyncio
import json
import logging
import random
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace

import paho.mqtt.client as mqtt

from config import Settings
from telemetry import generate_adc, make_reading

logger = logging.getLogger("esp32_simulator")


class ConfigurationConflict(ValueError):
    """A caller tried to change an active simulation."""


class VirtualNode:
    def __init__(self, index: int, settings: Settings, client_factory: Callable):
        self.settings = settings
        self.device_id = f"{settings.device_prefix}-{index:03d}"
        self.location = f"{settings.location_prefix}-{index:03d}"
        # Unique even if a second simulator uses the same device prefix.
        self.client_id = f"sim-{uuid.uuid4().hex}"
        self.topic = f"simulacion/{self.device_id}/telemetria"
        self.availability_topic = f"simulacion/{self.device_id}/estado"
        self.availability = "desconectado"
        self._availability_mids = set()
        self._rng = random.Random()
        self._lock = threading.RLock()
        self._active = False
        self._connected = False
        self.manual_alarm = False
        self.generated = 0
        self.accepted = 0
        self.sent = 0
        self.skipped = 0
        self.errors = 0
        self.last_error = None
        self.last_reading = None
        self.client = client_factory(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
            reconnect_on_failure=True,
        )
        self.client.connect_timeout = 3.0
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

    def _error(self, message: str):
        with self._lock:
            self.errors += 1
            self.last_error = message
        logger.error("node=%s %s", self.device_id, message)

    def _publish_availability(self, status: str):
        with self._lock:
            self.availability = status
        info = self.client.publish(
            self.availability_topic,
            payload=status,
            qos=1,
            retain=True,
        )
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            with self._lock:
                self._availability_mids.add(info.mid)
            logger.info("Disponibilidad MQTT aceptada node=%s topic=%s payload=%s", self.device_id, self.availability_topic, status)
        else:
            self._error(f"Publicación de disponibilidad rechazada: {info.rc}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            with self._lock:
                self._connected = False
            self._error(f"Conexión MQTT rechazada: {reason_code}")
            return
        with self._lock:
            self._connected = self._active
            self.last_error = None
        self._publish_availability("conectado")
        logger.info("MQTT conectado node=%s client_id=%s", self.device_id, self.client_id)

    def _on_connect_fail(self, client, userdata):
        with self._lock:
            self._connected = False
        self._error("Conexión MQTT fallida; se reintentará con espera de 1 a 30 s")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        with self._lock:
            self._connected = False
            active = self._active
        if active:
            self._error(f"MQTT desconectado: {reason_code}; reconexión automática")
        else:
            logger.info("MQTT desconectado node=%s", self.device_id)

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        if reason_code.is_failure:
            self._error(f"Envío MQTT fallido: {reason_code}")
            return
        with self._lock:
            if mid in self._availability_mids:
                self._availability_mids.remove(mid)
                logger.info("Disponibilidad MQTT confirmada node=%s mid=%s", self.device_id, mid)
                return
            self.sent += 1
        logger.info("MQTT enviado node=%s mid=%s", self.device_id, mid)

    def start(self):
        with self._lock:
            self._active = True
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        result = self.client.loop_start()
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"No se pudo iniciar cliente MQTT: {result}")

    def stop(self):
        with self._lock:
            self._active = False
        try:
            self._publish_availability("desconectado")
            self.client.disconnect()
        finally:
            try:
                self.client.loop_stop()
            finally:
                with self._lock:
                    self._connected = False

    def set_manual_alarm(self, enabled: bool):
        with self._lock:
            self.manual_alarm = enabled

    def publish_reading(self):
        try:
            with self._lock:
                manual_alarm = self.manual_alarm
            reading = make_reading(
                self.device_id, self.location,
                generate_adc(
                    self.settings.alarm_probability,
                    self._rng,
                    self.settings.alarm_threshold,
                    manual_alarm,
                ),
                self.settings.alarm_threshold,
            )
            with self._lock:
                self.generated += 1
                self.last_reading = reading
                connected = self._connected
            if not connected:
                with self._lock:
                    self.skipped += 1
                return
            payload = json.dumps(reading, ensure_ascii=False, separators=(",", ":"))
            # Fixed topic, QoS 0, no retention, no subscriptions or actuator commands.
            info = self.client.publish(self.topic, payload, qos=0, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                self._error(f"Publicación MQTT rechazada por el cliente: {info.rc}")
                return
            with self._lock:
                self.accepted += 1
            logger.info("MQTT aceptado node=%s topic=%s payload=%s", self.device_id, self.topic, payload)
        except Exception as exc:
            self._error(f"Error generando/publicando lectura: {exc}")

    def snapshot(self):
        with self._lock:
            return {
                "device_id": self.device_id,
                "ubicacion": self.location,
                "client_id": self.client_id,
                "topic": self.topic,
                "availability_topic": self.availability_topic,
                "availability": self.availability,
                "connected": self._connected,
                "manual_alarm": self.manual_alarm,
                "generated": self.generated,
                "messages_accepted": self.accepted,
                "messages_sent": self.sent,
                "skipped_disconnected": self.skipped,
                "errors": self.errors,
                "last_error": self.last_error,
                "last_reading": self.last_reading,
            }


class Simulation:
    def __init__(self, settings: Settings, client_factory: Callable = mqtt.Client):
        self.settings = settings
        self.nodes = [VirtualNode(i, settings, client_factory) for i in range(1, settings.node_count + 1)]
        self._node_pool = list(self.nodes)
        self._client_factory = client_factory
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._task = None
        self.state = "stopped"

    async def _close_clients(self):
        results = await asyncio.gather(
            *(asyncio.to_thread(node.stop) for node in self.nodes), return_exceptions=True,
        )
        for node, result in zip(self.nodes, results):
            if isinstance(result, BaseException):
                node._error(f"Error cerrando cliente MQTT: {result}")

    def _check_configuration(self, parameters):
        if self.state in ("starting", "stopping"):
            raise ConfigurationConflict("La simulación está cambiando de estado. Espere antes de iniciar.")
        if self.state == "running" and any(
            getattr(self.settings, name) != value for name, value in parameters.items()
        ):
            raise ConfigurationConflict("Detenga la simulación antes de cambiar la configuración.")

    def _configure(self, parameters):
        settings = replace(self.settings, **parameters)
        # Create additions before mutating current state. Retired nodes stay in the
        # pool so resizing never erases their identities, readings or counters.
        additions = [
            VirtualNode(i, settings, self._client_factory)
            for i in range(len(self._node_pool) + 1, settings.node_count + 1)
        ]
        self._node_pool.extend(additions)
        for node in self._node_pool:
            node.settings = settings
        self.settings = settings
        self.nodes = self._node_pool[:settings.node_count]

    async def start(self, parameters: dict | None = None):
        parameters = parameters or {}
        self._check_configuration(parameters)
        async with self._lock:
            self._check_configuration(parameters)
            if self.state == "running":
                return self.snapshot()
            self._configure(parameters)
            self.state = "starting"
            self._stop_event.clear()
            try:
                # connect_async + Paho network threads: no DNS/socket waits on the API loop.
                for node in self.nodes:
                    await asyncio.to_thread(node.start)
                await asyncio.sleep(0.1)
                for node in self.nodes:
                    if node._connected:
                        node._publish_availability("conectado")
            except Exception:
                await self._close_clients()
                self.state = "stopped"
                raise
            self.state = "running"
            self._task = asyncio.create_task(self._run(), name="esp32-telemetry")
            logger.info("Simulación iniciada nodes=%s interval=%s", len(self.nodes), self.settings.interval_seconds)
            return self.snapshot()

    def _publish_tick(self):
        for node in self.nodes:
            node.publish_reading()

    async def _run(self):
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            started = loop.time()
            await asyncio.to_thread(self._publish_tick)
            delay = max(0.001, self.settings.interval_seconds - (loop.time() - started))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        async with self._lock:
            if self.state == "stopped":
                return self.snapshot()
            self.state = "stopping"
            self._stop_event.set()
            try:
                # Finish any tick before disconnecting; don't abandon a publishing thread.
                if self._task is not None:
                    await self._task
            finally:
                await self._close_clients()
                self._task = None
                self.state = "stopped"
            logger.info("Simulación detenida")
            return self.snapshot()

    def snapshot(self):
        history = [node.snapshot() for node in self._node_pool]
        nodes = history[:self.settings.node_count]
        return {
            "status": self.state,
            "running": self.state == "running",
            "broker": {"host": self.settings.mqtt_host, "port": self.settings.mqtt_port},
            "node_count": len(nodes),
            "connected_nodes": sum(node["connected"] for node in nodes),
            "interval_seconds": self.settings.interval_seconds,
            "alarm_probability": self.settings.alarm_probability,
            "alarm_threshold": self.settings.alarm_threshold,
            "messages_sent": sum(node["messages_sent"] for node in history),
            "errors": sum(node["errors"] for node in history),
            "nodes": nodes,
        }
