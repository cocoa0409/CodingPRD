"""The labour warranty: filing a claim and triaging it."""
from flask import Blueprint

import envelope
import fields
import store
from errors import ApiError
from fields import E, S, auth, body, need, pagination, validate
from routes.helpers import owner_customer
from services import calc, cascade

bp = Blueprint("warranty", __name__)

CLAIM_READ = ["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Customer"]

CLAIM_CREATE = [
    S("project_id"),
    E("claim_type", fields.CLAIM_TYPES),
    S("description", maxlen=500),
]

TRIAGE = [
    E("decision", fields.TRIAGE_DECISIONS),
    S("decision_note", required=False, maxlen=300),
    S("denial_reason", required=False, maxlen=300),
]


@bp.post("/warranty-claims")
def create_claim():
    actor = auth(["Customer"])
    data = validate(body(), CLAIM_CREATE)
    project = need("projects", data["project_id"])
    owner_customer(project, actor)
    if data["claim_type"] != "LABOR_DEFECT":
        raise ApiError("ERR_WARRANTY_EXPIRED")
    if (project["fulfillment_status"] != "CLOSED" or project["closed_at"] is None
            or store.now() > store.days_after(project["closed_at"], calc.WARRANTY_LABOR_DAYS)):
        raise ApiError("ERR_WARRANTY_EXPIRED")

    row = {
        "project_id": project["id"],
        "claim_type": data["claim_type"],
        "description": data["description"],
        "status": "SUBMITTED",
        "submitted_at": store.now(),
        "triaged_at": None,
        "decision_note": None,
        "denial_reason": None,
        "escalation_level": 0,
        "escalated_to_user_id": None,
    }
    store.insert("warranty_claims", row)
    return envelope.obj(row, 201)


@bp.get("/warranty-claims")
def list_claims():
    auth(CLAIM_READ)
    limit, offset = pagination()
    rows = store.all_rows("warranty_claims")
    for name in ("project_id", "status", "claim_type"):
        rows = fields.filter_eq(rows, name, fields.arg(name))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/warranty-claims/<row_id>")
def get_claim(row_id):
    auth(CLAIM_READ)
    return envelope.obj(need("warranty_claims", row_id))


@bp.post("/warranty-claims/<row_id>/triage")
def triage(row_id):
    actor = auth(["ServiceManager"])
    data = validate(body(), TRIAGE)
    decision = data["decision"]
    if decision == "DENY" and data.get("denial_reason") is None:
        raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                       "denial_reason is required when the decision is DENY.")
    claim = need("warranty_claims", row_id)
    if claim["status"] in ("UPHELD", "DENIED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if decision == "ESCALATE":
        if claim["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")
    elif claim["status"] not in ("SUBMITTED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE")

    if decision == "UPHOLD":
        claim["status"] = "UPHELD"
        claim["triaged_at"] = store.now()
        claim["decision_note"] = data.get("decision_note")
        installer_id = cascade.project_completed_installer_id(claim["project_id"])
        installer = store.get("installers", installer_id) if installer_id else None
        if installer is not None:
            cascade.append_event(installer, "WARRANTY_UPHELD", store.now(), "SYSTEM",
                                 project_id=claim["project_id"])
            cascade.rescore_and_touch(installer)
    elif decision == "DENY":
        claim["status"] = "DENIED"
        claim["triaged_at"] = store.now()
        claim["decision_note"] = data.get("decision_note")
        claim["denial_reason"] = data["denial_reason"]
    else:
        claim["status"] = "ESCALATED"
        claim["escalation_level"] = int(claim["escalation_level"]) + 1
        claim["escalated_to_user_id"] = actor.user_id
    store.touch(claim)
    return envelope.obj(claim)
