"""Non-linear state machines: the governance loop, the two axes and the fork-join."""

from test_helpers import (
    BOARD,
    OFFICER,
    ApprovalState,
    BoardActionType,
    CommitmentStatus,
    CycleStatus,
    ExecutionState,
    FundingState,
    ObjectiveStatus,
    Posture,
    SignatorySide,
    SignatureState,
    add_agreement,
    add_partner_party,
    assert_posture,
    build_scenario,
    create_cycle,
    make_partner_representative_headers,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_board_defer_returns_the_cycle_to_strategy_development(api):
    """PRD §3.7: "The cycle's `status` moves `BOARD_REVIEW` to
    `STRATEGY_DEVELOPMENT`, every implementation strategy reachable from the cycle
    whose `approval_state` is `SUBMITTED` moves to `RETURNED` while keeping its
    existing `submitted_at` intact, the cycle's `board_deferral_count` increases
    by 1, and `posture` is recomputed — returning to `OPEN` when
    `review_flag_count` stands at 0, or remaining `RESTRICTED` when a suspended
    strategy is still outstanding."

    Design: Difficulty/non_linear_state_machine/cycle_board_defer_returns_to_strategy_development_and_readvances
    """
    sc = build_scenario(api, stage="BOARD_REVIEW", with_partner=True)
    assert sc.cycle()["board_deferral_count"] == 0
    assert_posture(sc.cycle(), Posture.RESTRICTED)

    deferred = validate_success(
        api.board_action(
            sc.cycle_id,
            F.board_action_payload(
                action_type=BoardActionType.DEFER,
                votes_for=3,
                votes_against=8,
                note="Objectives need measurable mid-cycle checkpoints",
            ),
            headers=BOARD,
        )
    )
    assert deferred["status"] == CycleStatus.STRATEGY_DEVELOPMENT
    assert deferred["board_deferral_count"] == 1
    assert_posture(deferred, Posture.OPEN)

    strategy = sc.strategy()
    assert strategy["approval_state"] == ApprovalState.RETURNED
    assert strategy["submitted_at"] is not None
    assert strategy["execution_state"] == ExecutionState.NOT_STARTED
    assert sc.objective()["status"] == ObjectiveStatus.DRAFT
    assert sc.commitment()["status"] == CommitmentStatus.PENDING
    assert sc.agreement()["funding_state"] == FundingState.PLEDGED


def test_a_returned_strategy_resubmits_and_the_cycle_readvances_to_adoption(api):
    """PRD §3.5: "Submission is permitted from `DRAFT` or from `RETURNED` — the
    second case being a resubmission after the board sent the strategy back — and
    requires the owning cycle's `status` to be `STRATEGY_DEVELOPMENT`; either
    failure is `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/cycle_board_defer_returns_to_strategy_development_and_readvances
    """
    sc = build_scenario(api, stage="BOARD_REVIEW", with_partner=True)
    validate_success(
        api.board_action(
            sc.cycle_id,
            F.board_action_payload(
                action_type=BoardActionType.DEFER, votes_for=3, votes_against=8
            ),
            headers=BOARD,
        )
    )

    resubmitted = validate_success(api.submit_strategy(sc.strategy_id))
    assert resubmitted["approval_state"] == ApprovalState.SUBMITTED

    readvanced = validate_success(api.advance_cycle(sc.cycle_id, CycleStatus.BOARD_REVIEW))
    assert readvanced["status"] == CycleStatus.BOARD_REVIEW
    assert readvanced["board_deferral_count"] == 1

    adopted = validate_success(
        api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD)
    )
    assert adopted["status"] == CycleStatus.ADOPTED
    assert sc.strategy()["approval_state"] == ApprovalState.APPROVED


