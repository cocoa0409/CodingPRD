"""Payload factories — one per entity, input fields only, plus action/line builders.

Entity factories accept **overrides so tests control exactly the fields under
study; everything else gets a PRD-consistent default. Catalog codes, serial
numbers, lot numbers, and update versions default to counter-unique values so
multiple resources can be created inside one test without uniqueness clashes.
"""
from itertools import count as _count

from .constants import TEST_DEFAULTS as _D

__all__ = [
    "create_account_payload",
    "create_instrument_model_payload",
    "create_reagent_kit_payload",
    "create_software_update_payload",
    "create_instrument_payload",
    "create_placement_program_payload",
    "create_reagent_lot_payload",
    "create_reagent_order_payload",
    "create_service_contract_payload",
    "create_software_license_payload",
    "create_credit_grant_payload",
    "create_run_record_payload",
    "create_transition_program_payload",
    "create_supply_forecast_payload",
    "hardware_line",
    "order_line",
    "forecast_line",
    "instrument_event_payload",
    "program_review_payload",
    "program_amendment_payload",
    "order_advance_payload",
    "lot_qc_payload",
    "license_status_payload",
    "transition_advance_payload",
    "forecast_advance_payload",
    "uptime_reconciliation_payload",
    "clock_payload",
]

_account_seq = _count(1)
_model_seq = _count(1)
_kit_seq = _count(1)
_serial_seq = _count(1)
_lot_seq = _count(1)
_update_seq = _count(1)


