"""Settlements: create, read, list, finalize."""
from flask import Blueprint, request

import errors as E
import services as S
from db import STORE
from middleware import require_roles
from response import (new_common, ok_object, ok_array, paginate, require_field,
                      require_int, touch, get_json_body)

bp = Blueprint("settlements", __name__)

HM_REP = ("HouseManager", "CompanyRep")


def _get_settlement_or_404(sid):
    s = STORE.settlements.get(sid)
    if not s:
        raise E.not_found("Settlement not found")
    return s


@bp.post("/theatres/weekly-gross-reports/<rid>/settlements")
def create_settlement(rid):
    require_roles("HouseManager")
    report = STORE.weekly_reports.get(rid)
    if not report:
        raise E.not_found("Weekly gross report not found")
    for s in STORE.settlements.values():
        if s["report_id"] == rid:
            raise E.already_terminal("A settlement already exists for this report")
    if report["status"] != "VERIFIED":
        raise E.invalid_state("Settlement requires a VERIFIED weekly gross report")
    body = get_json_body()
    house_expenses = require_int(require_field(body, "house_expenses_cents"),
                                 "house_expenses_cents")
    booking = STORE.bookings.get(report["booking_id"])
    agreement = S.live_agreement(report["booking_id"])
    if not agreement:
        raise E.invalid_state("A license agreement is required for settlement")
    if house_expenses < 0:
        raise E.fiscal_guard("house_expenses_cents must be >= 0")
    amounts = S.compute_settlement_amounts(report, booking, agreement, house_expenses)
    rec = new_common()
    rec.update({"report_id": rid, "booking_id": report["booking_id"],
                "house_expenses_cents": house_expenses, "status": "DRAFT"})
    rec.update(amounts)
    STORE.settlements[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/settlements/<sid>")
def get_settlement(sid):
    require_roles(*HM_REP)
    return ok_object(_get_settlement_or_404(sid))


@bp.get("/theatres/settlements")
def list_settlements():
    require_roles(*HM_REP)
    items = list(STORE.settlements.values())
    booking_id = request.args.get("booking_id")
    if booking_id:
        items = [s for s in items if s["booking_id"] == booking_id]
    page, limit, offset, total = paginate(items, request.args)
    return ok_array(page, limit, offset, total)


@bp.post("/theatres/settlements/<sid>/finalize")
def finalize_settlement(sid):
    require_roles("HouseManager")
    settlement = _get_settlement_or_404(sid)
    if settlement["status"] == "FINALIZED":
        raise E.already_terminal("Settlement is already FINALIZED")
    if settlement["status"] != "DRAFT":
        raise E.invalid_state("Only a DRAFT settlement can be finalized")
    report = STORE.weekly_reports.get(settlement["report_id"])
    if not report or report["status"] != "VERIFIED":
        raise E.invalid_state("Finalization requires a VERIFIED weekly gross report")
    agreement = S.signed_agreement(settlement["booking_id"])
    if not agreement:
        raise E.invalid_state("Finalization requires a SIGNED license agreement")
    booking = STORE.bookings.get(settlement["booking_id"])
    total_points = S.royalty_point_total(booking["production_id"])
    if not (1 <= total_points <= 100):
        raise E.royalty_points_oob("Production royalty point total is outside [1, 100]")
    settlement["status"] = "FINALIZED"
    touch(settlement)
    return ok_object(settlement)
