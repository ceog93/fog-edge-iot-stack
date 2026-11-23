"""Pure telemetry generation, shared by the publisher and broker-free tests."""

import random
from datetime import datetime, timezone

ADC_MAX = 4095
ALARM_THRESHOLD = 1500
ALARM_ADC_MIN = 3000
BASELINE_MIN = 50
BASELINE_MAX = 200


def validate_threshold(threshold: int):
    if type(threshold) is not int or not 0 <= threshold < ADC_MAX:
        raise ValueError("threshold debe ser un entero entre 0 y 4094")


def evaluate_state(adc: int, threshold: int = ALARM_THRESHOLD) -> str:
    validate_threshold(threshold)
    if type(adc) is not int or not 0 <= adc <= ADC_MAX:
        raise ValueError("adc debe ser un entero entre 0 y 4095")
    return "alarma" if adc > threshold else "normal"


def generate_adc(alarm_probability: float, rng: random.Random, threshold: int = ALARM_THRESHOLD, manual_alarm: bool = False) -> int:
    validate_threshold(threshold)
    if not 0 <= alarm_probability <= 1:
        raise ValueError("alarm_probability debe estar entre 0 y 1")
    if manual_alarm or rng.random() < alarm_probability:
        return rng.randint(ALARM_ADC_MIN, ADC_MAX)

    normal_max = min(BASELINE_MAX, threshold)
    if normal_max < BASELINE_MIN:
        return rng.randint(0, threshold)
    return rng.randint(BASELINE_MIN, normal_max)


def make_reading(device_id: str, location: str, adc: int, threshold: int = ALARM_THRESHOLD, preventive_mode: bool = False, manual_alarm: bool = False) -> dict:
    if manual_alarm:
        state = "alarma"
    elif preventive_mode:
        state = "alarma preventiva"
    else:
        state = evaluate_state(adc, threshold)
    return {
        "device_id": device_id,
        "ubicacion": location,
        "adc": adc,
        "estado": state,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "simulado": True,
    }
