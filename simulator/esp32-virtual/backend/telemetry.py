"""Pure telemetry generation, shared by the publisher and broker-free tests."""

import random
from datetime import datetime, timezone

ADC_MAX = 4095
ALARM_THRESHOLD = 1500


def validate_threshold(threshold: int):
    if type(threshold) is not int or not 0 <= threshold < ADC_MAX:
        raise ValueError("threshold debe ser un entero entre 0 y 4094")


def evaluate_state(adc: int, threshold: int = ALARM_THRESHOLD) -> str:
    validate_threshold(threshold)
    if type(adc) is not int or not 0 <= adc <= ADC_MAX:
        raise ValueError("adc debe ser un entero entre 0 y 4095")
    return "alarma" if adc > threshold else "normal"


def generate_adc(alarm_probability: float, rng: random.Random, threshold: int = ALARM_THRESHOLD) -> int:
    validate_threshold(threshold)
    if not 0 <= alarm_probability <= 1:
        raise ValueError("alarm_probability debe estar entre 0 y 1")
    if rng.random() < alarm_probability:
        return rng.randint(threshold + 1, ADC_MAX)
    return rng.randint(0, threshold)


def make_reading(device_id: str, location: str, adc: int, threshold: int = ALARM_THRESHOLD) -> dict:
    return {
        "device_id": device_id,
        "ubicacion": location,
        "adc": adc,
        "estado": evaluate_state(adc, threshold),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "simulado": True,
    }
