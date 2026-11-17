import pytest

from config import Settings


@pytest.mark.parametrize("options", [
    {"mqtt_host": " "}, {"mqtt_port": 0}, {"mqtt_port": 65536},
    {"mqtt_password": "secret"}, {"node_count": 0},
    {"interval_seconds": 0}, {"interval_seconds": -1},
    {"interval_seconds": float("inf")}, {"interval_seconds": float("nan")},
    {"alarm_probability": -0.1}, {"alarm_probability": 1.1},
    {"alarm_probability": float("nan")}, {"location_prefix": " "},
    {"device_prefix": "physical/commands"}, {"device_prefix": "#"},
    {"node_count": 101}, {"interval_seconds": 3601},
    {"alarm_threshold": -1}, {"alarm_threshold": 4095}, {"alarm_threshold": True},
])
def test_invalid_configuration_fails_fast(options):
    with pytest.raises(ValueError):
        Settings(**options)


def test_environment_configuration(monkeypatch):
    values = {
        "MQTT_HOST": "test-broker", "MQTT_PORT": "21883",
        "MQTT_USERNAME": "tester", "MQTT_PASSWORD": "secret-test-value",
        "SIM_NODE_COUNT": "3", "SIM_INTERVAL_SECONDS": "0.25",
        "SIM_ALARM_PROBABILITY": "1", "SIM_DEVICE_PREFIX": "test-batch",
        "SIM_LOCATION_PREFIX": "sala",
        "SIM_ALARM_THRESHOLD": "2400",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.mqtt_host == "test-broker"
    assert settings.mqtt_port == 21883
    assert settings.mqtt_username == "tester"
    assert settings.mqtt_password == "secret-test-value"
    assert settings.node_count == 3
    assert settings.interval_seconds == 0.25
    assert settings.alarm_probability == 1
    assert settings.alarm_threshold == 2400
    assert settings.device_prefix == "test-batch"
    assert settings.location_prefix == "sala"
    assert "secret-test-value" not in repr(settings)
