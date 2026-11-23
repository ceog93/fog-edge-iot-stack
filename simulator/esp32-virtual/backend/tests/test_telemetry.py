import json
import random
from datetime import datetime, timedelta

import pytest

from telemetry import evaluate_state, generate_adc, make_reading


@pytest.mark.parametrize("adc,expected", [(0, "normal"), (1499, "normal"), (1500, "normal"), (1501, "alarma"), (4095, "alarma")])
def test_strict_emergency_threshold(adc, expected):
    assert evaluate_state(adc) == expected


@pytest.mark.parametrize("adc", [-1, 4096, 1.5, True])
def test_invalid_adc(adc):
    with pytest.raises(ValueError):
        evaluate_state(adc)


@pytest.mark.parametrize("probability,low,high", [(0, 0, 1500), (1, 1501, 4095), (0.5, 0, 4095)])
def test_adc_generation_range_and_alarm_modes(probability, low, high):
    rng = random.Random(42)
    values = [generate_adc(probability, rng) for _ in range(1000)]
    assert all(type(value) is int and low <= value <= high for value in values)
    if probability == 0.5:
        assert any(value <= 1500 for value in values)
        assert any(value > 1500 for value in values)


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan")])
def test_invalid_alarm_probability(probability):
    with pytest.raises(ValueError):
        generate_adc(probability, random.Random(1))


def test_json_contract_and_utc_timestamp():
    before = datetime.now().astimezone()
    payload = json.loads(json.dumps(make_reading("esp32-virtual-001", "laboratorio-001", 1501)))
    after = datetime.now().astimezone()
    assert set(payload) == {"device_id", "ubicacion", "adc", "estado", "timestamp", "simulado"}
    assert payload["device_id"] == "esp32-virtual-001"
    assert payload["ubicacion"] == "laboratorio-001"
    assert payload["adc"] == 1501
    assert payload["estado"] == "alarma"
    assert payload["simulado"] is True
    assert payload["timestamp"].endswith("Z")
    timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
    assert timestamp.utcoffset() == timedelta(0)
    assert before <= timestamp <= after


@pytest.mark.parametrize("threshold", [0, 2500, 4094])
def test_custom_threshold_generation_and_json_consistency(threshold):
    rng = random.Random(25)
    for probability in (0, 1):
        for _ in range(50):
            adc = generate_adc(probability, rng, threshold)
            payload = make_reading("test-001", "sala", adc, threshold)
            assert 0 <= adc <= 4095
            assert (adc > threshold) == bool(probability)
            assert payload["estado"] == ("alarma" if probability else "normal")
    assert evaluate_state(threshold, threshold) == "normal"
    assert evaluate_state(threshold + 1, threshold) == "alarma"


@pytest.mark.parametrize("threshold", [-1, 4095, True, 1.5])
def test_invalid_custom_threshold(threshold):
    with pytest.raises(ValueError):
        generate_adc(0.5, random.Random(1), threshold)
