"""PostElectionAudit endpoints (PRD 3.10).

At most one non-terminal audit per election definition. CLOSED_ESCALATED
requires a critical finding and quarantines the fleet (units of the audited
definition's jurisdiction and voting system in IN_SERVICE / IN_STORAGE /
IN_MAINTENANCE), aborting their open work orders; an IN_PROGRESS abort leaves
the unit QUARANTINED with pre_maintenance_status cleared.
"""
from flask import Blueprint

from auth import auth_context, require_role
from domains.definitions import get_definition_or_404
from domains.units import abort_open_work_orders
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import now, stamp_new, touch
from validation import body_json, no_extra, req_enum, req_int, req_str

bp = Blueprint("audits", __name__)

AUDIT_TYPES = {"RISK_LIMITING", "COMPLIANCE", "FULL_RECOUNT"}
AUDIT_STATES = {"INITIATED", "FINDINGS_FILED", "CLOSED_CONFIRMED", "CLOSED_ESCALATED"}
AUDIT_FROM = {
    "FINDINGS_FILED": {"INITIATED"},
    "CLOSED_CONFIRMED": {"FINDINGS_FILED"},
    "CLOSED_ESCALATED": {"FINDINGS_FILED"},
}
NONTERMINAL_AUDIT_STATES = {"INITIATED", "FINDINGS_FILED"}
TERMINAL_AUDIT_STATES = {"CLOSED_CONFIRMED", "CLOSED_ESCALATED"}


@bp.post("/evote/post-election-audits")
def create_audit():
    _, role = auth_context()
    require_role(role, {"Auditor"})
    body = body_json()
    no_extra(body, {"election_definition_id", "audit_type"})
    definition_id = req_str(body, "election_definition_id")
    audit_type = req_enum(body, "audit_type", AUDIT_TYPES)
    definition = db.election_definitions.get(definition_id)
    if definition is None:
        raise_err("ERR_ELECTION_DEFINITION_NOT_FOUND", 404, "election_definition_id does not resolve")
    if definition["status"] != "CANVASSING":
        err_invalid_state("audits open only on a CANVASSING election definition")
    for audit in db.post_election_audits.values():
        if audit["election_definition_id"] == definition_id and audit["status"] in NONTERMINAL_AUDIT_STATES:
            raise_err("ERR_AUDIT_ALREADY_ACTIVE", 409, "an audit of this definition is already active")
    rec = stamp_new({})
    rec.update({
        "election_definition_id": definition_id,
        "audit_type": audit_type,
        "critical_findings": 0,
        "major_findings": 0,
        "minor_findings": 0,
        "report_public": False,
        "published_at": None,
        "status": "INITIATED",
    })
    db.post_election_audits[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/election-definitions/<definition_id>/post-election-audits")
def list_definition_audits(definition_id):
    auth_context()
    get_definition_or_404(definition_id)
    items = [a for a in db.post_election_audits.values() if a["election_definition_id"] == definition_id]
    items = apply_filters(items, {"status"})
    return list_page(items)


def get_audit_or_404(audit_id):
    audit = db.post_election_audits.get(audit_id)
    if audit is None:
        err_not_found("post-election audit not found")
    return audit


def escalation_cascade(audit):
    definition = db.election_definitions.get(audit["election_definition_id"])
    if definition is None:
        return
    proc = db.procurements.get(definition["procurement_id"])
    system_id = proc["voting_system_id"] if proc is not None else None
    for unit in db.equipment_units.values():
        if (
            unit["jurisdiction_id"] == definition["jurisdiction_id"]
            and unit["voting_system_id"] == system_id
            and unit["operational_status"] in {"IN_SERVICE", "IN_STORAGE", "IN_MAINTENANCE"}
        ):
            abort_open_work_orders(unit, restoring=False)
            unit["operational_status"] = "QUARANTINED"
            touch(unit)


@bp.post("/evote/post-election-audits/<audit_id>/transitions")
def audit_transition(audit_id):
    _, role = auth_context()
    require_role(role, {"Auditor"})
    audit = get_audit_or_404(audit_id)
    body = body_json()
    no_extra(body, {"to_state", "critical_findings", "major_findings", "minor_findings"})
    to_state = req_enum(body, "to_state", AUDIT_STATES)
    crit = maj = mnr = None
    if to_state == "FINDINGS_FILED":
        crit = req_int(body, "critical_findings", minv=0)
        maj = req_int(body, "major_findings", minv=0)
        mnr = req_int(body, "minor_findings", minv=0)
    if to_state not in AUDIT_FROM or audit["status"] not in AUDIT_FROM[to_state]:
        err_invalid_state("audit cannot transition from %s to %s" % (audit["status"], to_state))
    if to_state == "CLOSED_ESCALATED" and audit["critical_findings"] < 1:
        raise_err("ERR_ESCALATION_REQUIRES_CRITICAL", 422, "escalation requires a critical finding")
    if to_state == "FINDINGS_FILED":
        audit["critical_findings"] = crit
        audit["major_findings"] = maj
        audit["minor_findings"] = mnr
    elif to_state == "CLOSED_ESCALATED":
        escalation_cascade(audit)
    audit["status"] = to_state
    touch(audit)
    return ok_object(audit, 200)


@bp.post("/evote/post-election-audits/<audit_id>/publish")
def publish_audit(audit_id):
    _, role = auth_context()
    require_role(role, {"Auditor"})
    audit = get_audit_or_404(audit_id)
    body = body_json()
    no_extra(body, set())
    if audit["status"] not in TERMINAL_AUDIT_STATES:
        err_invalid_state("only a terminal audit may be published")
    audit["report_public"] = True
    audit["published_at"] = now()
    touch(audit)
    return ok_object(audit, 200)
