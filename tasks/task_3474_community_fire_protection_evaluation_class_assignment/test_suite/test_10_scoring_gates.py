"""SCORING entry gates, the data window, and in-place draft recomputation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_cycle_to,
    attest_comms,
    create_community_bundle,
    create_cycle,
    create_score_sheet,
    get_cycle,
    get_success_data,
    make_fire_chief_headers,
    setup_scoring_cycle,
    submit_department_data,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]
ANALYST = TEST_USERS["field_analyst_headers"]


def test_scoring_gate_blocked_by_unattested_comms(api):
    """PRD §3.2: "Entering `SCORING` is gated on data completeness: no flow
    test of the community's water system may still sit in `SUBMITTED` or
    `WITNESSED`, the community's `comms_attested` must be true, and the
    department's `data_submitted` must be true; any shortfall is rejected
    with `ERR_CYCLE_DATA_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/scoring_gate_requires_cross_entity_data_completion
    """
    bundle = create_community_bundle(api, name="Gate A")
    community_id = bundle["community"]["id"]
    cycle = create_cycle(api, community_id)
    advance_cycle_to(api, cycle["id"], "DATA_COLLECTION")
    submit_department_data(api, bundle["department"]["id"], career_on_duty_per_shift=0)
    advance_cycle_to(api, cycle["id"], "FIELD_VERIFICATION")
    resp = api.transition_evaluation_cycle(cycle["id"], {"target_state": "SCORING"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_DATA_INCOMPLETE)
    attest_comms(api, community_id)
    resp2 = api.transition_evaluation_cycle(cycle["id"], {"target_state": "SCORING"}, COORD)
    entered = validate_success(resp2, 200)
    assert entered["status"] == "SCORING", "once the foreign entity is attested the gate opens"


def test_scoring_gate_blocked_by_pending_flow_test(api):
    """PRD §3.2: "no flow test of the community's water system may still sit
    in `SUBMITTED` or `WITNESSED`" — a test still SUBMITTED holds the cycle
    in FIELD_VERIFICATION even with comms and department data complete.

    Design: Difficulty/cross_entity_state_dependency/scoring_gate_requires_cross_entity_data_completion
    """
    ctx = setup_scoring_cycle(
        api, name="Gate B", target_state="FIELD_VERIFICATION",
        hydrant_count=1, flow_tests=[{"measured_flow_gpm": 1000}],
    )
    cycle_id = ctx["cycle"]["id"]
    resp = api.transition_evaluation_cycle(cycle_id, {"target_state": "SCORING"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CYCLE_DATA_INCOMPLETE)
    assert get_cycle(api, cycle_id)["status"] == "FIELD_VERIFICATION"


def test_department_patch_without_window_returns_data_window_closed(api):
    """PRD §2.8: "A community's **data window** is open whenever its
    non-terminal cycle is in `DATA_COLLECTION`, `FIELD_VERIFICATION`, or
    `SCORING`; a data-changing request that arrives while the window is
    closed is rejected with `ERR_DATA_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/errors/department_patch_without_window_returns_data_window_closed
    """
    bundle = create_community_bundle(api, name="NoWindow")
    department_id = bundle["department"]["id"]
    resp = api.patch_fire_department(
        department_id, {"career_on_duty_per_shift": 4}, make_fire_chief_headers(department_id)
    )
    validate_error(resp, ApiErrorId.ERR_DATA_WINDOW_CLOSED)


def test_scoring_to_review_without_final_sheet_returns_no_final(api):
    """PRD §3.2: "From `SCORING` the cycle enters `CLASSIFICATION_REVIEW`
    only once a `FINAL` score sheet exists for it, else
    `ERR_NO_FINAL_SCORE_SHEET` (HTTP 422)."

    Design: Corner/errors/scoring_to_review_without_final_sheet_returns_no_final
    """
    ctx = setup_scoring_cycle(api, name="DraftOnly")
    create_score_sheet(api, ctx["cycle"]["id"])
    resp = api.transition_evaluation_cycle(
        ctx["cycle"]["id"], {"target_state": "CLASSIFICATION_REVIEW"}, COORD
    )
    validate_error(resp, ApiErrorId.ERR_NO_FINAL_SCORE_SHEET)
    assert get_cycle(api, ctx["cycle"]["id"])["status"] == "SCORING"


def test_draft_sheet_recompute_on_reattestation(api):
    """PRD §2.8: "Whenever a scored input changes while the community's cycle
    is in `SCORING`, the cycle's `DRAFT` score sheet is recomputed in place
    so the draft always reflects the latest accepted data (§3.6)."

    Design: Corner/complexity_layers/draft_sheet_recompute_on_reattestation
    """
    ctx = setup_scoring_cycle(api, name="Recompute")
    sheet = create_score_sheet(api, ctx["cycle"]["id"])
    assert sheet["comms_points"] == 0, "unattested-style zeros score no communications credit"
    attest_comms(api, ctx["community"]["id"], operators_on_duty_min=2)
    recomputed = get_success_data(api.get_score_sheet(sheet["id"], ANALYST))
    assert recomputed["status"] == "DRAFT", "the same sheet is recomputed in place"
    assert recomputed["comms_points"] == 4
