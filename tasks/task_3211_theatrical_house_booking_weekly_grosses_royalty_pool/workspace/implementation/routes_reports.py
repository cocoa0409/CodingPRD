"""Weekly gross reports: create, read, submit, verify, reject, revise, settlement fetch."""
from datetime import timedelta

from flask import Blueprint

import errors as E
import services as S
from db import STORE
from middleware import require_roles, require_company_owns
from response import (new_common, ok_object, ok_array, paginate, require_field,
                      parse_dt, fmt_dt, clock_now, touch, get_json_body)

bp = Blueprint("reports", __name__)

HM_REP = ("HouseManager", "CompanyRep")


def _get_report_or_404(rid):
    r = STORE.weekly_reports.get(rid)
    if not r:
        raise E.not_found("Weekly gross report not found")
    return r


def _require_owning_rep(user_id, booking):
    require_company_owns(STORE, user_id, S.company_of_booking(booking))


@bp.post("/theatres/bookings/<bid>/weekly-gross-reports")
def create_report(bid):
    user_id, _ = require_roles("CompanyRep")
    booking = STORE.bookings.get(bid)
    if not booking:
        raise E.not_found("Booking not found")
    _require_owning_rep(user_id, booking)
    body = get_json_body()
    ws_raw = require_field(body, "week_start")
    ws = parse_dt(ws_raw, "week_start")
    # week_start must be a Monday 00:00:00 UTC
    if (ws.weekday() != 0 or ws.hour != 0 or ws.minute != 0
            or ws.second != 0 or ws.microsecond != 0):
        raise E.invalid_request("week_start must be a Monday at 00:00:00 UTC")
    ws_s = fmt_dt(ws)
    for r in STORE.weekly_reports.values():
        if r["booking_id"] == bid and r["week_start"] == ws_s:
            raise E.report_week_duplicate()
    we_s = fmt_dt(ws + timedelta(days=7))
    rec = new_common()
    rec.update({"booking_id": bid, "week_start": ws_s, "week_end": we_s,
                "status": "DRAFT",
                "gross_cents": S.weekly_gross(bid, ws_s, we_s)})
    STORE.weekly_reports[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/weekly-gross-reports/<rid>")
def get_report(rid):
    require_roles(*HM_REP)
    return ok_object(_get_report_or_404(rid))


@bp.post("/theatres/weekly-gross-reports/<rid>/submit")
def submit_report(rid):
    user_id, _ = require_roles("CompanyRep")
    report = _get_report_or_404(rid)
    booking = STORE.bookings.get(report["booking_id"])
    if report["status"] != "DRAFT":
        raise E.invalid_state("Only a DRAFT report can be submitted")
    if not booking or booking["status"] != "ACTIVE":
        raise E.invalid_state("Submitting requires an ACTIVE booking")
    _require_owning_rep(user_id, booking)
    if parse_dt(report["week_end"], "week_end") > clock_now():
        raise E.invalid_state("The week has not fully elapsed")
    # final variant: re-derive once and freeze for review
    report["gross_cents"] = S.weekly_gross(report["booking_id"],
                                           report["week_start"], report["week_end"])
    report["status"] = "SUBMITTED"
    touch(report)
    return ok_object(report)


@bp.post("/theatres/weekly-gross-reports/<rid>/verify")
def verify_report(rid):
    require_roles("HouseManager")
    report = _get_report_or_404(rid)
    if report["status"] != "SUBMITTED":
        raise E.invalid_state("Only a SUBMITTED report can be verified")
    report["status"] = "VERIFIED"  # gross_cents locked
    touch(report)
    booking = STORE.bookings.get(report["booking_id"])
    if booking:
        S.apply_stop_clause(booking, report["gross_cents"])
    return ok_object(report)


@bp.post("/theatres/weekly-gross-reports/<rid>/reject")
def reject_report(rid):
    require_roles("HouseManager")
    report = _get_report_or_404(rid)
    if report["status"] != "SUBMITTED":
        raise E.invalid_state("Only a SUBMITTED report can be rejected")
    report["status"] = "REJECTED"
    touch(report)
    return ok_object(report)


@bp.post("/theatres/weekly-gross-reports/<rid>/revise")
def revise_report(rid):
    user_id, _ = require_roles("CompanyRep")
    report = _get_report_or_404(rid)
    booking = STORE.bookings.get(report["booking_id"])
    if report["status"] != "REJECTED":
        raise E.invalid_state("Only a REJECTED report can be revised")
    if not booking or booking["status"] != "ACTIVE":
        raise E.invalid_state("Revising requires an ACTIVE booking")
    _require_owning_rep(user_id, booking)
    report["status"] = "DRAFT"
    report["gross_cents"] = S.weekly_gross(report["booking_id"],
                                           report["week_start"], report["week_end"])
    touch(report)
    return ok_object(report)


@bp.get("/theatres/weekly-gross-reports/<rid>/settlement")
def report_settlement(rid):
    require_roles(*HM_REP)
    _get_report_or_404(rid)
    items = [s for s in STORE.settlements.values() if s["report_id"] == rid]
    page, limit, offset, total = paginate(items, {"limit": "100", "offset": "0"})
    return ok_array(page, limit, offset, total)
