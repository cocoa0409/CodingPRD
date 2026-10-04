"""Legal clearances: parallel background/suitability dimensions under
segregation of duties; overall_status is derived (PRD 3.6)."""
from flask import Blueprint, request

from authz import auth, require_roles
from cascade import denial_cascade, legal_overall
from db import ROLES, STORE, touch
from errors import err, ok_object, paginate
from routes_applications import get_application_or_404
from validate import as_enum, body

bp = Blueprint("legal", __name__)


def get_legal_or_404(lid):
    lc = STORE["legal_clearances"].get(lid)
    if lc is None:
        err("ERR_LEGAL_CLEARANCE_NOT_FOUND", 404, "Legal clearance not found")
    return lc


def legal_view(lc):
    view = dict(lc)
    view["overall_status"] = legal_overall(lc)
    return view


@bp.get("/volunteer-portal/applications/<aid>/legal-clearances")
def list_legal_clearances(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_application_or_404(aid)
    records = sorted(
        (lc for lc in STORE["legal_clearances"].values()
         if lc["application_id"] == aid),
        key=lambda r: r["created_at"])
    limit_offset_records = [legal_view(lc) for lc in records]
    return paginate(limit_offset_records)


@bp.post("/volunteer-portal/legal-clearances/<lid>/adjudicate-background")
def adjudicate_background(lid):
    user_id, role = auth()
    require_roles(role, ("LegalReviewer",))
    lc = get_legal_or_404(lid)
    # State guards (priority 6): dimension PENDING, lifecycle ACTIVE.
    if lc["lifecycle"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Legal clearance lifecycle is VOID")
    if lc["background_check_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "background check already adjudicated (%s)" % lc["background_check_status"])
    data = body()
    outcome = as_enum(data, "outcome", ("CLEAR", "ADVERSE"))
    lc["background_check_status"] = outcome
    lc["background_adjudicated_by"] = user_id
    touch(lc)
    if outcome == "ADVERSE":
        # Denial cascade; per PRD 3.6 the denial also voids this clearance's
        # own lifecycle, freezing both dimensions where they stand.
        denial_cascade(lc["application_id"])
    return ok_object(legal_view(lc))


@bp.post("/volunteer-portal/legal-clearances/<lid>/determine-suitability")
def determine_suitability(lid):
    user_id, role = auth()
    require_roles(role, ("LegalReviewer",))
    lc = get_legal_or_404(lid)
    # State guards (priority 6): suitability PENDING, lifecycle ACTIVE, and the
    # background must already be adjudicated.
    if lc["lifecycle"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Legal clearance lifecycle is VOID")
    if lc["suitability_status"] != "PENDING":
        err("ERR_INVALID_STATE", 409,
            "suitability already determined (%s)" % lc["suitability_status"])
    if lc["background_check_status"] == "PENDING":
        err("ERR_INVALID_STATE", 409,
            "suitability requires an adjudicated background check first")
    # Compliance gate (priority 7): segregation of duties.
    if user_id == lc["background_adjudicated_by"]:
        err("ERR_SUITABILITY_SELF_APPROVAL", 422,
            "Suitability must be determined by a different reviewer than the "
            "background adjudicator")
    data = body()
    outcome = as_enum(data, "outcome", ("FAVORABLE", "UNFAVORABLE"))
    lc["suitability_status"] = outcome
    lc["suitability_decided_by"] = user_id
    touch(lc)
    if outcome == "UNFAVORABLE":
        denial_cascade(lc["application_id"])
    return ok_object(legal_view(lc))
