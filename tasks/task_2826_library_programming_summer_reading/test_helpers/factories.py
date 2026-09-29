"""Request payload builders.

Every money field is emitted as an integer number of cents, every instant as a
full ISO 8601 UTC instant with three fractional second digits, and every
date-granularity field as plain ``YYYY-MM-DD`` text, which is exactly the split
the PRD draws between its instant-granularity and date-granularity rules.
"""

from typing import Any, Dict, List, Optional


def _with_overrides(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Branches and rooms
# --------------------------------------------------------------------------
def branch_payload(
    name: str = "Central Library",
    branch_code: str = "CEN",
    overlapping_program_capacity: int = 2,
    per_program_fee_cap_cents: int = 150000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "name": name,
            "branch_code": branch_code,
            "overlapping_program_capacity": overlapping_program_capacity,
            "per_program_fee_cap_cents": per_program_fee_cap_cents,
        },
        overrides,
    )


def room_payload(
    room_name: str = "Story Room",
    capacity_seats: int = 60,
    min_setup_minutes: int = 15,
    min_teardown_minutes: int = 15,
    accessibility_features: Optional[List[str]] = None,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_name": room_name,
        "capacity_seats": capacity_seats,
        "min_setup_minutes": min_setup_minutes,
        "min_teardown_minutes": min_teardown_minutes,
    }
    if accessibility_features is not None:
        payload["accessibility_features"] = accessibility_features
    if status is not None:
        payload["status"] = status
    return _with_overrides(payload, overrides)


# --------------------------------------------------------------------------
# Inventory lots
# --------------------------------------------------------------------------
def inventory_lot_payload(
    branch_id: str,
    sku: str = "CRAFT-KIT",
    category: str = "SUPPLY",
    unit_cost_cents: int = 250,
    quantity_procured: int = 100,
    reuse_pool: bool = False,
    description: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "category": category,
        "sku": sku,
        "unit_cost_cents": unit_cost_cents,
        "quantity_procured": quantity_procured,
        "reuse_pool": reuse_pool,
    }
    if description is not None:
        payload["description"] = description
    return _with_overrides(payload, overrides)


