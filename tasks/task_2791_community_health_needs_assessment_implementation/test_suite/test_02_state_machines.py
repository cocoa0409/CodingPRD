"""State-machine corners: initial states, declared successors and terminal rows."""

from test_helpers import (
    BOARD,
    COMPLIANCE,
    OFFICER,
    STEWARD,
    ApiErrorId,
    ApprovalState,
    AttainmentStatus,
    CandidateStatus,
    CycleStatus,
    DataPointStatus,
    DataState,
    EvalType,
    ExecutionState,
    IndicatorDomain,
    InterviewStatus,
    ObjectiveStatus,
    Posture,
    SignatorySide,
    SignatureState,
    Subgroup,
    add_agreement,
    add_data_point,
    add_evaluation,
    add_indicator,
    add_interview,
    add_objective,
    add_partner_party,
    add_strategy,
    advance_to,
    assert_close,
    assert_common_fields,
    build_scenario,
    complete_interview,
    create_cycle,
    execute_agreement,
    file_return,
    finalize_report,
    make_partner_representative_headers,
    open_report,
    post_cost_based,
    publish_cycle,
    publish_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_a_new_strategy_starts_at_the_initial_state_of_both_axes(api):
    """PRD §3.5: "A new strategy starts with `approval_state` at `DRAFT`,
    `execution_state` at `NOT_STARTED`, `budget_available_cents` equal to its full
    `authorized_budget_cents`, `active_objective_count` at 0, and
    `superseded_by_strategy_id`, `submitted_at`, `approved_at` and
    `execution_note` all null."

    Design: Corner/state_machines/implementation_strategy_initial_state_is_draft_and_not_started
    """
    sc = build_scenario(api, stage="CANDIDATE_SELECTED")
    advance_to(api, sc.cycle_id, CycleStatus.STRATEGY_DEVELOPMENT)

    strategy = add_strategy(api, sc.candidate_id)

    assert_common_fields(strategy, expected_version=1)
    assert strategy["approval_state"] == ApprovalState.DRAFT
    assert strategy["execution_state"] == ExecutionState.NOT_STARTED
    assert strategy["authorized_budget_cents"] == C.AUTHORIZED_BUDGET_CENTS
    assert strategy["budget_available_cents"] == C.AUTHORIZED_BUDGET_CENTS
    assert strategy["active_objective_count"] == 0
    for field in ("superseded_by_strategy_id", "submitted_at", "approved_at", "execution_note"):
        assert strategy[field] is None, f"{field} should start null"


def test_a_new_objective_starts_draft_with_every_attainment_field_unset(api):
    """PRD §3.5: "An objective is created with `status` at `DRAFT`,
    `attainment_status` at `PENDING`, and `attainment_pct`, `actual_value`,
    `as_of_date` and `baseline_locked_at` all null."

    Design: Corner/state_machines/implementation_strategy_initial_state_is_draft_and_not_started
    """
    sc = build_scenario(api, stage="STRATEGY_DEVELOPMENT")

    objective = add_objective(api, sc.strategy_id)

    assert_common_fields(objective, expected_version=1)
    assert objective["strategy_id"] == sc.strategy_id
    assert objective["status"] == ObjectiveStatus.DRAFT
    assert objective["attainment_status"] == AttainmentStatus.PENDING
    for field in ("attainment_pct", "actual_value", "as_of_date", "baseline_locked_at"):
        assert objective[field] is None, f"{field} should start null"
    # The delivery axis does not start running merely because a metric exists.
    assert sc.strategy()["execution_state"] == ExecutionState.NOT_STARTED


def test_the_first_advance_is_what_opens_the_indicator_registration_window(api):
    """PRD §2.11: "Registering a health indicator and recording an observation
    both require the owning cycle's `status` to be `DATA_COLLECTION`."

    Design: Corner/state_machines/cycle_draft_to_data_collection_advances_and_recomputes_posture
    """
    cycle = create_cycle(api)
    assert cycle["status"] == CycleStatus.DRAFT
    assert cycle["posture"] == Posture.OPEN

    too_early = api.create_indicator(F.indicator_payload(cycle["id"]))
    validate_error(too_early, ApiErrorId.INVALID_STATE, 409)

    advanced = validate_success(api.advance_cycle(cycle["id"], CycleStatus.DATA_COLLECTION))
    assert advanced["status"] == CycleStatus.DATA_COLLECTION

    indicator = validate_success(api.create_indicator(F.indicator_payload(cycle["id"])), 201)
    assert indicator["cycle_id"] == cycle["id"]
    assert indicator["data_state"] == DataState.INSUFFICIENT


def test_the_advance_recomputes_the_posture_and_bumps_only_the_version(api):
    """PRD §3.1: "Every successful advance recomputes `posture` and increments the
    cycle's `version` by 1, and returns the updated cycle with HTTP 200."

    Design: Corner/state_machines/cycle_draft_to_data_collection_advances_and_recomputes_posture
    """
    cycle = create_cycle(api)
    assert cycle["version"] == 1

    advanced = validate_success(api.advance_cycle(cycle["id"], CycleStatus.DATA_COLLECTION))
    assert advanced["status"] == CycleStatus.DATA_COLLECTION
    # ``DATA_COLLECTION`` is an open phase, so the recomputation lands on ``OPEN``.
    assert advanced["posture"] == Posture.OPEN
    assert advanced["version"] == 2
    for counter in (
        "sufficient_indicator_count",
        "completed_interview_count",
        "selected_priority_count",
        "review_flag_count",
        "board_deferral_count",
        "mid_cycle_adjustment_count",
        "annual_report_count",
    ):
        assert advanced[counter] == 0, f"{counter} moved on a bare phase advance"

    stored = validate_success(api.get_cycle(cycle["id"]))
    assert stored["status"] == CycleStatus.DATA_COLLECTION
    assert stored["version"] == 2
    assert stored["fiscal_year"] == C.FISCAL_YEAR
    assert stored["service_area_name"] == C.SERVICE_AREA_NAME


def test_leaving_data_collection_requires_one_adequately_evidenced_indicator(api):
    """PRD §3.1: "Leaving `DATA_COLLECTION` requires `sufficient_indicator_count`
    to be at least 1 — the assessment must rest on at least one adequately
    evidenced health indicator — and otherwise fails with
    `ERR_INSUFFICIENT_INDICATOR_COVERAGE`."

    Design: Corner/state_machines/advance_rejected_when_coverage_or_selected_priority_preconditions_unmet
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])
    add_data_point(api, indicator["id"], population_subgroup=Subgroup.OVERALL, value=18.6)

    blocked = api.advance_cycle(cycle["id"], CycleStatus.INPUT_GATHERING)
    validate_error(blocked, ApiErrorId.INSUFFICIENT_INDICATOR_COVERAGE, 409)

    held = validate_success(api.get_cycle(cycle["id"]))
    assert held["status"] == CycleStatus.DATA_COLLECTION
    assert held["version"] == 2
    assert held["sufficient_indicator_count"] == 0

    add_data_point(api, indicator["id"], population_subgroup=Subgroup.BLACK_NH, value=24.8)
    add_data_point(api, indicator["id"], population_subgroup=Subgroup.WHITE_NH, value=15.5)
    armed = validate_success(api.get_cycle(cycle["id"]))
    assert armed["sufficient_indicator_count"] == 1

    opened = validate_success(api.advance_cycle(cycle["id"], CycleStatus.INPUT_GATHERING))
    assert opened["status"] == CycleStatus.INPUT_GATHERING


def test_leaving_prioritization_requires_a_selected_priority(api):
    """PRD §3.1: "Leaving `PRIORITIZATION` requires `selected_priority_count` to be
    at least 1, failing with `ERR_NO_SELECTED_PRIORITY`."

    Design: Corner/state_machines/advance_rejected_when_coverage_or_selected_priority_preconditions_unmet
    """
    sc = build_scenario(api, stage="CANDIDATE_SCORED")
    deferred = validate_success(api.defer_candidate(sc.candidate_id, "Deferred to the next cycle"))
    assert deferred["status"] == CandidateStatus.DEFERRED

    before = sc.cycle()
    assert before["selected_priority_count"] == 0

    blocked = api.advance_cycle(sc.cycle_id, CycleStatus.STRATEGY_DEVELOPMENT)
    validate_error(blocked, ApiErrorId.NO_SELECTED_PRIORITY, 409)

    after = sc.cycle()
    assert after["status"] == CycleStatus.PRIORITIZATION
    assert after["version"] == before["version"]
    assert after["selected_priority_count"] == 0


def test_backward_skipped_and_self_targeted_advances_are_all_rejected(api):
    """PRD §3.1: "Any other combination of current status and requested `to_status`
    — including every backward pair, every skipped rung, and any attempt to reach
    `ADOPTED`, `PUBLISHED` or `FILED` this way — is rejected with
    `ERR_INVALID_PHASE_TRANSITION`."

    Design: Corner/state_machines/backward_and_skipping_phase_transitions_rejected
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)

    for target in (
        CycleStatus.DRAFT,  # backward
        CycleStatus.PRIORITIZATION,  # skips INPUT_GATHERING
        CycleStatus.DATA_COLLECTION,  # the phase it already occupies
        CycleStatus.STRATEGY_DEVELOPMENT,  # skips two rungs
    ):
        rejected = api.advance_cycle(cycle["id"], target)
        validate_error(rejected, ApiErrorId.INVALID_PHASE_TRANSITION, 409)

    held = validate_success(api.get_cycle(cycle["id"]))
    assert held["status"] == CycleStatus.DATA_COLLECTION
    assert held["version"] == 2


