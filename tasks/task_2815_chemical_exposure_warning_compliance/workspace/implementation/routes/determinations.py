"""Warning determinations, label content and channel placements (PRD 3.7)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard, action_role
from routes.common import list_endpoint
from services import calc, cascade, posture, warning

bp = Blueprint("determinations", __name__)

DECISIONS = ("WARNING_REQUIRED", "NO_WARNING_REQUIRED")
CHANNELS = ("LABEL", "CATALOG", "INTERNET_POS", "POSTED_SIGN")
DISPLAY_POSITIONS = ("BEFORE_PURCHASE_LINK", "ON_PRODUCT_PAGE", "HYPERLINK_WARNING")
READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel",
              "LabelingSpecialist", "RegistryAdmin")
PLACEMENT_READ_ROLES = ("ComplianceAnalyst", "RegulatoryCounsel", "LabelingSpecialist",
                        "RegistryAdmin")
DET_TRIGGERS = ("SUBMIT_FOR_APPROVAL", "RETURN_FOR_REVISION", "APPROVE", "REVOKE")
DET_ROLES = {
    "SUBMIT_FOR_APPROVAL": ("LabelingSpecialist",),
    "RETURN_FOR_REVISION": ("RegulatoryCounsel",),
    "APPROVE": ("RegulatoryCounsel",),
    "REVOKE": ("RegulatoryCounsel",),
}
DET_LEGAL = {
    "SUBMIT_FOR_APPROVAL": ("DRAFT",),
    "RETURN_FOR_REVISION": ("PENDING_APPROVAL",),
    "APPROVE": ("PENDING_APPROVAL",),
    "REVOKE": ("APPROVED",),
}
PLC_TRIGGERS = ("IMPLEMENT", "VERIFY", "FLAG_NON_COMPLIANT", "REMEDIATE")
PLC_ROLES = {
    "IMPLEMENT": ("LabelingSpecialist",),
    "VERIFY": ("RegulatoryCounsel",),
    "FLAG_NON_COMPLIANT": ("RegulatoryCounsel",),
    "REMEDIATE": ("LabelingSpecialist",),
}
PLC_LEGAL = {
    "IMPLEMENT": ("PLANNED",),
    "VERIFY": ("IMPLEMENTED",),
    "FLAG_NON_COMPLIANT": ("IMPLEMENTED", "VERIFIED"),
    "REMEDIATE": ("NON_COMPLIANT",),
}
IN_FLIGHT = ("DRAFT", "PENDING_APPROVAL")


@bp.route("/warning-determinations", methods=["POST"])
@guard("LabelingSpecialist")
def create_determination(who):
    body = validate.body_json()
    validate.v_str(body, "product_id", required=True)
    validate.v_str(body, "assessment_id", required=True)
    decision = validate.v_enum(body, "decision", DECISIONS, required=True)
    expected = validate.v_version(body, "expected_product_version")
    product = validate.fk("products", body, "product_id", required=True)
    assessment = validate.fk("exposure_assessments", body, "assessment_id", required=True)
    if int(product["version"]) != int(expected):
        fail("ERR_STALE_PRODUCT_VERSION",
             "expected_product_version does not match the product's current version")
    validate.v_writable(body, ("product_id", "assessment_id", "decision",
                               "expected_product_version"))
    qualifying = warning.qualifying_set(product)
    if decision == "NO_WARNING_REQUIRED" and qualifying:
        fail("ERR_EXPOSURE_ABOVE_SAFE_HARBOR",
             "a qualifying exposure forbids a no-warning decision")
    if decision == "WARNING_REQUIRED" and not qualifying:
        fail("ERR_NO_QUALIFYING_EXPOSURE", "no FINAL assessment carries a qualifying result")
    if assessment["product_id"] != product["id"] or assessment["status"] != "FINAL":
        fail("ERR_BASIS_ASSESSMENT_NOT_FINAL",
             "the basis assessment is not FINAL for this product")
    for existing in calc.determinations_of(product["id"]):
        if existing["status"] in IN_FLIGHT:
            fail("ERR_OPEN_DETERMINATION_EXISTS",
                 "this product already holds an in-flight determination")
    row = db.insert("warning_determinations", {
        "product_id": product["id"],
        "assessment_id": assessment["id"],
        "decision": decision,
        "warning_type": None,
        "symbol_required": True,
        "named_chemicals": [],
        "website_url": None,
        "warning_text": None,
        "required_channels": [],
        "covered_channel_count": 0,
        "status": "DRAFT",
        "prepared_by_user_id": who.user_id,
        "approved_by_user_id": None,
        "review_note": None,
    })
    warning.compute_content(row, product)
    db.touch(product)
    posture.recompute_posture(product)
    return response.created(db.serialize("warning_determinations", row))


@bp.route("/warning-determinations/<determination_id>/transitions", methods=["POST"])
@guard("LabelingSpecialist", "RegulatoryCounsel")
def transition_determination(who, determination_id):
    body = validate.body_json()
    action = validate.v_action(body, DET_TRIGGERS)
    action_role(action, DET_ROLES, who.role)
    if action == "RETURN_FOR_REVISION":
        note = validate.v_str(body, "review_note", required=True, minlen=1)
    else:
        note = validate.v_str(body, "review_note")
    determination = validate.must_exist("warning_determinations", determination_id,
                                        "determination")
    if determination["status"] not in DET_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, determination["status"]))
    validate.v_writable(body, ("action", "review_note"))
    product = db.get("products", determination["product_id"])
    assessment = db.get("exposure_assessments", determination.get("assessment_id"))

    if action == "SUBMIT_FOR_APPROVAL":
        determination["status"] = "PENDING_APPROVAL"
        db.touch(determination)
    elif action == "RETURN_FOR_REVISION":
        determination["status"] = "DRAFT"
        determination["review_note"] = note
        db.touch(determination)
    elif action == "APPROVE":
        if who.user_id is not None and \
                who.user_id == determination.get("prepared_by_user_id"):
            fail("ERR_SEGREGATION_OF_DUTIES", "the preparer may not approve this determination")
        if assessment is None or assessment["status"] != "FINAL":
            fail("ERR_BASIS_ASSESSMENT_NOT_FINAL",
                 "the basis assessment is no longer FINAL")
        for other in calc.determinations_of(product["id"]):
            if other["id"] != determination["id"] and other["status"] == "APPROVED":
                cascade.supersede_determination(other)
        determination["status"] = "APPROVED"
        determination["approved_by_user_id"] = who.user_id
        warning.compute_content(determination, product)
        db.touch(determination)
        posture.refresh_covered_channel_count(determination)
    else:
        cascade.revoke_determination(determination, recompute_posture=False)
    db.touch(product)
    posture.recompute_posture(product)
    return response.ok(db.serialize("warning_determinations", determination))


@bp.route("/warning-determinations/<determination_id>/placements", methods=["POST"])
@guard("LabelingSpecialist")
def create_placement(who, determination_id):
    body = validate.body_json()
    channel = validate.v_enum(body, "channel", CHANNELS, required=True)
    effective_from = validate.v_dt(body, "effective_from", required=True)
    effective_to = validate.v_dt(body, "effective_to")
    detail = validate.v_str(body, "placement_detail", required=True, minlen=1, maxlen=200)
    catalog_ref = validate.v_str(body, "catalog_page_ref",
                                 required=(channel == "CATALOG"), minlen=1)
    display_position = validate.v_enum(body, "internet_display_position", DISPLAY_POSITIONS,
                                       required=(channel == "INTERNET_POS"))
    validate.v_interval(effective_from, effective_to)
    determination = validate.must_exist("warning_determinations", determination_id,
                                        "determination")
    validate.v_writable(body, ("channel", "effective_from", "effective_to",
                               "placement_detail", "catalog_page_ref",
                               "internet_display_position"))
    product = db.get("products", determination["product_id"])
    if product is not None and product["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_PARENT_STATE_FORBIDS_WRITE",
             "a placement may not be created under a discontinued product")
    if channel not in (determination.get("required_channels") or []):
        fail("ERR_CHANNEL_NOT_REQUIRED",
             "%s is not among the determination's required channels" % channel)
    for existing in calc.placements_of(determination["id"]):
        if existing["channel"] != channel or existing["status"] == "NON_COMPLIANT":
            continue
        existing_end = existing.get("effective_to")
        if effective_to is not None and existing["effective_from"] > effective_to:
            continue
        if existing_end is not None and effective_from > existing_end:
            continue
        fail("ERR_PLACEMENT_OVERLAP",
             "the closed effective window intersects an existing placement window")
    if determination["status"] != "APPROVED":
        fail("ERR_DETERMINATION_NOT_APPROVED", "the determination is not APPROVED")
    row = db.insert("warning_placements", {
        "determination_id": determination["id"],
        "channel": channel,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "placement_detail": detail,
        "catalog_page_ref": catalog_ref,
        "internet_display_position": display_position,
        "status": "PLANNED",
        "implemented_by_user_id": None,
        "remediation_count": 0,
    })
    posture.refresh_covered_channel_count(determination)
    posture.recompute_posture(product)
    return response.created(db.serialize("warning_placements", row))


@bp.route("/warning-placements/<placement_id>/transitions", methods=["POST"])
@guard("LabelingSpecialist", "RegulatoryCounsel")
def transition_placement(who, placement_id):
    body = validate.body_json()
    action = validate.v_action(body, PLC_TRIGGERS)
    action_role(action, PLC_ROLES, who.role)
    placement = validate.must_exist("warning_placements", placement_id, "placement")
    if placement["status"] not in PLC_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, placement["status"]))
    validate.v_writable(body, ("action",))
    determination = db.get("warning_determinations", placement["determination_id"])
    product = db.get("products", determination["product_id"]) if determination else None
    if action in ("IMPLEMENT", "REMEDIATE") and \
            (determination is None or determination["status"] != "APPROVED"):
        fail("ERR_DETERMINATION_NOT_APPROVED",
             "the parent determination is not APPROVED")
    if action == "IMPLEMENT":
        placement["status"] = "IMPLEMENTED"
        placement["implemented_by_user_id"] = who.user_id
    elif action == "VERIFY":
        placement["status"] = "VERIFIED"
    elif action == "FLAG_NON_COMPLIANT":
        placement["status"] = "NON_COMPLIANT"
    else:
        placement["status"] = "IMPLEMENTED"
        placement["remediation_count"] = int(placement.get("remediation_count") or 0) + 1
    db.touch(placement)
    if determination is not None:
        posture.refresh_covered_channel_count(determination)
    if product is not None:
        db.touch(product)
        posture.recompute_posture(product)
    return response.ok(db.serialize("warning_placements", placement))


@bp.route("/warning-determinations/<determination_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_determination(who, determination_id):
    determination = validate.must_exist("warning_determinations", determination_id,
                                        "determination")
    return response.ok(db.serialize("warning_determinations", determination))


@bp.route("/warning-determinations", methods=["GET"])
@guard(*READ_ROLES)
def list_determinations(who):
    return list_endpoint("warning_determinations", {
        "product_id": "product_id",
        "assessment_id": "assessment_id",
        "status": "status",
        "warning_type": "warning_type",
    })


@bp.route("/warning-placements/<placement_id>", methods=["GET"])
@guard(*PLACEMENT_READ_ROLES)
def read_placement(who, placement_id):
    placement = validate.must_exist("warning_placements", placement_id, "placement")
    return response.ok(db.serialize("warning_placements", placement))


@bp.route("/warning-placements", methods=["GET"])
@guard(*PLACEMENT_READ_ROLES)
def list_placements(who):
    return list_endpoint("warning_placements", {
        "determination_id": "determination_id",
        "channel": "channel",
        "status": "status",
    })
