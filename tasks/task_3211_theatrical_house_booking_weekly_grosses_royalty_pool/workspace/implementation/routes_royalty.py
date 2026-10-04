"""Royalty participants and discount codes."""
from flask import Blueprint

import errors as E
import services as S
from db import STORE
from middleware import require_roles, require_company_owns
from response import (new_common, ok_object, require_field, require_int,
                      touch, get_json_body)

bp = Blueprint("royalty", __name__)


def _get_production_or_404(pid):
    p = STORE.productions.get(pid)
    if not p:
        raise E.not_found("Production not found")
    return p


# ------------------------------------------------------------- participants

@bp.post("/theatres/productions/<pid>/royalty-participants")
def create_participant(pid):
    user_id, _ = require_roles("CompanyRep")
    prod = _get_production_or_404(pid)
    require_company_owns(STORE, user_id, prod["company_id"])
    body = get_json_body()
    name = require_field(body, "participant_name")
    points = require_int(require_field(body, "royalty_points"), "royalty_points")
    pool_eligible = require_field(body, "pool_eligible")
    fixed = body.get("fixed_royalty_cents", 0)
    fixed = require_int(fixed, "fixed_royalty_cents")
    if points < 1:
        raise E.royalty_points_oob("A participant must have at least 1 royalty point")
    if S.royalty_point_total(pid) + points > 100:
        raise E.royalty_points_oob("Production royalty point total exceeds 100")
    rec = new_common()
    rec.update({"production_id": pid, "participant_name": name,
                "royalty_points": points, "pool_eligible": bool(pool_eligible),
                "fixed_royalty_cents": fixed})
    STORE.royalty_participants[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/royalty-participants/<pid>")
def get_participant(pid):
    require_roles("HouseManager", "CompanyRep")
    rec = STORE.royalty_participants.get(pid)
    if not rec:
        raise E.not_found("Royalty participant not found")
    return ok_object(rec)


# ------------------------------------------------------------- discount codes

@bp.post("/theatres/productions/<pid>/discount-codes")
def create_discount_code(pid):
    user_id, _ = require_roles("CompanyRep")
    prod = _get_production_or_404(pid)
    require_company_owns(STORE, user_id, prod["company_id"])
    body = get_json_body()
    code = require_field(body, "code")
    percent = require_field(body, "percent_off")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        raise E.invalid_request("percent_off must be a number")
    if not (0 < percent < 100):
        raise E.discount_code_invalid("percent_off must be strictly between 0 and 100")
    for c in STORE.discount_codes.values():
        if c["production_id"] == pid and c["code"] == code:
            raise E.invalid_request("Discount code must be unique within the production")
    rec = new_common()
    rec.update({"production_id": pid, "code": code, "percent_off": percent, "active": True})
    STORE.discount_codes[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/theatres/discount-codes/<cid>")
def get_discount_code(cid):
    require_roles("HouseManager", "CompanyRep", "BoxOfficeAgent")
    rec = STORE.discount_codes.get(cid)
    if not rec:
        raise E.not_found("Discount code not found")
    return ok_object(rec)


@bp.post("/theatres/discount-codes/<cid>/deactivate")
def deactivate_discount_code(cid):
    user_id, _ = require_roles("CompanyRep")
    rec = STORE.discount_codes.get(cid)
    if not rec:
        raise E.not_found("Discount code not found")
    prod = STORE.productions.get(rec["production_id"])
    require_company_owns(STORE, user_id, prod["company_id"])
    if rec["active"]:
        rec["active"] = False
        touch(rec)
    return ok_object(rec)