def test_execution_axis_moves_freely_among_the_three_live_states(api):
    """PRD §3.8: "From `ON_TRACK`, `AT_RISK` or `BEHIND`, a change to `AT_RISK`,
    `BEHIND` or `ON_TRACK` is always permitted — `AT_RISK` to `BEHIND`, `BEHIND`
    back to `AT_RISK`, and `BEHIND` straight back to `ON_TRACK` are all legal,
    because a delivery axis that could only degrade would be useless."

    Design: Difficulty/non_linear_state_machine/strategy_execution_axis_moves_independently_of_approval_axis
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    assert sc.strategy()["execution_state"] == ExecutionState.ON_TRACK

    at_risk = validate_success(
        api.set_execution_status(
            sc.strategy_id,
            F.execution_status_payload(
                ExecutionState.AT_RISK, execution_note="Partner hiring delayed"
            ),
        )
    )
    assert at_risk["execution_state"] == ExecutionState.AT_RISK

    behind = validate_success(
        api.set_execution_status(
            sc.strategy_id,
            F.execution_status_payload(
                ExecutionState.BEHIND, execution_note="Two quarters of shortfall"
            ),
        )
    )
    assert behind["execution_state"] == ExecutionState.BEHIND

    recovered = validate_success(
        api.set_execution_status(
            sc.strategy_id,
            F.execution_status_payload(
                ExecutionState.ON_TRACK, execution_note="Recovered after second-site launch"
            ),
        )
    )
    assert recovered["execution_state"] == ExecutionState.ON_TRACK
    assert recovered["execution_note"] == "Recovered after second-site launch"


def test_execution_axis_moves_never_touch_the_approval_axis_or_the_posture(api):
    """PRD §3.8: "Every such change requires the strategy's `approval_state` to be
    `APPROVED`; an attempt against a `DRAFT`, `SUBMITTED`, `RETURNED` or
    `SUPERSEDED` strategy is rejected with `ERR_STRATEGY_NOT_APPROVED`, and the
    `approval_state` itself never changes as a result of an execution move."

    Design: Difficulty/non_linear_state_machine/strategy_execution_axis_moves_independently_of_approval_axis
    """
    sc = build_scenario(api, stage="ADOPTED", with_partner=True)
    approved_at = sc.strategy()["approved_at"]
    assert approved_at is not None

    for destination in (ExecutionState.AT_RISK, ExecutionState.BEHIND, ExecutionState.ON_TRACK):
        moved = validate_success(
            api.set_execution_status(sc.strategy_id, F.execution_status_payload(destination))
        )
        assert moved["approval_state"] == ApprovalState.APPROVED
        assert moved["approved_at"] == approved_at

    # No execution-axis move re-derives the objective, and neither AT_RISK nor
    # BEHIND is a review flag: only SUSPENDED_PENDING_REVIEW is.
    assert sc.objective()["status"] == ObjectiveStatus.ACTIVE
    cycle = sc.cycle()
    assert cycle["review_flag_count"] == 0
    assert_posture(cycle, Posture.OPEN)


def test_partner_signature_alone_leaves_the_agreement_unfunded_and_half_signed(api):
    """PRD §3.6: "Recording a `PARTNER` signature on an agreement in
    `NEGOTIATING` moves `signature_state` to `PARTNER_SIGNED`, stamps
    `partner_signed_at` from the logical clock, and stores the acting `X-User-ID`
    as `partner_signatory_user_id` — a value that, by the identity rule in §2.1,
    necessarily equals the agreement's `party_id`; `hospital_signed_at` and
    `hospital_signatory_user_id` stay null and `funding_state` stays
    `UNFUNDED`."

    Design: Difficulty/non_linear_state_machine/partnership_fork_join_requires_both_signatures_before_executed
    """
    cycle = create_cycle(api)
    partner = add_partner_party(api)
    agreement = add_agreement(api, cycle["id"], partner["id"])
    assert agreement["signature_state"] == SignatureState.NEGOTIATING
    assert agreement["funding_state"] == FundingState.UNFUNDED
    assert agreement["pledged_cents"] == C.PLEDGED_CENTS

    signed = validate_success(
        api.sign_agreement(
            agreement["id"],
            SignatorySide.PARTNER,
            headers=make_partner_representative_headers(partner["id"]),
        )
    )
    assert signed["signature_state"] == SignatureState.PARTNER_SIGNED
    assert signed["funding_state"] == FundingState.UNFUNDED
    assert signed["partner_signed_at"] is not None
    assert signed["partner_signatory_user_id"] == partner["id"]
    assert signed["hospital_signed_at"] is None
    assert signed["hospital_signatory_user_id"] is None


def test_the_second_signature_closes_the_join_and_only_pledges(api):
    """PRD §3.6: "In both cases, and only on reaching the join, `funding_state`
    moves `UNFUNDED` to `PLEDGED` — the point at which the agreement becomes
    eligible to fund resource commitments."

    Design: Difficulty/non_linear_state_machine/partnership_fork_join_requires_both_signatures_before_executed
    """
    cycle = create_cycle(api)
    partner = add_partner_party(api)
    agreement = add_agreement(api, cycle["id"], partner["id"])

    first = validate_success(
        api.sign_agreement(
            agreement["id"],
            SignatorySide.PARTNER,
            headers=make_partner_representative_headers(partner["id"]),
        )
    )
    second = validate_success(
        api.sign_agreement(agreement["id"], SignatorySide.HOSPITAL, headers=OFFICER)
    )

    assert second["signature_state"] == SignatureState.EXECUTED
    assert second["funding_state"] == FundingState.PLEDGED
    assert second["hospital_signed_at"] is not None
    assert second["hospital_signatory_user_id"] == OFFICER["X-User-ID"]
    assert second["partner_signed_at"] == first["partner_signed_at"]
    # The join pledges but does not fund; funding follows commitment activation.
    assert second["funded_cents"] == 0
