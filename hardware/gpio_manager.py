#!/usr/bin/env python3
"""
LabGuard+ Raspberry Pi 2/3/4/5 12-Channel Locker & Safety Status GPIO Manager.

Controls up to 12 electric locker lock relays/MOSFETs (HIGH/LOW digital outputs),
the 3-color Safety Status LED tower (Green = SAFE, Yellow = CAUTION, Red = UNSAFE),
and an active buzzer via ``gpiozero.DigitalOutputDevice``.

Supports:
  - Raspberry Pi 2 Model B & Pi 3 Model B/B+ (RPi.GPIO / rpi-lgpio)
  - Raspberry Pi 4B, Pi 5, and Pi Zero 2 W (lgpio / rpi-lgpio)
  - Automatic PC / macOS / Linux simulation fallback with identical electrical
    HIGH/LOW and logical LOCKED/UNLOCKED state tracking.

Default 16-pin mapping leaves I2C (GPIO 2, 3), SPI0 (GPIO 7-11), UART (GPIO 14, 15),
PWM0 (GPIO 18), and EEPROM (GPIO 0, 1) completely free.
"""

from __future__ import annotations

import atexit
import collections
import copy
import logging
import math
import os
import platform
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("labguard.gpio")

# Raspberry Pi 40-pin J8 header mapping: BCM GPIO (2..27) -> Physical Pin (1..40)
BCM_TO_PHYSICAL: Dict[int, int] = {
    2: 3,
    3: 5,
    4: 7,
    5: 29,
    6: 31,
    7: 26,
    8: 24,
    9: 21,
    10: 19,
    11: 23,
    12: 32,
    13: 33,
    14: 8,
    15: 10,
    16: 36,
    17: 11,
    18: 12,
    19: 35,
    20: 38,
    21: 40,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
    26: 37,
    27: 13,
}

# Hardware peripheral bus warnings for shared Raspberry Pi GPIO pins
BUS_WARNINGS: Dict[int, str] = {
    2: "I2C1 SDA",
    3: "I2C1 SCL",
    7: "SPI0 CE1",
    8: "SPI0 CE0",
    9: "SPI0 MISO",
    10: "SPI0 MOSI",
    11: "SPI0 SCLK",
    14: "UART TX",
    15: "UART RX",
    18: "PWM0 / PCM CLK",
}

VALID_MODES: Tuple[str, ...] = ("auto", "enabled", "simulation")
LED_CHANNELS: Tuple[str, ...] = ("green", "yellow", "red", "buzzer")
LOCKER_ACTIONS: Tuple[str, ...] = ("pulse", "unlock", "lock", "high", "low")
LED_ACTIONS: Tuple[str, ...] = ("pulse", "high", "low")

_DEFAULT_LED_LABELS: Dict[str, str] = {
    "green": "Green LED (SAFE)",
    "yellow": "Yellow LED (CAUTION)",
    "red": "Red LED (UNSAFE)",
    "buzzer": "Active Buzzer",
}

_DEFAULT_LOCKER_SPECS: Tuple[Tuple[int, str, str, int], ...] = (
    (1, "Locker 1", "1st - 1st Section", 5),
    (2, "Locker 2", "2nd - 1st Section", 6),
    (3, "Locker 3", "3rd - 1st Section", 13),
    (4, "Locker 4", "4th - 1st Section", 19),
    (5, "Locker 5", "1st - 2nd Section", 26),
    (6, "Locker 6", "2nd - 2nd Section", 12),
    (7, "Locker 7", "3rd - 2nd Section", 16),
    (8, "Locker 8", "4th - 2nd Section", 20),
    (9, "Locker 9", "1st - 3rd Section", 21),
    (10, "Locker 10", "2nd - 3rd Section", 24),
    (11, "Locker 11", "3rd - 3rd Section", 25),
    (12, "Locker 12", "4th - 3rd Section", 4),
)

_SAFETY_LEVEL_TO_COLOR: Dict[str, str] = {
    "SAFE": "green",
    "CAUTION": "yellow",
    "UNSAFE": "red",
}

_DIAG_BUFFER_MAXLEN = 50
_DIAG_PUBLIC_LIMIT = 30


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _detect_board_info() -> Tuple[bool, str, str]:
    """Detect Raspberry Pi board model, whether host is a Pi, and CPU architecture."""
    arch = platform.machine() or "unknown"
    model_paths = (
        "/proc/device-tree/model",
        "/sys/firmware/devicetree/base/model",
    )
    for model_path in model_paths:
        try:
            if os.path.exists(model_path):
                with open(model_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read().replace("\x00", "").strip()
                if text:
                    is_pi = "raspberry pi" in text.lower()
                    return is_pi, text, arch
        except OSError:
            continue

    os_label = "macOS" if sys.platform == "darwin" else (platform.system() or "Unknown OS")
    return False, f"Simulation Host ({os_label})", arch


def _parse_env_optional_pin(env_name: str, default: Optional[int]) -> Optional[int]:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in ("", "0", "none", "off", "false", "disabled"):
        return None
    try:
        pin = int(raw)
        if pin in BCM_TO_PHYSICAL:
            return pin
        logger.warning(
            "GPIO pin %s=%r is outside valid BCM 2..27 range; using default %r",
            env_name,
            raw,
            default,
        )
        return default
    except ValueError:
        logger.warning("Invalid GPIO pin value %s=%r; using default %r", env_name, raw, default)
        return default


def _parse_env_bool(env_name: str, default: bool) -> bool:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    if val in ("1", "true", "yes", "on", "enabled"):
        return True
    return default


def _parse_env_mode(env_name: str = "LABGUARD_GPIO_ENABLED", default: str = "auto") -> str:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "on", "enabled"):
        return "enabled"
    if val in ("0", "false", "no", "off", "disabled", "simulation", "sim"):
        return "simulation"
    if val == "auto":
        return "auto"
    return default


