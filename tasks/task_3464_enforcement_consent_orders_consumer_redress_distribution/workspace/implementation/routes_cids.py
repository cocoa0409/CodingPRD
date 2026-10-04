"""CivilInvestigativeDemand lifecycle transitions."""
from flask import Blueprint

import envelope
import errors
import requtil
import store
from timeutil import parse_iso, seconds

bp = Blueprint("cids", __name__)

CID_STATES = {"DRAFT", "ISSUED", "QUASH_PETITIONED", "ENFORCED", "RESPONDED", "WITHDRAWN"}
CID_TARGET_ROLES = {
    "ISSUED": ["StaffAttorney"],
    "ENFORCED": ["StaffAttorney"],
    "WITHDRAWN": ["StaffAttorney"],
    "RESPONDED": ["CompanyRepresentative"],
    "QUASH_PETITIONED": ["CompanyRepresentative"],
}
CID_TRANSITIONS = {
    "ISSUED": {"DRAFT"},
    "RESPONDED": {"ISSUED", "ENFORCED"},
    "QUASH_PETITIONED": {"ISSUED"},
    "ENFORCED": {"QUASH_PETITIONED"},
    "WITHDRAWN": {"DRAFT", "ISSUED"},
}


@bp.route("/enforcement/cids/<cidId>/transition", methods=["POST"])
def transition_cid(cidId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["StaffAttorney", "CompanyRepresentative"])
    cid = requtil.get_or_404(store.db.cids, cidId, "ERR_CID_NOT_FOUND", "CID")
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", CID_STATES)
    requtil.require_target_role(role, target, CID_TARGET_ROLES)
    # Tier 4: transition-scoped required inputs.
    response_ref = None
    if target == "RESPONDED":
        response_ref = requtil.need_str(body, "response_document_ref")
    # Tier 5: state legality (from-state membership; parent gate on issuance).
    if target not in CID_TRANSITIONS or cid["status"] not in CID_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "CID cannot transition from {} to {}".format(cid["status"], target),
        )
    inv = store.db.investigations.get(cid["investigation_id"])
    if target == "ISSUED" and (inv is None or inv["status"] != "EVIDENCE_GATHERING"):
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A CID can be issued only while its investigation is EVIDENCE_GATHERING",
        )
    # Tier 9: deadline discipline. The overdue check applies only to a merely
    # ISSUED demand; court enforcement strips the deadline's protection.
    if target == "RESPONDED" and cid["status"] == "ISSUED":
        if seconds(store.db.clock_dt) >= seconds(parse_iso(cid["response_due_date"])):
            errors.fail(
                "ERR_CID_RESPONSE_OVERDUE",
                "The response_due_date has been reached or passed",
            )
    # Tier 13: subject-company ownership on company-side transitions.
    if target in ("RESPONDED", "QUASH_PETITIONED"):
        if inv is None or user_id != inv["subject_company_id"]:
            errors.fail(
                "ERR_SUBJECT_COMPANY_MISMATCH",
                "X-User-ID must equal the investigation's subject company id",
            )
    with store.db.lock:
        cid["status"] = target
        if target == "RESPONDED":
            cid["response_document_ref"] = response_ref
            cid["responded_at"] = store.now_str()
        store.touch(cid)
    return envelope.success(store.public(cid), 200)
