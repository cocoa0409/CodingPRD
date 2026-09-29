"""Program configuration: languages, courthouses and rate schedules (PRD 3.1)."""
from flask import Blueprint, request

import cascades
import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, touch
from util import fmt_date, parse_date
from validation import (
    LOWER3,
    UPPER3,
    bool_field,
    body_of,
    date_field,
    enum_field,
    int_field,
    num_field,
    query_date,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("config", __name__)

READ_ALL = (
    "ProgramAdmin",
    "CredentialingOfficer",
    "SchedulingCoordinator",
    "FiscalOfficer",
    "QualityReviewer",
    "Interpreter",
)
TIER_CLASSES = ("DESIGNATED", "NON_DESIGNATED", "RARE")
EQUIPMENT_TIERS = ("NONE", "BASIC", "CERTIFIED_VRI")
FACILITY_STATUSES = ("OPEN", "CLOSED")


# --------------------------------------------------------------------------
# languages
# --------------------------------------------------------------------------
@bp.route("/languages", methods=["POST"])
def create_language():
    require("ProgramAdmin")
    body = body_of(request)
    code = str_field(body, "code", pattern=LOWER3, label="three lowercase letters")
    name = str_field(body, "name")
    tier_class = enum_field(body, "tier_class", TIER_CLASSES)
    oral_exam_available = bool_field(body, "oral_exam_available")
    telephonic = bool_field(body, "telephonic_vendor_available", required=False, default=False)

    for existing in db.languages.values():
        if existing["code"] == code:
            raise ApiError(
                "ERR_DUPLICATE_LANGUAGE_CODE", "That language code is already registered."
            )

    row = new_row()
    row.update(
        {
            "code": code,
            "name": name,
            "tier_class": tier_class,
            "oral_exam_available": oral_exam_available,
            "telephonic_vendor_available": telephonic,
        }
    )
    db.languages[row["id"]] = row
    return object_response(S.language_out(row), 201)


@bp.route("/languages", methods=["GET"])
def list_languages():
    require(*READ_ALL)
    limit, offset = read_pagination(request.args)
    tier_class = query_enum(request.args, "tier_class", TIER_CLASSES)
    rows = [
        r
        for r in db.languages.values()
        if tier_class is None or r["tier_class"] == tier_class
    ]
    rows = sorted(rows, key=lambda r: (r["code"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response([S.language_out(r) for r in page], limit, offset, total)


@bp.route("/languages/<language_id>", methods=["GET"])
def get_language(language_id):
    require(*READ_ALL)
    row = derive.get_language(language_id)
    return object_response(S.language_out(row))


# --------------------------------------------------------------------------
# courthouses
# --------------------------------------------------------------------------
@bp.route("/courthouses", methods=["POST"])
def create_courthouse():
    require("ProgramAdmin")
    body = body_of(request)
    name = str_field(body, "name")
    county_code = str_field(body, "county_code", pattern=UPPER3, label="three uppercase letters")
    courtroom_count = int_field(body, "courtroom_count", minimum=1)
    tier = enum_field(body, "remote_equipment_tier", EQUIPMENT_TIERS)
    capacity = int_field(body, "vri_concurrent_capacity", minimum=0)
    budget = int_field(body, "pay_budget_cents", minimum=0)
    status = enum_field(body, "status", FACILITY_STATUSES, required=False, default="OPEN")

    row = new_row()
    row.update(
        {
            "name": name,
            "county_code": county_code,
            "courtroom_count": courtroom_count,
            "remote_equipment_tier": tier,
            "vri_concurrent_capacity": capacity,
            "status": status,
            "pay_budget_cents": budget,
        }
    )
    db.courthouses[row["id"]] = row
    return object_response(S.courthouse_out(row), 201)


@bp.route("/courthouses", methods=["GET"])
def list_courthouses():
    require(*READ_ALL)
    limit, offset = read_pagination(request.args)
    county_code = query_str(request.args, "county_code")
    tier = query_enum(request.args, "remote_equipment_tier", EQUIPMENT_TIERS)
    status = query_enum(request.args, "status", FACILITY_STATUSES)
    rows = []
    for r in db.courthouses.values():
        if county_code is not None and r["county_code"] != county_code:
            continue
        if tier is not None and r["remote_equipment_tier"] != tier:
            continue
        if status is not None and r["status"] != status:
            continue
        rows.append(r)
    rows = sorted(rows, key=lambda r: (r["name"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response([S.courthouse_out(r) for r in page], limit, offset, total)


@bp.route("/courthouses/<courthouse_id>", methods=["GET"])
def get_courthouse(courthouse_id):
    require(*READ_ALL)
    row = derive.get_courthouse(courthouse_id)
    return object_response(S.courthouse_out(row))


@bp.route("/courthouses/<courthouse_id>", methods=["PATCH"])
def update_courthouse(courthouse_id):
    require("ProgramAdmin")
    body = body_of(request)
    tier = enum_field(body, "remote_equipment_tier", EQUIPMENT_TIERS, required=False)
    capacity = int_field(body, "vri_concurrent_capacity", required=False, minimum=0)
    status = enum_field(body, "status", FACILITY_STATUSES, required=False)
    budget = int_field(body, "pay_budget_cents", required=False, minimum=0)

    row = derive.get_courthouse(courthouse_id)

    if budget is not None:
        encumbered, obligated, _ = derive.ledger(row)
        if budget < encumbered + obligated:
            raise ApiError(
                "ERR_COURTHOUSE_BUDGET_EXCEEDED",
                "The program will not un-commit money already promised.",
            )

    if tier is not None:
        row["remote_equipment_tier"] = tier
    if capacity is not None:
        row["vri_concurrent_capacity"] = capacity
    if status is not None:
        row["status"] = status
    if budget is not None:
        row["pay_budget_cents"] = budget
    touch(row)

    if (tier is not None and tier == "NONE") or (status is not None and status == "CLOSED"):
        withdrawn = []
        for assignment in db.assignments.values():
            if assignment["delivery_mode"] != "VRI":
                continue
            if assignment["service_status"] not in derive.CANCELLABLE_SERVICE_STATUSES:
                continue
            hearing = db.hearings.get(assignment["hearing_id"])
            if hearing is None or hearing["courthouse_id"] != row["id"]:
                continue
            withdrawn.append(assignment)
        cascades.cancel_live_assignments(withdrawn, "EQUIPMENT_WITHDRAWN")

    return object_response(S.courthouse_out(row))


@bp.route("/courthouses/<courthouse_id>/unmet-need-reports", methods=["GET"])
def list_courthouse_reports(courthouse_id):
    require("ProgramAdmin", "SchedulingCoordinator", "QualityReviewer")
    limit, offset = read_pagination(request.args)
    row = derive.get_courthouse(courthouse_id)
    rows = S.reports_of_courthouse(row["id"])
    page, total = paginate(rows, limit, offset)
    return array_response(
        [S.unmet_need_report_out(r) for r in page], limit, offset, total
    )


# --------------------------------------------------------------------------
# rate schedules
# --------------------------------------------------------------------------
@bp.route("/rate-schedules", methods=["POST"])
def create_rate_schedule():
    require("ProgramAdmin")
    body = body_of(request)
    effective_from = date_field(body, "effective_from")
    effective_through = date_field(body, "effective_through", required=False)
    master = int_field(body, "master_hourly_cents", minimum=0)
    certified = int_field(body, "certified_hourly_cents", minimum=0)
    registered = int_field(body, "registered_hourly_cents", minimum=0)
    provisional = int_field(body, "provisional_hourly_cents", minimum=0)
    minimum_call_hours = num_field(body, "minimum_call_hours", minimum=0)
    mileage_rate = num_field(body, "travel_mileage_rate_cents", minimum=0)
    free_radius = num_field(body, "travel_free_radius_miles", minimum=0)
    remote_multiplier = num_field(body, "remote_rate_multiplier", minimum=0)
    late_hours = int_field(body, "late_cancellation_hours", minimum=0)
    late_pay_hours = num_field(body, "late_cancellation_pay_hours", minimum=0)
    low_pct = num_field(body, "rare_premium_low_pct", minimum=0)
    high_pct = num_field(body, "rare_premium_high_pct", minimum=0)
    bracket = int_field(body, "rare_premium_bracket_cents", minimum=0)

    for existing in db.rate_schedules.values():
        start = parse_date(existing["effective_from"])
        through = (
            parse_date(existing["effective_through"])
            if existing["effective_through"]
            else None
        )
        overlaps = (through is None or effective_from <= through) and (
            effective_through is None or start <= effective_through
        )
        if overlaps:
            raise ApiError(
                "ERR_RATE_SCHEDULE_OVERLAP",
                "That window overlaps an existing rate schedule.",
            )

    row = new_row()
    row.update(
        {
            "effective_from": fmt_date(effective_from),
            "effective_through": fmt_date(effective_through),
            "master_hourly_cents": master,
            "certified_hourly_cents": certified,
            "registered_hourly_cents": registered,
            "provisional_hourly_cents": provisional,
            "minimum_call_hours": minimum_call_hours,
            "travel_mileage_rate_cents": mileage_rate,
            "travel_free_radius_miles": free_radius,
            "remote_rate_multiplier": remote_multiplier,
            "late_cancellation_hours": late_hours,
            "late_cancellation_pay_hours": late_pay_hours,
            "rare_premium_low_pct": low_pct,
            "rare_premium_high_pct": high_pct,
            "rare_premium_bracket_cents": bracket,
        }
    )
    db.rate_schedules[row["id"]] = row
    return object_response(S.rate_schedule_out(row), 201)


@bp.route("/rate-schedules", methods=["GET"])
def list_rate_schedules():
    require("ProgramAdmin", "FiscalOfficer", "SchedulingCoordinator", "Interpreter")
    limit, offset = read_pagination(request.args)
    effective_on = query_date(request.args, "effective_on")
    rows = list(db.rate_schedules.values())
    if effective_on is not None:
        match = derive.effective_rate_schedule(effective_on)
        rows = [match] if match is not None else []
    rows = sorted(rows, key=lambda r: (r["effective_from"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response([S.rate_schedule_out(r) for r in page], limit, offset, total)


@bp.route("/rate-schedules/<rate_schedule_id>", methods=["GET"])
def get_rate_schedule(rate_schedule_id):
    require("ProgramAdmin", "FiscalOfficer", "SchedulingCoordinator", "Interpreter")
    row = derive.get_rate_schedule(rate_schedule_id)
    return object_response(S.rate_schedule_out(row))
