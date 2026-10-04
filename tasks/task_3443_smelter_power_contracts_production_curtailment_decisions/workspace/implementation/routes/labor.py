"""Labor agreements: register and expire (PRD 3.8)."""
from flask import Blueprint

from auth import require_roles
from db import STORE, bump, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import labor_agreement_json
from util import as_bool, as_int, as_number, as_str, get_body, req

bp = Blueprint("labor", __name__, url_prefix="/smelter-ops")


@bp.post("/labor-agreements")
@require_roles("PlatformAdmin")
def create_labor_agreement():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    if STORE["smelters"].get(smelter_id) is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    union_name = as_str(req(body, "union_name"), "union_name")
    notice = as_int(req(body, "notice_period_days"), "notice_period_days")
    if notice < 0:
        raise_err("ERR_INVALID_REQUEST", "notice_period_days must be >= 0.")
    severance = as_number(
        req(body, "severance_weeks_per_year"), "severance_weeks_per_year"
    )
    if severance < 0:
        raise_err("ERR_INVALID_REQUEST", "severance_weeks_per_year must be >= 0.")
    community = body.get("community_impact_clause", False)
    if community is None:
        community = False
    community = as_bool(community, "community_impact_clause")
    for a in STORE["labor_agreements"].values():
        if a["smelter_id"] == smelter_id and a["status"] == "ACTIVE":
            raise_err(
                "ERR_LABOR_AGREEMENT_EXISTS",
                "An ACTIVE labor agreement already exists for the smelter.",
            )
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "union_name": union_name,
            "notice_period_days": notice,
            "severance_weeks_per_year": severance,
            "community_impact_clause": community,
            "status": "ACTIVE",
        }
    )
    STORE["labor_agreements"][rec["id"]] = rec
    return ok_object(labor_agreement_json(rec), 201)


@bp.post("/labor-agreements/<agreement_id>/expire")
@require_roles("PlatformAdmin")
def expire_labor_agreement(agreement_id):
    a = STORE["labor_agreements"].get(agreement_id)
    if a is None:
        raise_err("ERR_NOT_FOUND", "LaborAgreement not found.")
    if a["status"] != "ACTIVE":
        raise_err(
            "ERR_INVALID_LIFECYCLE_STATE",
            "Only an ACTIVE labor agreement can be expired.",
        )
    a["status"] = "EXPIRED"
    bump(a)
    return ok_object(labor_agreement_json(a))
