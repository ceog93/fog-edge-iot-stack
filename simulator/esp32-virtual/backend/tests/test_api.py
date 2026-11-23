"""In-memory MQTT doubles only: these tests never open MQTT sockets."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import paho.mqtt.client as mqtt
import pytest
from fastapi.testclient import TestClient

from app import create_app
from config import Settings
from simulation import Simulation

SUCCESS = SimpleNamespace(is_failure=False)
FAILURE = SimpleNamespace(is_failure=True)


class FakeClient:
    def __init__(self, **options):
        self.options = options
        self.connect_available = True
        self.publish_rc = mqtt.MQTT_ERR_SUCCESS
        self.raise_publish = False
        self.start_rc = mqtt.MQTT_ERR_SUCCESS
        self.starts = 0
        self.stops = 0
        self.disconnects = 0
        self.publications = []
        self.credentials = None

    def reconnect_delay_set(self, **kwargs):
        self.reconnect_delays = kwargs

    def username_pw_set(self, username, password):
        self.credentials = (username, password)

    def connect_async(self, host, port, keepalive):
        self.connection = (host, port, keepalive)

    def loop_start(self):
        self.starts += 1
        if self.start_rc != mqtt.MQTT_ERR_SUCCESS:
            return self.start_rc
        if self.connect_available:
            self.on_connect(self, None, None, SUCCESS, None)
        else:
            self.on_connect_fail(self, None)
        return mqtt.MQTT_ERR_SUCCESS

    def disconnect(self):
        self.disconnects += 1
        self.on_disconnect(self, None, None, SUCCESS, None)

    def loop_stop(self):
        self.stops += 1

    def publish(self, topic, payload, qos, retain):
        if self.raise_publish:
            raise OSError("test socket error")
        if self.publish_rc != mqtt.MQTT_ERR_SUCCESS:
            return SimpleNamespace(rc=self.publish_rc)
        self.publications.append((topic, payload, qos, retain))
        self.on_publish(self, None, len(self.publications), SUCCESS, None)
        return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)


@pytest.fixture
def mqtt_factory():
    clients = []

    def factory(**options):
        client = FakeClient(**options)
        clients.append(client)
        return client

    return factory, clients


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("Condition not met within timeout")


def test_initial_ten_independent_nodes_and_api_docs(mqtt_factory):
    factory, clients = mqtt_factory
    with TestClient(create_app(Settings(), factory)) as api:
        response = api.get("/status")
        assert response.status_code == 200
        state = response.json()
        assert state["status"] == "stopped"
        assert state["running"] is False
        assert state["connected_nodes"] == 0
        assert state["node_count"] == len(clients) == 10
        assert state["interval_seconds"] == 2
        assert len({node["device_id"] for node in state["nodes"]}) == 10
        assert len({node["ubicacion"] for node in state["nodes"]}) == 10
        assert len({client.options["client_id"] for client in clients}) == 10
        assert all(client.starts == 0 for client in clients)
        assert api.get("/docs").status_code == 200
        assert api.get("/openapi.json").status_code == 200


def test_start_stop_restart_and_actual_publication_contract(mqtt_factory):
    factory, clients = mqtt_factory
    settings = Settings(node_count=3, interval_seconds=0.03, alarm_probability=1)
    with TestClient(create_app(settings, factory)) as api:
        assert api.post("/simulation/stop").json()["status"] == "stopped"
        assert api.post("/simulation/start").json()["running"] is True
        assert api.post("/simulation/start").json()["connected_nodes"] == 3
        wait_until(lambda: all(len(client.publications) >= 2 for client in clients))
        state = api.post("/simulation/stop").json()
        assert state["status"] == "stopped"
        assert state["connected_nodes"] == 0
        count = sum(len(client.publications) for client in clients)
        time.sleep(0.06)
        assert sum(len(client.publications) for client in clients) == count
        assert state["messages_sent"] == count
        for index, client in enumerate(clients, 1):
            assert client.starts == client.stops == client.disconnects == 1
            assert client.options["callback_api_version"] == mqtt.CallbackAPIVersion.VERSION2
            assert client.reconnect_delays == {"min_delay": 1, "max_delay": 30}
            for topic, payload, qos, retain in client.publications:
                body = json.loads(payload)
                assert topic == f"simulacion/esp32-virtual-{index:03d}/telemetria"
                assert topic == f"simulacion/{body['device_id']}/telemetria"
                assert body["simulado"] is True
                assert body["estado"] == "alarma"
                assert 1500 < body["adc"] <= 4095
                assert qos == 0
                assert retain is False
        assert api.post("/simulation/stop").status_code == 200
        assert api.post("/simulation/start").json()["running"] is True
        wait_until(lambda: sum(len(client.publications) for client in clients) > count)
    assert all(client.stops == 2 for client in clients)  # lifespan shutdown


def test_broker_unavailable_does_not_block_api_and_can_recover(mqtt_factory):
    factory, clients = mqtt_factory
    app = create_app(Settings(node_count=1, interval_seconds=0.02), factory)
    with TestClient(app) as api:
        client = clients[0]
        client.connect_available = False
        state = api.post("/simulation/start").json()
        assert state["running"] is True
        assert state["connected_nodes"] == 0
        wait_until(lambda: api.get("/status").json()["nodes"][0]["skipped_disconnected"] > 0)
        assert client.publications == []
        client.on_connect(client, None, None, FAILURE, None)
        assert api.get("/status").json()["errors"] == 2
        client.on_connect(client, None, None, SUCCESS, None)
        wait_until(lambda: len(client.publications) > 0)
        client.on_disconnect(client, None, None, FAILURE, None)
        assert api.get("/status").json()["connected_nodes"] == 0
        client.on_connect(client, None, None, SUCCESS, None)
        assert api.get("/status").json()["connected_nodes"] == 1
        assert api.post("/simulation/stop").json()["status"] == "stopped"


def test_publication_failures_are_reported_and_do_not_kill_the_loop(mqtt_factory):
    factory, clients = mqtt_factory
    with TestClient(create_app(Settings(node_count=1, interval_seconds=0.02), factory)) as api:
        clients[0].publish_rc = mqtt.MQTT_ERR_NO_CONN
        api.post("/simulation/start")
        wait_until(lambda: api.get("/status").json()["errors"] > 0)
        assert api.get("/status").json()["messages_sent"] == 0
        clients[0].raise_publish = True
        wait_until(lambda: "test socket error" in (api.get("/status").json()["nodes"][0]["last_error"] or ""))
        clients[0].raise_publish = False
        clients[0].publish_rc = mqtt.MQTT_ERR_SUCCESS
        wait_until(lambda: api.get("/status").json()["messages_sent"] > 0)
        assert api.get("/status").json()["running"] is True


def test_start_failure_cleans_up_partial_clients_and_allows_retry(mqtt_factory):
    factory, clients = mqtt_factory
    with TestClient(create_app(Settings(node_count=2), factory)) as api:
        clients[1].start_rc = mqtt.MQTT_ERR_INVAL
        assert api.post("/simulation/start").status_code == 503
        assert api.get("/status").json()["status"] == "stopped"
        assert all(client.stops == 1 for client in clients)
        clients[1].start_rc = mqtt.MQTT_ERR_SUCCESS
        assert api.post("/simulation/start").json()["connected_nodes"] == 2


def test_credentials_passed_to_clients_but_never_returned_by_api(mqtt_factory):
    factory, clients = mqtt_factory
    settings = Settings(node_count=1, mqtt_username="tester", mqtt_password="private-test-value")
    with TestClient(create_app(settings, factory)) as api:
        assert clients[0].credentials == ("tester", "private-test-value")
        assert "private-test-value" not in api.get("/status").text


def test_slow_mqtt_close_does_not_block_status_endpoint(mqtt_factory):
    factory, clients = mqtt_factory
    entered = threading.Event()
    release = threading.Event()
    with TestClient(create_app(Settings(node_count=1), factory)) as api:
        api.post("/simulation/start")
        original_stop = clients[0].loop_stop

        def delayed_stop():
            entered.set()
            assert release.wait(3)
            original_stop()

        clients[0].loop_stop = delayed_stop
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(api.post, "/simulation/stop")
            try:
                assert entered.wait(3)
                response = api.get("/status")
                assert response.status_code == 200
                assert response.json()["status"] == "stopping"
            finally:
                release.set()
            assert pending.result(timeout=3).json()["status"] == "stopped"


def test_real_paho_clients_are_independent_without_connecting():
    # Exercises Paho construction/callback API without requiring a broker.
    simulation = Simulation(Settings(node_count=2))
    assert simulation.nodes[0].client is not simulation.nodes[1].client
    assert simulation.snapshot()["connected_nodes"] == 0


def test_real_paho_network_threads_close_and_restart_after_connection_failure():
    # No broker or network access: real Paho threads, mocked socket creation.
    with patch("paho.mqtt.client.socket.create_connection", side_effect=ConnectionRefusedError("test offline")):
        app = create_app(Settings(node_count=2, interval_seconds=0.02))
        with TestClient(app) as api:
            for _ in range(2):
                baseline = api.get("/status").json()["errors"]
                assert api.post("/simulation/start").json()["running"] is True
                wait_until(lambda: api.get("/status").json()["errors"] >= baseline + 2)
                assert api.get("/status").json()["connected_nodes"] == 0
                assert api.post("/simulation/stop").json()["status"] == "stopped"
                for node in app.state.simulation.nodes:
                    # Paho clears its thread reference when its network loop ends.
                    assert node.client._thread is None


def test_configure_start_and_polling_preserve_backend_state(mqtt_factory):
    factory, clients = mqtt_factory
    app = create_app(Settings(node_count=2, interval_seconds=0.02), factory)
    with TestClient(app) as api:
        simulation = app.state.simulation
        original_nodes = list(simulation.nodes)
        parameters = {"node_count": 3, "interval_seconds": 0.03, "alarm_threshold": 2500, "alarm_probability": 1}
        state = api.post("/simulation/start", json=parameters).json()
        assert state["connected_nodes"] == 3
        for key, value in parameters.items():
            assert state[key] == value
        wait_until(lambda: all(client.publications for client in clients))
        for client in clients:
            payload = json.loads(client.publications[-1][1])
            assert 2500 < payload["adc"] <= 4095
            assert payload["estado"] == "alarma"
        for _ in range(3):
            assert api.get("/status").json()["running"] is True
        assert app.state.simulation is simulation
        assert simulation.nodes[:2] == original_nodes
        assert len(clients) == 3
        stopped = api.post("/simulation/stop").json()
        for _ in range(3):
            assert api.get("/status").json() == stopped
        assert api.post("/simulation/start").json()["alarm_threshold"] == 2500
        assert len(clients) == 3


@pytest.mark.parametrize("parameters", [
    {"node_count": 0}, {"node_count": 101}, {"node_count": 1.5},
    {"node_count": True}, {"node_count": "10"},
    {"interval_seconds": 0}, {"interval_seconds": -1}, {"interval_seconds": 3601},
    {"interval_seconds": True}, {"alarm_threshold": -1}, {"alarm_threshold": 4095},
    {"alarm_threshold": 2.5}, {"alarm_probability": -0.01}, {"alarm_probability": 1.01},
    {"alarm_probability": True}, {"node_count": None},
    {"mqtt_host": "physical-broker"}, {"unknown": 42},
])
def test_start_rejects_invalid_configuration_without_mutation(mqtt_factory, parameters):
    factory, clients = mqtt_factory
    with TestClient(create_app(Settings(node_count=2), factory)) as api:
        before = api.get("/status").json()
        response = api.post("/simulation/start", json=parameters)
        assert response.status_code == 422
        assert api.get("/status").json() == before
        assert len(clients) == 2
        assert all(client.starts == 0 for client in clients)


def test_running_configuration_is_immutable_but_identical_start_is_idempotent(mqtt_factory):
    factory, clients = mqtt_factory
    with TestClient(create_app(Settings(node_count=2, interval_seconds=0.03), factory)) as api:
        assert api.post("/simulation/start").status_code == 200
        for parameters in [
            {"node_count": 3}, {"interval_seconds": 1},
            {"alarm_threshold": 800}, {"alarm_probability": 0.5},
        ]:
            assert api.post("/simulation/start", json=parameters).status_code == 409
        state = api.post("/simulation/start", json={"node_count": 2, "interval_seconds": 0.03}).json()
        assert state["node_count"] == 2
        assert state["alarm_threshold"] == 1500
        assert state["alarm_probability"] == 0.1
        assert all(client.starts == 1 for client in clients)


def test_resize_preserves_retired_node_history_and_partial_update(mqtt_factory):
    factory, clients = mqtt_factory
    app = create_app(Settings(node_count=2, interval_seconds=0.02), factory)
    with TestClient(app) as api:
        api.post("/simulation/start")
        wait_until(lambda: all(client.publications for client in clients))
        stopped = api.post("/simulation/stop").json()
        ids = [node["client_id"] for node in stopped["nodes"]]
        first_objects = list(app.state.simulation.nodes)
        state = api.post("/simulation/start", json={"node_count": 1}).json()
        assert state["messages_sent"] >= stopped["messages_sent"]
        api.post("/simulation/stop")
        restored = api.post("/simulation/start", json={"node_count": 3}).json()
        assert [node["client_id"] for node in restored["nodes"][:2]] == ids
        assert app.state.simulation.nodes[:2] == first_objects
        assert restored["nodes"][1]["messages_sent"] >= stopped["nodes"][1]["messages_sent"]
        assert restored["interval_seconds"] == 0.02
        assert len(clients) == 3


@pytest.mark.parametrize("action,expected_state", [("start", "starting"), ("stop", "stopping")])
def test_configuration_conflict_during_transition(mqtt_factory, action, expected_state):
    factory, clients = mqtt_factory
    entered = threading.Event()
    release = threading.Event()
    with TestClient(create_app(Settings(node_count=1), factory)) as api:
        if action == "stop":
            api.post("/simulation/start")
        method_name = "loop_start" if action == "start" else "loop_stop"
        original = getattr(clients[0], method_name)

        def delayed_method():
            entered.set()
            assert release.wait(3)
            return original()

        setattr(clients[0], method_name, delayed_method)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(api.post, f"/simulation/{action}")
            try:
                assert entered.wait(3)
                assert api.get("/status").json()["status"] == expected_state
                assert api.post("/simulation/start", json={"node_count": 3}).status_code == 409
            finally:
                release.set()
            assert pending.result(timeout=3).status_code == 200


@pytest.mark.parametrize("body", ['{"interval_seconds":1e309}', '{"alarm_probability":1e309}', '{'])
def test_invalid_json_or_overflowing_numbers_return_validation_error(mqtt_factory, body):
    factory, _ = mqtt_factory
    with TestClient(create_app(Settings(node_count=1), factory)) as api:
        response = api.post("/simulation/start", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert api.get("/status").json()["status"] == "stopped"
