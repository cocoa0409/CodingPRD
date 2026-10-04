"""Payload factories — one per write endpoint, input fields only.

Date defaults are chosen to be reachable from the default logical clock
2026-09-01T00:00:00Z (PRD §2.4):
- agreement window 2026-01-01..2027-12-31 brackets the default clock date;
- requested_install_date 2026-12-15 satisfies clock + max_lead_time_days for
  every catalog configuration (max possible lead is 365+21+12, but every
  fixture family here uses base <= 42, so lead <= 59 << 105 days);
- production_date 2026-11-02 satisfies notice (>= clock + 2) and transit
  (<= 2026-12-15 - 4 for PLANT_GR) at the default clock;
- window defaults sit inside a normal install week in December.
"""
import itertools
import uuid

from .constants import DEFAULT_CLOCK_UTC

_family_counter = itertools.count(1)

# Clock-reachable date defaults (see module docstring).
DEFAULT_AGREEMENT_START = "2026-01-01"
DEFAULT_AGREEMENT_END = "2027-12-31"
DEFAULT_TIER_DISCOUNTS = (0.10, 0.15, 0.20)
DEFAULT_REQUESTED_INSTALL_DATE = "2026-12-15"
DEFAULT_PRODUCTION_DATE = "2026-11-02"
DEFAULT_WINDOW_START = "2026-12-01T09:00:00Z"
DEFAULT_WINDOW_END = "2026-12-01T12:00:00Z"
DEFAULT_LAST_ORDER_DATE = "2026-12-31"

_UNSET = object()


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:6].upper()


def make_dealer_payload(**overrides) -> dict:
    """PRD §3.1 inputs: name, territory_codes, service_capability_level,
    optional showroom_compliant (defaults server-side to true)."""
    payload = {
        "name": f"Dealer {_unique_suffix()}",
        "territory_codes": ["MI", "OH"],
        "service_capability_level": 4,
    }
    payload.update(overrides)
    return payload


def make_end_user_payload(**overrides) -> dict:
    """PRD §3.2 inputs: name, industry."""
    payload = {
        "name": f"EndUser {_unique_suffix()}",
        "industry": "technology",
    }
    payload.update(overrides)
    return payload


def make_volume_agreement_payload(end_user_id, **overrides) -> dict:
    """PRD §3.2 inputs: end_user_id, effective window, three tier discounts."""
    payload = {
        "end_user_id": end_user_id,
        "effective_start": DEFAULT_AGREEMENT_START,
        "effective_end": DEFAULT_AGREEMENT_END,
        "tier1_discount_pct": DEFAULT_TIER_DISCOUNTS[0],
        "tier2_discount_pct": DEFAULT_TIER_DISCOUNTS[1],
        "tier3_discount_pct": DEFAULT_TIER_DISCOUNTS[2],
    }
    payload.update(overrides)
    return payload


def make_product_family_payload(**overrides) -> dict:
    """PRD §3.3 inputs: family_code (unique), name, category,
    base_lead_time_days. family_code is auto-uniquified per call."""
    n = next(_family_counter)
    payload = {
        "family_code": f"FAM-{n:03d}-{_unique_suffix()}",
        "name": f"Family {n}",
        "category": "SEATING",
        "base_lead_time_days": 28,
    }
    payload.update(overrides)
    return payload


def make_module_entry(module_type="TASK_CHAIR_SET", fabric_grade=_UNSET, qty=4) -> dict:
    """One modules[] entry. fabric_grade defaults to None for STORAGE_WALL
    (fabric must be absent) and "A" otherwise (fabric required)."""
    if fabric_grade is _UNSET:
        fabric_grade = None if module_type == "STORAGE_WALL" else "A"
    return {
        "module_type": module_type,
        "fabric_grade": fabric_grade,
        "qty": qty,
    }


def make_configuration_payload(**overrides) -> dict:
    """PRD §3.4 inputs: name, modules (non-empty)."""
    payload = {
        "name": f"Config {_unique_suffix()}",
        "modules": [make_module_entry()],
    }
    payload.update(overrides)
    return payload


def make_project_order_payload(volume_agreement_id, configuration_id, **overrides) -> dict:
    """PRD §3.5 inputs: volume_agreement_id, configuration_id, territory_code,
    requested_install_date."""
    payload = {
        "volume_agreement_id": volume_agreement_id,
        "configuration_id": configuration_id,
        "territory_code": "MI",
        "requested_install_date": DEFAULT_REQUESTED_INSTALL_DATE,
    }
    payload.update(overrides)
    return payload


def make_submit_payload(expected_order_version) -> dict:
    return {"expected_order_version": expected_order_version}


def make_lock_payload(expected_configuration_version) -> dict:
    return {"expected_configuration_version": expected_configuration_version}


def make_phase_payload(**overrides) -> dict:
    """PRD §3.6 inputs: floor_number, phase_sequence, building_zone_id,
    planned_units."""
    payload = {
        "floor_number": 1,
        "phase_sequence": 1,
        "building_zone_id": "Z1",
        "planned_units": 10,
    }
    payload.update(overrides)
    return payload


def make_reserve_slot_payload(**overrides) -> dict:
    """PRD §3.6 inputs: plant_code, production_date."""
    payload = {
        "plant_code": "PLANT_GR",
        "production_date": DEFAULT_PRODUCTION_DATE,
    }
    payload.update(overrides)
    return payload


def make_install_window_payload(installation_phase_id, **overrides) -> dict:
    """PRD §3.7 inputs: installation_phase_id, start_at, end_at,
    union_required, elevator_required, crew_size."""
    payload = {
        "installation_phase_id": installation_phase_id,
        "start_at": DEFAULT_WINDOW_START,
        "end_at": DEFAULT_WINDOW_END,
        "union_required": False,
        "elevator_required": True,
        "crew_size": 4,
    }
    payload.update(overrides)
    return payload


def make_punch_ticket_payload(installation_phase_id, **overrides) -> dict:
    """PRD §3.8 inputs: installation_phase_id, severity, description,
    optional requires_part (default false) / part_number."""
    payload = {
        "installation_phase_id": installation_phase_id,
        "severity": "MINOR",
        "description": "Punch item",
    }
    payload.update(overrides)
    return payload


def make_resolve_payload(resolution_note="Resolved") -> dict:
    return {"resolution_note": resolution_note}


def make_verify_payload(outcome="CONFIRMED") -> dict:
    return {"outcome": outcome}


def make_warranty_claim_payload(project_order_id, installation_phase_id, **overrides) -> dict:
    """PRD §3.8 inputs: project_order_id, installation_phase_id, claim_type,
    description, part_number (required exactly when claim_type is PARTS)."""
    payload = {
        "project_order_id": project_order_id,
        "installation_phase_id": installation_phase_id,
        "claim_type": "LABOR",
        "description": "Warranty claim",
    }
    payload.update(overrides)
    return payload


def make_review_payload(decision="APPROVE", review_note=None) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def make_cancel_payload(reason=None) -> dict:
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    return payload


def make_clock_payload(to_iso8601=DEFAULT_CLOCK_UTC) -> dict:
    return {"to_iso8601": to_iso8601}
