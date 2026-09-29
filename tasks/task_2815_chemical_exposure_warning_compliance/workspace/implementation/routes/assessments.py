"""Exposure assessment and independent peer review (PRD 3.6)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard, action_role
from routes.common import list_endpoint
from services import calc, cascade, posture

bp = Blueprint("assessments", __name__)

METHODS = ("LAB_TESTED", "MODELED")
ROUTES = ("ORAL", "DERMAL", "INHALATION")
READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel",
              "LabelingSpecialist", "RegistryAdmin")
TRIGGERS = ("SUBMIT", "PEER_REVIEW", "REJECT", "REOPEN", "FINALIZE")
ACTION_ROLES = {
    "SUBMIT": ("ComplianceAnalyst",),
    "REOPEN": ("ComplianceAnalyst",),
    "PEER_REVIEW": ("ToxicologyReviewer",),
    "REJECT": ("ToxicologyReviewer",),
    "FINALIZE": ("ToxicologyReviewer",),
}
LEGAL = {
    "SUBMIT": ("DRAFT",),
    "PEER_REVIEW": ("SUBMITTED",),
    "REJECT": ("SUBMITTED", "PEER_REVIEWED"),
    "REOPEN": ("REJECTED",),
    "FINALIZE": ("SUBMITTED", "PEER_REVIEWED"),
}
REJECTION_CEILING = 2


def contributing_links(product, chemical_id):
    """Links on any material in an active component's subtree for this chemical."""
    out = []
    seen = set()
    for component in calc.active_components(product["id"]):
        material = db.get("materials", component["material_id"])
        if material is None:
            continue
        for node in calc.subtree(material):
            link = calc.link_for(node["id"], chemical_id)
            if link is not None and link["id"] not in seen:
                seen.add(link["id"])
                out.append((node, link))
    return out


@bp.route("/products/<product_id>/exposure-assessments", methods=["POST"])
@guard("ComplianceAnalyst")
def create_assessment(who, product_id):
    body = validate.body_json()
    validate.v_str(body, "chemical_id", required=True)
    method = validate.v_enum(body, "method", METHODS, required=True)
    route = validate.v_enum(body, "route", ROUTES, required=True)
    uses = validate.v_num(body, "uses_per_day", required=True)
    validate.v_domain(body)
    product = validate.must_exist("products", product_id, "product")
    chemical = validate.fk("listed_chemicals", body, "chemical_id", required=True)
    if product["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_PARENT_STATE_FORBIDS_WRITE",
             "an assessment may not be opened on a discontinued product")
    validate.v_writable(body, ("chemical_id", "method", "route", "uses_per_day"))
    if chemical["status"] != "LISTED":
        fail("ERR_CHEMICAL_NOT_LISTED", "the chemical is not currently listed")
    row = db.insert("exposure_assessments", {
        "product_id": product["id"],
        "chemical_id": chemical["id"],
        "method": method,
        "route": route,
        "uses_per_day": uses,
        "daily_exposure_ug": None,
        "margin_ratio": None,
        "result": None,
        "contribution_count": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "finalized_at": None,
        "rejection_count": 0,
        "review_note": None,
    })
    calc.recompute_assessment_numbers(row)
    return response.created(db.serialize("exposure_assessments", row))