def prize_lot_payload(
    branch_id: str,
    sku: str = "MEDAL",
    unit_cost_cents: int = 500,
    quantity_procured: int = 10,
    reuse_pool: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    return inventory_lot_payload(
        branch_id,
        sku=sku,
        category="PRIZE",
        unit_cost_cents=unit_cost_cents,
        quantity_procured=quantity_procured,
        reuse_pool=reuse_pool,
        **overrides,
    )


# --------------------------------------------------------------------------
# Programs
# --------------------------------------------------------------------------
def program_payload(
    branch_id: str,
    title: str = "Craft Hour",
    age_group: str = "SCHOOL_AGE",
    delivery_mode: str = "IN_BRANCH",
    registration_policy: str = "REGISTRATION",
    start_utc: str = "2026-08-12T14:00:00.000Z",
    end_utc: str = "2026-08-12T15:00:00.000Z",
    attendance_target: int = 10,
    attendance_cap: int = 20,
    supply_sku: str = "CRAFT-KIT",
    supply_units_per_attendee: int = 1,
    materials_budget_cents: int = 50000,
    presenter_fee_budget_cents: int = 200000,
    challenge_id: Optional[str] = None,
    partner_type: Optional[str] = None,
    partner_org_name: Optional[str] = None,
    partner_insurance_expires_on: Optional[str] = None,
    accessibility_accommodations: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "title": title,
        "age_group": age_group,
        "delivery_mode": delivery_mode,
        "registration_policy": registration_policy,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "attendance_target": attendance_target,
        "attendance_cap": attendance_cap,
        "supply_sku": supply_sku,
        "supply_units_per_attendee": supply_units_per_attendee,
        "materials_budget_cents": materials_budget_cents,
        "presenter_fee_budget_cents": presenter_fee_budget_cents,
    }
    if challenge_id is not None:
        payload["challenge_id"] = challenge_id
    if partner_type is not None:
        payload["partner_type"] = partner_type
    if partner_org_name is not None:
        payload["partner_org_name"] = partner_org_name
    if partner_insurance_expires_on is not None:
        payload["partner_insurance_expires_on"] = partner_insurance_expires_on
    if accessibility_accommodations is not None:
        payload["accessibility_accommodations"] = accessibility_accommodations
    return _with_overrides(payload, overrides)


def adult_program_payload(
    branch_id: str,
    title: str = "Adult Book Club",
    start_utc: str = "2026-08-12T18:00:00.000Z",
    end_utc: str = "2026-08-12T19:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """An ADULT program, whose ``serves_minors`` derives false."""
    return program_payload(
        branch_id,
        title=title,
        age_group="ADULT",
        start_utc=start_utc,
        end_utc=end_utc,
        **overrides,
    )


def schedule_payload(
    start_utc: Optional[str] = None, end_utc: Optional[str] = None
) -> Dict[str, Any]:
    """A schedule body: both window fields are optional and move the window."""
    payload: Dict[str, Any] = {}
    if start_utc is not None:
        payload["start_utc"] = start_utc
    if end_utc is not None:
        payload["end_utc"] = end_utc
    return payload


def registration_payload(
    registrant_reference: str = "card-0001", seats: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"registrant_reference": registrant_reference}
    if seats is not None:
        payload["seats"] = seats
    return payload


def close_out_payload(
    verified_registrant_attendance: int,
    drop_in_headcount: int,
    surveys_collected: int,
) -> Dict[str, Any]:
    return {
        "verified_registrant_attendance": verified_registrant_attendance,
        "drop_in_headcount": drop_in_headcount,
        "surveys_collected": surveys_collected,
    }


def closure_payload(closure_reason: str) -> Dict[str, Any]:
    return {"closure_reason": closure_reason}


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
def reservation_payload(
    room_id: str,
    expected_program_version: int,
    start_utc: str = "2026-08-12T14:00:00.000Z",
    end_utc: str = "2026-08-12T15:00:00.000Z",
    setup_minutes: int = 15,
    teardown_minutes: int = 15,
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "room_id": room_id,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "setup_minutes": setup_minutes,
            "teardown_minutes": teardown_minutes,
            "expected_program_version": expected_program_version,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Presenters, screening and contracts
# --------------------------------------------------------------------------
def presenter_payload(
    legal_name: str = "Marisol Vega",
    presenter_type: str = "INDIVIDUAL",
    insurance_certificate_expires_on: str = "2027-01-01",
    quoted_fee_cents: int = 50000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "legal_name": legal_name,
            "presenter_type": presenter_type,
            "insurance_certificate_expires_on": insurance_certificate_expires_on,
            "quoted_fee_cents": quoted_fee_cents,
        },
        overrides,
    )


def screening_request_payload(screening_tier: str = "NAME_CHECK") -> Dict[str, Any]:
    return {"screening_tier": screening_tier}


def screening_result_payload(result: str, decided_on: str) -> Dict[str, Any]:
    return {"result": result, "decided_on": decided_on}


def adjudication_payload(decision: str, decided_on: str) -> Dict[str, Any]:
    return {"decision": decision, "decided_on": decided_on}


def contract_payload(
    presenter_id: str, program_id: str, round_trip_miles: int = 20, **overrides: Any
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "presenter_id": presenter_id,
            "program_id": program_id,
            "round_trip_miles": round_trip_miles,
        },
        overrides,
    )


def offer_payload(offered_fee_cents: int = 50000) -> Dict[str, Any]:
    return {"offered_fee_cents": offered_fee_cents}


def counter_payload(countered_fee_cents: int) -> Dict[str, Any]:
    return {"countered_fee_cents": countered_fee_cents}


# --------------------------------------------------------------------------
# Challenges, tiers, participants and the ledger
# --------------------------------------------------------------------------
def challenge_payload(
    name: str = "Summer 2026",
    logging_method: str = "MINUTES",
    unit_label: str = "minutes",
    start_on: str = "2026-07-01",
    end_on: str = "2026-08-31",
    correction_policy: str = "LEDGER_TRUTH",
    prize_budget_cents: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "name": name,
            "logging_method": logging_method,
            "unit_label": unit_label,
            "start_on": start_on,
            "end_on": end_on,
            "correction_policy": correction_policy,
            "prize_budget_cents": prize_budget_cents,
        },
        overrides,
    )


def tier_payload(
    tier_index: int = 1,
    threshold_units: int = 5000,
    prize_sku: str = "MEDAL",
    prize_units_per_participant: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "tier_index": tier_index,
            "threshold_units": threshold_units,
            "prize_sku": prize_sku,
            "prize_units_per_participant": prize_units_per_participant,
        },
        overrides,
    )


def participant_payload(
    challenge_id: str,
    home_branch_id: str,
    display_name: str = "Ada L.",
    age_band: str = "AGE_5_11",
    **overrides: Any,
) -> Dict[str, Any]:
    return _with_overrides(
        {
            "challenge_id": challenge_id,
            "home_branch_id": home_branch_id,
            "display_name": display_name,
            "age_band": age_band,
        },
        overrides,
    )


def log_entry_payload(
    units: int, logged_on: str, source: str = "STAFF_DESK", **overrides: Any
) -> Dict[str, Any]:
    return _with_overrides(
        {"units": units, "logged_on": logged_on, "source": source}, overrides
    )


def log_correction_payload(
    corrected_entry_id: str,
    units_delta: int,
    expected_participant_version: int,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "corrected_entry_id": corrected_entry_id,
        "units_delta": units_delta,
        "expected_participant_version": expected_participant_version,
    }
    if note is not None:
        payload["note"] = note
    return _with_overrides(payload, overrides)