def test_the_three_off_chain_statuses_are_unreachable_by_a_phase_advance(api):
    """PRD §3.1: "The three statuses missing from that chain are reached by their
    own dedicated actions: `ADOPTED` by a board decision, `PUBLISHED` by
    publication, and `FILED` by the regulatory filing."

    PRD §3.9: "The cycle's `status` must be `ADOPTED` and its `adopted_at` must not
    be null — the record of the board's decision has to exist, not merely the
    phase."

    Design: Corner/state_machines/backward_and_skipping_phase_transitions_rejected
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)

    for target in (CycleStatus.ADOPTED, CycleStatus.PUBLISHED, CycleStatus.FILED):
        rejected = api.advance_cycle(cycle["id"], target)
        validate_error(rejected, ApiErrorId.INVALID_PHASE_TRANSITION, 409)

    # The dedicated actions refuse the phase too, and they answer on their own
    # state-legality code rather than the successor code.
    validate_error(
        api.publish_cycle(cycle["id"], F.publish_cycle_payload()),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.board_action(cycle["id"], F.board_action_payload(), headers=BOARD),
        ApiErrorId.INVALID_STATE,
        409,
    )

    held = validate_success(api.get_cycle(cycle["id"]))
    assert held["status"] == CycleStatus.DATA_COLLECTION
    assert held["version"] == 2
    assert held["adopted_at"] is None
    assert held["published_at"] is None


def test_reaching_prioritization_refuses_a_newly_scheduled_session(api):
    """PRD §3.1: "Reaching `PRIORITIZATION` closes the interview scheduling window:
    from that point on, scheduling a *new* session on the cycle is rejected with
    `ERR_INPUT_WINDOW_CLOSED`, while completing or cancelling a session that was
    already `SCHEDULED` remains permitted."

    Design: Corner/state_machines/prioritization_advance_closes_the_interview_scheduling_window
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    second = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    assert second["status"] == InterviewStatus.SCHEDULED

    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)

    late = api.create_interview(
        F.interview_payload(
            sc.cycle_id,
            sc.facilitator_party_id,
            organization_name="Eastside Food Bank",
            starts_at="2026-04-09T14:00:00Z",
            ends_at="2026-04-09T15:00:00Z",
        )
    )
    validate_error(late, ApiErrorId.INPUT_WINDOW_CLOSED, 409)

    listed, meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id))
    assert meta["total_count"] == 2
    assert {row["id"] for row in listed} == {sc.interview_id, second["id"]}


