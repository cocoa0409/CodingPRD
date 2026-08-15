"""AcceptanceTest endpoints and the rework cascade trigger (PRD §3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from db import children, store
from errors import invalid_state, not_found
from middleware import authenticate
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from middleware import ROLE_SERVICE_MANAGER as SM
from response import success, success_list
from services import calculations as calc
from services.domain import (common_fields, milestone_amount_for_phase, pub, pubs,
                             rework_cascade, touch)
from validation import as_enum, as_int, as_num, body, paginate, pagination, req

bp = Blueprint("tests", __name__)

READ_ROLES = {FA, PE, SS, SM}
PHASES = ("FAT", "SAT")


def get_test(test_id):
    t = store.tests.get(test_id)
    if t is None:
        raise not_found("Acceptance test not found")
    return t


def _derive_verdict(test, project):
    """PASS / CONDITIONAL_PASS / FAIL from stored measurements (PRD §3.6)."""
    contracted = calc.d(project["contracted_cycle_time_s"])
    guaranteed = calc.d(project["guaranteed_oee_pct"])
    mct = calc.d(test["measured_cycle_time_s"])
    moee = calc.d(test["measured_oee_pct"])
    defects = test["defects_observed"]
    pass_all = mct <= contracted and moee >= guaranteed and defects == 0
    if pass_all:
        return "PASS"
    conditional = (
        mct <= contracted * Decimal("1.02")
        and moee >= guaranteed - Decimal("2.0")
        and defects <= 3
    )
    return "CONDITIONAL_PASS" if conditional else "FAIL"


def _apply_verdict(test, project, verdict):
    milestone = milestone_amount_for_phase(project, test["phase"])
    if verdict == "PASS":
        test["retention_released_cents"] = milestone
    elif verdict == "CONDITIONAL_PASS":
        test["retention_released_cents"] = calc.conditional_half(milestone)
    else:
        test["retention_released_cents"] = 0
    test["verdict"] = verdict
    touch(test)
    # Failing a PENDING test triggers the FAT/SAT -> DESIGN rework cascade when
    # the project currently stands in the matching stage.
    if verdict == "FAIL" and project["status"] == test["phase"]:
        rework_cascade(project, test["phase"])
        touch(project)


@bp.post("/robotics/cell-projects/<project_id>/acceptance-tests")
def create_test(project_id):
    uid, _role = authenticate({SS})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    phase = as_enum(req(b, "phase"), "phase", PHASES)
    prior = [t for t in children("tests", "cell_project_id", project_id)
             if t["phase"] == phase]
    test = {
        **common_fields(),
        "cell_project_id": project_id,
        "phase": phase,
        "attempt": len(prior) + 1,
        "measured_cycle_time_s": as_num(req(b, "measured_cycle_time_s"), "measured_cycle_time_s"),
        "measured_oee_pct": as_num(req(b, "measured_oee_pct"), "measured_oee_pct"),
        "defects_observed": as_int(req(b, "defects_observed"), "defects_observed", min_v=0),
        "verdict": "PENDING",
        "retention_released_cents": None,
        "recorded_by_user_id": uid,
    }
    store.tests[test["id"]] = test
    return success(pub(test), 201)


@bp.get("/robotics/cell-projects/<project_id>/acceptance-tests")
def list_tests(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("tests", "cell_project_id", project_id)
    phase = request.args.get("phase")
    if phase is not None:
        items = [t for t in items if t["phase"] == phase]
    verdict = request.args.get("verdict")
    if verdict is not None:
        items = [t for t in items if t["verdict"] == verdict]
    recorder = request.args.get("recorded_by_user_id")
    if recorder is not None:
        items = [t for t in items if t["recorded_by_user_id"] == recorder]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/acceptance-tests/<test_id>")
def get_one_test(test_id):
    authenticate(READ_ROLES)
    return success(pub(get_test(test_id)))


@bp.post("/robotics/acceptance-tests/<test_id>/record")
def record_test(test_id):
    authenticate({SS})
    test = get_test(test_id)
    if test["verdict"] != "PENDING":
        raise invalid_state("Only a PENDING acceptance test can be recorded")
    project = store.projects[test["cell_project_id"]]
    _apply_verdict(test, project, _derive_verdict(test, project))
    return success(pub(test))


@bp.post("/robotics/acceptance-tests/<test_id>/fail")
def fail_test(test_id):
    authenticate({SS})
    test = get_test(test_id)
    if test["verdict"] != "PENDING":
        raise invalid_state("Only a PENDING acceptance test can be failed")
    project = store.projects[test["cell_project_id"]]
    _apply_verdict(test, project, "FAIL")
    return success(pub(test))
