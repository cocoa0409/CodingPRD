"""Platform configuration: branches, technicians, plans, campaigns, clock."""

from flask import Blueprint, request

from constants import (ROLE_PLATFORM_ADMIN, ROLE_DISPATCHER, ROLE_MANAGER,
                       PLAN_STATUSES, TECH_STATUSES, CAMPAIGN_CHANNELS,
                       DEFAULT_BRANCH_CAPACITY_HOURS, TERM_MONTHS_ALLOWED)
from common import (body_json, require_roles, require_str, optional_field,
                    optional_int, optional_number, optional_str, optional_datetime,
                    enum_field, is_five_digits, require_int)
import store
import serializers
import calc
from errors import not_found, invalid_request, ApiError, ERR_NOT_FOUND
from response import array_ok, created, object_ok, read_pagination, paginate, success

bp = Blueprint("org", __name__)


# --------------------------------------------------------------- branches
@bp.route("/branches", methods=["POST"])
def create_branch():
    require_roles([ROLE_PLATFORM_ADMIN])
    payload = body_json()
    name = require_str(payload, "name")
    postal_code = require_str(payload, "postal_code")
    if not is_five_digits(postal_code):
        raise invalid_request("postal_code must be exactly five digits")
    capacity = optional_number(payload, "daily_dispatch_capacity_hours",
                               DEFAULT_BRANCH_CAPACITY_HOURS)
    if capacity is None or float(capacity) <= 0:
        raise invalid_request("daily_dispatch_capacity_hours must be greater than zero")
    row = store.new_row(
        "Branch",
        name=name,
        postal_code=postal_code,
        daily_dispatch_capacity_hours=float(calc.hours_of(capacity)),
    )
    store.branches[row["id"]] = row
    return created(serializers.branch(row))


@bp.route("/branches/<branch_id>", methods=["GET"])
def get_branch(branch_id):
    require_roles([ROLE_PLATFORM_ADMIN, ROLE_DISPATCHER, ROLE_MANAGER])
    row = store.branches.get(branch_id)
    if row is None:
        raise not_found("branch")
    return object_ok(serializers.branch(row))


@bp.route("/branches/<branch_id>/technicians", methods=["POST"])
def hire_technician(branch_id):
    require_roles([ROLE_PLATFORM_ADMIN])
    branch = store.branches.get(branch_id)
    if branch is None:
        raise not_found("branch")
    payload = body_json()
    name = require_str(payload, "name")
    postal_code = require_str(payload, "postal_code")
    if not is_five_digits(postal_code):
        raise invalid_request("postal_code must be exactly five digits")
    capacity = optional_number(payload, "daily_capacity_hours")
    if capacity is None or float(capacity) <= 0:
        raise invalid_request("daily_capacity_hours must be greater than zero and is required")
    segments = payload.get("shift_segments")
    if not isinstance(segments, list) or not segments:
        raise invalid_request("shift_segments must be a non-empty array")
    parsed_segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise invalid_request("each shift_segment must be an object")
        start = optional_datetime(segment, "start_utc")
        end = optional_datetime(segment, "end_utc")
        if start is None or end is None:
            raise invalid_request("a shift_segment requires start_utc and end_utc")
        if not end > start:
            raise invalid_request("a shift segment's end_utc must be strictly later than its start_utc")
        parsed_segments.append({"start_utc": start, "end_utc": end})
    skills = payload.get("skill_codes")
    if skills is None:
        skills = []
    if not isinstance(skills, list) or any(not isinstance(s, str) for s in skills):
        raise invalid_request("skill_codes must be an array of strings")
    status = enum_field(payload, "status", TECH_STATUSES, "AVAILABLE")
    row = store.new_row(
        "Technician",
        home_branch_id=branch_id,
        name=name,
        postal_code=postal_code,
        skill_codes=list(skills),
        shift_segments=parsed_segments,
        daily_capacity_hours=float(calc.hours_of(capacity)),
        status=status,
        performance_status="CLEAR",
        sales_coaching_strike_count=0,
        _excluded_appointments=[],
    )
    store.technicians[row["id"]] = row
    return created(serializers.technician(row))