def _logical_to_electrical(is_active: bool, active_high: bool) -> str:
    """Convert logical active state + polarity into electrical level ('HIGH' or 'LOW')."""
    is_high = is_active if active_high else (not is_active)
    return "HIGH" if is_high else "LOW"


def _electrical_to_logical(electrical: str, active_high: bool) -> bool:
    """Convert raw electrical level ('HIGH'/'LOW') + polarity into logical active state."""
    is_high = electrical.upper() == "HIGH"
    return is_high if active_high else (not is_high)


def _build_base_default_gpio_config(
    *,
    mode: str = "auto",
    led_active_high: bool = True,
    green_pin: Optional[int] = 17,
    yellow_pin: Optional[int] = 27,
    red_pin: Optional[int] = 22,
    buzzer_pin: Optional[int] = 23,
    buzzer_enabled: bool = True,
) -> Dict[str, Any]:
    default_unlock = 5.0
    lockers: List[Dict[str, Any]] = [
        {
            "id": lid,
            "name": name,
            "compartment": compartment,
            "bcm_pin": bcm_pin,
            "active_high": False,
            "pulse_seconds": default_unlock,
            "enabled": True,
        }
        for lid, name, compartment, bcm_pin in _DEFAULT_LOCKER_SPECS
    ]

    return {
        "mode": mode,
        "default_unlock_seconds": default_unlock,
        "auto_unlock_on_borrow": True,
        "auto_unlock_on_return": True,
        "leds": {
            "green": {
                "label": _DEFAULT_LED_LABELS["green"],
                "bcm_pin": green_pin,
                "active_high": led_active_high,
                "enabled": green_pin is not None,
            },
            "yellow": {
                "label": _DEFAULT_LED_LABELS["yellow"],
                "bcm_pin": yellow_pin,
                "active_high": led_active_high,
                "enabled": yellow_pin is not None,
            },
            "red": {
                "label": _DEFAULT_LED_LABELS["red"],
                "bcm_pin": red_pin,
                "active_high": led_active_high,
                "enabled": red_pin is not None,
            },
            "buzzer": {
                "label": _DEFAULT_LED_LABELS["buzzer"],
                "bcm_pin": buzzer_pin,
                "active_high": True,
                "enabled": buzzer_enabled and (buzzer_pin is not None),
            },
        },
        "lockers": lockers,
    }


def get_default_gpio_config() -> Dict[str, Any]:
    """Return a fresh copy of the conflict-free 16-pin Raspberry Pi 2/3 default GPIO config."""
    mode = _parse_env_mode("LABGUARD_GPIO_ENABLED", "auto")
    led_active_high = _parse_env_bool("LABGUARD_LED_ACTIVE_HIGH", True)
    buzzer_enabled = _parse_env_bool("LABGUARD_BUZZER_ENABLED", True)
    green_pin = _parse_env_optional_pin("LABGUARD_LED_GREEN_PIN", 17)
    yellow_pin = _parse_env_optional_pin("LABGUARD_LED_YELLOW_PIN", 27)
    red_pin = _parse_env_optional_pin("LABGUARD_LED_RED_PIN", 22)
    buzzer_pin = _parse_env_optional_pin("LABGUARD_BUZZER_PIN", 23)

    return _build_base_default_gpio_config(
        mode=mode,
        led_active_high=led_active_high,
        green_pin=green_pin,
        yellow_pin=yellow_pin,
        red_pin=red_pin,
        buzzer_pin=buzzer_pin,
        buzzer_enabled=buzzer_enabled,
    )


def _validate_float_in_range(
    raw: Any,
    field_name: str,
    min_val: float,
    max_val: float,
) -> Tuple[bool, str, float]:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False, f"Field '{field_name}' must be a number between {min_val} and {max_val}.", 0.0
    val = float(raw)
    if not math.isfinite(val) or val < min_val or val > max_val:
        return False, f"Field '{field_name}' must be between {min_val} and {max_val} seconds.", 0.0
    return True, "", round(val, 3)


def _validate_bcm_pin(
    raw_pin: Any,
    *,
    enabled: bool,
    channel_display: str,
) -> Tuple[bool, str, Optional[int]]:
    if raw_pin is None or (isinstance(raw_pin, str) and raw_pin.strip() == ""):
        if enabled:
            return (
                False,
                f"Enabled channel '{channel_display}' must have a BCM GPIO pin (2..27) assigned.",
                None,
            )
        return True, "", None

    if isinstance(raw_pin, bool):
        return (
            False,
            f"Invalid BCM GPIO pin for '{channel_display}': boolean value is not allowed.",
            None,
        )

    pin: Optional[int] = None
    if isinstance(raw_pin, int):
        pin = raw_pin
    elif isinstance(raw_pin, str):
        text = raw_pin.strip()
        if text.lstrip("-").isdigit():
            pin = int(text)
    if pin is None:
        return (
            False,
            f"Invalid BCM GPIO pin {raw_pin!r} for '{channel_display}'. Expected integer BCM 2..27.",
            None,
        )

    if pin not in BCM_TO_PHYSICAL:
        return (
            False,
            f"Invalid BCM GPIO pin {pin} for '{channel_display}'. Allowed Raspberry Pi GPIO pins are BCM 2..27.",
            None,
        )
    return True, "", pin


