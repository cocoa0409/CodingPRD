"""Three-link cascades: adoption, retraction and the mid-cycle publication."""

from test_helpers import (
    BOARD,
    STEWARD,
    ApprovalState,
    AttainmentStatus,
    CandidateStatus,
    CommitmentStatus,
    CycleStatus,
    DataState,
    EvalType,
    EvalStatus,
    ExecutionState,
    FundingState,
    ObjectiveStatus,
    Posture,
    add_evaluation,
    assert_close,
    assert_posture,
    build_scenario,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_adoption_approves_the_strategy_and_activates_its_objective(api):
    """PRD §3.7: "For each strategy that link one just moved to `APPROVED`, every
    objective of that strategy whose `status` is `DRAFT` moves to `ACTIVE` and has
    `baseline_locked_at` stamped from the logical clock, at which point that
    objective's `baseline_value` becomes immutable — a strategy cannot be judged
    against a baseline it is allowed to move."

    Design: Difficulty/transitive_cascade/adoption_cascades_strategy_approval_objective_activation_commitment_funding
    """
    sc = build_scenario(api, stage="BOARD_REVIEW", with_partner=True)
    assert sc.strategy()["approval_state"] == ApprovalState.SUBMITTED
    assert sc.strategy()["active_objective_count"] == 0
    assert sc.objective()["status"] == ObjectiveStatus.DRAFT

    adopted = validate_success(
        api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD)
    )
    assert adopted["status"] == CycleStatus.ADOPTED

    strategy = sc.strategy()
    assert strategy["approval_state"] == ApprovalState.APPROVED
    assert strategy["approved_at"] is not None
    assert strategy["execution_state"] == ExecutionState.ON_TRACK
    assert strategy["active_objective_count"] == 1

    objective = sc.objective()
    assert objective["status"] == ObjectiveStatus.ACTIVE
    assert objective["baseline_locked_at"] is not None
    assert_close(objective["baseline_value"], C.OBJECTIVE_BASELINE_VALUE, "baseline_value")


def test_adoption_commits_the_pending_commitment_and_funds_the_agreement(api):
    """PRD §3.7: "What does change is partnership funding, which counts only
    committed rows: for each activated commitment whose `partnership_id` is not
    null, that agreement's `funded_cents` increases by the commitment's
    `funding_cents` and the agreement's `funding_state` moves `PLEDGED` to
    `FUNDED`."

    Design: Difficulty/transitive_cascade/adoption_cascades_strategy_approval_objective_activation_commitment_funding
    """
    sc = build_scenario(api, stage="BOARD_REVIEW", with_partner=True)
    assert sc.commitment()["status"] == CommitmentStatus.PENDING
    before_agreement = sc.agreement()
    assert before_agreement["funded_cents"] == 0
    assert before_agreement["funding_state"] == FundingState.PLEDGED
    assert sc.partner()["committed_fte_bp"] == C.COMMITMENT_FTE_BP

    validate_success(api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD))

    commitment = sc.commitment()
    assert commitment["status"] == CommitmentStatus.COMMITTED
    assert commitment["committed_at"] is not None

    agreement = sc.agreement()
    assert agreement["funded_cents"] == C.COMMITMENT_FUNDING_CENTS
    assert agreement["funding_state"] == FundingState.FUNDED


def test_activation_is_neutral_on_the_two_conserved_quantities(api):
    """PRD §3.7: "Activation is deliberately neutral on the two conserved
    quantities: because a `PENDING` commitment already encumbered both the party's
    `committed_fte_bp` and the strategy's `budget_available_cents`, neither figure
    changes when the commitment becomes `COMMITTED`."

    Design: Difficulty/transitive_cascade/adoption_cascades_strategy_approval_objective_activation_commitment_funding
    """
    sc = build_scenario(api, stage="BOARD_REVIEW", with_partner=True)
    budget_before = sc.strategy()["budget_available_cents"]
    fte_before = sc.partner()["committed_fte_bp"]
    assert budget_before == C.AUTHORIZED_BUDGET_CENTS - C.COMMITMENT_FUNDING_CENTS

    adopted = validate_success(
        api.board_action(
            sc.cycle_id,
            F.board_action_payload(votes_for=9, votes_against=2),
            headers=BOARD,
        )
    )

    assert sc.strategy()["budget_available_cents"] == budget_before
    assert sc.partner()["committed_fte_bp"] == fte_before
    assert adopted["adopted_at"] is not None
    assert adopted["adoption_board_user_id"] == BOARD["X-User-ID"]
    assert adopted["votes_for_at_adoption"] == 9
    assert adopted["votes_against_at_adoption"] == 2
    assert adopted["review_flag_count"] == 0
    assert_posture(adopted, Posture.OPEN)
    # Adoption alone does not publish.
    assert adopted["public_availability_met"] is False


