"""Validated environment settings; no dependency on the main infrastructure."""

import math
import os
import re
from dataclasses import dataclass, field

MAX_NODE_COUNT = 100
MAX_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1884
    mqtt_username: str | None = None
    mqtt_password: str | None = field(default=None, repr=False)
    node_count: int = 10
    interval_seconds: float = 2.0
    alarm_probability: float = 0.0
    alarm_threshold: int = 1500
    device_prefix: str = "esp32-virtual"
    location_prefix: str = "laboratorio"

    def __post_init__(self):
        if not self.mqtt_host.strip():
            raise ValueError("MQTT_HOST no puede estar vacío")
        if not 1 <= self.mqtt_port <= 65535:
            raise ValueError("MQTT_PORT debe estar entre 1 y 65535")
        if self.mqtt_password and not self.mqtt_username:
            raise ValueError("MQTT_PASSWORD requiere MQTT_USERNAME")
        if not 1 <= self.node_count <= MAX_NODE_COUNT:
            raise ValueError(f"SIM_NODE_COUNT debe estar entre 1 y {MAX_NODE_COUNT}")
        if not math.isfinite(self.interval_seconds) or not 0 < self.interval_seconds <= MAX_INTERVAL_SECONDS:
            raise ValueError(f"SIM_INTERVAL_SECONDS debe ser mayor que cero y hasta {MAX_INTERVAL_SECONDS}")
        if not math.isfinite(self.alarm_probability) or not 0 <= self.alarm_probability <= 1:
            raise ValueError("SIM_ALARM_PROBABILITY debe estar entre 0 y 1")
        if type(self.alarm_threshold) is not int or not 0 <= self.alarm_threshold <= 4094:
            raise ValueError("SIM_ALARM_THRESHOLD debe ser un entero entre 0 y 4094")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.device_prefix):
            raise ValueError("SIM_DEVICE_PREFIX: use 1-64 letras, números, guiones o guiones bajos")
        if not self.location_prefix.strip():
            raise ValueError("SIM_LOCATION_PREFIX no puede estar vacío")

    @classmethod
    def from_env(cls):
        return cls(
            mqtt_host=os.getenv("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1884")),
            mqtt_username=os.getenv("MQTT_USERNAME") or None,
            mqtt_password=os.getenv("MQTT_PASSWORD") or None,
            node_count=int(os.getenv("SIM_NODE_COUNT", "10")),
            interval_seconds=float(os.getenv("SIM_INTERVAL_SECONDS", "2")),
            alarm_probability=float(os.getenv("SIM_ALARM_PROBABILITY", "0")),
            alarm_threshold=int(os.getenv("SIM_ALARM_THRESHOLD", "1500")),
            device_prefix=os.getenv("SIM_DEVICE_PREFIX", "esp32-virtual"),
            location_prefix=os.getenv("SIM_LOCATION_PREFIX", "laboratorio"),
        )