def validate_gpio_config(cfg: Any) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validate and normalize a LabGuard+ GPIO configuration dictionary.

    Returns ``(True, "", normalized_config)`` on success or
    ``(False, error_message, {})`` on validation failure / pin conflict.
    """
    if not isinstance(cfg, dict):
        return False, "GPIO configuration must be a JSON object.", {}

    # 1. Mode
    raw_mode = cfg.get("mode", "auto")
    if not isinstance(raw_mode, str):
        return False, "GPIO 'mode' must be one of: 'auto', 'enabled', 'simulation'.", {}
    mode = raw_mode.strip().lower()
    if mode not in VALID_MODES:
        return (
            False,
            f"Invalid GPIO mode {raw_mode!r}. Allowed values are 'auto', 'enabled', 'simulation'.",
            {},
        )

    # 2. Global timing and auto-unlock flags
    raw_default_unlock = cfg.get("default_unlock_seconds", 5.0)
    ok, err, default_unlock_seconds = _validate_float_in_range(
        raw_default_unlock, "default_unlock_seconds", 0.5, 60.0
    )
    if not ok:
        return False, err, {}

    auto_unlock_on_borrow = cfg.get("auto_unlock_on_borrow", True)
    if not isinstance(auto_unlock_on_borrow, bool):
        return False, "Field 'auto_unlock_on_borrow' must be a boolean.", {}

    auto_unlock_on_return = cfg.get("auto_unlock_on_return", True)
    if not isinstance(auto_unlock_on_return, bool):
        return False, "Field 'auto_unlock_on_return' must be a boolean.", {}

    # 3. LEDs & Buzzer
    raw_leds = cfg.get("leds")
    if not isinstance(raw_leds, dict):
        return False, "Field 'leds' must be an object containing green, yellow, red, and buzzer.", {}

    default_cfg = _build_base_default_gpio_config()
    normalized_leds: Dict[str, Dict[str, Any]] = {}
    used_pins: Dict[int, str] = {}

    for ch in LED_CHANNELS:
        ch_raw = raw_leds.get(ch)
        if ch_raw is None:
            return False, f"Missing required LED/indicator channel '{ch}' in 'leds'.", {}
        if not isinstance(ch_raw, dict):
            return False, f"LED channel '{ch}' must be an object.", {}

        raw_label = ch_raw.get("label")
        label = (
            raw_label.strip()
            if isinstance(raw_label, str) and raw_label.strip()
            else default_cfg["leds"][ch]["label"]
        )

        enabled = ch_raw.get("enabled", True)
        if not isinstance(enabled, bool):
            return False, f"Field 'enabled' for '{label}' must be a boolean.", {}

        active_high = ch_raw.get("active_high", True)
        if not isinstance(active_high, bool):
            return False, f"Field 'active_high' for '{label}' must be a boolean.", {}

        ok, err, bcm_pin = _validate_bcm_pin(
            ch_raw.get("bcm_pin"), enabled=enabled, channel_display=label
        )
        if not ok:
            return False, err, {}

        if enabled and bcm_pin is not None:
            if bcm_pin in used_pins:
                prev_ch = used_pins[bcm_pin]
                phys = BCM_TO_PHYSICAL[bcm_pin]
                return (
                    False,
                    f"GPIO pin conflict: BCM {bcm_pin} (Pin {phys}) is assigned to both '{prev_ch}' and '{label}'.",
                    {},
                )
            used_pins[bcm_pin] = label

        normalized_leds[ch] = {
            "label": label,
            "bcm_pin": bcm_pin,
            "active_high": active_high,
            "enabled": enabled,
        }

    # 4. Lockers
    raw_lockers = cfg.get("lockers")
    if not isinstance(raw_lockers, list):
        return False, "Field 'lockers' must be a list of locker channel configurations.", {}

    normalized_lockers: List[Dict[str, Any]] = []
    seen_locker_ids: set[int] = set()

    for idx, item in enumerate(raw_lockers):
        if not isinstance(item, dict):
            return False, f"Locker entry at index {idx} must be an object.", {}

        raw_id = item.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or raw_id <= 0:
            return False, f"Locker entry at index {idx} must have a positive integer 'id'.", {}
        if raw_id in seen_locker_ids:
            return False, f"Duplicate locker id {raw_id} in 'lockers'.", {}
        seen_locker_ids.add(raw_id)

        raw_name = item.get("name")
        name = (
            raw_name.strip()
            if isinstance(raw_name, str) and raw_name.strip()
            else f"Locker {raw_id}"
        )

        raw_comp = item.get("compartment", "")
        if raw_comp is None:
            compartment = ""
        elif isinstance(raw_comp, str):
            compartment = raw_comp.strip()
        else:
            return False, f"Field 'compartment' for '{name}' must be a string.", {}

        display_name = f"{name} ({compartment})" if compartment else name

        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            return False, f"Field 'enabled' for '{display_name}' must be a boolean.", {}

        active_high = item.get("active_high", False)
        if not isinstance(active_high, bool):
            return False, f"Field 'active_high' for '{display_name}' must be a boolean.", {}

        raw_pulse = item.get("pulse_seconds", default_unlock_seconds)
        if raw_pulse is None:
            raw_pulse = default_unlock_seconds
        ok, err, pulse_seconds = _validate_float_in_range(
            raw_pulse, f"{name}.pulse_seconds", 0.5, 60.0
        )
        if not ok:
            return False, err, {}

        ok, err, bcm_pin = _validate_bcm_pin(
            item.get("bcm_pin"), enabled=enabled, channel_display=display_name
        )
        if not ok:
            return False, err, {}

        if enabled and bcm_pin is not None:
            if bcm_pin in used_pins:
                prev_ch = used_pins[bcm_pin]
                phys = BCM_TO_PHYSICAL[bcm_pin]
                return (
                    False,
                    f"GPIO pin conflict: BCM {bcm_pin} (Pin {phys}) is assigned to both '{prev_ch}' and '{display_name}'.",
                    {},
                )
            used_pins[bcm_pin] = display_name

        normalized_lockers.append(
            {
                "id": raw_id,
                "name": name,
                "compartment": compartment,
                "bcm_pin": bcm_pin,
                "active_high": active_high,
                "pulse_seconds": pulse_seconds,
                "enabled": enabled,
            }
        )

    normalized: Dict[str, Any] = {
        "mode": mode,
        "default_unlock_seconds": default_unlock_seconds,
        "auto_unlock_on_borrow": auto_unlock_on_borrow,
        "auto_unlock_on_return": auto_unlock_on_return,
        "leds": normalized_leds,
        "lockers": normalized_lockers,
    }
    return True, "", normalized


class GPIOManager:
    """
    Thread-safe live-reconfigurable GPIO controller for LabGuard+ Raspberry Pi cabinets.

    Manages 12 locker lock channels (Active-LOW or Active-HIGH), 3 Safety Status LEDs,
    and an active buzzer, with automatic simulation fallback on non-Pi hosts.
    """

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.RLock()
        self.is_raspberry_pi, self.board_model, self.arch = _detect_board_info()
        self.pin_factory: str = "simulation"
        self.hardware_mode: str = "simulation"
        self.status_note: str = "Initializing GPIO manager..."

        self.current_level: str = "SAFE"
        self.led_state: Dict[str, bool] = {"green": True, "yellow": False, "red": False}
        self._led_active: Dict[str, bool] = {
            "green": True,
            "yellow": False,
            "red": False,
            "buzzer": False,
        }

        self._config: Dict[str, Any] = _build_base_default_gpio_config()
        self._locker_unlocked: Dict[int, bool] = {}
        self._locker_unlock_until: Dict[int, Optional[str]] = {}

        self._locker_devices: Dict[int, Any] = {}
        self._led_devices: Dict[str, Any] = {}

        self._locker_timers: Dict[int, threading.Timer] = {}
        self._locker_timer_tokens: Dict[int, object] = {}
        self._led_timers: Dict[str, threading.Timer] = {}
        self._led_timer_tokens: Dict[str, object] = {}

        self._diag_log: Deque[Dict[str, Any]] = collections.deque(maxlen=_DIAG_BUFFER_MAXLEN)

        if initial_config is not None:
            self.apply_config(initial_config, source="init")
        else:
            env_cfg = get_default_gpio_config()
            ok, err, _ = validate_gpio_config(env_cfg)
            if not ok:
                logger.warning(
                    "Environment GPIO pin override caused validation error (%s); "
                    "falling back to clean Pi 2/3 defaults.",
                    err,
                )
                env_cfg = _build_base_default_gpio_config(
                    mode=_parse_env_mode("LABGUARD_GPIO_ENABLED", "auto")
                )
            self.apply_config(env_cfg, source="init")

        atexit.register(self.cleanup)

    # ------------------------------------------------------------------
    # Backward-compatible attribute properties (SafetyLEDController)
    # ------------------------------------------------------------------
    @property
    def gpio_mode_setting(self) -> str:
        with self._lock:
            return self._config["mode"]

    @property
    def active_high(self) -> bool:
        with self._lock:
            return bool(self._config["leds"]["green"]["active_high"])

    @property
    def buzzer_enabled(self) -> bool:
        with self._lock:
            return bool(self._config["leds"]["buzzer"]["enabled"])

    @property
    def pins(self) -> Dict[str, Optional[int]]:
        with self._lock:
            leds = self._config["leds"]
            return {
                ch: (leds[ch]["bcm_pin"] if leds[ch]["enabled"] else None)
                for ch in LED_CHANNELS
            }

    # ------------------------------------------------------------------
    # Internal logging, timers, and hardware device lifecycle
    # ------------------------------------------------------------------
    def _record_event_locked(
        self,
        *,
        channel: str,
        bcm_pin: Optional[int],
        action: str,
        electrical_state: str,
        logical_state: str,
        source: str,
    ) -> None:
        self._diag_log.appendleft(
            {
                "timestamp": _utc_now_iso(),
                "channel": channel,
                "bcm_pin": bcm_pin,
                "action": action,
                "electrical_state": electrical_state,
                "logical_state": logical_state,
                "source": source,
            }
        )

    def _cancel_locker_timer_locked(self, locker_id: int) -> None:
        timer = self._locker_timers.pop(locker_id, None)
        self._locker_timer_tokens.pop(locker_id, None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _cancel_led_timer_locked(self, channel: str) -> None:
        timer = self._led_timers.pop(channel, None)
        self._led_timer_tokens.pop(channel, None)
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _cancel_all_timers_locked(self) -> None:
        for lid in list(self._locker_timers.keys()):
            self._cancel_locker_timer_locked(lid)
        for ch in list(self._led_timers.keys()):
            self._cancel_led_timer_locked(ch)

    def _close_devices_locked(self) -> None:
        for dev in list(self._locker_devices.values()):
            try:
                dev.off()
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass
        self._locker_devices.clear()

        for dev in list(self._led_devices.values()):
            try:
                dev.off()
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass
        self._led_devices.clear()

    def _find_locker_cfg_locked(self, locker_id: int) -> Optional[Dict[str, Any]]:
        for locker in self._config["lockers"]:
            if locker["id"] == locker_id:
                return locker
        return None

    def _sync_safety_leds_to_hardware_locked(self) -> None:
        if self.hardware_mode != "raspberry_pi_gpio":
            return
        for color in ("green", "yellow", "red"):
            dev = self._led_devices.get(color)
            if dev is not None:
                try:
                    if self._led_active.get(color, False):
                        dev.on()
                    else:
                        dev.off()
                except Exception as exc:
                    logger.warning("Failed to drive %s LED: %s", color, exc)

    def _bind_devices_locked(self) -> None:
        mode = self._config["mode"]
        if mode == "simulation":
            self.hardware_mode = "simulation"
            self.pin_factory = "simulation"
            self.status_note = "GPIO simulation mode active (configured in settings)."
            return

        if mode == "auto" and not self.is_raspberry_pi:
            self.hardware_mode = "simulation"
            self.pin_factory = "simulation"
            self.status_note = "Non-Raspberry Pi host detected; running in simulation mode."
            return

        try:
            from gpiozero import Device, DigitalOutputDevice  # type: ignore
        except ImportError:
            self.hardware_mode = "simulation"
            self.pin_factory = "simulation"
            self.status_note = "gpiozero not installed; running in simulation mode."
            return

        try:
            for ch in LED_CHANNELS:
                ch_cfg = self._config["leds"][ch]
                if ch_cfg["enabled"] and ch_cfg["bcm_pin"] is not None:
                    self._led_devices[ch] = DigitalOutputDevice(
                        ch_cfg["bcm_pin"],
                        active_high=ch_cfg["active_high"],
                        initial_value=False,
                    )

            for locker in self._config["lockers"]:
                if locker["enabled"] and locker["bcm_pin"] is not None:
                    # Lockers ALWAYS start LOCKED (initial_value=False -> HIGH for Active-LOW, LOW for Active-HIGH)
                    self._locker_devices[locker["id"]] = DigitalOutputDevice(
                        locker["bcm_pin"],
                        active_high=locker["active_high"],
                        initial_value=False,
                    )

            factory_obj = getattr(Device, "pin_factory", None)
            factory_name = (
                factory_obj.__class__.__name__ if factory_obj is not None else "gpiozero"
            )
            self.pin_factory = factory_name
            self.hardware_mode = "raspberry_pi_gpio"
            self.status_note = (
                f"Active Raspberry Pi GPIO ({factory_name}): "
                f"{len(self._locker_devices)} locker(s), {len(self._led_devices)} indicator(s)."
            )
            logger.info("LabGuard+ GPIO initialized: %s", self.status_note)
        except Exception as exc:
            self._close_devices_locked()
            self.hardware_mode = "simulation"
            self.pin_factory = "simulation"
            self.status_note = f"GPIO unavailable ({exc}); fell back to simulation mode."
            logger.warning("GPIO init failed, falling back to simulation: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def apply_config(
        self, new_config: Dict[str, Any], *, source: str = "config_reload"
    ) -> Dict[str, Any]:
        """Validate, cleanly rebind GPIO handles live, and return the full GPIO state."""
        ok, err, normalized = validate_gpio_config(new_config)
        if not ok:
            raise ValueError(err)

        with self._lock:
            self._cancel_all_timers_locked()
            self._close_devices_locked()

            self._config = copy.deepcopy(normalized)

            # Lockers always initialize in LOCKED state after reload
            self._locker_unlocked = {locker["id"]: False for locker in self._config["lockers"]}
            self._locker_unlock_until = {locker["id"]: None for locker in self._config["lockers"]}

            # Restore safety LED logical state from current_level; buzzer starts OFF
            active_color = _SAFETY_LEVEL_TO_COLOR.get(self.current_level, "green")
            self.led_state = {
                "green": active_color == "green",
                "yellow": active_color == "yellow",
                "red": active_color == "red",
            }
            self._led_active = {
                "green": self.led_state["green"],
                "yellow": self.led_state["yellow"],
                "red": self.led_state["red"],
                "buzzer": False,
            }

            self._bind_devices_locked()
            self._sync_safety_leds_to_hardware_locked()

            enabled_lockers = sum(1 for l in self._config["lockers"] if l["enabled"])
            self._record_event_locked(
                channel="System",
                bcm_pin=None,
                action="reload",
                electrical_state="N/A",
                logical_state=f"{self.hardware_mode} ({enabled_lockers} lockers)",
                source=source,
            )
            return self.get_full_state()

    def set_safety_level(
        self,
        level: str,
        *,
        beep_on_change: bool = True,
        source: str = "system",
    ) -> Dict[str, Any]:
        """Set active safety status ('SAFE', 'CAUTION', or 'UNSAFE') and update LEDs."""
        normalized = (level or "SAFE").strip().upper()
        if normalized not in _SAFETY_LEVEL_TO_COLOR:
            normalized = "SAFE"

        should_beep_pattern: Optional[str] = None
        with self._lock:
            prev_level = self.current_level
            self.current_level = normalized

            for color in ("green", "yellow", "red"):
                self._cancel_led_timer_locked(color)

            active_color = _SAFETY_LEVEL_TO_COLOR[normalized]
            self.led_state = {
                "green": active_color == "green",
                "yellow": active_color == "yellow",
                "red": active_color == "red",
            }
            for color, is_on in self.led_state.items():
                self._led_active[color] = is_on

            self._sync_safety_leds_to_hardware_locked()

            if normalized != prev_level:
                led_cfg = self._config["leds"][active_color]
                electrical = (
                    _logical_to_electrical(True, led_cfg["active_high"])
                    if led_cfg["enabled"]
                    else "LOW"
                )
                self._record_event_locked(
                    channel=led_cfg["label"],
                    bcm_pin=led_cfg["bcm_pin"] if led_cfg["enabled"] else None,
                    action=f"safety_{normalized.lower()}",
                    electrical_state=electrical,
                    logical_state=normalized,
                    source=source,
                )

                if beep_on_change:
                    if normalized == "CAUTION":
                        should_beep_pattern = "caution"
                    elif normalized == "UNSAFE":
                        should_beep_pattern = "unsafe"
                    elif normalized == "SAFE":
                        should_beep_pattern = "safe"

            status = self.get_status()

        if should_beep_pattern is not None:
            self.beep(should_beep_pattern)
        return status

    def beep(self, pattern: str = "confirm") -> None:
        """Trigger a short non-blocking buzzer chirp when running on Raspberry Pi GPIO."""
        with self._lock:
            buzzer_cfg = self._config["leds"]["buzzer"]
            if (
                not buzzer_cfg["enabled"]
                or buzzer_cfg["bcm_pin"] is None
                or self.hardware_mode != "raspberry_pi_gpio"
                or "buzzer" not in self._led_devices
            ):
                return

        pulses = {
            "confirm": [(0.08, 0.0)],
            "safe": [(0.07, 0.0)],
            "caution": [(0.12, 0.08), (0.12, 0.0)],
            "unsafe": [(0.18, 0.08), (0.18, 0.08), (0.25, 0.0)],
        }.get(pattern, [(0.08, 0.0)])

        def _run() -> None:
            for on_s, off_s in pulses:
                with self._lock:
                    dev = self._led_devices.get("buzzer")
                    if dev is None or self.hardware_mode != "raspberry_pi_gpio":
                        return
                    try:
                        dev.on()
                        self._led_active["buzzer"] = True
                    except Exception:
                        return
                time.sleep(on_s)
                with self._lock:
                    dev = self._led_devices.get("buzzer")
                    self._led_active["buzzer"] = False
                    if dev is None:
                        return
                    try:
                        dev.off()
                    except Exception:
                        return
                if off_s > 0:
                    time.sleep(off_s)

        threading.Thread(target=_run, daemon=True).start()

    def _auto_relock_locker(self, locker_id: int, token: object) -> None:
        with self._lock:
            if self._locker_timer_tokens.get(locker_id) is not token:
                return
            self._locker_timers.pop(locker_id, None)
            self._locker_timer_tokens.pop(locker_id, None)

            locker_cfg = self._find_locker_cfg_locked(locker_id)
            if locker_cfg is None:
                return

            dev = self._locker_devices.get(locker_id)
            if dev is not None and self.hardware_mode == "raspberry_pi_gpio":
                try:
                    dev.off()
                except Exception as exc:
                    logger.warning("Failed to auto-relock locker %s: %s", locker_id, exc)

            self._locker_unlocked[locker_id] = False
            self._locker_unlock_until[locker_id] = None
            electrical = _logical_to_electrical(False, locker_cfg["active_high"])
            self._record_event_locked(
                channel=locker_cfg["name"],
                bcm_pin=locker_cfg["bcm_pin"],
                action="auto_relock",
                electrical_state=electrical,
                logical_state="LOCKED",
                source="auto_relock_timer",
            )

    def _auto_restore_led(self, channel: str, token: object) -> None:
        with self._lock:
            if self._led_timer_tokens.get(channel) is not token:
                return
            self._led_timers.pop(channel, None)
            self._led_timer_tokens.pop(channel, None)

            led_cfg = self._config["leds"].get(channel)
            if led_cfg is None:
                return

            if channel == "buzzer":
                expected_on = False
            else:
                expected_on = _SAFETY_LEVEL_TO_COLOR.get(self.current_level, "green") == channel

            dev = self._led_devices.get(channel)
            if dev is not None and self.hardware_mode == "raspberry_pi_gpio":
                try:
                    if expected_on:
                        dev.on()
                    else:
                        dev.off()
                except Exception as exc:
                    logger.warning("Failed to auto-restore %s: %s", channel, exc)

            self._led_active[channel] = expected_on
            if channel in self.led_state:
                self.led_state[channel] = expected_on

            electrical = _logical_to_electrical(expected_on, led_cfg["active_high"])
            self._record_event_locked(
                channel=led_cfg["label"],
                bcm_pin=led_cfg["bcm_pin"],
                action="auto_restore",
                electrical_state=electrical,
                logical_state="ON" if expected_on else "OFF",
                source="pulse_timer",
            )

    def _build_locker_view_locked(self, locker_cfg: Dict[str, Any]) -> Dict[str, Any]:
        lid = locker_cfg["id"]
        bcm_pin = locker_cfg["bcm_pin"]
        enabled = locker_cfg["enabled"]
        active_high = locker_cfg["active_high"]
        is_unlocked = bool(self._locker_unlocked.get(lid, False)) if enabled else False
        electrical_state = (
            _logical_to_electrical(is_unlocked, active_high) if enabled else "LOW"
        )
        return {
            "id": lid,
            "name": locker_cfg["name"],
            "compartment": locker_cfg["compartment"],
            "bcm_pin": bcm_pin,
            "physical_pin": BCM_TO_PHYSICAL.get(bcm_pin) if bcm_pin is not None else None,
            "bus_warning": BUS_WARNINGS.get(bcm_pin) if bcm_pin is not None else None,
            "active_high": active_high,
            "pulse_seconds": locker_cfg["pulse_seconds"],
            "enabled": enabled,
            "is_unlocked": is_unlocked,
            "electrical_state": electrical_state,
            "unlock_until": self._locker_unlock_until.get(lid) if is_unlocked else None,
        }

    def _build_led_view_locked(self, ch: str, led_cfg: Dict[str, Any]) -> Dict[str, Any]:
        bcm_pin = led_cfg["bcm_pin"]
        enabled = led_cfg["enabled"]
        active_high = led_cfg["active_high"]
        is_on = bool(self._led_active.get(ch, False)) if enabled else False
        electrical_state = _logical_to_electrical(is_on, active_high) if enabled else "LOW"
        return {
            "label": led_cfg["label"],
            "bcm_pin": bcm_pin,
            "physical_pin": BCM_TO_PHYSICAL.get(bcm_pin) if bcm_pin is not None else None,
            "bus_warning": BUS_WARNINGS.get(bcm_pin) if bcm_pin is not None else None,
            "active_high": active_high,
            "enabled": enabled,
            "is_on": is_on,
            "electrical_state": electrical_state,
        }

    def control_locker(
        self,
        locker_id: int,
        action: str,
        duration_seconds: Optional[float] = None,
        source: str = "manual",
    ) -> Dict[str, Any]:
        """
        Control an individual locker channel.

        Supported actions: ``pulse``, ``unlock``, ``lock``, ``high``, ``low``.
        Raises ``KeyError`` for unknown locker ID and ``ValueError`` for invalid
        action, disabled locker, or out-of-range pulse duration.
        """
        if isinstance(locker_id, bool) or not isinstance(locker_id, int):
            raise ValueError(f"Invalid locker_id {locker_id!r}; expected integer.")

        act = (action or "").strip().lower()
        if act not in LOCKER_ACTIONS:
            raise ValueError(
                f"Invalid locker action {action!r}. Must be one of: {', '.join(LOCKER_ACTIONS)}."
            )

        with self._lock:
            locker_cfg = self._find_locker_cfg_locked(locker_id)
            if locker_cfg is None:
                raise KeyError(f"Locker ID {locker_id} not found.")

            if not locker_cfg["enabled"] or locker_cfg["bcm_pin"] is None:
                raise ValueError(
                    f"Locker {locker_id} ('{locker_cfg['name']}') is disabled or has no BCM pin."
                )

            pulse_dur = locker_cfg["pulse_seconds"]
            if act == "pulse":
                raw_dur = pulse_dur if duration_seconds is None else duration_seconds
                ok, err, pulse_dur = _validate_float_in_range(
                    raw_dur, "duration_seconds", 0.05, 60.0
                )
                if not ok:
                    raise ValueError(err)

            self._cancel_locker_timer_locked(locker_id)

            active_high = locker_cfg["active_high"]
            dev = (
                self._locker_devices.get(locker_id)
                if self.hardware_mode == "raspberry_pi_gpio"
                else None
            )

            if act == "pulse":
                is_unlocked = True
                electrical = _logical_to_electrical(True, active_high)
                if dev is not None:
                    dev.on()
                self._locker_unlocked[locker_id] = True
                unlock_until = (
                    datetime.now(timezone.utc) + timedelta(seconds=pulse_dur)
                ).isoformat().replace("+00:00", "Z")
                self._locker_unlock_until[locker_id] = unlock_until

                token = object()
                timer = threading.Timer(
                    pulse_dur, self._auto_relock_locker, args=(locker_id, token)
                )
                timer.daemon = True
                self._locker_timer_tokens[locker_id] = token
                self._locker_timers[locker_id] = timer
                timer.start()

            elif act == "unlock":
                is_unlocked = True
                electrical = _logical_to_electrical(True, active_high)
                if dev is not None:
                    dev.on()
                self._locker_unlocked[locker_id] = True
                self._locker_unlock_until[locker_id] = None

            elif act == "lock":
                is_unlocked = False
                electrical = _logical_to_electrical(False, active_high)
                if dev is not None:
                    dev.off()
                self._locker_unlocked[locker_id] = False
                self._locker_unlock_until[locker_id] = None

            elif act == "high":
                electrical = "HIGH"
                is_unlocked = _electrical_to_logical("HIGH", active_high)
                if dev is not None:
                    if active_high:
                        dev.on()
                    else:
                        dev.off()
                self._locker_unlocked[locker_id] = is_unlocked
                self._locker_unlock_until[locker_id] = None

            else:  # act == "low"
                electrical = "LOW"
                is_unlocked = _electrical_to_logical("LOW", active_high)
                if dev is not None:
                    if active_high:
                        dev.off()
                    else:
                        dev.on()
                self._locker_unlocked[locker_id] = is_unlocked
                self._locker_unlock_until[locker_id] = None

            self._record_event_locked(
                channel=locker_cfg["name"],
                bcm_pin=locker_cfg["bcm_pin"],
                action=act,
                electrical_state=electrical,
                logical_state="UNLOCKED" if is_unlocked else "LOCKED",
                source=source,
            )

            view = self._build_locker_view_locked(locker_cfg)
            view["hardware_mode"] = self.hardware_mode
            if act == "pulse":
                view["pulse_seconds"] = pulse_dur
            return view

    def unlock_for_compartments(
        self,
        compartments: List[str],
        source: str = "transaction",
        trigger_type: str = "borrow",
    ) -> List[Dict[str, Any]]:
        """
        Pulse all enabled lockers whose compartment matches any name in ``compartments``
        (case-insensitive, whitespace-trimmed, deduplicated).
        """
        trig = (trigger_type or "borrow").strip().lower()
        with self._lock:
            if trig == "borrow" and not self._config.get("auto_unlock_on_borrow", True):
                return []
            if trig == "return" and not self._config.get("auto_unlock_on_return", True):
                return []

            requested: List[str] = []
            seen_comp: set[str] = set()
            for raw in compartments or []:
                if not isinstance(raw, str):
                    continue
                norm = raw.strip().lower()
                if norm and norm not in seen_comp:
                    seen_comp.add(norm)
                    requested.append(norm)

            if not requested:
                return []

            matched_ids: List[int] = []
            seen_ids: set[int] = set()
            for comp_key in requested:
                for locker in self._config["lockers"]:
                    if not locker["enabled"] or locker["bcm_pin"] is None:
                        continue
                    if locker["compartment"].strip().lower() == comp_key:
                        lid = locker["id"]
                        if lid not in seen_ids:
                            seen_ids.add(lid)
                            matched_ids.append(lid)

            unlocked: List[Dict[str, Any]] = []
            for lid in matched_ids:
                res = self.control_locker(lid, "pulse", source=source)
                unlocked.append(
                    {
                        "id": res["id"],
                        "name": res["name"],
                        "compartment": res["compartment"],
                        "bcm_pin": res["bcm_pin"],
                        "physical_pin": res["physical_pin"],
                        "pulse_seconds": res["pulse_seconds"],
                        "electrical_state": res["electrical_state"],
                        "hardware_mode": self.hardware_mode,
                    }
                )
            return unlocked

    def control_led_channel(
        self,
        channel: str,
        action: str,
        duration_seconds: float = 1.0,
        source: str = "manual",
    ) -> Dict[str, Any]:
        """
        Manually test or override an LED / buzzer channel ('green', 'yellow', 'red', 'buzzer')
        with action 'pulse', 'high', or 'low'.
        """
        ch = (channel or "").strip().lower()
        if ch not in LED_CHANNELS:
            raise ValueError(
                f"Invalid LED channel {channel!r}. Must be one of: {', '.join(LED_CHANNELS)}."
            )

        act = (action or "").strip().lower()
        if act not in LED_ACTIONS:
            raise ValueError(
                f"Invalid LED action {action!r}. Must be one of: {', '.join(LED_ACTIONS)}."
            )

        with self._lock:
            led_cfg = self._config["leds"][ch]
            if not led_cfg["enabled"] or led_cfg["bcm_pin"] is None:
                raise ValueError(
                    f"Channel '{led_cfg['label']}' is disabled or has no BCM pin assigned."
                )

            pulse_dur = 1.0
            if act == "pulse":
                ok, err, pulse_dur = _validate_float_in_range(
                    duration_seconds, "duration_seconds", 0.05, 60.0
                )
                if not ok:
                    raise ValueError(err)

            self._cancel_led_timer_locked(ch)

            active_high = led_cfg["active_high"]
            dev = (
                self._led_devices.get(ch)
                if self.hardware_mode == "raspberry_pi_gpio"
                else None
            )

            if act == "pulse":
                is_on = True
                electrical = _logical_to_electrical(True, active_high)
                if dev is not None:
                    dev.on()
                self._led_active[ch] = True
                if ch in self.led_state:
                    self.led_state[ch] = True

                token = object()
                timer = threading.Timer(
                    pulse_dur, self._auto_restore_led, args=(ch, token)
                )
                timer.daemon = True
                self._led_timer_tokens[ch] = token
                self._led_timers[ch] = timer
                timer.start()

            elif act == "high":
                electrical = "HIGH"
                is_on = _electrical_to_logical("HIGH", active_high)
                if dev is not None:
                    if active_high:
                        dev.on()
                    else:
                        dev.off()
                self._led_active[ch] = is_on
                if ch in self.led_state:
                    self.led_state[ch] = is_on

            else:  # act == "low"
                electrical = "LOW"
                is_on = _electrical_to_logical("LOW", active_high)
                if dev is not None:
                    if active_high:
                        dev.off()
                    else:
                        dev.on()
                self._led_active[ch] = is_on
                if ch in self.led_state:
                    self.led_state[ch] = is_on

            self._record_event_locked(
                channel=led_cfg["label"],
                bcm_pin=led_cfg["bcm_pin"],
                action=act,
                electrical_state=electrical,
                logical_state="ON" if is_on else "OFF",
                source=source,
            )

            view = self._build_led_view_locked(ch, led_cfg)
            view["channel"] = ch
            view["hardware_mode"] = self.hardware_mode
            return view

    def unlock_all_lockers(
        self,
        duration_seconds: Optional[float] = None,
        source: str = "admin_emergency",
    ) -> List[Dict[str, Any]]:
        """Pulse all enabled lockers (auto-relocking after duration_seconds or per-locker pulse)."""
        with self._lock:
            results: List[Dict[str, Any]] = []
            for locker in self._config["lockers"]:
                if locker["enabled"] and locker["bcm_pin"] is not None:
                    results.append(
                        self.control_locker(
                            locker["id"],
                            "pulse",
                            duration_seconds=duration_seconds,
                            source=source,
                        )
                    )
            return results

    def lock_all_lockers(self, source: str = "admin_relock_all") -> List[Dict[str, Any]]:
        """Immediately force-lock all enabled lockers and cancel any pending pulse timers."""
        with self._lock:
            results: List[Dict[str, Any]] = []
            for locker in self._config["lockers"]:
                if locker["enabled"] and locker["bcm_pin"] is not None:
                    results.append(
                        self.control_locker(locker["id"], "lock", source=source)
                    )
            return results

    def get_status(self) -> Dict[str, Any]:
        """Return compact backward-compatible hardware telemetry summary."""
        with self._lock:
            enabled_lockers = [
                l for l in self._config["lockers"] if l["enabled"] and l["bcm_pin"] is not None
            ]
            active_unlocked = sum(
                1 for l in enabled_lockers if self._locker_unlocked.get(l["id"], False)
            )
            return {
                "hardware_mode": self.hardware_mode,
                "is_raspberry_pi": self.is_raspberry_pi,
                "board_model": self.board_model,
                "arch": self.arch,
                "pin_factory": self.pin_factory,
                "gpio_active": self.hardware_mode == "raspberry_pi_gpio",
                "active_high": bool(self._config["leds"]["green"]["active_high"]),
                "current_level": self.current_level,
                "led_state": dict(self.led_state),
                "pins": self.pins,
                "locker_count": len(enabled_lockers),
                "active_unlocked_count": active_unlocked,
                "note": self.status_note,
            }

    def get_full_state(self) -> Dict[str, Any]:
        """Return complete GPIO configuration, live electrical states, pin maps, and diagnostics."""
        with self._lock:
            lockers_view = [
                self._build_locker_view_locked(locker)
                for locker in self._config["lockers"]
            ]
            leds_view = {
                ch: self._build_led_view_locked(ch, self._config["leds"][ch])
                for ch in LED_CHANNELS
            }
            return {
                "status": self.get_status(),
                "config": copy.deepcopy(self._config),
                "lockers": lockers_view,
                "leds": leds_view,
                "bcm_to_physical": dict(BCM_TO_PHYSICAL),
                "bus_warnings": dict(BUS_WARNINGS),
                "diagnostic_log": list(self._diag_log)[:_DIAG_PUBLIC_LIMIT],
            }

    def cleanup(self) -> None:
        """Cancel all active timers and safely release all open GPIO handles."""
        with self._lock:
            self._cancel_all_timers_locked()
            self._close_devices_locked()
            for lid in list(self._locker_unlocked.keys()):
                self._locker_unlocked[lid] = False
                self._locker_unlock_until[lid] = None
            for ch in LED_CHANNELS:
                self._led_active[ch] = False