def test_retracting_the_overall_observation_makes_the_indicator_insufficient(api):
    """PRD §3.2: "**Link one:** the owning indicator re-derives all five computed
    fields, and `severity_score` and `disparity_ratio` become null when their
    inputs disappear. If the re-derivation leaves `latest_overall_value` null or
    `subgroup_count` below 2, the indicator moves `SUFFICIENT` to `INSUFFICIENT`
    and the cycle's `sufficient_indicator_count` is reduced by 1."

    Design: Difficulty/transitive_cascade/data_void_cascades_indicator_insufficient_candidate_invalidated_strategy_suspended
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    assert sc.indicator()["data_state"] == DataState.SUFFICIENT
    assert sc.cycle()["sufficient_indicator_count"] == 1

    voided = validate_success(
        api.void_data_point(
            sc.data_point_ids[0],
            "Source dataset reissued with a corrected denominator",
            headers=STEWARD,
        )
    )
    assert voided["status"] == "VOID"
    assert voided["void_reason"] == "Source dataset reissued with a corrected denominator"
    assert voided["voided_by_user_id"] == STEWARD["X-User-ID"]

    indicator = sc.indicator()
    assert indicator["latest_overall_value"] is None
    assert indicator["severity_score"] is None
    assert indicator["evidence_count"] == 2
    assert indicator["data_state"] == DataState.INSUFFICIENT
    # The two subgroup rows survive, so only the OVERALL-dependent fields collapse.
    assert_close(indicator["disparity_ratio"], 1.60, "disparity_ratio")
    assert indicator["subgroup_count"] == 2
    assert sc.cycle()["sufficient_indicator_count"] == 0


def test_the_void_cascade_invalidates_the_selected_candidate_and_suspends_its_strategy(api):
    """PRD §3.2: "**Link three**, caused by link two: for every candidate that had
    been `SELECTED`, each implementation strategy whose `candidate_id` names that
    candidate and whose `execution_state` is anything other than `COMPLETED`,
    `DISCONTINUED` or `CLOSED_OUT` moves to `SUSPENDED_PENDING_REVIEW`; the
    cycle's `review_flag_count` is then recomputed and, because it is now at least
    1, the cycle's `posture` becomes `RESTRICTED`."

    Design: Difficulty/transitive_cascade/data_void_cascades_indicator_insufficient_candidate_invalidated_strategy_suspended
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    assert sc.candidate()["status"] == CandidateStatus.SELECTED
    assert sc.cycle()["selected_priority_count"] == 1

    validate_success(
        api.void_data_point(sc.data_point_ids[0], "Source dataset withdrawn", headers=STEWARD)
    )

    candidate = sc.candidate()
    assert candidate["status"] == CandidateStatus.SCORE_INVALIDATED
    assert candidate["composite_score"] is None
    assert candidate["severity_input"] is None
    assert candidate["disparity_points"] is None
    assert candidate["community_concern_index"] is None
    assert sc.cycle()["selected_priority_count"] == 0

    strategy = sc.strategy()
    assert strategy["execution_state"] == ExecutionState.SUSPENDED_PENDING_REVIEW
    assert strategy["approval_state"] == ApprovalState.APPROVED

    cycle = sc.cycle()
    assert cycle["review_flag_count"] == 1
    assert_posture(cycle, Posture.RESTRICTED)
    # Posture, not phase, absorbs the shock.
    assert cycle["status"] == CycleStatus.ADOPTED


