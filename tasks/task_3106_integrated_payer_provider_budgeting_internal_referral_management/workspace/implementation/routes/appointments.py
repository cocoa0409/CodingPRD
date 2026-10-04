"""Appointment endpoints (PRD 3.4)."""

from flask import Blueprint

from calculations import wait_days_between
from clock import CLOCK, parse_iso8601
from constants import ROLE_ACCESS_SCHEDULER, ROLE_CARE_TEAM_MEMBER
from db import STORE
from domain import (
    auto_review_overcommitted_plans,
    capacity_plan_for,
    check_member_version,
    committed_appointments_for,
    enforce_posture_gate,
    enforce_same_region,
    get_appointment,
    get_department,
    in_network_available,
    new_record,
    perfor_m_fiscal_line_check,
    recompute_region_aggregates,
    refresh_capacity_plan,
    require_body_reference,
    run_posture_ladder,
    store_row,
    touch,
)
from projections import period_of
from errors import (
    ERR_DEPARTMENT_CAPACITY_EXHAUSTED,
    ERR_INVALID_STATE,
    ERR_PROVIDER_SCHEDULE_OVERLAP,
    ERR_REFERRAL_EXPIRED,
    ERR_REFERRAL_NOT_AUTHORIZED,
    ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK,
    raise_error,
)
from routes._common import (
    READERS,
    arg,
    filter_rows,
    list_response,
    optional_field,
    payload,
    principal,
    require_field,
    single_response,
)

bp = Blueprint("appointments", __name__)


def _overlaps(start_a, dur_a, start_b, dur_b):
    end_a = start_a.timestamp() + dur_a * 60
    end_b = start_b.timestamp() + dur_b * 60
    return start_a.timestamp() < end_b and start_b.timestamp() < end_a


@bp.post("/appointments")
def book_appointment():
    principal((ROLE_ACCESS_SCHEDULER,))
    body = payload()

    department_id = require_field(body, "department_id")
    provider_id = require_field(body, "provider_id")
    member_id = require_field(body, "member_id")
    referral_id = optional_field(body, "referral_id")
    appointment_type = require_field(body, "appointment_type")
    start_utc = require_field(body, "start_utc")
    duration_minutes = optional_field(body, "duration_minutes", 20)
    expected = optional_field(body, "expected_member_version")

    department = require_body_reference("departments", department_id)
    provider = require_body_reference("providers", provider_id)
    member = require_body_reference("members", member_id)
    referral = None
    if referral_id is not None:
        referral = require_body_reference("referrals", referral_id)

    region_id = department["region_id"]

    # --- cross-region referential integrity before state admissibility ---
    enforce_same_region(region_id, provider.get("region_id"),
                        member.get("region_id"))

    # --- optimistic concurrency on the member (PRD 2.9) ---
    check_member_version(member, expected)

    # --- network availability before the specialty-referral match ---
    if referral is not None:
        if not in_network_available(region_id, referral.get("service_code")):
            raise_error(ERR_SERVICE_NOT_AVAILABLE_IN_NETWORK)

    # --- specialty match before the referral-expiry check ---
    if appointment_type == "SPECIALTY":
        if referral is None:
            raise_error(ERR_REFERRAL_NOT_AUTHORIZED)
        if referral.get("member_id") != member_id:
            raise_error(ERR_REFERRAL_NOT_AUTHORIZED)
        if referral.get("target_department_id") != department_id:
            raise_error(ERR_REFERRAL_NOT_AUTHORIZED)
        if referral.get("status") != "AUTHORIZED":
            raise_error(ERR_REFERRAL_NOT_AUTHORIZED)

        if referral.get("expires_at"):
            if CLOCK.now() >= parse_iso8601(referral["expires_at"]):
                raise_error(ERR_REFERRAL_EXPIRED)

    # --- posture gate before the department capacity check ---
    enforce_posture_gate(region_id)

    # --- department capacity before the FTE budget check ---
    if department.get("status") == "CLOSED":
        raise_error(ERR_DEPARTMENT_CAPACITY_EXHAUSTED)
    committed = len(committed_appointments_for(department_id))
    if committed + 1 > int(department.get("appointment_slots_budgeted") or 0):
        raise_error(ERR_DEPARTMENT_CAPACITY_EXHAUSTED)

    # --- provider schedule overlap ---
    new_start = parse_iso8601(start_utc)
    for existing in STORE.appointments.values():
        if existing.get("provider_id") != provider_id:
            continue
        if existing.get("fulfillment_status") == "CANCELLED":
            continue
        existing_start = parse_iso8601(existing["start_utc"])
        if existing_start.date() != new_start.date():
            continue
        if _overlaps(new_start, int(duration_minutes),
                     existing_start, int(existing.get("duration_minutes") or 0)):
            raise_error(ERR_PROVIDER_SCHEDULE_OVERLAP)

    # --- fiscal line is the last business check ---
    perfor_m_fiscal_line_check(region_id)

    booking_instant = CLOCK.now()
    wait_days = wait_days_between(booking_instant, new_start)
    threshold = _as_dec(department.get("wait_threshold_days", 14))
    access_status = ("BREACHED_ACCESS_TARGET"
                     if wait_days >= threshold
                     else "WITHIN_ACCESS_TARGET")

    row = new_record(
        department_id=department_id,
        provider_id=provider_id,
        member_id=member_id,
        referral_id=referral_id,
        appointment_type=appointment_type,
        start_utc=start_utc,
        duration_minutes=duration_minutes,
        wait_days=wait_days,
        fulfillment_status="SCHEDULED",
        access_status=access_status,
        hold_status="NONE",
    )
    store_row("appointments", row)

    department["appointment_slots_committed"] = committed + 1
    touch(department)
    if (committed + 1 >= int(department.get("appointment_slots_budgeted") or 0)
            and department.get("status") == "OPEN"):
        department["status"] = "CONSTRAINED"

    if referral is not None and referral.get("status") == "AUTHORIZED":
        referral["status"] = "SCHEDULED"
        touch(referral)

    touch(member)
    _ = provider

    plan = capacity_plan_for(department_id, period_of(start_utc))
    if plan is not None:
        refresh_capacity_plan(plan)
        touch(plan)

    auto_review_overcommitted_plans(region_id)
    recompute_region_aggregates(region_id, bump_version=True)
    run_posture_ladder(region_id)
    return single_response("appointments", row, 201)


