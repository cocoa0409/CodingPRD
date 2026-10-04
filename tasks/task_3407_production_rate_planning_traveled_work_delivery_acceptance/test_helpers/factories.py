"""Payload factories — one per endpoint request body, input fields only (PRD §3/§4)."""
import itertools

from .constants import TEST_DEFAULTS as D

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Unique suffix so uniqueness-guarded codes never collide across tests."""
    return f"{prefix}-{next(_seq)}"


# --- Registrations (PRD §3.1) ---

def create_program_payload(**overrides) -> dict:
    defaults = {
        "model_code": _uniq(D["MODEL_CODE"]),
        "current_rate_per_month": D["CURRENT_RATE_PER_MONTH"],
        "required_component_codes": D["REQUIRED_COMPONENT_CODES"],
        "rework_budget_total_cents": D["REWORK_BUDGET_TOTAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": _uniq(D["SUPPLIER_CODE"]),
        "name": D["SUPPLIER_NAME"],
        "region": D["SUPPLIER_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "airline_code": _uniq(D["CUSTOMER_AIRLINE_CODE"]),
        "name": D["CUSTOMER_NAME"],
        "credit_standing": D["CUSTOMER_CREDIT_STANDING"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_unit_payload(program_customer_id, **overrides) -> dict:
    """PRD §3.1: customer_id, unique-per-program line_number, both config codes,
    contract_price_cents >= 1, contracted_delivery_date."""
    defaults = {
        "customer_id": program_customer_id,
        "line_number": D["LINE_NUMBER"],
        "configuration_code": D["CONFIGURATION_CODE"],
        "ordered_configuration_code": D["CONFIGURATION_CODE"],
        "contract_price_cents": D["CONTRACT_PRICE_CENTS"],
        "contracted_delivery_date": D["CONTRACTED_DELIVERY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_workforce_plan_payload(**overrides) -> dict:
    defaults = {
        "skill_code": _uniq(D["SKILL_CODE"]),
        "required_headcount": D["REQUIRED_HEADCOUNT"],
    }
    defaults.update(overrides)
    return defaults


def hire_payload(count=D["REQUIRED_HEADCOUNT"], **overrides) -> dict:
    defaults = {"count": count}
    defaults.update(overrides)
    return defaults


# --- Rate cases (PRD §3.2) ---

def create_rate_case_payload(expected_program_version, **overrides) -> dict:
    """OCC-guarded create: expected_program_version is required (PRD §2.7)."""
    defaults = {
        "proposed_rate": D["PROPOSED_RATE"],
        "effective_month": D["EFFECTIVE_MONTH"],
        "demand_backlog_units": D["DEMAND_BACKLOG_UNITS"],
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


# --- Capacity commitments (PRD §3.3) ---

def create_commitment_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "component_code": D["COMPONENT_CODE"],
        "committed_rate_per_month": D["COMMITTED_RATE_PER_MONTH"],
        "lead_time_months": D["LEAD_TIME_MONTHS"],
        "unit_price_cents": D["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def place_order_payload(**overrides) -> dict:
    defaults = {
        "quantity": D["ORDER_QUANTITY"],
        "assumed_rate_per_month": D["ASSUMED_RATE_PER_MONTH"],
        "required_by_month": D["REQUIRED_BY_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def cancel_commitment_payload(cancel_quantity=None) -> dict:
    """cancel_quantity optional (PRD §3.3: omitted defaults to active quantity)."""
    if cancel_quantity is None:
        return {}
    return {"cancel_quantity": cancel_quantity}


# --- Work packages and rework (PRD §3.4, §3.5) ---

def create_work_package_payload(**overrides) -> dict:
    defaults = {
        "station_sequence": D["STATION_SEQUENCE"],
        "description": D["WORK_PACKAGE_DESCRIPTION"],
        "planned_hours": D["PLANNED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def travel_work_package_payload(traveled_hours=4, **overrides) -> dict:
    """traveled_hours >= 1 (PRD §3.4)."""
    defaults = {"traveled_hours": traveled_hours}
    defaults.update(overrides)
    return defaults


def create_escape_rework_order_payload(estimated_hours=3, **overrides) -> dict:
    defaults = {"estimated_hours": estimated_hours}
    defaults.update(overrides)
    return defaults


def close_rework_order_payload(actual_hours=4, parts_cents=0, **overrides) -> dict:
    defaults = {"actual_hours": actual_hours, "parts_cents": parts_cents}
    defaults.update(overrides)
    return defaults


# --- Quality escapes (PRD §3.6) ---

def report_escape_payload(**overrides) -> dict:
    defaults = {"severity": "MAJOR", "description": "Nonconformance"}
    defaults.update(overrides)
    return defaults


def begin_root_cause_payload(conformance_refs=None, **overrides) -> dict:
    """conformance_refs must carry >= 1 entry (PRD §3.6)."""
    defaults = {"conformance_refs": conformance_refs if conformance_refs is not None else ["DOC-1"]}
    defaults.update(overrides)
    return defaults


def disposition_payload(disposition_code="USE_AS_IS", **overrides) -> dict:
    defaults = {"disposition_code": disposition_code}
    defaults.update(overrides)
    return defaults


# --- Flight tests and delivery pipeline (PRD §3.8) ---

def schedule_flight_test_payload(**overrides) -> dict:
    defaults = {
        "range_code": D["RANGE_CODE"],
        "window_start": D["FLIGHT_WINDOW_START"],
        "window_end": D["FLIGHT_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def record_outcome_payload(outcome="PASS", rework_estimated_hours=None, **overrides) -> dict:
    """rework_estimated_hours optional; only meaningful on FAIL (PRD §3.5/§3.8)."""
    defaults = {"outcome": outcome}
    if rework_estimated_hours is not None:
        defaults["rework_estimated_hours"] = rework_estimated_hours
    defaults.update(overrides)
    return defaults


def conduct_walkthrough_payload(snag_count=0, **overrides) -> dict:
    defaults = {"snag_count": snag_count}
    defaults.update(overrides)
    return defaults


# --- Storage (PRD §3.7) ---

def create_storage_preservation_payload(**overrides) -> dict:
    defaults = {
        "bay_code": D["BAY_CODE"],
        "window_start": D["STORAGE_WINDOW_START"],
        "window_end": D["STORAGE_WINDOW_END"],
        "daily_rate_cents": D["DAILY_RATE_CENTS"],
        "preservation_cycle_days": D["PRESERVATION_CYCLE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


# --- Delivery negotiations (PRD §3.9) ---

def create_delivery_negotiation_payload(**overrides) -> dict:
    defaults = {
        "proposed_delivery_date": D["PROPOSED_DELIVERY_DATE"],
        "compensation_variant": D["COMPENSATION_VARIANT"],
    }
    defaults.update(overrides)
    return defaults


def counter_negotiation_payload(expected_negotiation_version, **overrides) -> dict:
    """OCC-guarded counter: expected_negotiation_version is required (PRD §2.7)."""
    defaults = {
        "proposed_delivery_date": D["PROPOSED_DELIVERY_DATE"],
        "compensation_variant": D["COMPENSATION_VARIANT"],
        "expected_negotiation_version": expected_negotiation_version,
    }
    defaults.update(overrides)
    return defaults


# --- Logical clock (PRD §2.4) ---

def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
