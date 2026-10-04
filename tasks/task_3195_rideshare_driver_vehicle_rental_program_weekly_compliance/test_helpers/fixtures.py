"""Composite setup helpers.

The test harness restarts the API server before every individual pytest test,
so each test starts against an empty database. Every helper below therefore
builds its preconditions from scratch using only the programme's declared
operations, and every version-guarded write re-reads the parent row's current
`version` immediately before the call.
"""
from types import SimpleNamespace
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_driver_payload,
    create_enrollment_payload,
    create_fleet_fact_payload,
    create_maintenance_event_payload,
    create_purchase_option_payload,
    create_unlimited_agreement_payload,
    create_vehicle_payload,
    mileage_payload,
    open_week_payload,
    tender_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_unknown_role_headers,
)

ADMIN = TEST_USERS["admin_headers"]
FLEET = TEST_USERS["fleet_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
SUPPORT = TEST_USERS["support_headers"]


# ─── Derived-figure helpers ───────────────────────────

def platform_credit_for(activity_score: int, program_tier: str = "TIER_1") -> int:
    """The platform activity credit in whole cents for a score and tier.

    Below the 50-point floor nothing is earned; the 50-to-74 band pays 10 cents
    per qualifying point with the point at 50 included; from 75 the escalated
    band pays 10 cents multiplied by three halves per point, floored as it is
    applied; a TIER_3 enrolment then multiplies the whole band sum by five
    quarters, and the result is capped at 600 cents.
    """
    points = activity_score
    if points < 50:
        credit = 0
    elif points < 75:
        credit = (points - 50 + 1) * 10
    else:
        credit = (75 - 50) * 10 + (points - 75 + 1) * 10 * 3 // 2
    if program_tier == "TIER_3":
        credit = credit * 5 // 4
    return min(credit, 600)


def eligibility_score_for(driving_record_points: int, activity_score: int) -> int:
    """The composite 0..100 eligibility score, floor before bonus.

    The three bands are the in-range bands PRD §3.1 states: 3 points or fewer
    deduct 5 per point; 4 to 6 points deduct a flat 15 for the first tier plus
    10 for each point above 3; above 6 points deduct a flat 15 plus a flat 30
    plus 20 for each point above 6. Enrolment is refused outright at more than
    6 points, so the third band is only reachable through re-evaluation.
    """
    pts = driving_record_points
    score = 100
    if pts <= 3:
        score -= pts * 5
    elif pts <= 6:
        score -= 15 + (pts - 3) * 10
    else:
        score -= 15 + 30 + (pts - 6) * 20
    score = max(0, score)
    if score <= 40 and activity_score >= 90:
        score += 15
    return min(100, score)


def equity_credit_for(paid_amounts: List[int], waived_amounts: Optional[List[int]] = None) -> int:
    """Equity credit: one tenth of paid-minus-waived, floored, never negative."""
    waived_amounts = waived_amounts or []
    subtotal = sum(paid_amounts) - sum(waived_amounts)
    gross = subtotal * 1 // 10
    credit = int(round(gross * 100 / 100))
    return max(0, credit)


def escrow_required_for(purchase_price_cents: int, equity_credit_cents: int,
                        escrow_weeks_required: int) -> int:
    """The recurring escrow amount, derived from the equity credit."""
    from decimal import ROUND_HALF_UP, Decimal

    raw = Decimal(purchase_price_cents - equity_credit_cents) / Decimal(escrow_weeks_required)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ─── Tier 0: clock ────────────────────────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Move the logical clock. Returns the new clock value."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp).get("current_utc")


# ─── Individual entities ──────────────────────────────

def register_driver(**overrides) -> dict:
    resp = api_client.register_driver(create_driver_payload(**overrides), ADMIN)
    return get_success_data(resp)


def enroll_driver(driver_id: str, program_tier: str = "TIER_1") -> dict:
    resp = api_client.enroll_driver(
        create_enrollment_payload(driver_id, program_tier=program_tier), COMPLIANCE
    )
    return get_success_data(resp, expected_status=201)


def verify_enrollment(enrollment_id: str) -> dict:
    resp = api_client.verify_enrollment(enrollment_id, COMPLIANCE)
    return get_success_data(resp)


def enroll_and_verify(driver_id: str, program_tier: str = "TIER_1") -> dict:
    enrollment = enroll_driver(driver_id, program_tier)
    return verify_enrollment(enrollment["id"])


def admit_vehicle(**overrides) -> dict:
    resp = api_client.admit_vehicle(create_vehicle_payload(**overrides), FLEET)
    return get_success_data(resp, expected_status=201)


def create_draft_agreement(enrollment_id: str, driver_id: str, vehicle_id: str,
                           unlimited: bool = True, **overrides) -> dict:
    builder = create_unlimited_agreement_payload if unlimited else create_agreement_payload
    resp = api_client.create_agreement(
        builder(enrollment_id, driver_id, vehicle_id, **overrides), FLEET
    )
    return get_success_data(resp, expected_status=201)


def agreement_version(agreement_id: str) -> int:
    return get_success_data(api_client.get_agreement(agreement_id, FLEET))["version"]


def vehicle_version(vehicle_id: str) -> int:
    return get_success_data(api_client.get_vehicle(vehicle_id, FLEET))["version"]


def activate_agreement(agreement_id: str) -> dict:
    resp = api_client.activate_agreement(agreement_id, FLEET)
    return get_success_data(resp)


# ─── Weekly periods ───────────────────────────────────

def open_week(agreement_id: str, **overrides) -> dict:
    """Open the next weekly period, re-reading the agreement's live version."""
    payload = open_week_payload(agreement_id, agreement_version(agreement_id))
    payload.update(overrides)
    resp = api_client.open_week(payload, FLEET)
    return get_success_data(resp, expected_status=201)


def record_mileage(week_id: str, miles_driven: int) -> dict:
    resp = api_client.record_mileage(week_id, mileage_payload(miles_driven), FLEET)
    return get_success_data(resp)


def settle_week(week_id: str) -> dict:
    resp = api_client.settle_week(week_id, COMPLIANCE)
    return get_success_data(resp)


def tender_week(week_id: str, amount_cents: int, outcome: str = "SUCCEEDED") -> dict:
    resp = api_client.tender_payment(week_id, tender_payload(amount_cents, outcome), SUPPORT)
    return get_success_data(resp, expected_status=201)


def pay_week_in_full(week_id: str) -> dict:
    """Settle a week's bill by tendering exactly its outstanding amount."""
    week = get_success_data(api_client.get_week(week_id, SUPPORT))
    return tender_week(week_id, week["amount_due_cents"])


def get_week(week_id: str) -> dict:
    return get_success_data(api_client.get_week(week_id, SUPPORT))


def get_agreement(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement(agreement_id, FLEET))


def get_vehicle(vehicle_id: str) -> dict:
    return get_success_data(api_client.get_vehicle(vehicle_id, FLEET))


def get_driver(driver_id: str) -> dict:
    return get_success_data(api_client.get_driver(driver_id, COMPLIANCE))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, COMPLIANCE))