def test_the_void_cascade_stops_at_the_strategy_and_releases_no_resources(api):
    """PRD §3.2: "The whole chain is the intended serialization point between the
    epidemiological record and the work justified by it: pull the evidence, and
    the work built on it stops until somebody reviews it."

    Design: Difficulty/transitive_cascade/data_void_cascades_indicator_insufficient_candidate_invalidated_strategy_suspended
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    assert sc.objective()["status"] == ObjectiveStatus.ACTIVE
    assert sc.commitment()["status"] == CommitmentStatus.COMMITTED

    validate_success(
        api.void_data_point(sc.data_point_ids[0], "Source dataset withdrawn", headers=STEWARD)
    )

    # One link further out than the strategy, nothing moves.
    assert sc.objective()["status"] == ObjectiveStatus.ACTIVE
    assert sc.commitment()["status"] == CommitmentStatus.COMMITTED
    assert sc.agreement()["funded_cents"] == C.COMMITMENT_FUNDING_CENTS
    assert sc.partner()["committed_fte_bp"] == C.COMMITMENT_FTE_BP


def test_publishing_a_mid_cycle_evaluation_revises_the_under_performing_objective(api):
    """PRD §3.8: "Publishing a `MID_CYCLE` evaluation increases the cycle's
    `mid_cycle_adjustment_count` by 1 and additionally triggers objective
    revision: every objective reachable from the cycle whose `status` is `ACTIVE`
    and whose `attainment_pct` is not null and strictly below 50.00 moves to
    `REVISED`; each such revision moves its owning strategy's `execution_state`
    from `ON_TRACK` to `BEHIND`, and increments this evaluation's
    `objectives_revised_count`."

    Design: Difficulty/transitive_cascade/mid_cycle_evaluation_publish_cascades_objective_revision_and_strategy_behind
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    progress = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(1799, "2027-01-15"))
    )
    # (1799 - 1200) / (2400 - 1200) * 100 = 49.9166... -> 49.92.
    assert_close(progress["attainment_pct"], 49.92, "attainment_pct")
    assert progress["attainment_status"] == AttainmentStatus.NOT_MET

    evaluation = add_evaluation(
        api,
        sc.cycle_id,
        eval_type=EvalType.MID_CYCLE,
        period_year=2027,
        findings_summary="Screening volume is tracking below the mid-point expectation",
    )
    assert evaluation["objectives_revised_count"] == 0

    published = validate_success(
        api.publish_evaluation(
            evaluation["id"],
            F.publish_evaluation_payload(
                public_url="https://riverbendhealth.example.org/chna/2026/mid-cycle"
            ),
        )
    )
    assert published["status"] == EvalStatus.PUBLISHED
    assert published["published_at"] is not None
    assert published["public_url"] == "https://riverbendhealth.example.org/chna/2026/mid-cycle"
    assert published["objectives_revised_count"] == 1

    objective = sc.objective()
    assert objective["status"] == ObjectiveStatus.REVISED
    assert_close(objective["attainment_pct"], 49.92, "attainment_pct")
    assert objective["attainment_status"] == AttainmentStatus.NOT_MET


def test_the_revision_drags_the_strategy_behind_and_counts_the_adjustment(api):
    """PRD §3.8: "each such revision moves its owning strategy's
    `execution_state` from `ON_TRACK` to `BEHIND`, and increments this
    evaluation's `objectives_revised_count`."

    Design: Difficulty/transitive_cascade/mid_cycle_evaluation_publish_cascades_objective_revision_and_strategy_behind
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(1799, "2027-01-15"))
    )
    evaluation = add_evaluation(
        api, sc.cycle_id, eval_type=EvalType.MID_CYCLE, period_year=2027
    )

    validate_success(
        api.publish_evaluation(evaluation["id"], F.publish_evaluation_payload())
    )

    strategy = sc.strategy()
    assert strategy["execution_state"] == ExecutionState.BEHIND
    assert strategy["approval_state"] == ApprovalState.APPROVED

    cycle = sc.cycle()
    assert cycle["mid_cycle_adjustment_count"] == 1
    assert cycle["annual_report_count"] == 0
    assert cycle["status"] == CycleStatus.ADOPTED
    # A revision is not a review flag.
    assert_posture(cycle, Posture.OPEN)
    # A mid-cycle revision does not disturb resources.
    assert sc.commitment()["status"] == CommitmentStatus.COMMITTED
    assert sc.agreement()["funded_cents"] == C.COMMITMENT_FUNDING_CENTS
