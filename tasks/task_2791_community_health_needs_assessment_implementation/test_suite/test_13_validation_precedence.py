"""Rule-ladder precedence: which of two simultaneously violated rules is reported."""

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    ApprovalState,
    CycleStatus,
    InterviewStatus,
    Posture,
    ReportStatus,
    Sector,
    add_commitment,
    add_internal_party,
    add_interview,
    assert_posture,
    build_scenario,
    open_report,
    post_charge_based,
    publish_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_budget_availability_is_reachable_while_the_strategy_is_still_draft(api):
    """PRD §3.6: "Last of all, the requested `funding_cents` must not exceed the
    strategy's current `budget_available_cents`, or the create fails with
    `ERR_STRATEGY_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/locked_strategy_beats_budget_exceeded_on_commitment_create
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    add_commitment(api, sc.strategy_id, sc.facilitator_party_id)
    strategy = sc.strategy()
    assert strategy["approval_state"] == ApprovalState.DRAFT
    assert strategy["budget_available_cents"] == 3500000

    validate_error(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=100, funding_cents=4000000
            )
        ),
        ApiErrorId.STRATEGY_BUDGET_EXCEEDED,
    )
    assert sc.strategy()["budget_available_cents"] == 3500000


def test_the_approval_axis_lock_outranks_the_budget_check_on_the_same_body(api):
    """PRD §2.11: "When one request violates several rules, exactly one error is
    returned, and it is the one from the earliest rung of the ladder below."

    Design: Difficulty/priority_pair_validation_conflict/locked_strategy_beats_budget_exceeded_on_commitment_create
    """
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    add_commitment(api, sc.strategy_id, sc.facilitator_party_id)

    submitted = validate_success(api.submit_strategy(sc.strategy_id))
    assert submitted["approval_state"] == ApprovalState.SUBMITTED

    # The identical body now violates the state rule at rung 11 as well as the
    # budget rule at rung 22.
    validate_error(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=100, funding_cents=4000000
            )
        ),
        ApiErrorId.STRATEGY_LOCKED,
    )
    assert sc.strategy()["budget_available_cents"] == 3500000
    party = validate_success(api.get_party(sc.facilitator_party_id))
    assert party["committed_fte_bp"] == C.COMMITMENT_FTE_BP


def test_public_availability_outranks_the_locked_report_gate_on_filing(api):
    """PRD §3.9: "Filing is deliberately reachable from `ADOPTED` as well as from
    `PUBLISHED`, so that an attempt to file an unpublished assessment is not turned
    away as a phase error but is caught by the substantive compliance check:
    `public_availability_met` must be true, and when it is not the rejection is
    `ERR_PUBLIC_AVAILABILITY_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/public_availability_beats_report_not_locked_on_file_return
    """
    sc = build_scenario(api, stage="ADOPTED")
    report = open_report(api, sc.cycle_id)
    post_charge_based(api, report["id"], 1234567)
    assert sc.cycle()["public_availability_met"] is False

    validate_error(
        api.file_return(sc.cycle_id, "F990-SCHH-2026-0001", headers=COMPLIANCE),
        ApiErrorId.PUBLIC_AVAILABILITY_NOT_MET,
    )

    cycle = sc.cycle()
    assert cycle["status"] == CycleStatus.ADOPTED
    assert cycle["filed_at"] is None
    assert_posture(cycle, Posture.OPEN)


def test_publishing_the_cycle_exposes_the_locked_report_gate_underneath(api):
    """PRD §3.9: "The second check is that the cycle has exactly one community
    benefit report whose `status` is `LOCKED`; a cycle with no locked report, or
    with a report still sitting `OPEN`, is rejected with `ERR_REPORT_NOT_LOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/public_availability_beats_report_not_locked_on_file_return
    """
    sc = build_scenario(api, stage="ADOPTED")
    report = open_report(api, sc.cycle_id)
    post_charge_based(api, report["id"], 1234567)

    published = publish_cycle(api, sc.cycle_id)
    assert published["status"] == CycleStatus.PUBLISHED
    assert published["public_availability_met"] is True

    validate_error(
        api.file_return(sc.cycle_id, "F990-SCHH-2026-0001", headers=COMPLIANCE),
        ApiErrorId.REPORT_NOT_LOCKED,
    )

    cycle = sc.cycle()
    assert cycle["status"] == CycleStatus.PUBLISHED
    assert_posture(cycle, Posture.OPEN)
    assert validate_success(api.get_report(report["id"]))["status"] == ReportStatus.OPEN


def test_the_facilitator_buffer_outranks_the_organization_uniqueness_rule(api):
    """PRD §2.11: "15. Facilitator window occupancy —
    `ERR_FACILITATOR_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/facilitator_conflict_beats_duplicate_org_on_interview_create
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")

    # Same organization name AND a window butting straight onto the existing
    # session, which the symmetric 30-minute buffer treats as a conflict.
    validate_error(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                sc.facilitator_party_id,
                organization_name=C.ORGANIZATION_NAME,
                starts_at="2026-04-06T15:00:00Z",
                ends_at="2026-04-06T16:00:00Z",
            )
        ),
        ApiErrorId.FACILITATOR_WINDOW_CONFLICT,
    )


def test_clearing_the_buffer_leaves_only_the_duplicate_organization_rejection(api):
    """PRD §3.3: "`organization_name` is unique within a cycle across sessions
    whose `status` is `SCHEDULED` or `COMPLETED`; a duplicate is rejected with
    `ERR_DUPLICATE_ORGANIZATION`."

    Design: Difficulty/priority_pair_validation_conflict/facilitator_conflict_beats_duplicate_org_on_interview_create
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")

    # Starting exactly 30 minutes after the existing session ends clears the buffer.
    validate_error(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                sc.facilitator_party_id,
                organization_name=C.ORGANIZATION_NAME,
                starts_at="2026-04-06T15:30:00Z",
                ends_at="2026-04-06T16:30:00Z",
            )
        ),
        ApiErrorId.DUPLICATE_ORGANIZATION,
    )

    accepted = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Resident Coalition",
        sector=Sector.RESIDENT_COALITION,
        starts_at="2026-04-06T15:30:00Z",
        ends_at="2026-04-06T16:30:00Z",
    )
    assert accepted["status"] == InterviewStatus.SCHEDULED

    assert sc.cycle()["completed_interview_count"] == 0
    rows, _meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id))
    assert len(rows) == 2