def get_option(option_id: str) -> dict:
    return get_success_data(api_client.get_purchase_option(option_id, COMPLIANCE))


def get_maintenance_event(event_id: str) -> dict:
    return get_success_data(api_client.get_maintenance_event(event_id, COMPLIANCE))


def agreement_summary(agreement_id: str) -> dict:
    return get_success_data(api_client.get_agreement_summary(agreement_id, FLEET))


def lapse_grace(week_id: str) -> dict:
    resp = api_client.grace_lapse(week_id, COMPLIANCE)
    return get_success_data(resp)


# ─── Counting helpers ─────────────────────────────────

def list_vehicles(**params) -> List[dict]:
    resp = api_client.list_vehicles(FLEET, params=params or None)
    return resp.json()["data"]


def vehicles_in_region(region_code: str, vehicle_status: Optional[str] = None) -> List[dict]:
    params = {"region_code": region_code}
    if vehicle_status is not None:
        params["vehicle_status"] = vehicle_status
    resp = api_client.list_vehicles(FLEET, params=params)
    body = resp.json()
    return body["data"]


def count_assigned_vehicles(region_code: str) -> int:
    return len(vehicles_in_region(region_code, "ASSIGNED"))


def count_non_retired_vehicles(region_code: str) -> int:
    total = 0
    for status in ("AVAILABLE", "ASSIGNED", "MAINTENANCE", "RECOVERY"):
        total += len(vehicles_in_region(region_code, status))
    return total


