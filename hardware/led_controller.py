#!/usr/bin/env python3
"""
LabGuard+ Raspberry Pi GPIO LED Safety Status Controller (Compatibility Wrapper).

Backward-compatible wrapper around :class:`hardware.gpio_manager.GPIOManager` so
existing callers importing ``SafetyLEDController`` continue working seamlessly
while gaining full Raspberry Pi 2/3/4/5 locker & LED GPIO support.
"""

from __future__ import annotations

import os
from typing import Optional

from hardware.gpio_manager import (
    BCM_TO_PHYSICAL,
    BUS_WARNINGS,
    GPIOManager,
    _detect_board_info,
    _parse_env_mode,
    _parse_env_optional_pin,
    get_default_gpio_config,
    validate_gpio_config,
)


def _detect_raspberry_pi() -> bool:
    """Return True if running on a Raspberry Pi Linux kernel."""
    is_pi, _, _ = _detect_board_info()
    return is_pi


def _parse_optional_pin(env_name: str, default: Optional[int]) -> Optional[int]:
    return _parse_env_optional_pin(env_name, default)


def _parse_bool_mode(env_name: str, default: str = "auto") -> str:
    mode = _parse_env_mode(env_name, default)
    return "disabled" if mode == "simulation" else mode


class SafetyLEDController(GPIOManager):
    """Backward-compatible wrapper around :class:`GPIOManager`."""

    def __init__(self) -> None:
        super().__init__(initial_config=None)


__all__ = [
    "BCM_TO_PHYSICAL",
    "BUS_WARNINGS",
    "GPIOManager",
    "SafetyLEDController",
    "get_default_gpio_config",
    "validate_gpio_config",
    "_detect_raspberry_pi",
    "_parse_optional_pin",
    "_parse_bool_mode",
]