def test_sessions_already_scheduled_still_complete_and_cancel_after_the_window_closes(api):
    """PRD §3.3: "Completing a session is what turns a booking into evidence. It
    requires the session's `status` to be `SCHEDULED` and the owning cycle's
    `status` to be either `INPUT_GATHERING` or `PRIORITIZATION`; either failure is
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/prioritization_advance_closes_the_interview_scheduling_window
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    second = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    third = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Eastside Food Bank",
        starts_at="2026-04-08T14:00:00Z",
        ends_at="2026-04-08T15:00:00Z",
    )

    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)

    completed = validate_success(
        api.complete_interview(
            second["id"],
            F.complete_interview_payload(
                domain=IndicatorDomain.BEHAVIORAL_HEALTH, rating=4, attendee_count=8
            ),
        )
    )
    assert completed["status"] == InterviewStatus.COMPLETED
    assert completed["completed_at"] is not None
    assert completed["attendee_count"] == 8

    cancelled = validate_success(api.cancel_interview(third["id"], "Organization withdrew"))
    assert cancelled["status"] == InterviewStatus.CANCELLED
    assert cancelled["cancel_reason"] == "Organization withdrew"

    cycle = sc.cycle()
    # Only the two completions count; the cancellation contributes nothing.
    assert cycle["completed_interview_count"] == 2


def test_a_terminated_agreement_refuses_both_signatures_and_a_second_termination(api):
    """PRD §3.6: "Signing an agreement that is already `EXECUTED` or `TERMINATED`,
    or re-signing the side that has already signed, is rejected with
    `ERR_INVALID_STATE`."

    PRD §3.6: "Termination is available from `NEGOTIATING`, `HOSPITAL_SIGNED`,
    `PARTNER_SIGNED` or `EXECUTED`, rejecting a second termination with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    cycle = create_cycle(api)
    partner = add_partner_party(api)
    agreement = add_agreement(api, cycle["id"], partner["id"])
    executed = execute_agreement(api, agreement["id"], partner["id"])
    assert executed["signature_state"] == SignatureState.EXECUTED

    terminated = validate_success(
        api.terminate_agreement(agreement["id"], "Partner organization dissolved")
    )
    assert terminated["signature_state"] == SignatureState.TERMINATED
    assert terminated["terminate_reason"] == "Partner organization dissolved"
    assert terminated["funded_cents"] == 0

    partner_headers = make_partner_representative_headers(partner["id"])
    validate_error(
        api.sign_agreement(agreement["id"], SignatorySide.HOSPITAL, headers=OFFICER),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.sign_agreement(agreement["id"], SignatorySide.PARTNER, headers=partner_headers),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_error(
        api.terminate_agreement(agreement["id"], "Second attempt"),
        ApiErrorId.INVALID_STATE,
        409,
    )

    after = validate_success(api.get_agreement(agreement["id"]))
    assert after["signature_state"] == SignatureState.TERMINATED
    assert after["terminate_reason"] == "Partner organization dissolved"
    assert after["version"] == terminated["version"]


def test_a_retracted_observation_refuses_a_second_retraction(api):
    """PRD §3.2: "It requires the observation's `status` to be `ACTIVE`, rejecting a
    second attempt with `ERR_INVALID_STATE`, and it records the supplied `reason`
    into `void_reason` alongside the acting user in `voided_by_user_id` before
    moving `status` to `VOID`."

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    indicator = add_indicator(api, cycle["id"])
    observation = add_data_point(api, indicator["id"])
    assert observation["status"] == DataPointStatus.ACTIVE

    voided = validate_success(
        api.void_data_point(observation["id"], "Source dataset revised", headers=STEWARD)
    )
    assert voided["status"] == DataPointStatus.VOID
    assert voided["void_reason"] == "Source dataset revised"
    assert voided["voided_by_user_id"] == STEWARD["X-User-ID"]

    validate_error(
        api.void_data_point(observation["id"], "Retracting again", headers=STEWARD),
        ApiErrorId.INVALID_STATE,
        409,
    )

    after = validate_success(api.get_data_point(observation["id"], headers=STEWARD))
    assert after["status"] == DataPointStatus.VOID
    assert after["void_reason"] == "Source dataset revised"
    assert after["version"] == voided["version"]


def test_completing_an_already_completed_session_is_rejected(api):
    """PRD §3.3: "It requires the session's `status` to be `SCHEDULED` and the
    owning cycle's `status` to be either `INPUT_GATHERING` or `PRIORITIZATION`;
    either failure is `ERR_INVALID_STATE`."

    PRD §3.3: "On success `status` moves `SCHEDULED` to `COMPLETED`, `completed_at`
    is stamped from the logical clock, and the cycle's `completed_interview_count`
    increases by 1."

    Design: Corner/state_machines/repeating_a_completed_transition_is_rejected
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    before = validate_success(api.get_interview(sc.interview_id))
    assert before["status"] == InterviewStatus.COMPLETED

    repeated = api.complete_interview(
        sc.interview_id,
        F.complete_interview_payload(
            domain=IndicatorDomain.MATERNAL_CHILD_HEALTH, rating=1, attendee_count=99
        ),
    )
    validate_error(repeated, ApiErrorId.INVALID_STATE, 409)

    after = validate_success(api.get_interview(sc.interview_id))
    assert after["concern_ratings"] == {IndicatorDomain.BEHAVIORAL_HEALTH: 5}
    assert after["attendee_count"] == C.ATTENDEE_COUNT
    assert after["completed_at"] == before["completed_at"]
    assert after["version"] == before["version"]
    assert sc.cycle()["completed_interview_count"] == 1


def test_cancelling_an_already_completed_session_is_rejected(api):
    """PRD §3.3: "It requires the session's `status` to be `SCHEDULED` and the
    owning cycle's `status` to be `INPUT_GATHERING` or `PRIORITIZATION`, rejecting
    otherwise with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/repeating_a_completed_transition_is_rejected
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    before = validate_success(api.get_interview(sc.interview_id))

    validate_error(
        api.cancel_interview(sc.interview_id, "Too late to cancel"),
        ApiErrorId.INVALID_STATE,
        409,
    )

    after = validate_success(api.get_interview(sc.interview_id))
    assert after["status"] == InterviewStatus.COMPLETED
    assert after["cancel_reason"] is None
    assert after["version"] == before["version"]
    assert sc.cycle()["completed_interview_count"] == 1


def _filed_cycle_with_a_met_and_a_revised_objective(api):
    """A ``FILED`` cycle whose one strategy carries two objectives in different
    states: one finished at exactly 100.00 attainment and still ``ACTIVE``, one at
    49.92 and pushed to ``REVISED`` by a published mid-cycle evaluation."""
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    lagging_id = add_objective(
        api, sc.strategy_id, metric_name="Warm handoffs to behavioral health"
    )["id"]

    validate_success(api.submit_strategy(sc.strategy_id))
    advance_to(api, sc.cycle_id, CycleStatus.BOARD_REVIEW)
    validate_success(api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD))

    # (2400 - 1200) / (2400 - 1200) * 100 = 100.00 -> MET.
    met = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(2400, "2027-01-15"))
    )
    assert_close(met["attainment_pct"], 100.00, "attainment_pct")
    assert met["attainment_status"] == AttainmentStatus.MET
    # (1799 - 1200) / 1200 * 100 = 49.9166... -> 49.92 -> NOT_MET, and below the
    # 50.00 mid-cycle revision threshold.
    lagging = validate_success(
        api.report_progress(lagging_id, F.report_progress_payload(1799, "2027-01-15"))
    )
    assert_close(lagging["attainment_pct"], 49.92, "attainment_pct")
    assert lagging["attainment_status"] == AttainmentStatus.NOT_MET

    mid_cycle = add_evaluation(
        api, sc.cycle_id, eval_type=EvalType.MID_CYCLE, period_year=2027
    )
    published_mid = publish_evaluation(api, mid_cycle["id"])
    assert published_mid["objectives_revised_count"] == 1
    assert validate_success(api.get_objective(lagging_id))["status"] == ObjectiveStatus.REVISED
    assert sc.strategy()["execution_state"] == ExecutionState.BEHIND

    annual = add_evaluation(
        api, sc.cycle_id, eval_type=EvalType.ANNUAL, period_year=C.FISCAL_YEAR
    )
    publish_evaluation(api, annual["id"])

    report = open_report(api, sc.cycle_id)
    post_cost_based(api, report["id"], 850000)
    finalize_report(api, report["id"])
    publish_cycle(api, sc.cycle_id)
    filed = file_return(api, sc.cycle_id)
    assert filed["status"] == CycleStatus.FILED
    assert filed["posture"] == Posture.FROZEN
    return sc, lagging_id


def test_close_out_finalizes_the_active_and_the_revised_objective_differently(api):
    """PRD §3.1: "Second, caused by that close-out, every objective of those
    strategies whose `status` is `ACTIVE` or `REVISED` is finalized: it moves to
    `FINALIZED_MET` when its `attainment_pct` is not null and is at least 100.00,
    and to `FINALIZED_NOT_MET` in every other case — including the case where
    `attainment_pct` was never computed at all."

    Design: Corner/state_machines/cycle_close_out_cascade_finalizes_active_and_revised_objectives
    """
    sc, lagging_id = _filed_cycle_with_a_met_and_a_revised_objective(api)

    closed = validate_success(
        api.advance_cycle(sc.cycle_id, CycleStatus.CLOSED, headers=COMPLIANCE)
    )
    assert closed["status"] == CycleStatus.CLOSED
    assert closed["posture"] == Posture.FROZEN

    met = validate_success(api.get_objective(sc.objective_id))
    assert met["status"] == ObjectiveStatus.FINALIZED_MET
    assert_close(met["attainment_pct"], 100.00, "attainment_pct")

    lagging = validate_success(api.get_objective(lagging_id))
    assert lagging["status"] == ObjectiveStatus.FINALIZED_NOT_MET
    assert_close(lagging["attainment_pct"], 49.92, "attainment_pct")


def test_close_out_moves_the_delivery_axis_only_and_leaves_the_approval_axis_alone(api):
    """PRD §3.1: "First, every implementation strategy reachable from the cycle whose
    `execution_state` is `ON_TRACK`, `AT_RISK`, `BEHIND` or
    `SUSPENDED_PENDING_REVIEW` moves to `CLOSED_OUT`; strategies already in
    `COMPLETED`, `DISCONTINUED` or `CLOSED_OUT` are untouched."

    PRD §3.1: "The cycle's `posture` stays `FROZEN` throughout, because `CLOSED` is
    itself a frozen status."

    Design: Corner/state_machines/cycle_close_out_cascade_finalizes_active_and_revised_objectives
    """
    sc, _ = _filed_cycle_with_a_met_and_a_revised_objective(api)
    before = sc.strategy()
    assert before["execution_state"] == ExecutionState.BEHIND
    assert before["approval_state"] == ApprovalState.APPROVED

    validate_success(api.advance_cycle(sc.cycle_id, CycleStatus.CLOSED, headers=COMPLIANCE))

    after = sc.strategy()
    assert after["execution_state"] == ExecutionState.CLOSED_OUT
    assert after["approval_state"] == ApprovalState.APPROVED
    assert after["approved_at"] == before["approved_at"]
    assert sc.cycle()["posture"] == Posture.FROZEN
