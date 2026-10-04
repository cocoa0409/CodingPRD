"""PromoProgram endpoints (PRD SS3.7): draft, authorize, settle."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import store
from domain import CENT, PROMO_BRAND_SHARE, PROMO_FLOOR_PCT, touch
from errors import fail
from serializers import ser_promo
from store import db
from util import (auth, body, list_response, new_id, ok, req_array, req_date,
                  req_enum, req_int, req_str, sort_std)

bp = Blueprint("promos", __name__)

PROMO_READERS = ("BrandAdmin", "DistributorRep", "RetailManager")


def _get_promo(pid):
    p = db["promos"].get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", 404, "promo program not found")
    return p


def _markdown(product, program):
    return product["base_price_cents"] - program["promo_price_cents"]


def _round_cents(value):
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


@bp.post("/api/promo-programs")
def create_promo():
    _, uid = auth("DistributorRep")
    b = body()
    account_id = req_str(b, "account_id")
    product_id = req_str(b, "product_id")
    promo_price_cents = req_int(b, "promo_price_cents", min_value=1)
    start_date = req_date(b, "start_date")
    end_date = req_date(b, "end_date")
    if not start_date <= end_date:
        fail("ERR_VALIDATION", 400, "start_date must be on or before end_date")
    budget_cents = req_int(b, "budget_cents", min_value=1)
    estimated_units = req_int(b, "estimated_units", min_value=1)
    account = db["accounts"].get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND", 404, "account not found")
    product = db["products"].get(product_id)
    if product is None:
        fail("ERR_NOT_FOUND", 404, "product not found")
    # standing activity gates (tier 10): distributor ACTIVE, account APPROVED
    dist = db["distributors"].get(uid)
    if dist is None:
        fail("ERR_NOT_FOUND", 404, "distributor not found")
    if dist["status"] != "ACTIVE":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", 409, "distributor is not ACTIVE")
    if account["approval_status"] != "APPROVED":
        fail("ERR_ACCOUNT_NOT_APPROVED", 409, "account is not APPROVED")
    # per-unit brand allowance: markdown * 60% share, round half up
    markdown = product["base_price_cents"] - promo_price_cents
    unit_allowance = _round_cents(Decimal(markdown) * PROMO_BRAND_SHARE)
    now = store.now()
    p = {
        "id": new_id(), "_seq": store.next_seq(), "account_id": account_id,
        "product_id": product_id, "promo_price_cents": promo_price_cents,
        "start_date": start_date, "end_date": end_date,
        "budget_cents": budget_cents, "estimated_units": estimated_units,
        "status": "DRAFT", "unit_allowance_cents": unit_allowance,
        "reserved_cents": 0, "spent_cents": 0, "released_cents": 0,
        "created_at": now, "updated_at": now, "version": 1,
    }
    db["promos"][p["id"]] = p
    return ok(ser_promo(p), 201)


@bp.get("/api/promo-programs")
def list_promos():
    auth(*PROMO_READERS)
    items = sort_std(db["promos"].values())
    account_id = request.args.get("account_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if product_id is not None:
        items = [p for p in items if p["product_id"] == product_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response([ser_promo(p) for p in items])


@bp.get("/api/promo-programs/<pid>")
def get_promo(pid):
    auth(*PROMO_READERS)
    return ok(ser_promo(_get_promo(pid)))


@bp.post("/api/promo-programs/<pid>/authorize")
def authorize_promo(pid):
    auth("BrandAdmin")
    b = body()
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})
    p = _get_promo(pid)
    if p["status"] in ("REJECTED", "SETTLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "promo program is " + p["status"])
    if p["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "promo program is " + p["status"])
    if decision == "REJECT":
        p["status"] = "REJECTED"
        touch(p)
        return ok(ser_promo(p))
    # temporal (tier 9): closed-interval overlap against AUTHORIZED/SUSPENDED
    # programs for the same account + product; starting the day after the
    # existing end is allowed, starting on the final day is not
    for q in db["promos"].values():
        if q["id"] == p["id"]:
            continue
        if (q["account_id"] == p["account_id"] and q["product_id"] == p["product_id"]
                and q["status"] in ("AUTHORIZED", "SUSPENDED")):
            if p["start_date"] <= q["end_date"] and q["start_date"] <= p["end_date"]:
                fail("ERR_PROMO_WINDOW_OVERLAP", 409,
                     "promo window overlaps an AUTHORIZED or SUSPENDED program")
    # fiscal (tier 11): regulatory floor — 85% of base price, round half up
    product = db["products"][p["product_id"]]
    floor = _round_cents(Decimal(product["base_price_cents"]) * PROMO_FLOOR_PCT)
    if p["promo_price_cents"] < floor:
        fail("ERR_PROMO_BELOW_FLOOR", 422, "promo price is below the regulatory floor")
    # fiscal (tier 11): provisional reserve must fit the budget
    reserve = p["estimated_units"] * p["unit_allowance_cents"]
    if reserve > p["budget_cents"]:
        fail("ERR_PROMO_BUDGET_EXCEEDED", 422, "provisional reserve exceeds budget_cents")
    p["reserved_cents"] = reserve  # the reserve locks at authorization
    p["status"] = "AUTHORIZED"
    touch(p)
    return ok(ser_promo(p))


@bp.post("/api/promo-programs/<pid>/settle")
def settle_promo(pid):
    auth("BrandAdmin")
    b = body()
    lines_in = req_array(b, "redemption_lines")
    parsed = []
    for item in lines_in:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", 400, "each redemption line must be an object")
        req_str(item, "period")
        units = req_int(item, "units", min_value=1)
        parsed.append(units)
    p = _get_promo(pid)
    if p["status"] in ("REJECTED", "SETTLED"):
        fail("ERR_ALREADY_TERMINAL", 409, "promo program is " + p["status"])
    if p["status"] not in ("AUTHORIZED", "SUSPENDED"):
        fail("ERR_INVALID_STATE", 409, "promo program is " + p["status"])
    product = db["products"][p["product_id"]]
    markdown = _markdown(product, p)
    # PINNED ROUNDING ORDER: round each redemption line to integer cents
    # FIRST, then sum; summing units across lines and rounding once is
    # explicitly rejected (PRD SS2.7 / SS3.7)
    final_amount = 0
    for units in parsed:
        final_amount += _round_cents(Decimal(units * markdown) * PROMO_BRAND_SHARE)
    if final_amount > p["budget_cents"]:
        fail("ERR_PROMO_BUDGET_EXCEEDED", 422, "final settlement exceeds budget_cents")
    p["spent_cents"] = final_amount
    p["released_cents"] = p["reserved_cents"] - final_amount
    p["status"] = "SETTLED"
    touch(p)
    return ok(ser_promo(p))
