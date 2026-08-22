"""CertificationCredit and CreditEvidence endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, D, ROLE_CX_AUTHORITY, ROLE_OWNER_REP, authenticate, body_json,
    bump_project, clock, db, fail, new_row, num, ok, ok_list, paginate, public, q,
    q_bool, rhu, sorted_rows, touch, v_enum, v_int, v_number, v_string,
)
from finders import get_credit, get_project

bp = Blueprint("credits", __name__)


def _resolve_evidence_ref(evidence_type, ref_id, project_id):
    """Resolve evidence_ref_id inside its declared family and engagement (PRD 3.8)."""
    if evidence_type == "EQUIPMENT_VERIFICATION":
        row = db.equipment.get(ref_id)
        owner = row["project_id"] if row else None
    elif evidence_type == "FUNCTIONAL_TEST":
        row = db.tests.get(ref_id)
        equipment_row = db.equipment.get(row["equipment_id"]) if row else None
        owner = equipment_row["project_id"] if equipment_row else None
    elif evidence_type == "CHECKLIST":
        row = db.checklists.get(ref_id)
        equipment_row = db.equipment.get(row["equipment_id"]) if row else None
        owner = equipment_row["project_id"] if equipment_row else None
    elif evidence_type in ("TRAINING", "MANUAL_SECTION"):
        row = db.deliverables.get(ref_id)
        owner = row["project_id"] if row else None
    elif evidence_type == "ENERGY_BASELINE":
        row = db.baselines.get(ref_id)
        owner = row["project_id"] if row else None
    else:
        row, owner = None, None
    if row is None or owner != project_id:
        fail("ERR_EVIDENCE_REF_INVALID",
             "evidence_ref_id does not resolve to a %s row of this engagement."
             % evidence_type)
    return row


@bp.post("/certification-credits")
def create_credit():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    project_id = v_string(body, "project_id")
    credit_code = v_string(body, "credit_code")
    required_evidence_count = v_int(body, "required_evidence_count", minimum=0)
    max_points = v_number(body, "max_points", minimum=0)

    get_project(project_id)

    row = new_row(db.credits, {
        "project_id": project_id,
        "credit_code": credit_code,
        "required_evidence_count": required_evidence_count,
        "max_points": max_points,
        "status": "NOT_STARTED",
        "evidence_count": 0,
        "fresh_evidence_count": 0,
        "stale_evidence_count": 0,
        "completeness_ratio": 0,
        "provisional_tier": "NONE",
        "documentation_score": 0,
        "final_tier": "NONE",
        "awarded_points": 0,
        "submitted_at": None,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/certification-credits")
def list_credits():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.credits.values()))
    for param in ("project_id", "status"):
        value = q(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/certification-credits/<credit_id>")
def read_credit(credit_id):
    authenticate(ALL_ROLES)
    return ok(public(get_credit(credit_id)))


@bp.post("/certification-credits/<credit_id>/evidence")
def attach_evidence(credit_id):
    authenticate([ROLE_CX_AUTHORITY])
    credit = get_credit(credit_id)
    body = body_json()
    evidence_type = v_enum(body, "evidence_type", calc.EVIDENCE_TYPES)
    evidence_ref_id = v_string(body, "evidence_ref_id")

    _resolve_evidence_ref(evidence_type, evidence_ref_id, credit["project_id"])

    row = new_row(db.evidence, {
        "credit_id": credit["id"],
        "evidence_type": evidence_type,
        "evidence_ref_id": evidence_ref_id,
        "is_stale": False,
        "staled_at": None,
    })
    if calc.evidence_is_stale(row):
        row["is_stale"] = True
        row["staled_at"] = clock.now_iso()

    if credit["status"] in ("NOT_STARTED", "WITHDRAWN"):
        credit["status"] = "IN_PREPARATION"
        touch(credit)

    services.recompute_credit(credit)
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/certification-credits/<credit_id>/evidence")
def list_evidence(credit_id):
    authenticate(ALL_ROLES)
    credit = get_credit(credit_id)
    rows = calc.credit_evidence(credit["id"])
    is_stale = q_bool("is_stale")
    if is_stale is not None:
        rows = [r for r in rows if r["is_stale"] == is_stale]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/certification-credits/<credit_id>/submit")
def submit_credit(credit_id):
    authenticate([ROLE_CX_AUTHORITY])
    credit = get_credit(credit_id)
    body = body_json()
    expected_project_version = v_int(body, "expected_project_version")

    project = db.projects.get(credit["project_id"])

    if expected_project_version != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION",
             "expected_project_version %s does not match the engagement version %s."
             % (expected_project_version, project["version"]))
    if project["readiness_posture"] == "FROZEN":
        fail("ERR_PROJECT_FROZEN", "The engagement is FROZEN.")
    if credit["status"] != "IN_PREPARATION":
        fail("ERR_INVALID_STATE", "Only an IN_PREPARATION credit may be submitted.")

    plan = calc.newest_plan(project["id"])
    if plan is None or plan["status"] != "APPROVED":
        fail("ERR_PLAN_NOT_APPROVED",
             "The engagement's newest commissioning plan is not APPROVED.")
    if plan["pin_stale"]:
        fail("ERR_PLAN_PIN_STALE", "The newest commissioning plan has a stale pin set.")
    if credit["fresh_evidence_count"] < credit["required_evidence_count"]:
        fail("ERR_EVIDENCE_INSUFFICIENT",
             "fresh_evidence_count %d is below required_evidence_count %d."
             % (credit["fresh_evidence_count"], credit["required_evidence_count"]))

    credit["status"] = "SUBMITTED"
    credit["submitted_at"] = clock.now_iso()
    touch(credit)
    bump_project(project)
    services.reconcile()
    return ok(public(credit))


@bp.post("/certification-credits/<credit_id>/adjudicate")
def adjudicate_credit(credit_id):
    authenticate([ROLE_OWNER_REP])
    credit = get_credit(credit_id)
    body = body_json()
    decision = v_enum(body, "decision", calc.ADJUDICATION_DECISIONS)
    v_string(body, "reason", required=False, default=None)

    if credit["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED credit may be adjudicated.")
    if decision == "AWARDED" and credit["final_tier"] == "NONE":
        fail("ERR_INVALID_STATE", "A credit whose final_tier is NONE cannot be awarded.")

    project = db.projects.get(credit["project_id"])
    if decision == "AWARDED":
        points = rhu(
            D(credit["max_points"]) * calc.TIER_AWARD_FRACTION[credit["final_tier"]], 2)
        credit["status"] = "AWARDED"
        credit["awarded_points"] = num(points)
    else:
        credit["status"] = "DENIED"
        credit["awarded_points"] = 0
    touch(credit)
    bump_project(project)
    services.reconcile()
    return ok(public(credit))