# ---------------------------------------------------------------------------
# Entity creation payloads (input fields only)
# ---------------------------------------------------------------------------
def create_account_payload(**overrides) -> dict:
    n = next(_account_seq)
    defaults = {
        "name": f"Test Lab {n}",
        "regulatory_class": "RUO",
        "region": _D["ACCOUNT_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_instrument_model_payload(**overrides) -> dict:
    n = next(_model_seq)
    defaults = {
        "model_code": f"SQ-T{n:03d}",
        "generation": _D["MODEL_GENERATION"],
        "base_price_cents": _D["MODEL_BASE_PRICE_CENTS"],
        "supported_chemistry_versions": ["V1"],
        "base_run_modes": ["STD_SHORT"],
        # support_status omitted on purpose: PRD defaults it to CURRENT.
    }
    defaults.update(overrides)
    return defaults


def create_reagent_kit_payload(**overrides) -> dict:
    n = next(_kit_seq)
    defaults = {
        "kit_code": f"K-T{n:03d}",
        "run_type": "STD_SHORT",
        "flow_cell_version": "FC_LOW",
        "chemistry_version": "V1",
        "regulatory_clearance": "RUO_ONLY",
        "shelf_life_days": _D["KIT_SHELF_LIFE_DAYS"],
        "cold_chain_class": "FROZEN_20",
        "price_cents": _D["KIT_PRICE_CENTS"],
        "samples_per_kit": _D["KIT_SAMPLES_PER_KIT"],
        "min_model_generation": _D["KIT_MIN_MODEL_GENERATION"],
    }
    defaults.update(overrides)
    return defaults


def create_software_update_payload(**overrides) -> dict:
    n = next(_update_seq)
    defaults = {
        "update_version": f"9.{n}.0",
        "min_model_generation": 1,
        "unlocks_run_modes": ["STD_LONG"],
        "clinical_validation_status": "VALIDATED",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(account_id: str, model_id: str, **overrides) -> dict:
    n = next(_serial_seq)
    defaults = {
        "account_id": account_id,
        "model_id": model_id,
        "serial_number": f"SN-T{n:04d}",
        "regulatory_mode": "RUO",
        # installed_at omitted on purpose: PRD stamps it at INSTALL when absent.
    }
    defaults.update(overrides)
    return defaults


def create_placement_program_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "term_months": _D["PROGRAM_TERM_MONTHS"],
        "committed_annual_reagent_cents": _D["PROGRAM_COMMITTED_ANNUAL_CENTS"],
        "subsidy_pct": _D["PROGRAM_SUBSIDY_PCT"],
        "hardware_lines": [hardware_line()],
    }
    defaults.update(overrides)
    return defaults


def create_reagent_lot_payload(kit_id: str, **overrides) -> dict:
    n = next(_lot_seq)
    defaults = {
        "kit_id": kit_id,
        "lot_number": f"LOT-T{n:04d}",
        "manufacture_date": _D["LOT_MANUFACTURE_DATE"],
        "quantity_units": _D["LOT_QUANTITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_reagent_order_payload(account_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "lines": lines,
        # program_id omitted unless supplied: it is optional.
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(account_id: str, instrument_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "coverage_start": _D["COVERAGE_START"],
        "coverage_end": _D["COVERAGE_END"],
        "committed_uptime_percent": _D["CONTRACT_COMMITTED_UPTIME_PERCENT"],
        "monthly_fee_cents": _D["CONTRACT_MONTHLY_FEE_CENTS"],
        "annual_credit_cap_cents": _D["CONTRACT_ANNUAL_CREDIT_CAP_CENTS"],
        # reagent_guarantee omitted: PRD defaults it to false.
    }
    defaults.update(overrides)
    return defaults


def create_software_license_payload(account_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


def create_credit_grant_payload(credits: int, **overrides) -> dict:
    defaults = {
        "credits": credits,
        "grant_type": "PURCHASE",
        # granted_on omitted unless supplied: defaults to the current clock date.
    }
    defaults.update(overrides)
    return defaults


def create_run_record_payload(
    instrument_id: str, lot_id: str, license_id: str, **overrides
) -> dict:
    defaults = {
        "instrument_id": instrument_id,
        "lot_id": lot_id,
        "license_id": license_id,
        "run_at": _D["RUN_AT"],
        "run_mode": "STD_SHORT",
        "analysis_mode": "LOCAL",
        "samples_count": 10,
        "output_gb": 1.0,
        "outcome": "SUCCESS",
    }
    defaults.update(overrides)
    return defaults


def create_transition_program_payload(
    account_id: str, old_instrument_id: str, new_model_id: str, **overrides
) -> dict:
    defaults = {
        "account_id": account_id,
        "old_instrument_id": old_instrument_id,
        "new_model_id": new_model_id,
        "enrollment_window_end": _D["TRANSITION_ENROLLMENT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_forecast_payload(account_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Line builders
# ---------------------------------------------------------------------------
def hardware_line(description: str = "instrument", quantity: int = 1,
                  unit_price_cents: int = None) -> dict:
    return {
        "description": description,
        "quantity": quantity,
        "unit_price_cents": (
            unit_price_cents
            if unit_price_cents is not None
            else _D["PROGRAM_HARDWARE_UNIT_PRICE_CENTS"]
        ),
    }


def order_line(kit_code: str, quantity: int) -> dict:
    return {"kit_code": kit_code, "quantity": quantity}


def forecast_line(kit_code: str, week_start: str = None, quantity: int = 10) -> dict:
    return {
        "kit_code": kit_code,
        "week_start": week_start if week_start is not None else _D["FORECAST_WEEK_START"],
        "quantity": quantity,
    }


# ---------------------------------------------------------------------------
# Action payloads for multi-action endpoints
# ---------------------------------------------------------------------------
def instrument_event_payload(action: str) -> dict:
    return {"action": action}


def program_review_payload(action: str) -> dict:
    return {"action": action}


def program_amendment_payload(
    action: str,
    expected_program_version: int = None,
    new_committed_annual_reagent_cents: int = None,
    new_subsidy_pct: float = None,
) -> dict:
    payload: dict = {"action": action}
    if expected_program_version is not None:
        payload["expected_program_version"] = expected_program_version
    if new_committed_annual_reagent_cents is not None:
        payload["new_committed_annual_reagent_cents"] = new_committed_annual_reagent_cents
    if new_subsidy_pct is not None:
        payload["new_subsidy_pct"] = new_subsidy_pct
    return payload


def order_advance_payload(action: str) -> dict:
    return {"action": action}


def lot_qc_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def license_status_payload(action: str) -> dict:
    return {"action": action}


def transition_advance_payload(action: str, condition_flags: list = None) -> dict:
    payload: dict = {"action": action}
    if condition_flags is not None:
        payload["condition_flags"] = condition_flags
    return payload


def forecast_advance_payload(action: str, expected_forecast_version: int = None) -> dict:
    payload: dict = {"action": action}
    if expected_forecast_version is not None:
        payload["expected_forecast_version"] = expected_forecast_version
    return payload


def uptime_reconciliation_payload(period_start: str, period_end: str) -> dict:
    return {"period_start": period_start, "period_end": period_end}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
