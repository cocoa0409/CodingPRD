"""Booking, lines, listing and repricing (PRD 3.3, 3.4)."""

from flask import Blueprint, request

from constants import (ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER,
                       ROLE_CUSTOMER_SERVICE, LINE_STATUSES, OPTION_TIERS)
from common import (body_json, require_roles, require_str, require_int,
                    optional_int, optional_str, optional_datetime, enum_field,
                    is_five_digits, require_field)
from constants import clock
import store
import serializers
import calc
from errors import (not_found, invalid_request, ApiError,
                    ERR_WINDOW_INVALID, ERR_WINDOW_OVERLAP,
                    ERR_AGREEMENT_NOT_ACTIVE, ERR_MEMBER_VISIT_SEQUENCE_INVALID,
                    ERR_PRICEBOOK_REVISION_NOT_PUBLISHED, ERR_STALE_VERSION,
                    ERR_INVALID_STATE)
from response import (created, object_ok, array_ok, read_pagination, paginate)

bp = Blueprint("appointments", __name__)

READ_ROLES = [ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER, ROLE_CUSTOMER_SERVICE]
LINE_READ_ROLES = [ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER]


def _get_appointment(appointment_id):
    row = store.appointments.get(appointment_id)
    if row is None:
        raise not_found("appointment")
    return row


def _overlaps(start_a, end_a, start_b, end_b):
    """Half-open interval intersection (PRD 3.3)."""
    return start_a < end_b and start_b < end_a


def branch_window_collision(branch_id, start, end, exclude_id=None):
    # The collision guard is priority 7 and runs ahead of the window-ordering guard at
    # priority 8 (PRD 2.10), so it must be able to see a collision even when the
    # supplied window is reversed: its occupied span is the interval between the two
    # supplied endpoints.
    low, high = (start, end) if start <= end else (end, start)
    for other in store.appointments.values():
        if other["id"] == exclude_id:
            continue
        if other["branch_id"] != branch_id:
            continue
        if other["status"] not in ("SCHEDULED", "DISPATCHED"):
            continue
        if _overlaps(low, high, other["window_start_utc"], other["window_end_utc"]):
            return True
    return False


@bp.route("/appointments", methods=["POST"])
def create_appointment():
    require_roles([ROLE_DISPATCHER])
    payload = body_json()
    branch_id = require_str(payload, "branch_id")
    branch = store.branches.get(branch_id)
    if branch is None:
        raise not_found("branch")
    customer_name = require_str(payload, "customer_name")
    postal_code = require_str(payload, "postal_code")
    if not is_five_digits(postal_code):
        raise invalid_request("postal_code must be exactly five digits")
    window_start = optional_datetime(payload, "window_start_utc")
    window_end = optional_datetime(payload, "window_end_utc")
    if window_start is None:
        raise invalid_request("window_start_utc is required")
    if window_end is None:
        raise invalid_request("window_end_utc is required")

    campaign_id = optional_str(payload, "campaign_id")
    call_record_id = optional_str(payload, "call_record_id")
    agreement_id = optional_str(payload, "membership_agreement_id")
    sequence = optional_int(payload, "membership_visit_sequence_number")

    call = None
    if call_record_id:
        call = store.call_records.get(call_record_id)
        if call is None:
            raise not_found("call record")
        if not campaign_id:
            campaign_id = call["campaign_id"]
    if campaign_id and campaign_id not in store.campaigns:
        raise not_found("campaign")

    agreement = None
    if agreement_id:
        agreement = store.membership_agreements.get(agreement_id)
        if agreement is None:
            raise not_found("membership agreement")

    # --- branch window collision guard (priority 7) ------------------------
    if branch_window_collision(branch_id, window_start, window_end):
        raise ApiError(ERR_WINDOW_OVERLAP)
    # --- window-ordering guard (priority 8) --------------------------------
    if not window_end > window_start:
        raise ApiError(ERR_WINDOW_INVALID)
    # --- linked-agreement status guard (priority 20) -----------------------
    if agreement is not None:
        if agreement["branch_id"] != branch_id:
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE)
        if agreement["status"] not in ("PENDING_PAYMENT", "ACTIVE"):
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE)
    # --- membership visit sequence guard (priority 11) ---------------------
    if sequence is not None:
        if agreement is None:
            raise ApiError(ERR_MEMBER_VISIT_SEQUENCE_INVALID)
        match = [v for v in calc.agreement_visits(agreement_id)
                 if int(v["sequence_number"]) == int(sequence)]
        if not match or match[0]["status"] == "COMPLETED":
            raise ApiError(ERR_MEMBER_VISIT_SEQUENCE_INVALID)

    row = store.new_row(
        "Appointment",
        branch_id=branch_id,
        technician_id=None,
        membership_agreement_id=agreement_id,
        membership_visit_sequence_number=sequence,
        campaign_id=campaign_id,
        call_record_id=call_record_id,
        customer_name=customer_name,
        postal_code=postal_code,
        window_start_utc=window_start,
        window_end_utc=window_end,
        quoted_price_cents=0,
        authorization_required=False,
        current_pricebook_version_id=None,
        repriced_at=None,
        load_units_trace=[],
        pricing_status="NOT_QUOTED",
        status="SCHEDULED",
        dispatch_status="UNASSIGNED",
        _released_technician_ids=[],
    )
    store.appointments[row["id"]] = row

    if call is not None:
        call["attributed_appointment_id"] = row["id"]
        store.touch(call)

    return created(serializers.appointment(row))


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    require_roles(READ_ROLES)
    limit, offset = read_pagination(request.args)
    items = store.by_created(store.appointments)
    filters = {
        "branch_id": request.args.get("branch_id"),
        "technician_id": request.args.get("technician_id"),
        "status": request.args.get("status"),
        "campaign_id": request.args.get("campaign_id"),
        "membership_agreement_id": request.args.get("membership_agreement_id"),
        "call_record_id": request.args.get("call_record_id"),
    }
    for field, value in filters.items():
        if value not in (None, ""):
            items = [a for a in items if a.get(field) == value]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.appointment(a) for a in page], limit, offset, total)


