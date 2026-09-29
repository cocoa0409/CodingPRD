"""Market regime registry (PRD 2.10)."""
from flask import Blueprint, request

from auth import require_roles
from envelope import created, listing
from errors import fail
from serializers import market_json
from store import create_row, db
from validate import (body, distinct_codes, present, req_array, req_int,
                      req_number, req_string)

bp = Blueprint("markets", __name__)

ALL_ROLES = ("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
             "AccreditedLab", "CustomsOfficer", "Auditor")


def _opt_bool(payload, field, default):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


@bp.post("/labeling/market-requirements")
def register_market():
    require_roles("ComplianceAdmin")
    payload = body()
    code = req_string(payload, "market_code", min_len=2, max_len=8, pattern=r"^[A-Z_]{2,8}$")
    languages = distinct_codes(req_array(payload, "required_languages"),
                               "required_languages", r"^[a-z]{2}$")
    fields = {
        "market_code": code,
        "required_languages": languages,
        "fiber_tolerance_pp": req_number(payload, "fiber_tolerance_pp", 1, minimum=0.0, maximum=5.0),
        "absolute_claim_tolerance_pp": req_number(payload, "absolute_claim_tolerance_pp", 1,
                                                  minimum=0.0, maximum=1.0),
        "min_durability_cycles": req_int(payload, "min_durability_cycles", minimum=0),
        "marking_duty_rate": req_number(payload, "marking_duty_rate", 3, minimum=0.0, maximum=0.5),
        "requires_identity_disclosure": _opt_bool(payload, "requires_identity_disclosure", True),
        "requires_origin_statement": _opt_bool(payload, "requires_origin_statement", True),
    }
    for row in db.market_requirements.values():
        if row["market_code"] == code:
            fail("ERR_DUPLICATE_MARKET_CODE", "Market code %s is already registered." % code)
    row = create_row(db.market_requirements, fields, versioned=False)
    return created(market_json(row))


@bp.get("/labeling/market-requirements")
def list_markets():
    require_roles(*ALL_ROLES)
    rows = list(db.market_requirements.values())
    wanted = request.args.get("market_code")
    if wanted is not None:
        rows = [r for r in rows if r["market_code"] == wanted]
    rows.sort(key=lambda r: r["market_code"])
    return listing(rows, market_json)
