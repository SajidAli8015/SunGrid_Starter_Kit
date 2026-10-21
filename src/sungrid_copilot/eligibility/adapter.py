"""The only code that touches the eligibility service.

The service is loaded by module and function name from config, so nothing depends on where the
stub lives. Inputs are validated and normalised BEFORE the call (the service itself trusts its
inputs: for example it treats any non-empty string, including "no", as an approved installer).
The service's eligibility logic is never copied here: program rules such as the eligible size range
are left to the service.

Problems are returned as codes, never with the raw value, so nothing here can leak a member's
income or ZIP into logs or messages.
"""

from __future__ import annotations

import importlib
import math
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sungrid_copilot.config import ConfigError, Settings

_ZIP_RE = re.compile(r"^(\d{5})(?:-\d{4})?$")
MAX_SYSTEM_SIZE_KW = 10000  # sanity bound only, not a program rule
SERVICE_FIELDS = ("household_zip", "annual_income_usd", "system_size_kw", "installer_approved")


@dataclass(frozen=True)
class InvalidInput:
    field: str
    problem: str  # a code from messages.yaml `problems`
    escalate: bool = False  # the member can correct it


@dataclass(frozen=True)
class RawResult:
    raw: Any  # unvalidated service output; only gate.evaluate may interpret it


@dataclass(frozen=True)
class ToolError:
    kind: str  # "timeout" | "exception" | "malformed_result"
    detail: str = ""  # sanitised: an exception type name, never input values
    escalate: bool = True


AdapterResult = InvalidInput | RawResult | ToolError


def _normalise_zip(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value:05d}" if 0 <= value <= 99999 else None
    if isinstance(value, str):
        match = _ZIP_RE.match(value.strip())
        return match.group(1) if match else None
    return None


def _number_problem(value: object, *, allow_zero: bool, upper: float | None = None) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "not_a_number"
    if not math.isfinite(value):
        return "not_finite"
    if value <= 0 and not allow_zero:
        return "not_positive"
    if value < 0:
        return "negative"
    if upper is not None and value > upper:
        return "too_large"
    return None


def validate_inputs(slots: Mapping[str, Any]) -> InvalidInput | dict[str, Any]:
    """Normalised service arguments, or the first invalid field."""
    zip_code = _normalise_zip(slots.get("household_zip"))
    if zip_code is None:
        return InvalidInput("household_zip", "not_a_zip")

    income = slots.get("annual_income_usd")
    if problem := _number_problem(income, allow_zero=True):
        return InvalidInput("annual_income_usd", problem)

    size = slots.get("system_size_kw")
    if problem := _number_problem(size, allow_zero=False, upper=MAX_SYSTEM_SIZE_KW):
        return InvalidInput("system_size_kw", problem)

    approved = slots.get("installer_approved")
    if type(approved) is not bool:  # strict: no "no", no 1
        return InvalidInput("installer_approved", "not_yes_no")

    return {
        "household_zip": zip_code,
        "annual_income_usd": float(income),
        "system_size_kw": float(size),
        "installer_approved": approved,
    }


class EligibilityAdapter:
    def __init__(self, service: Callable[..., Any], *, timeout_s: float = 5.0):
        self._service = service
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls, settings: Settings) -> EligibilityAdapter:
        cfg = settings.eligibility
        try:
            module = importlib.import_module(cfg.service_module)
            service = getattr(module, cfg.service_function)
        except (ImportError, AttributeError) as e:
            raise ConfigError(
                f"Cannot load eligibility service {cfg.service_module}.{cfg.service_function} "
                "(eligibility.service_module / service_function in config.yaml). Run from the "
                "repo root so the service module is importable."
            ) from e
        if not callable(service):
            raise ConfigError(f"{cfg.service_module}.{cfg.service_function} is not callable.")
        return cls(service, timeout_s=cfg.timeout_s)

    def check(self, slots: Mapping[str, Any] | Any) -> AdapterResult:
        """Validate, normalise, then make a single call with a timeout. Never raises."""
        values = slots.model_dump() if hasattr(slots, "model_dump") else dict(slots)
        normalised = validate_inputs(values)
        if isinstance(normalised, InvalidInput):
            return normalised

        # Run in a daemon thread so a hung service can hang neither the reply nor process exit.
        # A timed-out call keeps running in its thread (Python cannot kill it); its result is
        # discarded, and the thread dies with the process.
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["result"] = self._service(**normalised)
            except Exception as e:  # the service failed; no details that could hold member data
                box["error"] = type(e).__name__

        thread = threading.Thread(target=call, name="eligibility", daemon=True)
        thread.start()
        thread.join(self.timeout_s)
        if thread.is_alive():
            return ToolError("timeout")
        if "error" in box:
            return ToolError("exception", box["error"])
        return RawResult(box.get("result"))  # nothing stored -> None, which the gate rejects
