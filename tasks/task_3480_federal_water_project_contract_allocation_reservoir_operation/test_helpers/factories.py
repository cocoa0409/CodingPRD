"""Request payload builders.

Each builder returns a valid body for one write endpoint, with sensible
defaults drawn from the shared setup data in ``constants`` that any test can
override by keyword. Money is emitted as JSON integers (cents), water volumes
as integer acre-feet, flow rates as integer cfs, and percentages as integers
from 0 to 100 - the representations the contract fixes (PRD §2.6).

Optional fields are only emitted when supplied: ``price_cents`` on a transfer
is omitted by default so the server-side default of 0 applies, and the
conditional fields of an environmental constraint are emitted per
``requirement_type`` (``required_min_cfs`` for MIN_FLOW / PULSE_FLOW,
``max_release_cfs`` for MAX_RELEASE - PRD §3.5).
"""

from typing import Any, Dict, Optional

from .constants import (
    AGREEMENT_NAME,
    CLOCK_OCTOBER,
    CONTRACT_JR,
    CONTRACT_SR,
    CONTRACT_TP,
    DISTRICT_JR,
    DISTRICT_SR,
    DISTRICT_TP,
    OBSERVED_ON_BASE,
    QUORUM_TWO,
    RESERVOIR_BIG,
    RESERVOIR_FLOOD,
    RESERVOIR_SMALL,
    SEASON_END,
    SEASON_START,
    TIER_1_JUNIOR_PCT,
    TIER_1_SENIOR_PCT,
    TIER_2_JUNIOR_PCT,
    TIER_2_SENIOR_PCT,
    YEAR_LABEL,
)

# ── Logical clock ──────────────────────────────────────────────────────────

