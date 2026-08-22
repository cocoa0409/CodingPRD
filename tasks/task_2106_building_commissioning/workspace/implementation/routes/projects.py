"""CxProject endpoints and the logical-clock test-driving endpoint."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, D, ROLE_CX_AUTHORITY, ROLE_OWNER_REP, ROLE_PLATFORM_ADMIN,
    authenticate, body_json, bump_project, clock, db, fail, new_row, num, ok, ok_list,
    paginate, parse_dt, public, q, sorted_rows, touch, v_datetime, v_enum, v_int, v_string,
)
from finders import get_project

bp = Blueprint("projects", __name__)

PHASE_ORDER = calc.DELIVERY_PHASES


@bp.post("/cx-projects")
def create_project():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = body_json()
    name = v_string(body, "name")
    building_name = v_string(body, "building_name")
    project_type = v_enum(body, "project_type", calc.PROJECT_TYPES)
    contract_value_cents = v_int(body, "contract_value_cents", minimum=1)
    certification_target = v_enum(
        body, "certification_target", calc.CERT_TARGETS, required=False, default="NONE")
    witness_capacity = v_int(body, "witness_capacity", required=False, default=1, minimum=1)

    project = new_row(db.projects, {
        "name": name,
        "building_name": building_name,
        "project_type": project_type,
        "certification_target": certification_target,
        "contract_value_cents": contract_value_cents,
        "witness_capacity": witness_capacity,
        "delivery_phase": "PLANNING",
        "readiness_posture": "OPEN",
        "issue_severity_index": 0,
        "retainage_withheld_cents": 0,
        "verified_prefunctional_units": 0,
        "open_blocking_issue_count": 0,
        "acceptance_completion_score": 0,
        "final_acceptance_score": None,
        "acceptance_kind": None,
        "withdrawn_credit_count": 0,
        "total_awarded_points": 0,
    })
    services.reconcile()
    return ok(public(project), 201)


@bp.get("/cx-projects/<project_id>")
def read_project(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    return ok(public(project))


@bp.get("/cx-projects")
def list_projects():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.projects.values()))
    project_type = q("project_type")
    delivery_phase = q("delivery_phase")
    readiness_posture = q("readiness_posture")
    if project_type is not None:
        rows = [r for r in rows if r["project_type"] == project_type]
    if delivery_phase is not None:
        rows = [r for r in rows if r["delivery_phase"] == delivery_phase]
    if readiness_posture is not None:
        rows = [r for r in rows if r["readiness_posture"] == readiness_posture]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/cx-projects/<project_id>/advance-phase")
def advance_phase(project_id):
    authenticate([ROLE_CX_AUTHORITY])
    project = get_project(project_id)
    body = body_json()
    target_phase = v_enum(body, "target_phase", calc.DELIVERY_PHASES)

    # 9 — frozen posture
    if project["readiness_posture"] == "FROZEN":
        fail("ERR_PROJECT_FROZEN", "The engagement is FROZEN.")

    # 10 — exactly the next phase
    current = project["delivery_phase"]
    index = PHASE_ORDER.index(current)
    next_phase = PHASE_ORDER[index + 1] if index + 1 < len(PHASE_ORDER) else None
    if next_phase is None or target_phase != next_phase:
        fail("ERR_PHASE_NOT_ALLOWED",
             "Only '%s' may follow '%s'." % (next_phase, current))

    # 11 — the hop's own precondition
    pid = project["id"]
    if next_phase == "DESIGN":
        if not any(r["status"] == "APPROVED" for r in db.requirements.values()
                   if r["project_id"] == pid):
            fail("ERR_INVALID_STATE", "At least one owner requirement must be APPROVED.")
    elif next_phase == "CONSTRUCTION":
        approved = [p for p in calc.project_plans(pid) if p["status"] == "APPROVED"]
        if len(approved) != 1:
            fail("ERR_INVALID_STATE", "Exactly one commissioning plan must be APPROVED.")
    elif next_phase == "FUNCTIONAL_TESTING":
        if project["verified_prefunctional_units"] < 1:
            fail("ERR_INVALID_STATE", "verified_prefunctional_units must be at least 1.")
    elif next_phase == "ACCEPTANCE":
        for eq in calc.project_equipment(pid):
            if eq["verification_status"] not in calc.VERIFIED_SET:
                fail("ERR_INVALID_STATE", "Every equipment unit must be verified.")
    elif next_phase == "WARRANTY":
        if project["acceptance_kind"] is None:
            fail("ERR_INVALID_STATE", "An acceptance certificate must have been issued.")
    elif next_phase == "CLOSED":
        if any(d["status"] in calc.DEFERRED_LIVE for d in calc.project_deferred_tests(pid)):
            fail("ERR_INVALID_STATE", "Deferred tests remain PLANNED or BLOCKED.")
        if any(i["status"] in calc.RETAINAGE_ISSUE_STATUSES for i in calc.project_issues(pid)):
            fail("ERR_INVALID_STATE", "Issues remain OPEN, IN_REVIEW or DEFERRED.")

    project["delivery_phase"] = next_phase
    bump_project(project)
    services.reconcile()
    return ok(public(project))


@bp.post("/cx-projects/<project_id>/issue-acceptance")
def issue_acceptance(project_id):
    authenticate([ROLE_OWNER_REP])
    project = get_project(project_id)
    body = body_json()
    acceptance_kind = v_enum(body, "acceptance_kind", calc.ACCEPTANCE_KINDS)

    if project["readiness_posture"] == "FROZEN":
        fail("ERR_PROJECT_FROZEN", "The engagement is FROZEN.")
    if project["delivery_phase"] != "ACCEPTANCE":
        fail("ERR_PHASE_NOT_ALLOWED", "The engagement must be in ACCEPTANCE.")

    final_score = calc.compute_acceptance_score(project["id"], "FINAL")
    floor = calc.SUBSTANTIAL_MIN_SCORE if acceptance_kind == "SUBSTANTIAL" else calc.FINAL_MIN_SCORE
    if final_score < floor:
        fail("ERR_ACCEPTANCE_SCORE_TOO_LOW",
             "The FINAL acceptance completion score %s is below %s." % (final_score, floor))

    issues = calc.project_issues(project["id"])
    if acceptance_kind == "SUBSTANTIAL":
        if any(i["severity"] == "S1" and i["status"] in calc.LIVE_ISSUE_STATUSES for i in issues):
            fail("ERR_OPEN_BLOCKING_ISSUES", "An S1 deficiency is still open.")
    else:
        if any(i["status"] in calc.RETAINAGE_ISSUE_STATUSES for i in issues):
            fail("ERR_OPEN_BLOCKING_ISSUES", "Deficiencies remain open, in review or deferred.")

    project["final_acceptance_score"] = num(final_score)
    project["acceptance_kind"] = acceptance_kind
    bump_project(project)
    services.reconcile()
    return ok(public(project))


@bp.get("/cx-projects/<project_id>/readiness")
def readiness(project_id):
    authenticate(ALL_ROLES)
    project = get_project(project_id)
    pid = project["id"]
    provisional = calc.compute_acceptance_score(pid, "PROVISIONAL")
    final = calc.compute_acceptance_score(pid, "FINAL")
    data = {
        "readiness_posture": project["readiness_posture"],
        "issue_severity_index": project["issue_severity_index"],
        "acceptance_completion_score_provisional": num(provisional),
        "acceptance_completion_score_final": num(final),
        "open_blocking_issue_count": project["open_blocking_issue_count"],
        "retainage_withheld_cents": project["retainage_withheld_cents"],
        "retainage_cap_cents": calc.retainage_cap_cents(project),
        "verified_prefunctional_units": project["verified_prefunctional_units"],
        "total_weight_units": calc.total_weight_units(pid),
        "withdrawn_credit_count": project["withdrawn_credit_count"],
        "total_awarded_points": project["total_awarded_points"],
    }
    return ok(data)


@bp.post("/cx-projects/<project_id>/run-seasonal-sweep")
def run_seasonal_sweep(project_id):
    authenticate([ROLE_CX_AUTHORITY])
    project = get_project(project_id)
    now = clock.now()

    for row in calc.project_deferred_tests(project["id"]):
        if row["status"] not in calc.DEFERRED_LIVE:
            continue
        if parse_dt(row["window_end"]) > now:
            continue
        row["status"] = "MISSED"
        touch(row)
        services.create_issue(
            project,
            origin="SEASONAL",
            severity="S2",
            description="Seasonal test window missed.",
            equipment_id=row["equipment_id"],
            source_ref_id=row["id"],
            opened_by_user_id="SYSTEM",
        )
        linked = db.issues.get(row.get("issue_id")) if row.get("issue_id") else None
        if linked is not None and linked["status"] == "DEFERRED":
            services.apply_issue_status_change(linked, "OPEN")
            linked["reopen_count"] = linked["reopen_count"] + 1
            touch(linked)

    bump_project(project)
    services.reconcile()
    return ok(public(project))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = body_json()
    target = v_datetime(body, "to_iso8601")
    clock.set(target)
    services.reconcile()
    return ok({"current_utc": clock.now_iso()})
