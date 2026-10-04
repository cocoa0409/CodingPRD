"""Formulas, formula lifecycle transitions, and safety tests (PRD section 3.3)."""
from flask import request

from constants import (
    OPS_ROLES, ROLE_FORMULATOR, ROLE_LAB_TECHNICIAN, ROLE_SAFETY_OFFICER,
)
from envelope import ok, paginate
from errors import ApiError
from store import STORE
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, opt_str,
    pagination_params, req_enum, req_str, require_role, touch,
)

FORMULA_ACTION_STATES = {
    "SUBMIT": ("DRAFT", "REVISION_REQUESTED"),
    "APPROVE": ("SUBMITTED",),
    "REJECT": ("SUBMITTED",),
    "REQUEST_REVISION": ("SUBMITTED",),
}
DECIDER_ACTIONS = ("APPROVE", "REJECT", "REQUEST_REVISION")


def serialize_formula(f):
    return {
        "id": f["id"],
        "color_id": f["color_id"],
        "intended_use": f["intended_use"],
        "pigment_recipe": f["pigment_recipe"],
        "status": f["status"],
        "submitted_by_user_id": f["submitted_by_user_id"],
        "approved_by_user_id": f["approved_by_user_id"],
        "licensed_use_count": f["licensed_use_count"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_safety_test(t):
    return {
        "id": t["id"],
        "formula_id": t["formula_id"],
        "test_standard": t["test_standard"],
        "test_seq": t["test_seq"],
        "status": t["status"],
        "result_notes": t["result_notes"],
        "recorded_by_user_id": t["recorded_by_user_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def create_formula():
    _, role = auth()
    require_role(role, {ROLE_FORMULATOR, ROLE_SAFETY_OFFICER})
    data = body()
    color_id = req_str(data, "color_id")
    intended_use = req_enum(data, "intended_use", ("CRAYON", "MARKER", "COLORED_PENCIL"))
    recipe = data.get("pigment_recipe")
    if not isinstance(recipe, list) or len(recipe) == 0:
        raise ApiError("ERR_INVALID_REQUEST", "pigment_recipe must be a non-empty array")
    get_or_404(STORE.colors, color_id)
    formula = new_entity({
        "color_id": color_id,
        "intended_use": intended_use,
        "pigment_recipe": recipe,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "licensed_use_count": 0,
    })
    STORE.formulas[formula["id"]] = formula
    return ok(serialize_formula(formula), status=201)


def get_formula(formula_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    formula = get_or_404(STORE.formulas, formula_id)
    return ok(serialize_formula(formula))


def _spawn_safety_test(formula):
    test = new_entity({
        "formula_id": formula["id"],
        "test_standard": "ASTM_D4236",
        "test_seq": STORE.next_scoped(STORE.test_seq, formula["id"]),
        "status": "SCHEDULED",
        "result_notes": None,
        "recorded_by_user_id": None,
    })
    STORE.safety_tests[test["id"]] = test
    return test


def _latest_test(formula_id):
    tests = [t for t in STORE.safety_tests.values() if t["formula_id"] == formula_id]
    if not tests:
        return None
    tests.sort(key=lambda t: (t["created_at"], t["test_seq"]))
    return tests[-1]


def formula_transition(formula_id):
    user_id, role = auth()
    require_role(role, {ROLE_FORMULATOR, ROLE_SAFETY_OFFICER})
    data = body()
    action = req_enum(data, "action",
                      ("SUBMIT", "APPROVE", "REJECT", "REQUEST_REVISION"))
    opt_str(data, "reason")
    formula = get_or_404(STORE.formulas, formula_id)
    # Action-level authorization: decider actions are SafetyOfficer-only.
    if action in DECIDER_ACTIONS and role != ROLE_SAFETY_OFFICER:
        raise ApiError("ERR_UNAUTHORIZED")
    # State gate (stage 6).
    if formula["status"] not in FORMULA_ACTION_STATES[action]:
        raise ApiError("ERR_INVALID_FORMULA_STATE")
    # Segregation of duties (stage 7): decider must not be the submitter.
    if action in DECIDER_ACTIONS and user_id == formula["submitted_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    if action == "SUBMIT":
        formula["status"] = "SUBMITTED"
        formula["submitted_by_user_id"] = user_id
        touch(formula)
        _spawn_safety_test(formula)
    elif action == "APPROVE":
        # Linked-entity gate (stage 10): latest safety test must be PASSED.
        latest = _latest_test(formula_id)
        if latest is None or latest["status"] != "PASSED":
            raise ApiError("ERR_FORMULA_NOT_APPROVABLE")
        formula["status"] = "APPROVED"
        formula["approved_by_user_id"] = user_id
        touch(formula)
        # Cascade: other APPROVED formulas of the same color -> SUPERSEDED;
        # their APPROVED licensed lines -> SUSPENDED.
        for other in STORE.formulas.values():
            if (other["id"] != formula["id"]
                    and other["color_id"] == formula["color_id"]
                    and other["status"] == "APPROVED"):
                other["status"] = "SUPERSEDED"
                touch(other)
                for line in STORE.lines.values():
                    if line["formula_id"] == other["id"] and line["status"] == "APPROVED":
                        line["status"] = "SUSPENDED"
                        touch(line)
    elif action == "REJECT":
        formula["status"] = "REJECTED"
        touch(formula)
    else:  # REQUEST_REVISION
        formula["status"] = "REVISION_REQUESTED"
        touch(formula)
    return ok(serialize_formula(formula))


def list_safety_tests(formula_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.formulas, formula_id)
    limit, offset = pagination_params()
    items = [t for t in STORE.safety_tests.values() if t["formula_id"] == formula_id]
    items = apply_filters(items, [("status", request.args.get("status"))])
    items.sort(key=lambda t: (t["created_at"], t["test_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_safety_test(t) for t in page], response_type="array", pagination=meta)


def list_formula_licensed_lines(formula_id):
    from licensed import serialize_line
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.formulas, formula_id)
    limit, offset = pagination_params()
    items = [l for l in STORE.lines.values() if l["formula_id"] == formula_id]
    items = apply_filters(items, [("status", request.args.get("status"))])
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_line(l) for l in page], response_type="array", pagination=meta)


def record_result(test_id):
    user_id, role = auth()
    require_role(role, {ROLE_LAB_TECHNICIAN})
    data = body()
    outcome = req_enum(data, "outcome", ("PASS", "FAIL"))
    result_notes = opt_str(data, "result_notes")
    test = get_or_404(STORE.safety_tests, test_id)
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_REQUEST", "safety test is no longer SCHEDULED")
    test["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    test["result_notes"] = result_notes
    test["recorded_by_user_id"] = user_id
    touch(test)
    return ok(serialize_safety_test(test))


def register(app):
    app.add_url_rule("/crayon-works/formulas", view_func=create_formula, methods=["POST"])
    app.add_url_rule("/crayon-works/formulas/<formula_id>", view_func=get_formula, methods=["GET"])
    app.add_url_rule("/crayon-works/formulas/<formula_id>/transition",
                     view_func=formula_transition, methods=["POST"])
    app.add_url_rule("/crayon-works/formulas/<formula_id>/safety-tests",
                     view_func=list_safety_tests, methods=["GET"])
    app.add_url_rule("/crayon-works/formulas/<formula_id>/licensed-lines",
                     view_func=list_formula_licensed_lines, methods=["GET"])
    app.add_url_rule("/crayon-works/safety-tests/<test_id>/record-result",
                     view_func=record_result, methods=["POST"])