def count_retired_vehicles(region_code: str) -> int:
    return len(vehicles_in_region(region_code, "RETIRED"))


def count_agreements(**params) -> int:
    resp = api_client.list_agreements(FLEET, params=params or None)
    return resp.json()["meta"]["total_count"]


def count_maintenance_events(**params) -> int:
    resp = api_client.list_maintenance_events(FLEET, params=params or None)
    return resp.json()["meta"]["total_count"]


def count_platform_checks(**params) -> int:
    resp = api_client.list_platform_checks(FLEET, params=params or None)
    return resp.json()["meta"]["total_count"]


# ─── Tier 1: state progression ────────────────────────

def setup_active_agreement(activity_score: int = TEST_DEFAULTS["ACTIVITY_SCORE"],
                           driving_record_points: int = TEST_DEFAULTS["DRIVING_RECORD_POINTS"],
                           program_tier: str = "TIER_1",
                           license_class: str = "FOR_HIRE",
                           unlimited: bool = True,
                           vehicle_overrides: Optional[dict] = None,
                           **agreement_overrides):
    """A verified driver on an ACTIVE agreement holding one assigned unit."""
    set_clock()
    driver = register_driver(
        platform_activity_score=activity_score,
        driving_record_points=driving_record_points,
        license_class=license_class,
    )
    enrollment = enroll_and_verify(driver["id"], program_tier)
    vehicle = admit_vehicle(**(vehicle_overrides or {}))
    agreement = create_draft_agreement(
        enrollment["id"], driver["id"], vehicle["id"],
        unlimited=unlimited, **agreement_overrides,
    )
    agreement = activate_agreement(agreement["id"])
    return SimpleNamespace(
        driver=driver, enrollment=enrollment, vehicle=vehicle, agreement=agreement,
        driver_headers=make_driver_headers(driver["id"]),
    )


def setup_agreement_with_open_week(settle: bool = False, miles: Optional[int] = None,
                                   mileage_cap_miles: Optional[int] = None, **kwargs):
    """An ACTIVE agreement plus its first weekly period in OPEN (or settled).

    The mileage provisions describe the agreement's shape rather than the week:
    passing `mileage_cap_miles` builds the metered shape with the unlimited-mile
    provision left off (PRD §3.1: "If unlimited_mileage is false the agreement is
    metered ... If unlimited_mileage is true that cap is not applicable").
    """
    if mileage_cap_miles is not None:
        kwargs.setdefault("unlimited", False)
        kwargs.setdefault("mileage_cap_miles", mileage_cap_miles)
    ctx = setup_active_agreement(**kwargs)
    week = open_week(ctx.agreement["id"])
    if miles is not None:
        week = record_mileage(week["id"], miles)
    if settle:
        week = settle_week(week["id"])
    ctx.week = week
    return ctx


def setup_agreement_with_due_week(**kwargs):
    """An ACTIVE agreement with week 1 settled to DUE."""
    return setup_agreement_with_open_week(settle=True, **kwargs)