@bp.route("/branches/<branch_id>/technicians", methods=["GET"])
def list_technicians(branch_id):
    require_roles([ROLE_DISPATCHER, ROLE_PLATFORM_ADMIN])
    branch = store.branches.get(branch_id)
    if branch is None:
        raise not_found("branch")
    limit, offset = read_pagination(request.args)
    items = [t for t in store.by_created(store.technicians)
             if t["home_branch_id"] == branch_id]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.technician(t) for t in page], limit, offset, total)


# -------------------------------------------------------- membership plans
@bp.route("/membership-plans", methods=["POST"])
def create_plan():
    require_roles([ROLE_PLATFORM_ADMIN])
    payload = body_json()
    name = require_str(payload, "name")
    annual = require_int(payload, "annual_price_cents")
    if annual <= 0:
        raise invalid_request("annual_price_cents must be greater than zero")
    visits = require_int(payload, "included_service_visit_count")
    if visits < 1:
        raise invalid_request("included_service_visit_count must be at least 1")
    interval = require_int(payload, "maintenance_visit_interval_days")
    if interval < 1:
        raise invalid_request("maintenance_visit_interval_days must be at least 1")
    discount = optional_number(payload, "included_labor_discount_pct")
    if discount is None:
        raise invalid_request("included_labor_discount_pct is required")
    if float(discount) < 0 or float(discount) > 1:
        raise invalid_request("included_labor_discount_pct must be between 0 and 1 inclusive")
    status = enum_field(payload, "status", PLAN_STATUSES, "DRAFT")
    row = store.new_row(
        "MembershipPlan",
        name=name,
        annual_price_cents=annual,
        included_service_visit_count=visits,
        maintenance_visit_interval_days=interval,
        included_labor_discount_pct=float(discount),
        status=status,
    )
    store.membership_plans[row["id"]] = row
    return created(serializers.membership_plan(row))


# --------------------------------------------------------------- campaigns
@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    require_roles([ROLE_PLATFORM_ADMIN])
    payload = body_json()
    name = require_str(payload, "name")
    channel = enum_field(payload, "channel", CAMPAIGN_CHANNELS, required=True)
    spend = optional_int(payload, "spend_cents", 0)
    if spend is None:
        spend = 0
    if spend < 0:
        raise invalid_request("spend_cents must not be negative")
    row = store.new_row("Campaign", name=name, channel=channel, spend_cents=spend)
    store.campaigns[row["id"]] = row
    return created(serializers.campaign(row))


# ------------------------------------------------------------ logical clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles([ROLE_PLATFORM_ADMIN])
    payload = body_json()
    to_iso = require_str(payload, "to_iso8601")
    reading = store.parse_iso(to_iso, "to_iso8601")
    from constants import clock
    clock.set(reading)
    _overdue_sweep(reading)
    return object_ok({})


def _overdue_sweep(reading):
    """PRD 3.9: visits past due go MISSED, ACTIVE agreements carrying a
    MISSED visit go OVERDUE, and the branches behind them are refreshed."""
    touched_branches = set()
    affected_agreements = set()
    for visit in store.by_created(store.membership_visits):
        if visit["status"] != "SCHEDULED":
            continue
        if visit["scheduled_date"] < reading:
            visit["status"] = "MISSED"
            store.touch(visit)
            affected_agreements.add(visit["membership_agreement_id"])
    for agreement_id in affected_agreements:
        agreement = store.membership_agreements.get(agreement_id)
        if agreement is None or agreement["status"] != "ACTIVE":
            continue
        if any(v["status"] == "MISSED" for v in calc.agreement_visits(agreement_id)):
            agreement["status"] = "OVERDUE"
            store.touch(agreement)
            touched_branches.add(agreement["branch_id"])
    for branch_id in touched_branches:
        branch = store.branches.get(branch_id)
        if branch is not None:
            branch["updated_at"] = store.now_utc()