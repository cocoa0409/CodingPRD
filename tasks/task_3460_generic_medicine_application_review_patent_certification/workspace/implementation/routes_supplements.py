"""Post-approval change supplements (PRD 3.9): parallel review/effectivity."""
from flask import Blueprint

from auth import ALL_ROLES, auth, own_application, require_role
from clock import today
from domain import PATHWAY_MAP
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import supplement
from state import STORE, create_entity, get, touch
from validate import body, opt_str, req_enum

bp = Blueprint("supplements", __name__)

CHANGE_TYPES = ("MANUFACTURING_SITE", "FORMULATION", "LABELING", "PACKAGING",
                "EDITORIAL")
PATHWAYS = ("PRIOR_APPROVAL", "CBE_30", "CBE_0", "ANNUAL_REPORT")


@bp.post("/generic-drug-review/applications/<app_id>/supplements")
def create_supplement(app_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    app = get("applications", app_id)
    if app is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    own_application(uid, app)
    b = body()
    change_type = req_enum(b, "change_type", CHANGE_TYPES)
    pathway = req_enum(b, "pathway", PATHWAYS)
    description = opt_str(b, "description", None)
    if app["status"] != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED",
             "Supplements require an APPROVED application")
    if pathway not in PATHWAY_MAP[change_type]:
        fail("ERR_INVALID_PATHWAY_FOR_CHANGE",
             "Pathway %s is not permitted for change_type %s"
             % (pathway, change_type))
    t = today().isoformat()
    # Creation posture per pathway (review_status x effectivity).
    if pathway == "ANNUAL_REPORT":
        review_status, effectivity, effective_date = "LOGGED", "EFFECTIVE", t
    elif pathway == "CBE_0":
        review_status, effectivity, effective_date = "SUBMITTED", "EFFECTIVE", t
    else:  # PRIOR_APPROVAL, CBE_30
        review_status, effectivity, effective_date = "SUBMITTED", "NOT_EFFECTIVE", None
    ent = create_entity("supplements", {
        "application_id": app_id,
        "change_type": change_type,
        "pathway": pathway,
        "description": description,
        "review_status": review_status,
        "effectivity": effectivity,
        "submitted_date": t,
        "effective_date": effective_date,
        "decision_date": None,
    })
    return success_object(supplement(ent), 201)


@bp.get("/generic-drug-review/applications/<app_id>/supplements")
def list_supplements(app_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("applications", app_id) is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    items = [s for s in STORE["supplements"].values()
             if s["application_id"] == app_id]
    return success_list([supplement(s) for s in sort_default(items)])


@bp.post("/generic-drug-review/supplements/<supp_id>/review-decision")
def supplement_review_decision(supp_id):
    _uid, role = auth()
    require_role(role, ["RegulatoryReviewer"])
    ent = get("supplements", supp_id)
    if ent is None:
        fail("ERR_SUPPLEMENT_NOT_FOUND", "Supplement id does not exist")
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    if ent["pathway"] == "ANNUAL_REPORT":
        fail("ERR_SUPPLEMENT_NOT_REVIEWABLE",
             "ANNUAL_REPORT supplements are LOGGED and never reviewable")
    if ent["review_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "A review decision requires review_status SUBMITTED")
    t = today().isoformat()
    ent["decision_date"] = t
    if decision == "APPROVE":
        ent["review_status"] = "APPROVED"
        if ent["effectivity"] == "NOT_EFFECTIVE" and ent["pathway"] == "PRIOR_APPROVAL":
            ent["effectivity"] = "EFFECTIVE"
            ent["effective_date"] = t
        # CBE_30 timing is unchanged by approval.
    else:
        ent["review_status"] = "REJECTED"
        if ent["effectivity"] == "EFFECTIVE":
            ent["effectivity"] = "REVOKED"
    touch(ent)
    return success_object(supplement(ent))


@bp.post("/generic-drug-review/supplements/<supp_id>/withdraw")
def withdraw_supplement(supp_id):
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    ent = get("supplements", supp_id)
    if ent is None:
        fail("ERR_SUPPLEMENT_NOT_FOUND", "Supplement id does not exist")
    app = get("applications", ent["application_id"])
    own_application(uid, app)
    if ent["review_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "Only a SUBMITTED supplement can be withdrawn")
    ent["review_status"] = "WITHDRAWN"
    if ent["effectivity"] == "EFFECTIVE":
        ent["effectivity"] = "REVOKED"
    touch(ent)
    return success_object(supplement(ent))