def setup_agreement_with_paid_week(weeks: int = 1, **kwargs):
    """An ACTIVE agreement with `weeks` fully paid rental periods."""
    ctx = setup_active_agreement(**kwargs)
    paid_weeks = []
    for _ in range(weeks):
        week = open_week(ctx.agreement["id"])
        week = settle_week(week["id"])
        pay_week_in_full(week["id"])
        paid_weeks.append(get_week(week["id"]))
    ctx.weeks = paid_weeks
    ctx.week = paid_weeks[-1] if paid_weeks else None
    return ctx


# ─── Tier 4: delinquency and posture targeting ────────

def setup_with_delinquent_weeks(count: int = 1, **kwargs):
    """An agreement carrying `count` DELINQUENT weeks; posture follows the count."""
    ctx = setup_active_agreement(**kwargs)
    weeks = [open_week(ctx.agreement["id"]) for _ in range(count)]
    for week in weeks:
        settle_week(week["id"])
    set_clock("2026-09-11T00:00:00Z")
    for week in weeks:
        lapse_grace(week["id"])
    ctx.weeks = [get_week(w["id"]) for w in weeks]
    ctx.week = ctx.weeks[0]
    ctx.agreement = get_agreement(ctx.agreement["id"])
    ctx.driver = get_driver(ctx.driver["id"])
    ctx.enrollment = get_enrollment(ctx.enrollment["id"])
    ctx.vehicle = get_vehicle(ctx.vehicle["id"])
    return ctx


def setup_frozen_agreement_with_option(purchase_price_cents: int = 1_800_000,
                                       escrow_weeks_required: int = 24,
                                       **kwargs):
    """A FROZEN (twice-delinquent) agreement carrying an OFFERED purchase option."""
    ctx = setup_active_agreement(**kwargs)
    set_clock()
    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            ctx.agreement["id"], ctx.driver["id"],
            purchase_price_cents=purchase_price_cents,
            escrow_weeks_required=escrow_weeks_required,
        ), ADMIN,
    ), expected_status=201)
    weeks = [open_week(ctx.agreement["id"]) for _ in range(2)]
    for week in weeks:
        settle_week(week["id"])
    set_clock("2026-09-11T00:00:00Z")
    for week in weeks:
        lapse_grace(week["id"])
    ctx.option = option
    ctx.weeks = [get_week(w["id"]) for w in weeks]
    ctx.agreement = get_agreement(ctx.agreement["id"])
    ctx.driver = get_driver(ctx.driver["id"])
    ctx.vehicle = get_vehicle(ctx.vehicle["id"])
    return ctx


def setup_recovery_pending(**kwargs):
    """An agreement escalated into RECOVERY_PENDING with its unit in RECOVERY."""
    ctx = setup_with_delinquent_weeks(count=2, **kwargs)
    resp = api_client.escalate_recovery(ctx.agreement["id"], FLEET)
    get_success_data(resp)
    ctx.agreement = get_agreement(ctx.agreement["id"])
    ctx.vehicle = get_vehicle(ctx.vehicle["id"])
    return ctx


def setup_recovered_agreement(**kwargs):
    """A recovered agreement: unit released, delinquent weeks closed."""
    ctx = setup_recovery_pending(**kwargs)
    resp = api_client.recover_agreement(ctx.agreement["id"], FLEET)
    get_success_data(resp)
    ctx.agreement = get_agreement(ctx.agreement["id"])
    ctx.vehicle = get_vehicle(ctx.vehicle["id"])
    ctx.weeks = [get_week(w["id"]) for w in ctx.weeks]
    return ctx


# ─── Tier 3/5: service events and purchases ───────────

