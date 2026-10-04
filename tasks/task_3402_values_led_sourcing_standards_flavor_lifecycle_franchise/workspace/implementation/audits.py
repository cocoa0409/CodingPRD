"""Supplier social audits (PRD section 3.2).

composite_score = round_half_up(0.4*labor + 0.3*environment + 0.3*community)
outcome = PASS iff composite_score >= 70 AND findings_count <= 2 (inclusive).
Verification always writes social_criteria_score onto the supplier; PASS
approves a PROSPECT/SUSPENDED supplier, FAIL runs the depth-3 cascade.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import cascades
from auth import authenticate, authorize
from db import STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from suppliers import get_supplier
from timeutil import fmt_dt
from validate import get_body, req_dt, req_int

bp = Blueprint("audits", __name__)

W_LABOR = Decimal("0.4")
W_ENVIRONMENT = Decimal("0.3")
W_COMMUNITY = Decimal("0.3")
PASS_COMPOSITE_MIN = 70
PASS_MAX_FINDINGS = 2


def get_audit(aid):
    a = STORE["audits"].get(aid)
    if a is None:
        fail("ERR_AUDIT_NOT_FOUND", "Audit id does not exist")
    return a


@bp.post("/suppliers/<sid>/audits")
def schedule_audit(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager",))
    get_supplier(sid)
    body = get_body()
    scheduled_for = req_dt(body, "scheduled_for")
    r = new_resource()
    r.update({
        "supplier_id": sid,
        "scheduled_for": fmt_dt(scheduled_for),
        "auditor_user_id": None,
        "labor_score": None,
        "environment_score": None,
        "community_score": None,
        "findings_count": None,
        "composite_score": None,
        "outcome": None,
        "status": "SCHEDULED",
    })
    STORE["audits"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/suppliers/<sid>/audits")
def list_audits(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager", "SustainabilityAuditor",
                     "AuditVerifier"))
    get_supplier(sid)
    items = [public(a) for a in sorted_items(
        a for a in STORE["audits"].values() if a["supplier_id"] == sid)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.post("/audits/<aid>/start")
def start_audit(aid):
    uid, role = authenticate()
    authorize(role, ("SustainabilityAuditor",))
    a = get_audit(aid)
    supplier = STORE["suppliers"].get(a["supplier_id"])
    if supplier is not None and supplier["status"] == "TERMINATED":
        fail("ERR_INVALID_STATE",
             "Cannot start an audit of a TERMINATED supplier")
    if a["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE", "Only a SCHEDULED audit can be started")
    a["auditor_user_id"] = uid
    a["status"] = "IN_PROGRESS"
    touch(a)
    return ok(public(a))


@bp.post("/audits/<aid>/complete")
def complete_audit(aid):
    uid, role = authenticate()
    authorize(role, ("SustainabilityAuditor",))
    a = get_audit(aid)
    # Ownership (ladder rung 3) precedes the state check: only the auditor
    # who started the audit may complete it.
    if uid != a["auditor_user_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Only the auditor who started the audit may complete it")
    body = get_body()
    labor = req_int(body, "labor_score", 0, 100)
    environment = req_int(body, "environment_score", 0, 100)
    community = req_int(body, "community_score", 0, 100)
    findings = req_int(body, "findings_count", 0)
    if a["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE",
             "Only an IN_PROGRESS audit can be completed")
    composite = int((W_LABOR * labor + W_ENVIRONMENT * environment
                     + W_COMMUNITY * community).quantize(
                         Decimal("1"), rounding=ROUND_HALF_UP))
    outcome = ("PASS" if composite >= PASS_COMPOSITE_MIN
               and findings <= PASS_MAX_FINDINGS else "FAIL")
    a.update({
        "labor_score": labor,
        "environment_score": environment,
        "community_score": community,
        "findings_count": findings,
        "composite_score": composite,
        "outcome": outcome,
        "status": "COMPLETED",
    })
    touch(a)
    return ok(public(a))


@bp.post("/audits/<aid>/verify")
def verify_audit(aid):
    uid, role = authenticate()
    authorize(role, ("AuditVerifier",))
    a = get_audit(aid)
    # Segregation of duties: the verifier must not be the performing auditor.
    if uid == a["auditor_user_id"]:
        fail("ERR_SOD_AUDITOR_VERIFY",
             "The verifier must differ from the performing auditor")
    if a["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "Only a COMPLETED audit can be verified")
    a["status"] = "VERIFIED"
    touch(a)
    supplier = STORE["suppliers"].get(a["supplier_id"])
    if supplier is not None:
        supplier["social_criteria_score"] = a["composite_score"]
        if a["outcome"] == "PASS":
            if supplier["status"] in ("PROSPECT", "SUSPENDED"):
                supplier["status"] = "APPROVED"
        else:
            cascades.audit_fail_cascade(supplier)
            if supplier["status"] in ("PROSPECT", "APPROVED", "SUSPENDED"):
                supplier["status"] = "SUSPENDED"
        touch(supplier)
    return ok(public(a))
