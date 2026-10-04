"""Payload factories — one per writable endpoint body, input fields only.

Each factory supplies contract-valid defaults so a test only overrides the
field under test. Defaults use the same names the PRD's examples and
narratives use; nothing here performs network I/O.
"""

from typing import Any, Dict, List, Optional

from .constants import MIN_PREPAYMENT_CENTS

DEFAULTS = {
    "MAKER_NAME": "Acme Devices",
    "MAKER_REGION": "US",
    "PROGRAM_NAME": "Eagle",
    "PRIMARY_MARKET": "CONSUMER_ELECTRONICS",
    "NDA_REFERENCE": "NDA-001",
    "DESIGN_FREEZE_DATE": "2027-03-01T00:00:00Z",
    "COMPOSITION_CODE": "GX-100",
    "COMPLEXITY_MULTIPLIER": 1.0,
    "TEST_PLAN_REF": "TP-1",
    "COMMITTED_UNITS": 5000,
    "REQUIRED_UNITS": 5000,
    # 2500000 cents buys 2500 credit units; base 7500 over required 5000 is
    # coverage 1.5, comfortably over the confirmation gate.
    "PREPAYMENT_CENTS": 2500000,
    "CAPACITY_UNITS_PER_DAY": 1000,
    "CAMPAIGN_START": "2028-03-01T00:00:00Z",
    "CAMPAIGN_END": "2029-03-01T00:00:00Z",
    "PLANNED_UNITS": 10000,
    "ALLOCATION_UNITS": 1000,
    "LICENSE_EFFECTIVE": "2027-01-01T00:00:00Z",
    "LICENSE_EXPIRY": "2028-12-31T00:00:00Z",
    "MARKETING_MATERIALS_REF": "MKT-1",
    "REPORT_PERIOD_START": "2027-01-01T00:00:00Z",
    "REPORT_PERIOD_END": "2027-03-31T00:00:00Z",
    "RECORD_DATE": "2028-06-01T00:00:00Z",
}


# ── Device makers ────────────────────────────────────────────────────────────

def create_device_maker_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": DEFAULTS["MAKER_NAME"],
        "region": DEFAULTS["MAKER_REGION"],
    }
    defaults.update(overrides)
    return defaults


def ip_review_payload(to_status: str = "UNDER_REVIEW", **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"to_status": to_status}
    defaults.update(overrides)
    return defaults


# ── Programs ─────────────────────────────────────────────────────────────────

def create_program_payload(device_maker_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "device_maker_id": device_maker_id,
        "name": DEFAULTS["PROGRAM_NAME"],
        "primary_market": DEFAULTS["PRIMARY_MARKET"],
    }
    defaults.update(overrides)
    return defaults


def execute_nda_payload(nda_reference: str = DEFAULTS["NDA_REFERENCE"], **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"nda_reference": nda_reference}
    defaults.update(overrides)
    return defaults


def begin_qualification_payload(
    design_freeze_date: str = DEFAULTS["DESIGN_FREEZE_DATE"], **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"design_freeze_date": design_freeze_date}
    defaults.update(overrides)
    return defaults


# ── Compositions and qualification cycles ────────────────────────────────────

def create_composition_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "program_id": program_id,
        "composition_code": DEFAULTS["COMPOSITION_CODE"],
        "complexity_multiplier": DEFAULTS["COMPLEXITY_MULTIPLIER"],
    }
    defaults.update(overrides)
    return defaults


def create_qual_cycle_payload(composition_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "composition_id": composition_id,
        "test_plan_ref": DEFAULTS["TEST_PLAN_REF"],
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(outcome: str = "PASSED", **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


# ── Commitments ──────────────────────────────────────────────────────────────

def create_commitment_payload(
    program_id: str,
    expected_program_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "program_id": program_id,
        "committed_units": DEFAULTS["COMMITTED_UNITS"],
        "required_units": DEFAULTS["REQUIRED_UNITS"],
        "prepayment_cents": DEFAULTS["PREPAYMENT_CENTS"],
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def apply_prepayment_payload(
    amount_cents: int = MIN_PREPAYMENT_CENTS, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


# ── Tanks and campaigns ──────────────────────────────────────────────────────

def create_tank_payload(commitment_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "commitment_id": commitment_id,
        "capacity_units_per_day": DEFAULTS["CAPACITY_UNITS_PER_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(tank_id: str, composition_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "tank_id": tank_id,
        "composition_id": composition_id,
        "start_date": DEFAULTS["CAMPAIGN_START"],
        "end_date": DEFAULTS["CAMPAIGN_END"],
        "planned_units": DEFAULTS["PLANNED_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def record_production_payload(
    good_units: int,
    scrap_units: int,
    record_date: str = DEFAULTS["RECORD_DATE"],
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "record_date": record_date,
        "good_units": good_units,
        "scrap_units": scrap_units,
    }
    defaults.update(overrides)
    return defaults


# ── Allocations ──────────────────────────────────────────────────────────────

def create_allocation_payload(
    commitment_id: str,
    campaign_id: str,
    expected_commitment_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "commitment_id": commitment_id,
        "campaign_id": campaign_id,
        "units": DEFAULTS["ALLOCATION_UNITS"],
        "expected_commitment_version": expected_commitment_version,
    }
    defaults.update(overrides)
    return defaults


# ── Licenses ─────────────────────────────────────────────────────────────────

def create_license_payload(device_maker_id: str, program_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "device_maker_id": device_maker_id,
        "program_id": program_id,
        "market": DEFAULTS["PRIMARY_MARKET"],
        "effective_date": DEFAULTS["LICENSE_EFFECTIVE"],
        "expiry_date": DEFAULTS["LICENSE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def submit_marketing_payload(
    materials_ref: str = DEFAULTS["MARKETING_MATERIALS_REF"], **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"materials_ref": materials_ref}
    defaults.update(overrides)
    return defaults


def review_marketing_payload(decision: str = "APPROVED", **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ── Usage reports ────────────────────────────────────────────────────────────

def usage_report_line(
    channel: str = "DOMESTIC",
    units: int = 100,
    net_revenue_cents: int = 50000,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "channel": channel,
        "units": units,
        "net_revenue_cents": net_revenue_cents,
    }
    defaults.update(overrides)
    return defaults


def create_usage_report_payload(
    license_id: str,
    lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "license_id": license_id,
        "period_start": DEFAULTS["REPORT_PERIOD_START"],
        "period_end": DEFAULTS["REPORT_PERIOD_END"],
        "lines": lines if lines is not None else [usage_report_line()],
    }
    defaults.update(overrides)
    return defaults


# ── Logical clock ────────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
