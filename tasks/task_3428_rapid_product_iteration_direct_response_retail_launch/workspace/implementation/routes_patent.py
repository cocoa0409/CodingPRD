"""Patent cases: filing (with provisional reserve), segregation-guarded
settlement, and judgments. Patent endpoints are exempt from the posture gate."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import ser_case
from services import get_or_404, recompute_category, req_fk
from state import DB, base_fields, bump
from util import body, ok_object, q0int, req_enum, req_int, req_string

bp = Blueprint("patent", __name__)

LEGAL = ("LegalCounsel",)


@bp.post("/patent-cases")
def create_case():
    uid, _ = require_roles(LEGAL)
    data = body()
    cat = req_fk(data, "category_id", DB.categories, "ERR_CATEGORY_NOT_FOUND")
    case_number = req_string(data, "case_number")
    claim_cents = req_int(data, "claim_cents", min_v=1)
    severity = req_enum(data, "severity", ("LOW", "MED", "HIGH"))
    if any(c["case_number"] == case_number for c in DB.cases.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "case_number must be globally unique")
    c = base_fields()
    c.update({
        "category_id": cat["id"],
        "case_number": case_number,
        "claim_cents": claim_cents,
        "severity": severity,
        "filed_by_user_id": uid,
        "status": "FILED",
        # provisional reserve booked immediately: claim * prior-adverse probability
        "provisional_reserve_cents": q0int(
            Decimal(claim_cents) * Decimal(CONSTANTS["PRIOR_ADVERSE_PROB"])),
        "final_amount_cents": None,
    })
    DB.cases[c["id"]] = c
    recompute_category(cat)  # reserve + exposure + OPEN -> GUARDED contagion
    return ok_object(ser_case(c), 201)


@bp.post("/patent-cases/<cid>/settle")
def settle_case(cid):
    uid, _ = require_roles(LEGAL)
    c = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if c["status"] not in ("FILED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a FILED or ACTIVE case can be settled")
    if uid == c["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the settling counsel must differ from the filing counsel")
    settlement_cents = req_int(body(), "settlement_cents", min_v=0)
    c["status"] = "SETTLED"
    c["final_amount_cents"] = settlement_cents
    bump(c)
    recompute_category(get_or_404(DB.categories, c["category_id"], "ERR_CATEGORY_NOT_FOUND"))
    return ok_object(ser_case(c))


@bp.post("/patent-cases/<cid>/record-judgment")
def record_judgment(cid):
    require_roles(LEGAL)
    c = get_or_404(DB.cases, cid, "ERR_CASE_NOT_FOUND")
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "a judgment can only be recorded on an ACTIVE case")
    data = body()
    outcome = req_enum(data, "outcome", ("ADVERSE", "FAVORABLE"))
    if outcome == "ADVERSE":
        award = data.get("award_cents")
        if isinstance(award, bool) or not isinstance(award, int) or award <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "an ADVERSE judgment requires award_cents > 0")
        c["status"] = "JUDGED_ADVERSE"
        c["final_amount_cents"] = award
    else:
        c["status"] = "JUDGED_FAVORABLE"
        c["final_amount_cents"] = 0
    bump(c)
    recompute_category(get_or_404(DB.categories, c["category_id"], "ERR_CATEGORY_NOT_FOUND"))
    return ok_object(ser_case(c))
