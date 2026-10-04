"""License agreements: create (OCC + supersede), read, sign (OCC)."""
from flask import Blueprint

import errors as E
import services as S
from db import STORE
from middleware import require_roles, require_company_owns
from response import (new_common, ok_object, require_field, require_int,
                      touch, get_json_body)

bp = Blueprint("licenses", __name__)


def _get_booking_or_404(bid):
    b = STORE.bookings.get(bid)
    if not b:
        raise E.not_found("Booking not found")
    return b


def _get_agreement_or_404(aid):
    a = STORE.license_agreements.get(aid)
    if not a:
        raise E.not_found("License agreement not found")
    return a


def _check_occ(body, booking):
    expected = require_field(body, "expected_booking_version")
    require_int(expected, "expected_booking_version")
    if expected != booking["version"]:
        raise E.stale_version()


@bp.post("/theatres/bookings/<bid>/license-agreements")
def create_license(bid):
    require_roles("HouseManager")
    booking = _get_booking_or_404(bid)
    if booking["status"] not in ("APPROVED", "ACTIVE"):
        raise E.invalid_state("A license agreement requires an APPROVED or ACTIVE booking")
    body = get_json_body()
    _check_occ(body, booking)
    floor = require_int(require_field(body, "stop_clause_weekly_floor_cents"),
                        "stop_clause_weekly_floor_cents")
    weeks = require_int(require_field(body, "stop_clause_consecutive_weeks"),
                        "stop_clause_consecutive_weeks")
    rent = body.get("weekly_rent_cents")
    if rent is not None:
        rent = require_int(rent, "weekly_rent_cents")
    if weeks < 1:
        raise E.invalid_request("stop_clause_consecutive_weeks must be >= 1")
    if floor < 0 or (rent is not None and rent < 0):
        raise E.fiscal_guard("weekly_rent_cents and stop_clause_weekly_floor_cents must be >= 0")
    if rent is None:
        theatre = STORE.theatres.get(booking["theatre_id"])
        rent = theatre["base_weekly_rent_cents"]
    # Supersede any existing live agreement (cascade)
    for a in STORE.license_agreements.values():
        if a["booking_id"] == bid and a["status"] in ("DRAFT", "SIGNED"):
            a["status"] = "SUPERSEDED"
            touch(a)
    rec = new_common()
    rec.update({"booking_id": bid, "weekly_rent_cents": rent,
                "stop_clause_weekly_floor_cents": floor,
                "stop_clause_consecutive_weeks": weeks, "status": "DRAFT"})
    STORE.license_agreements[rec["id"]] = rec
    touch(booking)  # OCC touch: booking.version +1
    return ok_object(rec, 201)


@bp.get("/theatres/license-agreements/<aid>")
def get_license(aid):
    require_roles("HouseManager", "CompanyRep")
    return ok_object(_get_agreement_or_404(aid))


@bp.post("/theatres/license-agreements/<aid>/sign")
def sign_license(aid):
    user_id, _ = require_roles("CompanyRep")
    agreement = _get_agreement_or_404(aid)
    booking = _get_booking_or_404(agreement["booking_id"])
    if agreement["status"] != "DRAFT":
        raise E.invalid_state("Only a DRAFT license agreement can be signed")
    if booking["status"] not in ("APPROVED", "ACTIVE"):
        raise E.invalid_state("Signing requires an APPROVED or ACTIVE booking")
    require_company_owns(STORE, user_id, S.company_of_booking(booking))
    body = get_json_body()
    _check_occ(body, booking)
    agreement["status"] = "SIGNED"
    touch(agreement)
    touch(booking)  # OCC touch: booking.version +1
    return ok_object(agreement)
