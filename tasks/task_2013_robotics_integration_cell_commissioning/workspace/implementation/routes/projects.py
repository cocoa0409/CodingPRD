"""CellProject lifecycle: advance / hold / resume / terminate (PRD §3.1, §3.6, §3.9)."""
from flask import Blueprint

from db import children, store
from errors import (ApiError, ERR_GATE_PRECONDITION_UNMET,
                    ERR_RETENTION_BALANCE_MISMATCH, ERR_STALE_PROJECT_VERSION,
                    bad_request, invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from response import success
from services import calculations as calc
from services.domain import (common_fields, guarantee_of_project, init_guarantee,
                             milestone_amount_for_phase, post_ledger_entry, pub,
                             terminate_cascade, touch)
from validation import as_str, body, req

bp = Blueprint("projects", __name__)

# Advance stage map: from_status -> (to_status, pinned actor role) (PRD §3.6).
ADVANCE_STAGES = {
    "DRAFT": ("STUDY", PE),
    "STUDY": ("DESIGN", PE),
    "DESIGN": ("BUILD", PE),
    "BUILD": ("FAT", SS),
    "FAT": ("SHIP", SS),
    "SHIP": ("SAT", SS),
    "SAT": ("TRAINING", SS),
    "TRAINING": ("GUARANTEE", PE),
}


def get_project(project_id):
    project = store.projects.get(project_id)
    if project is None:
        raise not_found("Cell project not found")
    return project


def _check_occ(project, b):
    expected = req(b, "expected_project_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise bad_request("Field 'expected_project_version' must be an integer")
    if expected != project["version"]:
        raise ApiError(
            ERR_STALE_PROJECT_VERSION, 412,
            f"expected_project_version {expected} does not match current "
            f"version {project['version']}",
        )


def _latest_test(project_id, phase):
    tests = [t for t in children("tests", "cell_project_id", project_id) if t["phase"] == phase]
    return tests[-1] if tests else None


def _gate_fail(message):
    raise ApiError(ERR_GATE_PRECONDITION_UNMET, 422, message)


@bp.post("/robotics/cell-projects/<project_id>/advance")
def advance(project_id):
    _uid, role = authenticate({PE, SS})
    project = get_project(project_id)
    status = project["status"]
    if status not in ADVANCE_STAGES:
        raise invalid_state(f"Project in status {status} cannot be advanced")
    to_status, pinned_role = ADVANCE_STAGES[status]
    if role != pinned_role:
        from errors import ERR_FORBIDDEN_ROLE
        raise ApiError(ERR_FORBIDDEN_ROLE, 403,
                       f"Stage {status} -> {to_status} is pinned to role {pinned_role}")
    b = body()
    _check_occ(project, b)

    # Retention-balance sufficiency (priority 16) evaluates before child-state
    # gates (priority 19) on retention-releasing advances (PRD §3.6).
    release_amount = None
    releasing_test = None
    if status in ("FAT", "SAT"):
        milestone = milestone_amount_for_phase(project, status)
        latest = _latest_test(project_id, status)
        if latest is not None and latest["verdict"] in ("PASS", "CONDITIONAL_PASS"):
            release_amount = latest["retention_released_cents"]
            releasing_test = latest
        else:
            release_amount = milestone
        if release_amount > project["retention_balance_cents"]:
            raise ApiError(
                ERR_RETENTION_BALANCE_MISMATCH, 422,
                "Computed milestone release exceeds current retention balance",
            )

    # Child-state gates (PRD §3.6).
    if status == "DRAFT":
        for s in children("studies", "cell_project_id", project_id):
            if s["status"] in ("DRAFT", "SUBMITTED"):
                _gate_fail("An application study in DRAFT or SUBMITTED exists")
    elif status == "STUDY":
        if not any(s["status"] == "APPROVED"
                   for s in children("studies", "cell_project_id", project_id)):
            _gate_fail("No APPROVED application study exists")
        if not any(a["status"] == "APPROVED"
                   for a in children("assessments", "cell_project_id", project_id)):
            _gate_fail("No APPROVED safety risk assessment exists")
    elif status == "DESIGN":
        if not any(s["selection_status"] == "LOCKED"
                   for s in children("selections", "cell_project_id", project_id)):
            _gate_fail("No LOCKED robot selection exists")
        if not any(p["dev_status"] == "RELEASED"
                   for p in children("programs", "cell_project_id", project_id)):
            _gate_fail("No RELEASED robot program exists")
    elif status == "BUILD":
        for p in children("programs", "cell_project_id", project_id):
            if not (p["dev_status"] == "RELEASED" and p["sim_status"] == "SIM_PASSED"):
                _gate_fail("Every robot program must be RELEASED with SIM_PASSED")
        approved = [a for a in children("assessments", "cell_project_id", project_id)
                    if a["status"] == "APPROVED"]
        if not approved:
            _gate_fail("No APPROVED safety risk assessment exists")
        latest_assessment = approved[-1]
        if calc.PL_RANK[latest_assessment["pl_achieved"]] < calc.PL_RANK[latest_assessment["pl_target"]]:
            _gate_fail("Approved assessment pl_achieved ranks below its pl_target")
    elif status in ("FAT", "SAT"):
        latest = _latest_test(project_id, status)
        if latest is None or latest["verdict"] not in ("PASS", "CONDITIONAL_PASS"):
            _gate_fail(f"Latest {status} acceptance test has no passing verdict")
    elif status == "SHIP":
        if not any(p["package_status"] in ("ORDERED", "DELIVERED")
                   for p in children("packages", "cell_project_id", project_id)):
            _gate_fail("No ORDERED or DELIVERED spare-parts package exists")
    elif status == "TRAINING":
        for s in children("sessions", "cell_project_id", project_id):
            threshold = 80 if s["audience"] == "OPERATOR" else 85
            if s["session_status"] != "COMPLETED" or s["completion_score_pct"] is None \
                    or calc.d(s["completion_score_pct"]) < calc.d(threshold):
                _gate_fail(
                    f"{s['audience']} training sessions must all be COMPLETED "
                    f"at or above their pass threshold")
        if not any(m["plan_status"] == "ACTIVE"
                   for m in children("plans", "cell_project_id", project_id)):
            _gate_fail("No ACTIVE maintenance plan exists")
        guarantee = guarantee_of_project(project_id)
        if guarantee is None or guarantee["guarantee_status"] != "MEASURING":
            _gate_fail("Throughput guarantee is not MEASURING")

    # Apply.
    project["status"] = to_status
    if status in ("FAT", "SAT") and releasing_test is not None:
        post_ledger_entry(project, "RELEASE", -release_amount, releasing_test["id"])
    if status == "SAT":
        init_guarantee(project)
    touch(project)
    return success(pub(project))


@bp.post("/robotics/cell-projects/<project_id>/hold")
def hold(project_id):
    authenticate({PE})
    project = get_project(project_id)
    if project["status"] in ("CLOSED", "TERMINATED", "ON_HOLD"):
        raise invalid_state(f"Project in status {project['status']} cannot be held")
    b = body()
    reason = as_str(req(b, "hold_reason"), "hold_reason")
    project["_prior_status"] = project["status"]
    project["status"] = "ON_HOLD"
    project["hold_reason"] = reason
    touch(project)
    return success(pub(project))


@bp.post("/robotics/cell-projects/<project_id>/resume")
def resume(project_id):
    authenticate({PE})
    project = get_project(project_id)
    if project["status"] != "ON_HOLD":
        raise invalid_state("Only an ON_HOLD project can be resumed")
    project["status"] = project["_prior_status"]
    project["_prior_status"] = None
    project["hold_reason"] = None
    touch(project)
    return success(pub(project))


@bp.post("/robotics/cell-projects/<project_id>/terminate")
def terminate(project_id):
    authenticate({FA})
    project = get_project(project_id)
    if project["status"] in ("CLOSED", "TERMINATED", "GUARANTEE"):
        raise invalid_state(f"Project in status {project['status']} cannot be terminated")
    # Clean-ledger requirement: a compensating PENALTY zeroes the balance atomically.
    if project["retention_balance_cents"] > 0:
        post_ledger_entry(project, "PENALTY", -project["retention_balance_cents"], "MANUAL")
    terminate_cascade(project)
    project["status"] = "TERMINATED"
    project["hold_reason"] = None
    project["_prior_status"] = None
    touch(project)
    return success(pub(project))