def setup_loaner_scenario(downtime_hours: int = 30,
                          event_type: str = "UNSCHEDULED_REPAIR",
                          damage_liability_cents: int = 0,
                          with_spare: bool = True,
                          spare_overrides: Optional[dict] = None,
                          **kwargs):
    """An ACTIVE agreement whose unit is reported into service.

    A spare unit of the same class in the same region exists as a loaner
    candidate unless `with_spare` is false.
    """
    ctx = setup_active_agreement(**kwargs)
    ctx.spare = None
    if with_spare:
        spare_overrides = spare_overrides or {}
        ctx.spare = admit_vehicle(
            vehicle_class=ctx.vehicle["vehicle_class"],
            region_code=ctx.vehicle["region_code"],
            **spare_overrides,
        )
    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            event_type=event_type,
            downtime_hours=downtime_hours,
            damage_liability_cents=damage_liability_cents,
        ), FLEET,
    ), expected_status=201)
    ctx.event = event
    return ctx


def setup_option_elected(purchase_price_cents: int = 1_800_000,
                         escrow_weeks_required: int = 24,
                         paid_weeks: int = 0,
                         funded_weeks: int = 0,
                         **kwargs):
    """An agreement in PURCHASE_PENDING with an ELECTED option."""
    ctx = setup_active_agreement(**kwargs)
    set_clock()
    for _ in range(paid_weeks):
        week = open_week(ctx.agreement["id"])
        week = settle_week(week["id"])
        pay_week_in_full(week["id"])
    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            ctx.agreement["id"], ctx.driver["id"],
            purchase_price_cents=purchase_price_cents,
            escrow_weeks_required=escrow_weeks_required,
        ), ADMIN,
    ), expected_status=201)
    resp = api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    option = get_success_data(resp)
    for _ in range(funded_weeks):
        option = get_success_data(api_client.fund_escrow(option["id"], ctx.driver_headers))
    ctx.option = option
    ctx.agreement = get_agreement(ctx.agreement["id"])
    return ctx


def setup_short_term_agreement(period_end: str = "2026-09-15T00:00:00Z", **kwargs):
    """An ACTIVE agreement whose contractual term ends on `period_end`."""
    kwargs.setdefault("unlimited", True)
    ctx = setup_active_agreement(period_end=period_end, period_start=DEFAULT_CLOCK, **kwargs)
    return ctx


# ─── Re-exports for test convenience ──────────────────

__all__ = [
    "ADMIN", "FLEET", "COMPLIANCE", "SUPPORT", "TEST_USERS",
    "make_driver_headers", "make_unknown_role_headers",
    "platform_credit_for", "eligibility_score_for", "equity_credit_for",
    "escrow_required_for",
    "set_clock", "register_driver", "enroll_driver", "verify_enrollment",
    "enroll_and_verify", "admit_vehicle", "create_draft_agreement",
    "agreement_version", "vehicle_version", "activate_agreement",
    "open_week", "record_mileage", "settle_week", "tender_week",
    "pay_week_in_full", "get_week", "get_agreement", "get_vehicle",
    "get_driver", "get_enrollment", "get_option", "get_maintenance_event",
    "agreement_summary", "lapse_grace",
    "list_vehicles", "vehicles_in_region", "count_assigned_vehicles",
    "count_non_retired_vehicles", "count_retired_vehicles", "count_agreements",
    "count_maintenance_events", "count_platform_checks",
    "setup_active_agreement", "setup_agreement_with_open_week",
    "setup_agreement_with_due_week", "setup_agreement_with_paid_week",
    "setup_with_delinquent_weeks", "setup_frozen_agreement_with_option",
    "setup_recovery_pending", "setup_recovered_agreement",
    "setup_loaner_scenario", "setup_option_elected", "setup_short_term_agreement",
    "report_service_event",
    "SimpleNamespace",
]

def report_service_event(agreement_id: str, vehicle_id: str, **overrides) -> dict:
    """Report a service event against a unit, re-reading the unit's live version."""
    payload = create_maintenance_event_payload(
        agreement_id, vehicle_id, vehicle_version(vehicle_id), **overrides
    )
    resp = api_client.report_maintenance_event(payload, FLEET)
    return get_success_data(resp, expected_status=201)
