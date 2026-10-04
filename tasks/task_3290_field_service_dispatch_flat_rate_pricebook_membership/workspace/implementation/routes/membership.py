"""Membership: sales, payments, visits and cancellation (PRD 3.8, 3.9)."""

from flask import Blueprint, request

from constants import (ROLE_TECHNICIAN, ROLE_DISPATCHER, ROLE_MANAGER,
                       ROLE_PLATFORM_ADMIN, TERM_MONTHS_ALLOWED,
                       DOWN_PAYMENT_FRACTION)
from common import (body_json, require_roles, require_str, require_int,
                    optional_int, optional_str, optional_datetime,
                    is_five_digits, enum_field)
from constants import clock
import store
import serializers
import calc
from errors import (ApiError, not_found, invalid_request, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_DUPLICATE_VISIT_SEQUENCE,
                    ERR_SUBSCRIPTION_TERM_EXCEEDED, ERR_OVER_COLLECTION,
                    ERR_MEMBERSHIP_CANCEL_BLOCKED, ERR_AGREEMENT_NOT_ACTIVE,
                    ERR_VISIT_OVERLAP)
from response import (created, object_ok, array_ok, read_pagination, paginate)

bp = Blueprint("membership", __name__)


def _get_agreement(agreement_id):
    row = store.membership_agreements.get(agreement_id)
    if row is None:
        raise not_found("membership agreement")
    return row


def _get_visit(visit_id):
    row = store.membership_visits.get(visit_id)
    if row is None:
        raise not_found("membership visit")
    return row


@bp.route("/membership-agreements", methods=["POST"])
def sell_agreement():
    require_roles([ROLE_TECHNICIAN])
    payload = body_json()
    plan_id = require_str(payload, "membership_plan_id")
    plan = store.membership_plans.get(plan_id)
    if plan is None:
        raise not_found("membership plan")
    branch_id = require_str(payload, "branch_id")
    branch = store.branches.get(branch_id)
    if branch is None:
        raise not_found("branch")
    homeowner_name = require_str(payload, "homeowner_name")
    postal_code = require_str(payload, "homeowner_postal_code")
    if not is_five_digits(postal_code):
        raise invalid_request("homeowner_postal_code must be exactly five digits")
    term = optional_int(payload, "term_months", 12)
    if term not in TERM_MONTHS_ALLOWED:
        raise invalid_request("term_months must be 12 or 24")

    if plan["status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE,
                       "the membership plan is not PUBLISHED and cannot be sold")
    if branch["postal_code"] != postal_code:
        raise ApiError(ERR_INVALID_STATE,
                       "homeowner_postal_code must equal the owning branch's postal_code")

    row = store.new_row(
        "MembershipAgreement",
        membership_plan_id=plan_id,
        branch_id=branch_id,
        homeowner_name=homeowner_name,
        homeowner_postal_code=postal_code,
        status="PENDING_PAYMENT",
        term_months=term,
        agreement_start_utc=None,
        annual_price_cents=plan["annual_price_cents"],
        collected_amount_cents=0,
        revenue_recognized_cents=0,
        unearned_revenue_balance_cents=0,
    )
    store.membership_agreements[row["id"]] = row
    return created(serializers.membership_agreement(row))


@bp.route("/membership-agreements", methods=["GET"])
def list_agreements():
    require_roles([ROLE_DISPATCHER, ROLE_MANAGER, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    items = store.by_created(store.membership_agreements)
    for field in ("branch_id", "membership_plan_id", "status"):
        value = request.args.get(field)
        if value not in (None, ""):
            items = [a for a in items if a.get(field) == value]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.membership_agreement(a) for a in page], limit, offset, total)


