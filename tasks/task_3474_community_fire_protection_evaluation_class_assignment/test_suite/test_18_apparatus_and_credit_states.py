"""Terminal and asymmetric states: apparatus exits, rejected tests and credits."""
from test_helpers import (
    ApiErrorId,
    make_field_analyst_headers,
    make_fire_chief_headers,
    setup_scoring_cycle,
    validate_error,
    validate_success,
)


def test_apparatus_out_of_service_exit_paths(api):
    """PRD §3.3: "from `OUT_OF_SERVICE` it may return only to `RESERVE`.
    Returning a unit directly from `OUT_OF_SERVICE` to `FRONTLINE` is
    deliberately forbidden — the unit must pass through the `RESERVE`
    inspection state first — and is rejected with
    `ERR_APPARATUS_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/apparatus_out_of_service_exit_paths
    """
    ctx = setup_scoring_cycle(
        api, name="Apparatus City", target_state="DATA_COLLECTION",
        apparatus=[{"kind": "ENGINE", "pump_capacity_gpm": 1500, "status": "OUT_OF_SERVICE"}],
    )
    department_id = ctx["department"]["id"]
    apparatus_id = ctx["apparatus"][0]["id"]
    headers = make_fire_chief_headers(department_id)
    resp = api.patch_apparatus(apparatus_id, {"status": "FRONTLINE"}, headers)
    validate_error(resp, ApiErrorId.ERR_APPARATUS_INVALID_STATE)
    ok = api.patch_apparatus(apparatus_id, {"status": "RESERVE"}, headers)
    assert validate_success(ok, 200)["status"] == "RESERVE"


def test_flow_test_rejected_terminal_lockdown(api):
    """PRD §3.4: "then either certifies it (`WITNESSED` → `CERTIFIED`) or
    rejects it (`WITNESSED` → `REJECTED`); any other transition, or one
    outside its window, is rejected with `ERR_FLOW_TEST_INVALID_STATE` or
    `ERR_DATA_WINDOW_CLOSED` respectively."

    Design: Corner/state_machines/flow_test_rejected_terminal_lockdown
    """
    ctx = setup_scoring_cycle(
        api, name="Reject Falls", target_state="FIELD_VERIFICATION",
        hydrant_count=1, flow_tests=[{"outcome": "rejected"}],
    )
    test_id = ctx["flow_tests"][0]["id"]
    resp = api.transition_flow_test(
        test_id, {"target_state": "CERTIFIED"}, make_field_analyst_headers()
    )
    validate_error(resp, ApiErrorId.ERR_FLOW_TEST_INVALID_STATE)


def test_credit_transition_after_reject_returns_invalid_state(api):
    """PRD §3.5: "Rejecting a pending credit (`PENDING` → `REJECTED`) zeroes
    its `credited_points`, and `REJECTED` is terminal." and "Any transition
    outside this graph is rejected with `ERR_CREDIT_INVALID_STATE`".

    Design: Corner/errors/credit_transition_after_reject_returns_invalid_state
    """
    ctx = setup_scoring_cycle(
        api, name="CreditLock", target_state="FIELD_VERIFICATION",
        credits=[{"program_type": "FIRE_INVESTIGATION", "activity_points": 1.0,
                  "evidence_note": "case file", "outcome": "rejected"}],
    )
    credit_id = ctx["credits"][0]["id"]
    resp = api.transition_risk_reduction_credit(
        credit_id, {"target_state": "VERIFIED"}, make_field_analyst_headers()
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_INVALID_STATE)
