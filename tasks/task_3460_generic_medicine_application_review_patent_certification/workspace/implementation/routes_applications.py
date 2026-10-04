"""Generic applications: create/list/get and the filing gate (PRD 3.3)."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, own_application, require_role
from clock import today
from domain import (
    PRIORITY_MONTHS,
    awards_for_rp,
    certification_completeness_check,
    certified_p4_certs,
    check_carve_out,
    has_accepted_be,
    nce_check,
)
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import application
from state import STORE, create_entity, get, touch
from validate import body, opt_enum, opt_str_list, req_enum, req_str

bp = Blueprint("applications", __name__)


@bp.post("/generic-drug-review/applications")
def create_application():
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    b = body()
    # Priority 3 ownership, then priority 4 body-reference existence in input
    # declaration order (reference_product_id, then applicant_id).
    aid = b.get("applicant_id")
    if isinstance(aid, str) and aid != uid:
        fail("ERR_NOT_RESOURCE_OWNER",
             "applicant_id must equal the acting ApplicantSponsor's X-User-ID")
    rpid = b.get("reference_product_id")
    if isinstance(rpid, str) and get("reference_products", rpid) is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    if isinstance(aid, str) and get("applicants", aid) is None:
        fail("ERR_APPLICANT_NOT_FOUND", "Applicant company id does not exist")
    # Priority 5 shape.
    rpid = req_str(b, "reference_product_id")
    aid = req_str(b, "applicant_id")
    priority = opt_enum(b, "review_priority", ("STANDARD", "PRIORITY"), "STANDARD")
    mode = req_enum(b, "labeling_mode", ("FULL", "CARVE_OUT"))
    carved = opt_str_list(b, "carved_indication_codes", [])
    # Priority 14: carve-out set equality against currently ACTIVE protections,
    # checked at creation. Validated before persisting anything.
    candidate = {
        "reference_product_id": rpid,
        "labeling_mode": mode,
        "carved_indication_codes": carved,
    }
    check_carve_out(candidate)
    ent = create_entity("applications", dict(candidate, **{
        "applicant_id": aid,
        "review_priority": priority,
        "status": "DRAFT",
        "received_date": None,
        "current_cycle_number": 0,
        "tentative_approval_date": None,
        "approval_date": None,
        "first_marketing_date": None,
    }))
    return success_object(application(ent), 201)


@bp.get("/generic-drug-review/applications")
def list_applications():
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    items = list(STORE["applications"].values())
    f_applicant = request.args.get("applicant_id")
    f_rp = request.args.get("reference_product_id")
    f_status = request.args.get("status")
    if f_applicant is not None:
        items = [a for a in items if a["applicant_id"] == f_applicant]
    if f_rp is not None:
        items = [a for a in items if a["reference_product_id"] == f_rp]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return success_list([application(a) for a in sort_default(items)])


@bp.get("/generic-drug-review/applications/<app_id>")
def get_application(app_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("applications", app_id)
    if ent is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    return success_object(application(ent))


@bp.post("/generic-drug-review/applications/<app_id>/submit")
def submit_application(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    # The filing gate in PRD 2.7 pipeline order.
    if app["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT application can be filed")
    if not has_accepted_be(app_id):
        fail("ERR_NO_ADEQUATE_BE_STUDY",
             "At least one ACCEPTED bioequivalence study is required")
    rp = get("reference_products", app["reference_product_id"])
    nce_check(rp, app)
    check_carve_out(app)
    certification_completeness_check(app["reference_product_id"], app_id)
    # Side effects of DRAFT -> RECEIVED.
    t = today()
    app["status"] = "RECEIVED"
    app["received_date"] = t.isoformat()
    app["current_cycle_number"] = 1
    create_entity("cycles", {
        "application_id": app_id,
        "cycle_number": 1,
        "status": "OPEN",
        "opened_date": t.isoformat(),
        "base_review_months": PRIORITY_MONTHS[app["review_priority"]],
        "major_amendment_extensions_count": 0,
        "deficiency_issued_date": None,
        "deficiency_response_due_date": None,
        "deficiency_response_received_date": None,
        "deficiency_summary": None,
        "closed_reason": None,
    })
    # First-filer determination: first RECEIVED application carrying a P4
    # challenge for this reference product gets the ELIGIBLE award; a prior
    # award of any status (even FORFEITED) blocks successors.
    if certified_p4_certs(app_id) and not awards_for_rp(app["reference_product_id"]):
        create_entity("awards", {
            "application_id": app_id,
            "reference_product_id": app["reference_product_id"],
            "status": "ELIGIBLE",
            "awarded_date": None,
            "approval_date": None,
            "marketing_deadline": None,
            "first_marketing_date": None,
            "exclusivity_end_date": None,
            "forfeiture_reason": None,
        })
    touch(app)
    return success_object(application(app))