@bp.route("/membership-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    require_roles([ROLE_DISPATCHER, ROLE_MANAGER, ROLE_PLATFORM_ADMIN])
    row = _get_agreement(agreement_id)
    return object_ok(serializers.membership_agreement(row))


@bp.route("/membership-agreements/<agreement_id>/payments", methods=["POST"])
def record_payment(agreement_id):
    require_roles([ROLE_DISPATCHER])
    agreement = _get_agreement(agreement_id)
    payload = body_json()
    amount = require_int(payload, "amount_cents")
    if amount <= 0:
        raise invalid_request("amount_cents must be strictly greater than zero")

    if agreement["status"] not in ("PENDING_PAYMENT", "ACTIVE", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE)

    collected = int(agreement["collected_amount_cents"])
    annual = int(agreement["annual_price_cents"])
    if collected + amount > annual:
        raise ApiError(ERR_OVER_COLLECTION)

    agreement["collected_amount_cents"] = collected + amount
    threshold = calc.half_up_int(calc.dec(annual) * calc.dec(DOWN_PAYMENT_FRACTION))
    if agreement["status"] == "PENDING_PAYMENT" and agreement["collected_amount_cents"] >= threshold:
        agreement["status"] = "ACTIVE"
        agreement["agreement_start_utc"] = clock.now()
    calc.deferred_revenue_waterfall(agreement_id)
    store.touch(agreement)
    return object_ok(serializers.membership_agreement(agreement))


@bp.route("/membership-agreements/<agreement_id>/membership-visits", methods=["POST"])
def schedule_visit(agreement_id):
    require_roles([ROLE_DISPATCHER])
    agreement = _get_agreement(agreement_id)
    payload = body_json()
    sequence = require_int(payload, "sequence_number")
    if sequence < 1:
        raise invalid_request("sequence_number must be at least 1")
    scheduled_date = optional_datetime(payload, "scheduled_date")
    if scheduled_date is None:
        raise invalid_request("scheduled_date is required")

    if agreement["status"] not in ("PENDING_PAYMENT", "ACTIVE", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE)

    existing = calc.agreement_visits(agreement_id)
    if any(int(v["sequence_number"]) == int(sequence) for v in existing):
        raise ApiError(ERR_DUPLICATE_VISIT_SEQUENCE)
    entitlement = calc.visit_bucket_total(agreement)
    if int(sequence) > entitlement:
        raise ApiError(ERR_SUBSCRIPTION_TERM_EXCEEDED)

    row = store.new_row(
        "MembershipVisit",
        membership_agreement_id=agreement_id,
        branch_id=agreement["branch_id"],
        sequence_number=int(sequence),
        scheduled_date=scheduled_date,
        status="SCHEDULED",
        completed_appointment_id=None,
        completed_at_utc=None,
        deferred_revenue_cents=0,
    )
    store.membership_visits[row["id"]] = row
    calc.deferred_revenue_waterfall(agreement_id)
    store.touch(agreement)
    return created(serializers.membership_visit(row))


@bp.route("/membership-agreements/<agreement_id>/membership-visits", methods=["GET"])
def list_visits(agreement_id):
    require_roles([ROLE_DISPATCHER, ROLE_MANAGER])
    _get_agreement(agreement_id)
    limit, offset = read_pagination(request.args)
    status = request.args.get("status")
    items = calc.agreement_visits(agreement_id)
    if status:
        items = [v for v in items if v["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.membership_visit(v) for v in page], limit, offset, total)


@bp.route("/membership-visits/<visit_id>/reschedule", methods=["POST"])
def reschedule_visit(visit_id):
    require_roles([ROLE_DISPATCHER])
    visit = _get_visit(visit_id)
    payload = body_json()
    new_date = optional_datetime(payload, "scheduled_date")
    if new_date is None:
        raise invalid_request("scheduled_date is required")

    agreement = _get_agreement(visit["membership_agreement_id"])

    if visit["status"] not in ("SCHEDULED", "MISSED"):
        raise ApiError(ERR_INVALID_STATE)
    if agreement["status"] not in ("PENDING_PAYMENT", "ACTIVE", "OVERDUE"):
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE)
    if not new_date > clock.now():
        raise invalid_request("scheduled_date must be strictly later than the logical clock reading")

    plan = store.membership_plans.get(agreement["membership_plan_id"])
    interval_days = int(plan["maintenance_visit_interval_days"]) if plan else 0
    from datetime import timedelta
    new_start = new_date
    new_end = new_date + timedelta(days=interval_days)

    alive_start = agreement.get("agreement_start_utc")
    for other in calc.agreement_visits(agreement["id"]):
        if other["id"] == visit["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_start = other["scheduled_date"]
        other_end = other["scheduled_date"] + timedelta(days=interval_days)
        if alive_start is not None:
            if other_end <= alive_start:
                continue
        if new_start < other_end and other_start < new_end:
            raise ApiError(ERR_VISIT_OVERLAP)

    visit["status"] = "SCHEDULED"
    visit["scheduled_date"] = new_date
    store.touch(visit)
    calc.deferred_revenue_waterfall(agreement["id"])
    if agreement["status"] == "OVERDUE":
        remaining = [v for v in calc.agreement_visits(agreement["id"]) if v["status"] == "MISSED"]
        if not remaining:
            agreement["status"] = "ACTIVE"
    store.touch(agreement)
    return object_ok(serializers.membership_visit(visit))


@bp.route("/membership-agreements/<agreement_id>/cancel", methods=["POST"])
def cancel_agreement(agreement_id):
    require_roles([ROLE_MANAGER])
    agreement = _get_agreement(agreement_id)
    payload = body_json()
    optional_str(payload, "reason")

    status = agreement["status"]
    if status == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE)

    if status == "ACTIVE":
        missed = [v for v in calc.agreement_visits(agreement_id) if v["status"] == "MISSED"]
        if missed:
            raise ApiError(ERR_MEMBERSHIP_CANCEL_BLOCKED)
        fulfilled = calc.visits_fulfilled_count(agreement_id)
        if fulfilled > 0:
            annual = int(agreement["annual_price_cents"])
            refund = calc.refund_amount_cents(annual)
            if refund >= annual:
                raise ApiError(ERR_MEMBERSHIP_CANCEL_BLOCKED)
        agreement["unearned_revenue_balance_cents"] = 0
        agreement["revenue_recognized_cents"] = int(agreement["annual_price_cents"])

    agreement["status"] = "CANCELLED"
    store.touch(agreement)
    branch = store.branches.get(agreement["branch_id"])
    if branch is not None:
        branch["updated_at"] = store.now_utc()
    return object_ok(serializers.membership_agreement(agreement))