@bp.route("/exposure-assessments/<assessment_id>/transitions", methods=["POST"])
@guard("ComplianceAnalyst", "ToxicologyReviewer")
def transition_assessment(who, assessment_id):
    body = validate.body_json()
    action = validate.v_action(body, TRIGGERS)
    action_role(action, ACTION_ROLES, who.role)
    note = None
    if action == "REJECT":
        note = validate.v_str(body, "review_note", required=True, minlen=1)
    else:
        note = validate.v_str(body, "review_note")
    assessment = validate.must_exist("exposure_assessments", assessment_id, "assessment")
    if assessment["status"] not in LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, assessment["status"]))
    validate.v_writable(body, ("action", "review_note"))
    product = db.get("products", assessment["product_id"])
    chemical = db.get("listed_chemicals", assessment["chemical_id"])

    if action == "SUBMIT":
        if not calc.active_components(product["id"]):
            fail("ERR_NO_ACTIVE_COMPONENTS", "the product has no ACTIVE components")
        if assessment["method"] == "LAB_TESTED":
            for material, link in contributing_links(product, assessment["chemical_id"]):
                if link.get("measurement_basis") != "LAB_TESTED" or \
                        link.get("lab_result_ppm") is None or link.get("lab_loq_ppm") is None:
                    fail("ERR_LAB_RESULT_MISSING",
                         "a contributing link carries no admissible laboratory figure")
            for material, link in contributing_links(product, assessment["chemical_id"]):
                if material.get("disclosure_status") == "REFUSED" and \
                        not material.get("naturally_occurring_claim"):
                    fail("ERR_SUPPLIER_DATA_INCOMPLETE",
                         "a contributing supplier refused disclosure and filed no "
                         "naturally-occurring claim")
        calc.recompute_assessment_numbers(assessment)
        assessment["status"] = "SUBMITTED"
        assessment["submitted_by_user_id"] = who.user_id
        db.touch(assessment)
    elif action == "PEER_REVIEW":
        if who.user_id is not None and who.user_id == assessment.get("submitted_by_user_id"):
            fail("ERR_SEGREGATION_OF_DUTIES", "the submitter may not peer-review this assessment")
        assessment["status"] = "PEER_REVIEWED"
        assessment["reviewed_by_user_id"] = who.user_id
        if note is not None:
            assessment["review_note"] = note
        db.touch(assessment)
    elif action == "REJECT":
        if assessment["status"] == "SUBMITTED" and who.user_id is not None and \
                who.user_id == assessment.get("submitted_by_user_id"):
            fail("ERR_SEGREGATION_OF_DUTIES", "the submitter may not reject this assessment")
        if int(assessment.get("rejection_count") or 0) >= REJECTION_CEILING:
            fail("ERR_REJECTION_LIMIT_REACHED", "the rejection ceiling has been reached")
        assessment["status"] = "REJECTED"
        assessment["review_note"] = note
        assessment["rejection_count"] = int(assessment.get("rejection_count") or 0) + 1
        db.touch(assessment)
    elif action == "REOPEN":
        assessment["status"] = "DRAFT"
        assessment["submitted_by_user_id"] = None
        if note is not None:
            assessment["review_note"] = note
        db.touch(assessment)
    else:
        if assessment["status"] == "SUBMITTED" and \
                assessment.get("reviewed_by_user_id") is None:
            fail("ERR_PEER_REVIEW_REQUIRED", "this assessment has no recorded peer reviewer")
        if chemical is None or chemical["status"] != "LISTED":
            fail("ERR_CHEMICAL_NOT_LISTED", "the chemical is not currently listed")
        calc.recompute_assessment_numbers(assessment)
        assessment["status"] = "FINAL"
        assessment["finalized_at"] = db.now()
        if note is not None:
            assessment["review_note"] = note
        db.touch(assessment)
        for other in calc.assessments_of(product["id"], assessment["chemical_id"]):
            if other["id"] != assessment["id"] and other["status"] == "FINAL":
                cascade.supersede_final_assessment(other)
        db.touch(product)
        posture.recompute_posture(product)
    if action in ("SUBMIT", "PEER_REVIEW", "REJECT", "REOPEN"):
        posture.recompute_posture(product)
    return response.ok(db.serialize("exposure_assessments", assessment))


@bp.route("/exposure-assessments/<assessment_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_assessment(who, assessment_id):
    assessment = validate.must_exist("exposure_assessments", assessment_id, "assessment")
    return response.ok(db.serialize("exposure_assessments", assessment))


@bp.route("/exposure-assessments", methods=["GET"])
@guard(*READ_ROLES)
def list_assessments(who):
    return list_endpoint("exposure_assessments", {
        "product_id": "product_id",
        "chemical_id": "chemical_id",
        "status": "status",
        "method": "method",
        "result": "result",
    })