def _as_dec(value):
    from rounding import dec
    return dec(value)


@bp.get("/appointments")
def list_appointments():
    principal(READERS)
    rows = list(STORE.appointments.values())
    rows = filter_rows(
        rows,
        department_id=arg("department_id"),
        member_id=arg("member_id"),
        provider_id=arg("provider_id"),
        referral_id=arg("referral_id"),
        fulfillment_status=arg("fulfillment_status"),
        access_status=arg("access_status"),
    )
    return list_response("appointments", rows)


@bp.get("/appointments/<appointment_id>")
def get_one_appointment(appointment_id):
    principal(READERS)
    return single_response("appointments", get_appointment(appointment_id))


@bp.post("/appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    principal((ROLE_ACCESS_SCHEDULER,))
    appointment = get_appointment(appointment_id)
    status = appointment.get("fulfillment_status")
    if status not in ("REQUESTED", "SCHEDULED"):
        raise_error(ERR_INVALID_STATE)

    department = get_department(appointment["department_id"])
    region_id = department["region_id"]

    if status == "REQUESTED":
        appointment["fulfillment_status"] = "CANCELLED"
        touch(appointment)
        return single_response("appointments", appointment)

    appointment["fulfillment_status"] = "CANCELLED"
    touch(appointment)

    department["appointment_slots_committed"] = max(
        0, int(department.get("appointment_slots_committed") or 0) - 1)
    touch(department)

    referral = None
    if appointment.get("referral_id"):
        referral = STORE.referrals.get(appointment["referral_id"])
    if referral is not None and referral.get("status") == "SCHEDULED":
        referral["status"] = "AUTHORIZED"
        touch(referral)

    plan = capacity_plan_for(department["id"], period_of(appointment.get("start_utc")))
    if plan is not None:
        refresh_capacity_plan(plan)
        touch(plan)

    recompute_region_aggregates(region_id, bump_version=False)
    return single_response("appointments", appointment)


@bp.post("/appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    principal((ROLE_CARE_TEAM_MEMBER,))
    appointment = get_appointment(appointment_id)
    if appointment.get("fulfillment_status") != "SCHEDULED":
        raise_error(ERR_INVALID_STATE)

    appointment["fulfillment_status"] = "COMPLETED"
    touch(appointment)

    referral = None
    if appointment.get("referral_id"):
        referral = STORE.referrals.get(appointment["referral_id"])
    if referral is not None and referral.get("status") == "SCHEDULED":
        referral["status"] = "COMPLETED"
        touch(referral)

    department = get_department(appointment["department_id"])
    recompute_region_aggregates(department["region_id"], bump_version=False)
    return single_response("appointments", appointment)