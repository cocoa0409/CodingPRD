"""Bookings: create, approve/decline/withdraw/close/execute_stop_notice, nested lists."""
from flask import Blueprint, request

import errors as E
import services as S
from db import STORE
from middleware import require_roles, require_company_owns
from response import (new_common, ok_object, ok_array, paginate, require_field,
                      parse_dt, fmt_dt, clock_now, touch, get_json_body)

bp = Blueprint("bookings", __name__)

ANY = ("HouseManager", "CompanyRep", "BoxOfficeAgent")
HM_REP = ("HouseManager", "CompanyRep")


def _get_booking_or_404(bid):
    b = STORE.bookings.get(bid)
    if not b:
        raise E.not_found("Booking not found")
    return b


def _require_owning_rep(user_id, booking):
    require_company_owns(STORE, user_id, S.company_of_booking(booking))


@bp.post("/theatres/bookings")
def create_booking():
    user_id, _ = require_roles("CompanyRep")
    body = get_json_body()
    production_id = require_field(body, "production_id")
    theatre_id = require_field(body, "theatre_id")
    loadin_raw = require_field(body, "loadin_start")
    runend_raw = require_field(body, "run_end")
    ls = parse_dt(loadin_raw, "loadin_start")
    re_ = parse_dt(runend_raw, "run_end")
    if re_ <= ls:
        raise E.invalid_request("run_end must be > loadin_start")
    prod = STORE.productions.get(production_id)
    if not prod:
        raise E.not_found("Production not found")
    theatre = STORE.theatres.get(theatre_id)
    if not theatre:
        raise E.not_found("Theatre not found")
    require_company_owns(STORE, user_id, prod["company_id"])
    if ls <= clock_now():
        raise E.invalid_request("loadin_start must be future-dated")
    rec = new_common()
    rec.update({"production_id": production_id, "theatre_id": theatre_id,
                "loadin_start": fmt_dt(ls), "run_end": fmt_dt(re_),
                "status": "REQUESTED"})
    if S.SIZE_RANK[theatre["size_class"]] < S.SIZE_RANK[prod["required_size_class"]]:
        raise E.size_class_mismatch()
    if S.conflicting_bookings_for(rec) or S.conflicting_projects_for(rec):
        raise E.window_conflict()
    rec["decline_notice_sent"] = False
    STORE.bookings[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/bookings/<bid>")
def get_booking(bid):
    require_roles(*ANY)
    return ok_object(_get_booking_or_404(bid))


@bp.get("/theatres/bookings")
def list_bookings():
    require_roles(*ANY)
    items = list(STORE.bookings.values())
    for f in ("production_id", "theatre_id", "status"):
        v = request.args.get(f)
        if v:
            items = [b for b in items if b.get(f) == v]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.post("/theatres/bookings/<bid>/approve")
def approve_booking(bid):
    require_roles("HouseManager")
    booking = _get_booking_or_404(bid)
    if booking["status"] != "REQUESTED":
        raise E.invalid_state("Only a REQUESTED booking can be approved")
    prod = STORE.productions.get(booking["production_id"])
    theatre = STORE.theatres.get(booking["theatre_id"])
    if S.SIZE_RANK[theatre["size_class"]] < S.SIZE_RANK[prod["required_size_class"]]:
        raise E.size_class_mismatch()
    if S.conflicting_bookings_for(booking) or S.conflicting_projects_for(booking):
        raise E.window_conflict()
    if not S.landmark_maintenance_satisfied(booking):
        raise E.window_conflict("Landmark theatre requires a scheduled maintenance window near the engagement")
    booking["status"] = "APPROVED"
    touch(booking)
    S.cascade_decline_competitors(booking)
    return ok_object(booking)


@bp.post("/theatres/bookings/<bid>/decline")
def decline_booking(bid):
    require_roles("HouseManager")
    booking = _get_booking_or_404(bid)
    if booking["status"] != "REQUESTED":
        raise E.invalid_state("Only a REQUESTED booking can be declined")
    booking["status"] = "DECLINED"
    touch(booking)
    S.void_agreements_for(booking["id"])
    return ok_object(booking)


@bp.post("/theatres/bookings/<bid>/withdraw")
def withdraw_booking(bid):
    user_id, _ = require_roles("CompanyRep")
    booking = _get_booking_or_404(bid)
    if booking["status"] not in ("REQUESTED", "APPROVED"):
        raise E.invalid_state("Only a REQUESTED or APPROVED booking can be withdrawn")
    _require_owning_rep(user_id, booking)
    booking["status"] = "WITHDRAWN"
    touch(booking)
    S.void_agreements_for(booking["id"])
    return ok_object(booking)


@bp.post("/theatres/bookings/<bid>/close")
def close_booking(bid):
    user_id, _ = require_roles("CompanyRep")
    booking = _get_booking_or_404(bid)
    if booking["status"] != "ACTIVE":
        raise E.invalid_state("Only an ACTIVE booking can be closed")
    _require_owning_rep(user_id, booking)
    open_reports = [r for r in STORE.weekly_reports.values()
                    if r["booking_id"] == bid and r["status"] in ("DRAFT", "SUBMITTED")]
    if open_reports:
        raise E.invalid_state("Cannot close while a weekly gross report is DRAFT or SUBMITTED")
    booking["status"] = "CLOSED"
    touch(booking)
    return ok_object(booking)


@bp.post("/theatres/bookings/<bid>/execute_stop_notice")
def execute_stop_notice(bid):
    require_roles("HouseManager")
    booking = _get_booking_or_404(bid)
    if booking["status"] != "ACTIVE":
        raise E.invalid_state("Only an ACTIVE booking can be evicted")
    notice = S.open_notice(bid)
    agreement = S.live_agreement(bid)
    if (not notice or not agreement or
            notice["consecutive_under_floor_weeks"] < agreement["stop_clause_consecutive_weeks"]):
        raise E.stop_clause_not_met()
    S.execute_eviction(booking, notice)
    return ok_object(booking)


# ------------------------------------------------------- nested booking lists

@bp.get("/theatres/bookings/<bid>/stop-notices")
def list_booking_notices(bid):
    require_roles(*HM_REP)
    _get_booking_or_404(bid)
    items = [n for n in STORE.stop_notices.values() if n["booking_id"] == bid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/bookings/<bid>/weekly-gross-reports")
def list_booking_reports(bid):
    require_roles(*HM_REP)
    _get_booking_or_404(bid)
    items = [r for r in STORE.weekly_reports.values() if r["booking_id"] == bid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/bookings/<bid>/ticket-orders")
def list_booking_orders(bid):
    require_roles(*ANY)
    _get_booking_or_404(bid)
    items = [o for o in STORE.ticket_orders.values() if o["booking_id"] == bid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/bookings/<bid>/crew-assignments")
def list_booking_crew(bid):
    require_roles(*HM_REP)
    _get_booking_or_404(bid)
    items = [c for c in STORE.crew_assignments.values() if c["booking_id"] == bid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.get("/theatres/bookings/<bid>/license-agreements")
def list_booking_agreements(bid):
    require_roles(*HM_REP)
    _get_booking_or_404(bid)
    items = [a for a in STORE.license_agreements.values() if a["booking_id"] == bid]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)
