#!/usr/bin/env python3
"""
LabGuard+ Raspberry Pi GPIO LED Safety Status Controller.

Drives the physical 3-color LED Safety Status Display (Green = SAFE,
Yellow = CAUTION, Red = UNSAFE) and optional active buzzer on Raspberry Pi
(Pi Zero 2 W, Pi 3B+, Pi 4B, Pi 5) via `gpiozero`.

When running on a non-Raspberry Pi host (macOS, Windows, desktop Linux) or when
GPIO hardware is unavailable/disabled, seamlessly runs in simulation mode so
development and testing never fail.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("labguard.gpio")


def _detect_raspberry_pi() -> bool:
    """Return True if running on a Raspberry Pi Linux kernel."""
    model_paths = (
        "/proc/device-tree/model",
        "/sys/firmware/devicetree/base/model",
    )
    for model_path in model_paths:
        try:
            if os.path.exists(model_path):
                with open(model_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().lower()
                if "raspberry pi" in text:
                    return True
        except OSError:
            continue
    return False


def _parse_optional_pin(env_name: str, default: Optional[int]) -> Optional[int]:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in ("", "0", "none", "off", "false", "disabled"):
        return None
    try:
        pin = int(raw)
        return pin if pin > 0 else None
    except ValueError:
        logger.warning("Invalid GPIO pin value %s=%r; using default %r", env_name, raw, default)
        return default


def _parse_bool_mode(env_name: str, default: str = "auto") -> str:
    raw = os.environ.get(env_name, default).strip().lower()
    if raw in ("1", "true", "yes", "on", "enabled"):
        return "enabled"
    if raw in ("0", "false", "no", "off", "disabled"):
        return "disabled"
    return "auto"


class SafetyLEDController:
    """Thread-safe controller for the 3-color LabGuard+ LED status tower."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.is_raspberry_pi = _detect_raspberry_pi()
        self.gpio_mode_setting = _parse_bool_mode("LABGUARD_GPIO_ENABLED", "auto")
        self.active_high = os.environ.get("LABGUARD_LED_ACTIVE_HIGH", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        self.buzzer_enabled = os.environ.get("LABGUARD_BUZZER_ENABLED", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )

        self.pins: Dict[str, Optional[int]] = {
            "green": _parse_optional_pin("LABGUARD_LED_GREEN_PIN", 17),
            "yellow": _parse_optional_pin("LABGUARD_LED_YELLOW_PIN", 27),
            "red": _parse_optional_pin("LABGUARD_LED_RED_PIN", 22),
            "buzzer": _parse_optional_pin("LABGUARD_BUZZER_PIN", 23),
        }

        self.current_level: str = "SAFE"
        self.led_state: Dict[str, bool] = {"green": True, "yellow": False, "red": False}
        self.hardware_mode: str = "simulation"
        self.status_note: str = "Running in PC/software simulation mode."

        self._devices: Dict[str, Any] = {}
        self._init_gpio()
        atexit.register(self.cleanup)

    def _init_gpio(self) -> None:
        if self.gpio_mode_setting == "disabled":
            self.hardware_mode = "simulation"
            self.status_note = "GPIO disabled via LABGUARD_GPIO_ENABLED=0."
            return

        if self.gpio_mode_setting == "auto" and not self.is_raspberry_pi:
            self.hardware_mode = "simulation"
            self.status_note = "Non-Raspberry Pi host detected; using simulated LED state."
            return

        try:
            from gpiozero import DigitalOutputDevice  # type: ignore
        except ImportError:
            self.hardware_mode = "simulation"
            self.status_note = "gpiozero not installed; using simulated LED state."
            return

        try:
            for color in ("green", "yellow", "red"):
                pin = self.pins.get(color)
                if pin is not None:
                    self._devices[color] = DigitalOutputDevice(
                        pin, active_high=self.active_high, initial_value=False
                    )
            buzzer_pin = self.pins.get("buzzer")
            if self.buzzer_enabled and buzzer_pin is not None:
                self._devices["buzzer"] = DigitalOutputDevice(
                    buzzer_pin, active_high=True, initial_value=False
                )

            self.hardware_mode = "raspberry_pi_gpio"
            self.status_note = (
                f"Active Raspberry Pi GPIO (BCM G={self.pins['green']}, "
                f"Y={self.pins['yellow']}, R={self.pins['red']}"
                + (f", Buzzer={self.pins['buzzer']})" if self.pins["buzzer"] else ")")
            )
            logger.info("LabGuard+ GPIO initialized: %s", self.status_note)
        except Exception as exc:
            self.cleanup()
            self.hardware_mode = "simulation"
            self.status_note = f"GPIO unavailable ({exc}); fell back to simulation mode."
            logger.warning("GPIO init failed, falling back to simulation: %s", exc)

    def set_safety_level(self, level: str, *, beep_on_change: bool = True) -> Dict[str, Any]:
        """Set active safety status ('SAFE', 'CAUTION', or 'UNSAFE') and update LEDs."""
        normalized = (level or "SAFE").strip().upper()
        if normalized not in ("SAFE", "CAUTION", "UNSAFE"):
            normalized = "SAFE"

        with self._lock:
            prev_level = self.current_level
            self.current_level = normalized
            self.led_state = {
                "green": normalized == "SAFE",
                "yellow": normalized == "CAUTION",
                "red": normalized == "UNSAFE",
            }

            if self.hardware_mode == "raspberry_pi_gpio":
                for color, is_on in self.led_state.items():
                    dev = self._devices.get(color)
                    if dev is not None:
                        try:
                            if is_on:
                                dev.on()
                            else:
                                dev.off()
                        except Exception as exc:
                            logger.warning("Failed to toggle %s LED: %s", color, exc)

            if beep_on_change and normalized != prev_level:
                if normalized == "CAUTION":
                    self.beep("caution")
                elif normalized == "UNSAFE":
                    self.beep("unsafe")
                elif normalized == "SAFE":
                    self.beep("safe")

            return self.get_status()

    def beep(self, pattern: str = "confirm") -> None:
        """Trigger a short non-blocking buzzer chirp if a Raspberry Pi buzzer is connected."""
        if not self.buzzer_enabled or self.hardware_mode != "raspberry_pi_gpio":
            return
        buzzer = self._devices.get("buzzer")
        if buzzer is None:
            return

        pulses = {
            "confirm": [(0.08, 0.0)],
            "safe": [(0.07, 0.0)],
            "caution": [(0.12, 0.08), (0.12, 0.0)],
            "unsafe": [(0.18, 0.08), (0.18, 0.08), (0.25, 0.0)],
        }.get(pattern, [(0.08, 0.0)])

        def _run() -> None:
            with self._lock:
                for on_s, off_s in pulses:
                    try:
                        buzzer.on()
                        time.sleep(on_s)
                        buzzer.off()
                        if off_s > 0:
                            time.sleep(off_s)
                    except Exception:
                        break

        threading.Thread(target=_run, daemon=True).start()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "hardware_mode": self.hardware_mode,
                "is_raspberry_pi": self.is_raspberry_pi,
                "gpio_active": self.hardware_mode == "raspberry_pi_gpio",
                "active_high": self.active_high,
                "current_level": self.current_level,
                "led_state": dict(self.led_state),
                "pins": dict(self.pins),
                "note": self.status_note,
            }

    def cleanup(self) -> None:
        with self._lock:
            for dev in list(self._devices.values()):
                try:
                    dev.off()
                    dev.close()
                except Exception:
                    pass
            self._devices.clear()
