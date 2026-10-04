"""Divestitures: propose, sign-spa (creates the TSA), close, separate."""

from flask import Blueprint, request

import clock
import storage
from calculations import new_record, bump
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import divestiture_out
from validation import body_json, f_str, f_int, f_dt

bp = Blueprint("divestitures", __name__, url_prefix="/portfolio")

OPEN_DIVESTITURE_STATES = ("PROPOSED", "SPA_SIGNED", "CLOSED")


def open_divestiture_for(brand_id):
    for d in storage.divestitures.values():
        if d["brand_id"] == brand_id and d["divestiture_status"] in OPEN_DIVESTITURE_STATES:
            return d
    return None


def tsa_for_divestiture(divestiture_id):
    for t in storage.tsas.values():
        if t["divestiture_id"] == divestiture_id:
            return t
    return None


@bp.post("/divestitures")
@synchronized
def create_divestiture():
    guard(["PortfolioManager"])
    body = body_json(required=True)
    brand_id = f_str(body, "brand_id")
    acquirer_name = f_str(body, "acquirer_name")
    headline_price = f_int(body, "headline_price_cents", 0)
    expected_close = f_dt(body, "expected_close_date")
    # step 6: body FK resolves
    brand = storage.brands.get(brand_id)
    if brand is None:
        fail("ERR_NOT_FOUND", f"brand {brand_id} not found")
    # step 7: brand must not be EXITED
    if brand["brand_status"] == "EXITED":
        fail("ERR_INVALID_STATE", "divestiture create requires brand not EXITED")
    # step 11: at most one open divestiture per brand
    if open_divestiture_for(brand_id) is not None:
        fail("ERR_DIVESTITURE_ALREADY_OPEN",
             "brand already has an open divestiture")
    # step 14: only non-core brands are divestable
    if brand["core_flag"]:
        fail("ERR_BRAND_CORE", "brand is core (core_flag true) and never divestable")
    rec = new_record()
    rec.update({
        "brand_id": brand_id,
        "acquirer_name": acquirer_name,
        "headline_price_cents": headline_price,
        "expected_close_date": expected_close,
        "divestiture_status": "PROPOSED",
    })
    storage.divestitures[rec["id"]] = rec
    # side effect: brand ACTIVE -> UNDER_REVIEW
    brand["brand_status"] = "UNDER_REVIEW"
    bump(brand)
    return success(divestiture_out(rec), status=201)


@bp.get("/divestitures")
@synchronized
def list_divestitures():
    guard(ALL_ROLES)
    records = list(storage.divestitures.values())
    for param in ("brand_id", "divestiture_status"):
        value = request.args.get(param)
        if value is not None:
            records = [d for d in records if d[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([divestiture_out(d) for d in page], response_type="array",
                   pagination=meta)


@bp.get("/divestitures/<did>")
@synchronized
def get_divestiture(did):
    guard(ALL_ROLES)
    d = storage.divestitures.get(did)
    if d is None:
        fail("ERR_NOT_FOUND", f"divestiture {did} not found")
    return success(divestiture_out(d))


@bp.post("/divestitures/<did>/sign-spa")
@synchronized
def sign_spa(did):
    guard(["PortfolioManager"])
    body = body_json(required=True)
    fee = f_int(body, "tsa_monthly_fee_cents", 0)
    tsa_start = f_dt(body, "tsa_start_date")
    tsa_end = f_dt(body, "tsa_end_date")
    d = storage.divestitures.get(did)
    if d is None:
        fail("ERR_NOT_FOUND", f"divestiture {did} not found")
    # step 7
    if d["divestiture_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "sign-spa requires divestiture PROPOSED")
    # step 14: window coherence; expected close inside the closed TSA window
    if not (tsa_start < tsa_end
            and tsa_start <= d["expected_close_date"] <= tsa_end):
        fail("ERR_CLOSE_DATE_OUTSIDE_TSA",
             "expected_close_date must lie within [tsa_start_date, tsa_end_date] "
             "and tsa_start_date must be strictly before tsa_end_date")
    d["divestiture_status"] = "SPA_SIGNED"
    bump(d)
    # creates exactly one TSA (DRAFT) bound to this divestiture
    tsa = new_record()
    tsa.update({
        "divestiture_id": d["id"],
        "monthly_fee_cents": fee,
        "start_date": tsa_start,
        "end_date": tsa_end,
        "tsa_status": "DRAFT",
        "terminated_at": None,
        "early_termination_penalty_cents": 0,
    })
    storage.tsas[tsa["id"]] = tsa
    # side effect: brand UNDER_REVIEW -> DIVESTING
    brand = storage.brands[d["brand_id"]]
    brand["brand_status"] = "DIVESTING"
    bump(brand)
    return success(divestiture_out(d))


@bp.post("/divestitures/<did>/close")
@synchronized
def close_divestiture(did):
    guard(["PortfolioManager"])
    d = storage.divestitures.get(did)
    if d is None:
        fail("ERR_NOT_FOUND", f"divestiture {did} not found")
    # step 7
    if d["divestiture_status"] != "SPA_SIGNED":
        fail("ERR_INVALID_STATE", "close requires divestiture SPA_SIGNED")
    # step 19: logical clock >= TSA start_date (boundary inclusive)
    tsa = tsa_for_divestiture(d["id"])
    if clock.now() < tsa["start_date"]:
        fail("ERR_TSA_NOT_STARTED",
             "logical clock is before the TSA start_date")
    d["divestiture_status"] = "CLOSED"
    bump(d)
    tsa["tsa_status"] = "ACTIVE"
    bump(tsa)
    brand = storage.brands[d["brand_id"]]
    brand["brand_status"] = "DIVESTED"
    bump(brand)
    return success(divestiture_out(d))


@bp.post("/divestitures/<did>/separate")
@synchronized
def separate_divestiture(did):
    guard(["PortfolioManager"])
    d = storage.divestitures.get(did)
    if d is None:
        fail("ERR_NOT_FOUND", f"divestiture {did} not found")
    # step 7: divestiture CLOSED and TSA TERMINATED
    if d["divestiture_status"] != "CLOSED":
        fail("ERR_INVALID_STATE", "separate requires divestiture CLOSED")
    tsa = tsa_for_divestiture(d["id"])
    if tsa["tsa_status"] != "TERMINATED":
        fail("ERR_TSA_STILL_ACTIVE", "separate requires TSA TERMINATED")
    d["divestiture_status"] = "SEPARATED"
    bump(d)
    brand = storage.brands[d["brand_id"]]
    brand["brand_status"] = "EXITED"
    bump(brand)
    return success(divestiture_out(d))
