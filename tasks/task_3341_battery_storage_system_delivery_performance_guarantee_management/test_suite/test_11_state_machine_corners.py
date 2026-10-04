"""State machine corner tests: terminal-state lockdowns, outcome/date
agreement, completion preconditions, test-window gating, augmentation gating,
commissioning gate, rejected-claim finality, bid-session settle gating."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bid_session,
    create_claim_under_review,
    create_manual_augmentation,
    create_milestone,
    get_success_data,
    record_milestone_outcome,
    schedule_performance_test,
    set_clock,
    setup_executed_project,
    setup_commissioned_project,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
SVC_ENG = TEST_USERS["service_engineer_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]
MARKET = TEST_USERS["market_operator_headers"]


def test_milestone_second_record_outcome_rejected_from_terminal(api):
    """PRD §3.3: "Recording the outcome of a milestone takes an `outcome` of
    `ACHIEVED` or `MISSED` and the `actual_date`. The milestone must still be
    `SCHEDULED` (`ERR_MILESTONE_NOT_SCHEDULED`)"

    Design: Corner/state_machines/milestone_second_record_outcome_rejected_from_terminal
    """
    _, esa = setup_executed_project(api=api)
    m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
    first = record_milestone_outcome(m1["id"], "ACHIEVED", "2026-09-30T00:00:00Z", api=api)
    assert first["status"] == "ACHIEVED"
    assert first["ld_applied_cents"] == 0

    resp = api.record_milestone_outcome(
        m1["id"], {"outcome": "MISSED", "actual_date": "2026-10-21T00:00:00Z"}, DEV
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_SCHEDULED)
    after = get_success_data(api.get_milestone(m1["id"], DEV))
    assert after["status"] == "ACHIEVED"
    assert after["ld_applied_cents"] == 0


def test_milestone_outcome_kind_must_match_date_ordering(api):
    """PRD §3.3: "the outcome must agree with the calendar: `ACHIEVED` requires
    the actual date to fall on or before the planned date, and `MISSED`
    requires it to fall strictly after; a disagreement is
    `ERR_MILESTONE_OUTCOME_MISMATCH`."

    Design: Corner/state_machines/milestone_outcome_kind_must_match_date_ordering
    """
    _, esa = setup_executed_project(api=api)
    m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
    m2 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)

    # ACHIEVED with a late actual_date
    resp = api.record_milestone_outcome(
        m1["id"], {"outcome": "ACHIEVED", "actual_date": "2026-10-05T00:00:00Z"}, DEV
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OUTCOME_MISMATCH)

    # MISSED with actual_date == planned_date (<= boundary)
    resp = api.record_milestone_outcome(
        m2["id"], {"outcome": "MISSED", "actual_date": "2026-10-01T00:00:00Z"}, DEV
    )
    validate_error(resp, ApiErrorId.ERR_MILESTONE_OUTCOME_MISMATCH)

    assert get_success_data(api.get_milestone(m1["id"], DEV))["status"] == "SCHEDULED"
    assert get_success_data(api.get_milestone(m2["id"], DEV))["status"] == "SCHEDULED"


def test_esa_complete_requires_delivery_achieved_and_commissioning_achieved(api):
    """PRD §3.3: "Completion of the agreement closes the commercial phase:
    every `DELIVERY` milestone must be `ACHIEVED` or `CANCELLED` (otherwise
    `ERR_DELIVERY_MILESTONES_OPEN`), and at least one `COMMISSIONING` milestone
    must be `ACHIEVED` (otherwise `ERR_NO_COMMISSIONING_ACHIEVED`)"
    PRD §3.3: "On completion the project's `commissioned_capacity_mwh` is
    reconciled to the agreement's `contracted_energy_mwh`, matching what the
    first commissioning achievement set earlier."

    Design: Corner/state_machines/esa_complete_requires_delivery_achieved_and_commissioning_achieved
    """
    project, esa = setup_executed_project(api=api)
    delivery = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
    commissioning = create_milestone(
        esa["id"], "COMMISSIONING", "2026-11-01T00:00:00Z", api=api
    )

    resp = api.complete_esa(esa["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_MILESTONES_OPEN)

    record_milestone_outcome(delivery["id"], "ACHIEVED", "2026-10-01T00:00:00Z", api=api)
    resp = api.complete_esa(esa["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_NO_COMMISSIONING_ACHIEVED)

    record_milestone_outcome(
        commissioning["id"], "ACHIEVED", "2026-10-20T00:00:00Z", api=api
    )
    completed = validate_success(api.complete_esa(esa["id"], DEV))
    assert completed["status"] == "COMPLETED"
    project_after = get_success_data(api.get_project(project["id"], DEV))
    assert project_after["commissioned_capacity_mwh"] == pytest.approx(40, abs=0.001)


def test_record_results_outside_window_rejected(api):
    """PRD §3.4: "Results are recorded inside the window — the logical clock
    must read at or after `window_start` and strictly before `window_end`,
    else `ERR_TEST_WINDOW_NOT_OPEN`, and the test must still be `SCHEDULED`."

    Design: Corner/state_machines/test_record_results_outside_window_rejected
    """
    project, _ = setup_executed_project(api=api)
    test = schedule_performance_test(
        project["id"], "CAPACITY_TEST",
        "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z", api=api,
    )
    # Default clock 2026-09-01 is before the window.
    resp = api.record_test_results(
        test["id"], {"measured_capacity_mwh": 39, "aux_load_mwh": 0.5}, PERF
    )
    validate_error(resp, ApiErrorId.ERR_TEST_WINDOW_NOT_OPEN)

    # Exactly at window_end (exclusive end) is also rejected.
    set_clock("2026-09-20T00:00:00Z", api=api)
    resp = api.record_test_results(
        test["id"], {"measured_capacity_mwh": 39, "aux_load_mwh": 0.5}, PERF
    )
    validate_error(resp, ApiErrorId.ERR_TEST_WINDOW_NOT_OPEN)

    after = get_success_data(api.get_performance_test(test["id"], PERF))
    assert after["status"] == "SCHEDULED"


def test_augmentation_execute_outside_window_and_wrong_state(api):
    """PRD §3.5: "Executing a planned event requires the logical clock inside
    its half-open window — at or after `planned_window_start` and strictly
    before `planned_window_end`, else `ERR_AUGMENTATION_WINDOW_NOT_OPEN` — and
    the event still `PLANNED`, else `ERR_AUGMENTATION_NOT_PLANNED`."

    Design: Corner/state_machines/augmentation_execute_outside_window_and_wrong_state
    """
    project, esa = setup_commissioned_project(api=api)
    aug = create_manual_augmentation(
        project["id"], api=api,
        planned_window_start="2026-10-01T00:00:00Z",
        planned_window_end="2026-11-01T00:00:00Z",
        added_capacity_mwh=2,
    )
    # Default clock 2026-09-01 is before the window.
    version = get_success_data(api.get_project(project["id"], DEV))["version"]
    resp = api.execute_augmentation(
        aug["id"], {"expected_project_version": version}, SVC_ENG
    )
    validate_error(resp, ApiErrorId.ERR_AUGMENTATION_WINDOW_NOT_OPEN)

    set_clock("2026-10-15T00:00:00Z", api=api)
    version = get_success_data(api.get_project(project["id"], DEV))["version"]
    executed = validate_success(
        api.execute_augmentation(
            aug["id"], {"expected_project_version": version}, SVC_ENG
        )
    )
    assert executed["status"] == "EXECUTED"

    # Re-executing an EXECUTED event -> state error. A successful execution
    # increments the project's version (PRD §3.5), so re-read it; with the
    # current version supplied the OCC check (§2.8 step 4) passes and the
    # state check (§2.8 step 5) fires.
    version = get_success_data(api.get_project(project["id"], DEV))["version"]
    resp = api.execute_augmentation(
        aug["id"], {"expected_project_version": version}, SVC_ENG
    )
    validate_error(resp, ApiErrorId.ERR_AUGMENTATION_NOT_PLANNED)


def test_manual_augmentation_requires_commissioned_project(api):
    """PRD §3.5: "Manual planning requires the project to be commissioned,
    meaning `commissioned_capacity_mwh` greater than zero, else
    `ERR_PROJECT_NOT_COMMISSIONED`"

    Design: Corner/state_machines/manual_augmentation_requires_commissioned_project
    """
    project, _ = setup_executed_project(api=api)
    resp = api.create_augmentation(
        {
            "project_id": project["id"],
            "planned_window_start": "2026-10-01T00:00:00Z",
            "planned_window_end": "2026-11-01T00:00:00Z",
            "added_capacity_mwh": 2,
        },
        SVC_ENG,
    )
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_COMMISSIONED)
    current = get_success_data(api.get_project(project["id"], DEV))
    assert current["commissioned_capacity_mwh"] == 0


def test_claim_decide_rejected_variant_leaves_credit_null(api):
    """PRD §3.7: "Rejection stamps `decided_at` the same way and leaves
    `credit_amount_cents` null."
    PRD §3.7: "The administrator decides an `UNDER_REVIEW` claim — any other
    state is `ERR_CLAIM_NOT_UNDER_REVIEW`"

    Design: Corner/state_machines/claim_decide_rejected_variant_leaves_credit_null
    """
    _, esa = setup_executed_project(api=api)
    claim = create_claim_under_review(
        esa["id"], api=api, defect_type="RTE_SHORTFALL",
        claimed_capacity_loss_mwh=1.5,
    )
    rejected = validate_success(
        api.decide_claim(claim["id"], {"decision": "REJECTED"}, WARRANTY)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["credit_amount_cents"] is None
    assert rejected["decided_at"] is not None

    resp = api.decide_claim(
        claim["id"],
        {"decision": "APPROVED", "credit_variant": "STRAIGHT_LINE"},
        WARRANTY,
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_UNDER_REVIEW)


def test_bid_session_settle_requires_cleared_state(api):
    """PRD §3.8: "settling requires `CLEARED`, else
    `ERR_BID_SESSION_NOT_CLEARED`"
    PRD §3.8: "if the clearing price is below the offer floor, `cleared_mwh` is
    zero even when capacity would allow the full offer; otherwise `cleared_mwh`
    is the smaller of `offer_mwh` and a capacity cap that is itself the smaller
    of the project's current `projected_capacity_mwh` and
    `market_cleared_mwh`, rounded half up to 2 decimal places."

    Design: Corner/state_machines/bid_session_settle_requires_cleared_state
    """
    project, _ = setup_executed_project(api=api)
    session = create_bid_session(project["id"], api=api)

    resp = api.settle_bid_session(session["id"], MARKET)
    validate_error(resp, ApiErrorId.ERR_BID_SESSION_NOT_CLEARED)

    cleared = validate_success(
        api.record_bid_clearing(
            session["id"],
            {"clearing_price_cents_per_mwh": 12000, "market_cleared_mwh": 15},
            MARKET,
        )
    )
    # Project was never commissioned -> projected_capacity_mwh == 0 ->
    # capacity cap 0 -> cleared 0.
    assert cleared["cleared_mwh"] == 0, (
        f"projected 0 caps the clearing, got {cleared['cleared_mwh']}"
    )
    settled = validate_success(api.settle_bid_session(session["id"], MARKET))
    assert settled["status"] == "SETTLED"
    assert settled["revenue_cents"] == 0

    resp = api.settle_bid_session(session["id"], MARKET)
    validate_error(resp, ApiErrorId.ERR_BID_SESSION_NOT_CLEARED)
