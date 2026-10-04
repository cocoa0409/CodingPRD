"""BoxOfficeReport endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_REPORT_NOT_FOUND, ERR_SLOT_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found, forbidden,
)
from util import (
    require_role, require_auth, get_body, req_str, req_int, req_enum,
    parse_pagination, paginate, success_object, success_list, stamp_new, sort_by_created,
    parse_iso_datetime, iso_format,
)
from domain import (
    serialize_box_office_report, recompute_slot_derived, recompute_statements_for_slot,
)

bp = Blueprint("box_office_reports", __name__)


def get_report_or_404(report_id):
    r = db.box_office_reports.get(report_id)
    if r is None:
        raise not_found(ERR_REPORT_NOT_FOUND, f"Report {report_id} not found")
    return r


def _owns_report(user_id, report):
    slot = db.screen_slots.get(report.get("screen_slot_id"))
    if slot is None:
        return False
    aud = db.auditoriums.get(slot.get("auditorium_id"))
    if aud is None:
        return False
    return aud.get("agreement_id") == user_id


@bp.post("/v1/box-office-reports")
def create_report():
    user_id, role = require_auth()
    if role not in ("ExhibitorFinanceUser", "BoxOfficeAnalyst"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    body = get_body()
    screen_slot_id = req_str(body, "screen_slot_id")
    reported_date = parse_iso_datetime(body.get("reported_date"), "reported_date")
    gross = req_int(body, "gross_receipts_cents")
    if gross < 0:
        raise bad_request(ERR_INVALID_REQUEST, "gross_receipts_cents must be >= 0")
    admissions = req_int(body, "admissions")
    if admissions < 0:
        raise bad_request(ERR_INVALID_REQUEST, "admissions must be >= 0")
    submission_channel = req_enum(body, "submission_channel",
                                  {"EXHIBITOR_PORTAL", "API_INGEST", "MANUAL_UPLOAD"})

    slot = db.screen_slots.get(screen_slot_id)
    if slot is None:
        raise not_found(ERR_SLOT_NOT_FOUND, f"Slot {screen_slot_id} not found")

    if role == "ExhibitorFinanceUser":
        aud = db.auditoriums.get(slot.get("auditorium_id"))
        if aud is None or aud.get("agreement_id") != user_id:
            raise forbidden("ExhibitorFinanceUser may only submit reports for own agreement's slots")

    report = {
        "screen_slot_id": screen_slot_id,
        "reported_date": iso_format(reported_date),
        "_reported_date_dt": reported_date,
        "gross_receipts_cents": gross,
        "admissions": admissions,
        "submission_channel": submission_channel,
        "status": "RECEIVED",
    }
    stamp_new(report, with_version=False)
    db.box_office_reports[report["id"]] = report
    return success_object(serialize_box_office_report(report), 201)


@bp.get("/v1/box-office-reports")
def list_reports():
    user_id, role = require_auth()
    if role not in ("BoxOfficeAnalyst", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.box_office_reports.values()))
    screen_slot_id = request.args.get("screen_slot_id")
    status = request.args.get("status")
    if screen_slot_id:
        items = [r for r in items if r.get("screen_slot_id") == screen_slot_id]
    if status:
        items = [r for r in items if r.get("status") == status]
    if role == "ExhibitorFinanceUser":
        items = [r for r in items if _owns_report(user_id, r)]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_box_office_report(r) for r in page], total, limit, offset)


@bp.get("/v1/box-office-reports/<report_id>")
def get_report(report_id):
    user_id, role = require_auth()
    if role not in ("BoxOfficeAnalyst", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    r = get_report_or_404(report_id)
    if role == "ExhibitorFinanceUser" and not _owns_report(user_id, r):
        raise forbidden("ExhibitorFinanceUser may only access own agreement resources")
    return success_object(serialize_box_office_report(r))


@bp.post("/v1/box-office-reports/<report_id>/validate")
def validate_report(report_id):
    require_role("BoxOfficeAnalyst")
    r = get_report_or_404(report_id)
    if r.get("status") != "RECEIVED":
        raise conflict(ERR_INVALID_STATE, f"Report in state {r.get('status')} cannot be validated")
    slot = db.screen_slots.get(r.get("screen_slot_id"))
    if slot is None or slot.get("status") not in ("CONFIRMED", "HELD_OVER", "PULLED", "SUSPENDED"):
        raise conflict(ERR_INVALID_STATE,
                       "Parent slot must be CONFIRMED, HELD_OVER, PULLED, or SUSPENDED")
    r["status"] = "VALIDATED"
    # immutable: no updated_at/version
    slot["weekly_gross_cents"] = slot.get("weekly_gross_cents", 0) + r.get("gross_receipts_cents", 0)
    slot["weekly_admissions"] = slot.get("weekly_admissions", 0) + r.get("admissions", 0)
    recompute_slot_derived(slot)
    recompute_statements_for_slot(slot)
    return success_object(serialize_box_office_report(r))


@bp.post("/v1/box-office-reports/<report_id>/flag-discrepancy")
def flag_discrepancy(report_id):
    require_role("BoxOfficeAnalyst")
    r = get_report_or_404(report_id)
    if r.get("status") != "RECEIVED":
        raise conflict(ERR_INVALID_STATE, f"Report in state {r.get('status')} cannot be flagged")
    r["status"] = "FLAGGED_DISCREPANCY"
    return success_object(serialize_box_office_report(r))