def clock_payload(current_utc: str = CLOCK_OCTOBER, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


# ── Districts ──────────────────────────────────────────────────────────────

def district_payload(
    name: str = "Test Irrigation District",
    service_area_acres: int = 10_000,
    contact_email: str = "ops@district.example",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "service_area_acres": service_area_acres,
        "contact_email": contact_email,
    }
    payload.update(overrides)
    return payload


def senior_district_payload(**overrides: Any) -> Dict[str, Any]:
    return district_payload(**{**DISTRICT_SR, **overrides})


def junior_district_payload(**overrides: Any) -> Dict[str, Any]:
    return district_payload(**{**DISTRICT_JR, **overrides})


def third_party_district_payload(**overrides: Any) -> Dict[str, Any]:
    return district_payload(**{**DISTRICT_TP, **overrides})


# ── Contracts ──────────────────────────────────────────────────────────────

def contract_payload(
    district_id: str,
    contract_number: str = "C-100",
    priority_class: str = "SENIOR",
    max_annual_quantity_af: int = 6_000,
    repayment_obligation_cents: int = 120_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "contract_number": contract_number,
        "priority_class": priority_class,
        "max_annual_quantity_af": max_annual_quantity_af,
        "repayment_obligation_cents": repayment_obligation_cents,
    }
    payload.update(overrides)
    return payload


def senior_contract_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    return contract_payload(district_id, **{**CONTRACT_SR, **overrides})


def junior_contract_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    return contract_payload(district_id, **{**CONTRACT_JR, **overrides})


def third_party_contract_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    return contract_payload(district_id, **{**CONTRACT_TP, **overrides})


# ── Water years ────────────────────────────────────────────────────────────

def water_year_payload(
    label: int = YEAR_LABEL,
    season_start: str = SEASON_START,
    season_end: str = SEASON_END,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": label,
        "season_start": season_start,
        "season_end": season_end,
    }
    payload.update(overrides)
    return payload


# ── Hydrology observations ─────────────────────────────────────────────────

def observation_payload(
    observation_type: str,
    value: int,
    observed_on: str = OBSERVED_ON_BASE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observation_type": observation_type,
        "value": value,
        "observed_on": observed_on,
    }
    payload.update(overrides)
    return payload


def snowpack_payload(value: int = 80, observed_on: str = OBSERVED_ON_BASE, **overrides: Any) -> Dict[str, Any]:
    return observation_payload("SNOWPACK_INDEX", value, observed_on, **overrides)


def runoff_forecast_payload(value: int = 5_000, observed_on: str = OBSERVED_ON_BASE, **overrides: Any) -> Dict[str, Any]:
    return observation_payload("RUNOFF_FORECAST_AF", value, observed_on, **overrides)


def inflow_payload(value: int, observed_on: str = OBSERVED_ON_BASE, **overrides: Any) -> Dict[str, Any]:
    return observation_payload("MEASURED_INFLOW_AF", value, observed_on, **overrides)


# ── Allocation announcements ───────────────────────────────────────────────

def announcement_payload(expected_water_year_version: int, **overrides: Any) -> Dict[str, Any]:
    """Draft creation is the contract's one OCC-guarded write (PRD §2.7)."""
    payload: Dict[str, Any] = {"expected_water_year_version": expected_water_year_version}
    payload.update(overrides)
    return payload


# ── Reservoir ──────────────────────────────────────────────────────────────

def reservoir_payload(
    name: str = "Shasta Unit",
    capacity_af: int = 50_000,
    dead_pool_af: int = 5_000,
    flood_control_max_storage_af: int = 20_000,
    initial_storage_af: int = 10_500,
    outlet_capacity_cfs: int = 15_000,
    power_conversion_mwh_per_af: float = 0.5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "capacity_af": capacity_af,
        "dead_pool_af": dead_pool_af,
        "flood_control_max_storage_af": flood_control_max_storage_af,
        "initial_storage_af": initial_storage_af,
        "outlet_capacity_cfs": outlet_capacity_cfs,
        "power_conversion_mwh_per_af": power_conversion_mwh_per_af,
    }
    payload.update(overrides)
    return payload


def small_reservoir_payload(**overrides: Any) -> Dict[str, Any]:
    return reservoir_payload(**{**RESERVOIR_SMALL, **overrides})


def big_reservoir_payload(**overrides: Any) -> Dict[str, Any]:
    return reservoir_payload(**{**RESERVOIR_BIG, **overrides})


def flood_reservoir_payload(**overrides: Any) -> Dict[str, Any]:
    return reservoir_payload(**{**RESERVOIR_FLOOD, **overrides})


# ── Release orders ─────────────────────────────────────────────────────────

def release_order_payload(
    purpose: str = "POWER",
    release_cfs: int = 1_000,
    duration_days: int = 10,
    scheduled_start: str = "2027-02-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "purpose": purpose,
        "release_cfs": release_cfs,
        "duration_days": duration_days,
        "scheduled_start": scheduled_start,
    }
    payload.update(overrides)
    return payload


# ── Environmental constraints ──────────────────────────────────────────────

def constraint_payload(
    species: str = "SMELT",
    requirement_type: str = "MIN_FLOW",
    enforce_start: str = "2027-01-01T00:00:00Z",
    enforce_end: str = "2027-03-01T00:00:00Z",
    required_min_cfs: Optional[int] = None,
    max_release_cfs: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a flow constraint.

    Emits the conditional field the requirement type demands and omits the
    forbidden one (PRD §3.5): pass ``required_min_cfs`` for MIN_FLOW /
    PULSE_FLOW, ``max_release_cfs`` for MAX_RELEASE. Overrides may inject the
    forbidden field deliberately to exercise the shape-validation rule.
    """
    payload: Dict[str, Any] = {
        "species": species,
        "requirement_type": requirement_type,
        "enforce_start": enforce_start,
        "enforce_end": enforce_end,
    }
    if required_min_cfs is not None:
        payload["required_min_cfs"] = required_min_cfs
    if max_release_cfs is not None:
        payload["max_release_cfs"] = max_release_cfs
    payload.update(overrides)
    return payload


def min_flow_constraint_payload(required_min_cfs: int = 500, **overrides: Any) -> Dict[str, Any]:
    return constraint_payload(requirement_type="MIN_FLOW", required_min_cfs=required_min_cfs, **overrides)


def pulse_flow_constraint_payload(
    required_min_cfs: int = 3_000,
    enforce_start: str = "2027-01-10T00:00:00Z",
    enforce_end: str = "2027-01-20T00:00:00Z",
    species: str = "SALMON",
    **overrides: Any,
) -> Dict[str, Any]:
    return constraint_payload(
        species=species,
        requirement_type="PULSE_FLOW",
        enforce_start=enforce_start,
        enforce_end=enforce_end,
        required_min_cfs=required_min_cfs,
        **overrides,
    )


def max_release_constraint_payload(max_release_cfs: int = 300, **overrides: Any) -> Dict[str, Any]:
    return constraint_payload(
        species="SALMON", requirement_type="MAX_RELEASE", max_release_cfs=max_release_cfs, **overrides
    )


# ── Compliance incidents ───────────────────────────────────────────────────

def resolve_incident_payload(resolution: str = "FLOW_RESTORED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload


# ── Delivery orders ────────────────────────────────────────────────────────

def delivery_order_payload(
    contract_id: str,
    water_year_id: str,
    ordered_af: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "water_year_id": water_year_id,
        "ordered_af": ordered_af,
    }
    payload.update(overrides)
    return payload


def record_delivery_payload(delivered_af: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"delivered_af": delivered_af}
    payload.update(overrides)
    return payload


# ── Revenue periods ────────────────────────────────────────────────────────

def revenue_period_payload(
    reservoir_id: str,
    period_month: str = "2027-02",
    rate_cents_per_mwh: int = 4_500,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reservoir_id": reservoir_id,
        "period_month": period_month,
        "rate_cents_per_mwh": rate_cents_per_mwh,
    }
    payload.update(overrides)
    return payload


# ── Transfer requests ──────────────────────────────────────────────────────

def transfer_payload(
    from_contract_id: str,
    to_contract_id: str,
    water_year_id: str,
    quantity_af: int = 100,
    price_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Propose a transfer; ``price_cents`` is omitted unless supplied so the
    server-side default of 0 applies (PRD §3.8)."""
    payload: Dict[str, Any] = {
        "from_contract_id": from_contract_id,
        "to_contract_id": to_contract_id,
        "water_year_id": water_year_id,
        "quantity_af": quantity_af,
    }
    if price_cents is not None:
        payload["price_cents"] = price_cents
    payload.update(overrides)
    return payload


def decide_payload(decision: str, rationale: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if rationale is not None:
        payload["rationale"] = rationale
    payload.update(overrides)
    return payload


def resubmit_payload(
    quantity_af: Optional[int] = None,
    price_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Seller resubmission; only the amended fields are emitted."""
    payload: Dict[str, Any] = {}
    if quantity_af is not None:
        payload["quantity_af"] = quantity_af
    if price_cents is not None:
        payload["price_cents"] = price_cents
    payload.update(overrides)
    return payload


# ── Impact reviews ─────────────────────────────────────────────────────────

def impact_review_payload(
    claimed_impact_af: int = 300,
    basis: str = "JUNIOR_IMPAIRMENT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claimed_impact_af": claimed_impact_af, "basis": basis}
    payload.update(overrides)
    return payload


def resolve_review_payload(outcome: str, rationale: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if rationale is not None:
        payload["rationale"] = rationale
    payload.update(overrides)
    return payload


# ── Shortage agreements ────────────────────────────────────────────────────

def shortage_agreement_payload(
    name: str = AGREEMENT_NAME,
    tier_1_senior_pct: int = TIER_1_SENIOR_PCT,
    tier_1_junior_pct: int = TIER_1_JUNIOR_PCT,
    tier_2_senior_pct: int = TIER_2_SENIOR_PCT,
    tier_2_junior_pct: int = TIER_2_JUNIOR_PCT,
    quorum_district_count: int = QUORUM_TWO,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "tier_1_senior_pct": tier_1_senior_pct,
        "tier_1_junior_pct": tier_1_junior_pct,
        "tier_2_senior_pct": tier_2_senior_pct,
        "tier_2_junior_pct": tier_2_junior_pct,
        "quorum_district_count": quorum_district_count,
    }
    payload.update(overrides)
    return payload


def activate_agreement_payload(water_year_label: int = YEAR_LABEL, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"water_year_label": water_year_label}
    payload.update(overrides)
    return payload


# ── Payloadless transitions ────────────────────────────────────────────────

def empty_payload() -> Dict[str, Any]:
    """Body for the transitions that take no input (publish, execute, settle,
    finalize, suspend, ratify)."""
    return {}
