"""Formulas and their safety tests: lifecycle, approval gates, supersession."""
import test_helpers.fixtures as fx
from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    assert_formula, NON_EXISTENT_UUID, make_formulator_headers,
)

ADMIN = fx.ADMIN
FORMULATOR = fx.FORMULATOR
SAFETY = fx.SAFETY
LAB = fx.LAB


def test_formula_created_in_draft_initial_state(api):
    """PRD section 3.3: "A new formula starts in `DRAFT` with
    `licensed_use_count` at 0." and PRD section 2.5: "`version` (integer):
    starts at 1 when the resource is created".

    Design: Corner/state_machines/formula_created_in_draft_initial_state
    """
    fx.reset_clock()
    color = fx.create_color()
    resp = api_client.create_formula(
        {"color_id": color["id"], "intended_use": "CRAYON",
         "pigment_recipe": [{"pigment_name": "Phthalo Blue", "parts": 3}]},
        FORMULATOR)
    data = validate_success(resp, 201)
    assert_formula(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["licensed_use_count"] == 0
    assert data["submitted_by_user_id"] is None
    assert data["approved_by_user_id"] is None
    assert get_success_data(api_client.list_safety_tests(data["id"], SAFETY)) == []


def test_formula_get_with_unknown_id_returns_not_found(api):
    """PRD section 2.8 stage 4: "Path identifiers must exist first; then body
    foreign keys are checked in the endpoint's declared input order, left
    to right. The first missing reference yields `ERR_NOT_FOUND` (HTTP
    404)." PRD section 2.2: the
    error envelope carries `error_id` and `message` under `data`.

    Design: Corner/entities/formula_get_with_unknown_id_returns_not_found
    """
    fx.reset_clock()
    resp = api_client.get_formula(NON_EXISTENT_UUID, SAFETY)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_formula_create_missing_required_recipe_returns_invalid_request(api):
    """PRD section 3.3: "a `pigment_recipe` — an opaque list of recipe lines,
    each naming a pigment and its parts — which must be a non-empty array".
    PRD section 2.8: "The stages are evaluated in the order below, the first
    failure wins" — body shape (stage 3) precedes existence (stage 4).

    Design: Corner/entities/formula_create_missing_required_recipe_returns_invalid_request
    """
    fx.reset_clock()
    color = fx.create_color()
    resp = api_client.create_formula(
        {"color_id": NON_EXISTENT_UUID, "intended_use": "CRAYON"}, FORMULATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    assert resp.json()["data"]["error_id"] != "ERR_NOT_FOUND"
    assert get_success_data(
        api_client.list_color_formulas(color["id"], FORMULATOR)) == []


def test_formula_submit_creates_scheduled_safety_test(api):
    """PRD section 3.3: "From `DRAFT`, or from `REVISION_REQUESTED` on a
    resubmission, the formula moves to `SUBMITTED`; the submitter's `X-User-ID`
    is recorded as `submitted_by_user_id`, and a new **safety test** is created
    in `SCHEDULED` for the formula, because safety certification is mandatory
    before approval." PRD section 3.3: "It carries the `test_standard` applied —
    `ASTM_D4236` by default, or `EN71_3`".

    Design: Corner/state_machines/formula_submit_creates_scheduled_safety_test
    """
    fx.reset_clock()
    color = fx.create_color()
    formula = fx.create_formula(color["id"])
    submitted = fx.submit_formula(formula["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "f-1"
    tests = fx.list_safety_tests(formula["id"])
    assert len(tests) == 1
    assert tests[0]["status"] == "SCHEDULED"
    assert tests[0]["test_standard"] == "ASTM_D4236"
    assert tests[0]["recorded_by_user_id"] is None
    assert tests[0]["formula_id"] == formula["id"]


def test_formula_approve_from_draft_is_rejected(api):
    """PRD section 3.3: "Any transition attempted from a state that does not
    permit it is rejected with `ERR_INVALID_FORMULA_STATE` (HTTP 409)."

    Design: Corner/state_machines/formula_approve_from_draft_is_rejected
    """
    fx.reset_clock()
    color = fx.create_color()
    formula = fx.create_formula(color["id"])
    resp = api_client.formula_transition(formula["id"], {"action": "APPROVE"}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_INVALID_FORMULA_STATE)
    assert resp.status_code == 409
    assert fx.get_formula(formula["id"])["status"] == "DRAFT"
    assert fx.list_safety_tests(formula["id"]) == []


def test_superseded_formula_is_terminal(api):
    """PRD section 3.3: "Its `status` enumeration is `DRAFT`, `SUBMITTED`,
    `REVISION_REQUESTED`, `APPROVED`, `REJECTED`, `SUPERSEDED`, with `REJECTED`
    and `SUPERSEDED` terminal." and "Any transition attempted from a state that
    does not permit it is rejected with `ERR_INVALID_FORMULA_STATE` (HTTP 409)."

    Design: Corner/state_machines/superseded_formula_is_terminal
    """
    fx.reset_clock()
    color = fx.make_active_color()
    f1 = fx.create_approved_formula(color["id"])
    f2 = fx.create_approved_formula(
        color["id"], intended_use="MARKER",
        pigment_recipe=[{"pigment_name": "Quinacridone", "parts": 1}])
    assert fx.get_formula(f1["id"])["status"] == "SUPERSEDED"
    resp = api_client.formula_transition(f1["id"], {"action": "SUBMIT"}, FORMULATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_FORMULA_STATE)
    assert fx.get_formula(f1["id"])["status"] == "SUPERSEDED"
    formulas = get_success_data(api_client.list_color_formulas(color["id"], FORMULATOR))
    assert len(formulas) == 2  # superseded formulas stay queryable


def test_formulas_subresource_filters_by_status(api):
    """PRD section 3.1: "its formulas can be listed with an optional `status`
    filter".

    Design: Corner/endpoints/formulas_subresource_filters_by_status
    """
    fx.reset_clock()
    color = fx.create_color()
    f1 = fx.create_formula(color["id"])
    f2 = fx.create_formula(color["id"], intended_use="MARKER",
                           pigment_recipe=[{"pigment_name": "Quinacridone", "parts": 1}])
    fx.submit_formula(f2["id"])
    filtered = get_success_data(
        api_client.list_color_formulas(color["id"], FORMULATOR, params={"status": "DRAFT"}))
    assert len(filtered) == 1
    assert filtered[0]["id"] == f1["id"]
    unfiltered = get_success_data(api_client.list_color_formulas(color["id"], FORMULATOR))
    assert len(unfiltered) == 2


def test_formulator_cannot_approve_formula(api):
    """PRD section 3.3: "Approval is a `SafetyOfficer` decision". PRD section
    2.1: "A request whose role is declared but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)". A Formulator (a
    role that may only create and submit) calling APPROVE is refused.

    Design: Corner/rbac/formulator_cannot_approve_formula
    """
    fx.reset_clock()
    color = fx.create_color()
    formula = fx.create_formula(color["id"])
    fx.submit_formula(formula["id"])
    fx.pass_latest_safety_test(formula["id"])
    resp = api_client.formula_transition(
        formula["id"], {"action": "APPROVE"}, make_formulator_headers("f-2"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    assert fx.get_formula(formula["id"])["status"] == "SUBMITTED"


def test_formula_approve_rejected_while_latest_test_failed(api):
    """PRD section 3.3: "An `APPROVE` on a `SUBMITTED` formula additionally
    requires that the formula's latest safety test — the last test in the
    creation-time and `test_seq` ordering — is `PASSED`; otherwise the decision
    is rejected with `ERR_FORMULA_NOT_APPROVABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/formula_approval_requires_latest_safety_test_passed
    """
    fx.reset_clock()
    color = fx.make_active_color()
    formula = fx.create_formula(color["id"])
    fx.submit_formula(formula["id"])
    tests = fx.list_safety_tests(formula["id"])
    fx.record_test_result(tests[0]["id"], "FAIL", "heavy metal trace")
    resp = api_client.formula_transition(formula["id"], {"action": "APPROVE"}, SAFETY)
    validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_APPROVABLE)
    assert resp.status_code == 409
    assert fx.get_formula(formula["id"])["status"] == "SUBMITTED"


def test_formula_resubmission_new_test_pass_then_approve_succeeds(api):
    """PRD section 3.3: "Resubmission always spawns a fresh test; older test
    results remain on their own rows as history." and "A failed test blocks
    formula approval until a later test for the same formula has passed."

    Design: Difficulty/cross_entity_state_dependency/formula_approval_requires_latest_safety_test_passed
    """
    fx.reset_clock()
    color = fx.make_active_color()
    formula = fx.create_formula(color["id"])
    fx.submit_formula(formula["id"])
    first = fx.list_safety_tests(formula["id"])
    fx.record_test_result(first[0]["id"], "FAIL", "heavy metal trace")
    api_client.formula_transition(
        formula["id"], {"action": "REQUEST_REVISION", "reason": "remediate and resubmit"}, SAFETY)
    fx.submit_formula(formula["id"])
    tests = fx.list_safety_tests(formula["id"])
    assert len(tests) == 2
    fx.record_test_result(tests[1]["id"], "PASS", "remediated")
    resp = api_client.formula_transition(formula["id"], {"action": "APPROVE"}, SAFETY)
    data = validate_success(resp, 200)
    assert data["status"] == "APPROVED"
    final_tests = fx.list_safety_tests(formula["id"])
    assert final_tests[0]["status"] == "FAILED"
    assert final_tests[1]["status"] == "PASSED"


def test_formula_approval_supersedes_other_approved_and_suspends_line(api):
    """PRD section 3.3: "On approval the formula becomes `APPROVED`,
    `approved_by_user_id` records the approver, and two cascades fire: every other `APPROVED` formula for the same color becomes
    `SUPERSEDED`, and every `APPROVED` licensed line whose `formula_id` is one
    of those newly superseded formulas becomes `SUSPENDED`".

    Design: Difficulty/transitive_cascade/formula_approval_supersedes_and_suspends_lines
    """
    fx.reset_clock()
    color = fx.make_active_color()
    f1 = fx.create_approved_formula(color["id"])
    line = fx.create_approved_licensed_line(f1["id"])
    f2 = fx.create_approved_formula(
        color["id"],
        pigment_recipe=[{"pigment_name": "Phthalo Blue", "parts": 2},
                        {"pigment_name": "Quinacridone", "parts": 1}])
    assert fx.get_formula(f2["id"])["status"] == "APPROVED"
    assert fx.get_formula(f1["id"])["status"] == "SUPERSEDED"
    assert fx.get_line(line["id"])["status"] == "SUSPENDED"


def test_reinstate_with_stale_pin_returns_error_after_supersede(api):
    """PRD section 3.6: "a stale pin or a non-approved formula is rejected with
    `ERR_STALE_PIN` (HTTP 409)" — the superseded formula's version advanced past
    the pin, so reinstatement of the suspended line is refused.

    Design: Difficulty/transitive_cascade/formula_approval_supersedes_and_suspends_lines
    """
    fx.reset_clock()
    color = fx.make_active_color()
    f1 = fx.create_approved_formula(color["id"])
    line = fx.create_approved_licensed_line(f1["id"])
    assert line["pinned_formula_version"] == 4
    fx.create_approved_formula(
        color["id"],
        pigment_recipe=[{"pigment_name": "Phthalo Blue", "parts": 2},
                        {"pigment_name": "Quinacridone", "parts": 1}])
    f1_now = fx.get_formula(f1["id"])
    assert f1_now["version"] == 5  # supersede mutated the formula
    assert f1_now["version"] != line["pinned_formula_version"]
    resp = api_client.licensed_line_transition(
        line["id"], {"action": "REINSTATE", "expected_formula_version": f1_now["version"]},
        fx.BRAND)
    validate_error(resp, ApiErrorId.ERR_STALE_PIN)
    assert resp.status_code == 409