@bp.route("/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    require_roles(READ_ROLES)
    row = _get_appointment(appointment_id)
    return object_ok(serializers.appointment(row))


# ------------------------------------------------------------------- lines
@bp.route("/appointments/<appointment_id>/lines", methods=["POST"])
def add_line(appointment_id):
    require_roles([ROLE_DISPATCHER])
    row = _get_appointment(appointment_id)
    payload = body_json()
    code = require_str(payload, "pricebook_task_code")
    option_tier = enum_field(payload, "option_tier", OPTION_TIERS, None)
    line_status = enum_field(payload, "status", LINE_STATUSES, "PROPOSED")

    revision = calc.selected_revision(code)
    if revision is None:
        raise ApiError(ERR_PRICEBOOK_REVISION_NOT_PUBLISHED)

    line = store.new_child_row(
        appointment_id=appointment_id,
        pricebook_task_id=revision["id"],
        option_tier=option_tier,
        status=line_status,
        flat_rate_cents=revision["flat_rate_cents"],
    )
    store.appointment_lines[line["id"]] = line
    store.LINE_ADD_SEQ[line["id"]] = store.next_line_seq()

    row["load_units_trace"] = calc.household_load_trace(appointment_id)
    row["current_pricebook_version_id"] = revision["id"]
    store.touch(row)
    return created(serializers.appointment_line(line))


@bp.route("/appointments/<appointment_id>/lines", methods=["GET"])
def list_lines(appointment_id):
    require_roles(LINE_READ_ROLES)
    _get_appointment(appointment_id)
    limit, offset = read_pagination(request.args)
    status = request.args.get("status")
    items = [ln for ln in store.by_created(store.appointment_lines)
             if ln["appointment_id"] == appointment_id]
    if status:
        items = [ln for ln in items if ln["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.appointment_line(ln) for ln in page], limit, offset, total)


# ----------------------------------------------------------------- reprice
@bp.route("/appointments/<appointment_id>/reprice", methods=["POST"])
def reprice(appointment_id):
    require_roles([ROLE_DISPATCHER])
    row = _get_appointment(appointment_id)
    payload = body_json()
    expected = require_field(payload, "expected_pricebook_task_version")
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        raise invalid_request("expected_pricebook_task_version must be an integer")
    optional_str(payload, "pricebook_task_id")

    if row["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE)

    # stale-version precondition (PRD 2.7, 3.4)
    for line in calc.appointment_lines(appointment_id):
        task = store.pricebook_tasks.get(line["pricebook_task_id"])
        if task is not None and int(task["version"]) != int(expected):
            raise ApiError(ERR_STALE_VERSION)

    # the operation only does something when the pricebook has genuinely moved
    if not calc.has_newer_published_revision(appointment_id):
        return object_ok(serializers.appointment(row))

    touched_tasks = set()
    for line in calc.appointment_lines(appointment_id):
        task = store.pricebook_tasks.get(line["pricebook_task_id"])
        if task is None:
            continue
        head = calc.selected_revision(task["code"])
        if head is None:
            continue
        line["pricebook_task_id"] = head["id"]
        line["flat_rate_cents"] = head["flat_rate_cents"]
        if line.get("option_tier"):
            line["status"] = "PROPOSED"
        touched_tasks.add(head["id"])

    discount = calc.invoice_discount_pct(row)
    new_base = calc.appointment_labor_base(appointment_id)
    row["quoted_price_cents"] = calc.cubic_quote(new_base, discount)
    row["authorization_required"] = calc.authorization_required_for(
        row["quoted_price_cents"], new_base)
    row["repriced_at"] = clock.now()
    row["current_pricebook_version_id"] = calc.current_pricebook_version_id(appointment_id)
    row["load_units_trace"] = calc.household_load_trace(appointment_id)
    store.touch(row)
    # PRD 3.4: "Repricing bumps the version of the `PricebookTask` revision as well as
    # the appointment's own version, because the revision — or rather the code's head —
    # has been touched."  Every revision the operation re-anchored is advanced, so a
    # later reprice still carrying the version read before it is refused as stale.
    for task_id in touched_tasks:
        task = store.pricebook_tasks.get(task_id)
        if task is not None:
            store.touch(task)
    return object_ok(serializers.appointment(row))