"""Rework cycles, spec-unit completion, appeal cycles and the quality embargo."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_worker_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    REVIEWER,
    REVIEWER_TWO,
    attach_item,
    commit_label,
    create_gold_audit,
    create_program,
    create_unit,
    dispatch_panel,
    enroll_qualification,
    escalate_appeal,
    file_appeal,
    get_appeal_case,
    get_program,
    get_unit,
    make_pool,
    open_program,
    pay_commit,
    production_commits,
    propose_appeal,
    setup_certified_item,
    setup_certified_standard_unit,
    setup_dispatched_item,
    setup_graded_gold_audits,
    setup_pending_embargo,
    verify_qualification,
    worker_for_commit,
)


def test_spec_unit_cycles_complete_to_active_on_a_rework_round(api):
    """PRD §3.11: "A completed unit can also be reopened: a `PlatformAdmin`
    reopens a `COMPLETE` unit when at least one attached piece has
    `consensus_status` `REWORK` and the parent engagement is in `ACTIVE` or
    `QUALITY_EMBARGO`, which returns the unit's status to `ACTIVE` and its
    `piece_status` to `REWORK`"

    Design: Difficulty/non_linear_state_machine/spec_unit_complete_reopen_cycle
    """
    program, unit, pool, item, commit = setup_certified_standard_unit(max_items=10)
    assert get_unit(unit["id"])["status"] == "COMPLETE", (
        "the single committed member met the quorum of 1 with an agreement ratio of "
        "1.0 and the commit is paid, so the unit has already completed"
    )

    reopened = get_success_data(
        api_client.reviewer_action(item["id"], {"reviewer_action": "OPEN_REWORK"}, REVIEWER), 200
    )
    assert reopened["consensus_status"] == "REWORK"
    assert reopened["rework_cycles"] == 1

    # PRD §3.11: reopening the unit is the admin's own action, admitted once an
    # attached piece carries consensus_status REWORK.
    get_success_data(
        api_client.advance_unit(unit["id"], {"unit_action": "REOPEN"}, ADMIN), 200
    )

    live_unit = get_unit(unit["id"])
    assert live_unit["status"] == "ACTIVE"
    assert live_unit["piece_status"] == "REWORK"


def test_spec_unit_completes_only_after_its_piece_certifies(api):
    """PRD §3.11: "the unit completes when every attached piece has a
    `consensus_status` of `CERTIFIED` or `REJECTED`, at least one attached piece
    is `CERTIFIED`, and every `COMMITTED` commit on the unit's pieces is paid so
    that `payout_complete` is true on each certified piece."

    Design: Difficulty/non_linear_state_machine/spec_unit_complete_reopen_cycle
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=1, commitment_quorum=1, max_items=10
    )
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    # Certified but unpaid, so the unit has not completed yet.
    live_unit = get_unit(unit["id"])
    assert live_unit["status"] != "COMPLETE", "an unpaid certificate does not complete the unit"

    pay_commit(commit["id"], 8)

    live_unit = get_unit(unit["id"])
    assert live_unit["status"] == "COMPLETE"
    assert live_unit["piece_status"] == "CERTIFIED"
    assert live_unit["certified_item_count"] == 1


def test_appeal_claim_traverses_proposed_adjudication_proposed(api):
    """PRD §3.12: "Alternatively, a `PlatformReviewer` may escalate a claim out of
    `ADJUDICATION` again with the `ESCALATE` action, which requires that the acting
    reviewer's `X-User-ID` differs from the claim's `adjudicator_id`, and which
    returns the claim to `PROPOSED` with `adjudicator_id` set to the acting
    reviewer's `X-User-ID` and `proposed_outcome` set to the resubmitted outcome"

    Design: Difficulty/non_linear_state_machine/appeal_claim_reviewer_to_reviewer_cycle
    """
    program, unit, pool, item, commit = setup_certified_standard_unit()
    worker = worker_for_commit(commit, pool)

    claim = file_appeal(item, worker)
    assert claim["status"] == "ADVOCACY"

    proposed = propose_appeal(claim["id"], "QUALIFICATION_RESET", REVIEWER)
    assert proposed["status"] == "PROPOSED"
    assert proposed["adjudicator_id"] is not None

    escalated = escalate_appeal(claim["id"], REVIEWER_TWO)
    assert escalated["status"] == "ADJUDICATION"

    # PRD §3.12 requires the escalating reviewer to differ from the claim's
    # adjudicator_id, which REVIEWER_TWO (the proposer) is not, so it may carry
    # the claim back out of ADJUDICATION. The resubmitted outcome accompanies
    # the escalation.
    returned = escalate_appeal(claim["id"], REVIEWER_TWO, proposed_outcome="QUALIFICATION_RESET")
    assert returned["status"] == "PROPOSED", "the cycle is traversable more than once on one row"


def test_appeal_concurrence_from_adjudication_accepts_only_a_qualification_reset(api):
    """PRD §3.12: "From `ADJUDICATION`, a `PlatformReviewer` who holds no commit on
    the disputed piece may concur on a `QUALIFICATION_RESET` proposal, which moves
    the claim to `CONCURRENCE` and resets the disputed qualification's
    `gold_fail_streak` to 0"

    Design: Difficulty/non_linear_state_machine/appeal_claim_reviewer_to_reviewer_cycle
    """
    program, unit, pool, item, commit = setup_certified_standard_unit()
    worker = worker_for_commit(commit, pool)

    claim = file_appeal(item, worker)
    proposed = propose_appeal(claim["id"], "QUALIFICATION_RESET", REVIEWER)
    escalated = escalate_appeal(claim["id"], REVIEWER_TWO)
    assert escalated["status"] == "ADJUDICATION"

    # PRD §3.12: the ADJUDICATION concurrence is the second reviewer's act, and
    # the claim's adjudicator is barred from concurring with its own proposal.
    concurred = get_success_data(
        api_client.concur_appeal(
            claim["id"], {"expected_claim_version": escalated["version"]}, REVIEWER_TWO
        ),
        200,
    )
    assert concurred["status"] == "CONCURRENCE"


def test_the_claim_adjudicator_cannot_concur_with_its_own_proposal(api):
    """PRD §3.12: "A `PlatformReviewer` concurs on a `PROPOSED` claim, which
    requires three things: the acting reviewer's `X-User-ID` must differ from the
    claim's `adjudicator_id`, the acting reviewer must hold no commit on the
    disputed piece, and the claim's `proposed_outcome` must be `PAY_REVERSAL` while
    its `grounds` is `AMBIGUOUS_INSTRUCTIONS`."

    PRD §2.1: "A reviewer who is the claim's own `adjudicator_id` is additionally
    barred from concurring with that claim, and that case is reported under the
    same error."

    Design: Difficulty/non_linear_state_machine/appeal_claim_reviewer_to_reviewer_cycle
    """
    program, unit, pool, item, commit = setup_certified_standard_unit()
    worker = worker_for_commit(commit, pool)

    claim = file_appeal(item, worker)
    proposed = propose_appeal(claim["id"], "PAY_REVERSAL", REVIEWER)

    validate_error(
        api_client.concur_appeal(
            claim["id"], {"expected_claim_version": proposed["version"]}, REVIEWER
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    concurred = get_success_data(
        api_client.concur_appeal(
            claim["id"], {"expected_claim_version": proposed["version"]}, REVIEWER_TWO
        ),
        200,
    )
    # PRD §3.12: the concurrence moves the claim to CONCURRENCE, and once it
    # completes without disagreement the claim transitions automatically to
    # ACCEPTED, so the terminal status is what the second reviewer observes.
    assert concurred["status"] == "ACCEPTED", "the cycle closes across two distinct reviewers"


def test_payout_acceptance_embargoes_the_program_and_stops_the_unit(api):
    """PRD §3.13: "the engagement's status becomes `QUALITY_EMBARGO` and its
    `version` is incremented by 1"

    PRD §3.13: "every **SpecUnit** under the engagement whose status is `ACTIVE`
    transitions to `piece_status` `REWORK` and has its own `version` incremented by
    1"

    Design: Difficulty/transitive_cascade/payout_acceptance_embargo_cascade_depth_three
    """
    program, unit, pool, items, commits = setup_pending_embargo(
        accuracy_floor_pct=85, quorum=3, panel_size=2
    )
    read = get_program(program["id"])
    assert read["accepted_accuracy_pct"] == pytest.approx(80.0), "four PASSED of five"

    pay_commit(commits[0]["id"], 8)

    read = get_program(program["id"])
    assert read["status"] == "QUALITY_EMBARGO", "accepted accuracy 80.00 is below the 85 floor"

    live_unit = get_unit(unit["id"])
    assert live_unit["piece_status"] == "REWORK", "hop 3 reaches the unit only via the program"


def test_the_embargo_cascade_demotes_both_pending_pieces(api):
    """PRD §3.13: "for each such unit every attached **LabelingItem** whose
    `consensus_status` is `AWAITING_CONSENSUS` transitions to `consensus_status`
    `REWORK` and `item_status` `REWORK` with its `rework_cycles` incremented by 1
    and its `rework_started_at` set to the current logical clock."

    Design: Difficulty/transitive_cascade/payout_acceptance_embargo_cascade_depth_three
    """
    program, unit, pool, items, commits = setup_pending_embargo(
        accuracy_floor_pct=85, quorum=3, panel_size=2
    )
    pay_commit(commits[0]["id"], 8)

    for item in items:
        live = get_success_data(api_client.get_item(item["id"], ADMIN), 200)
        assert live["consensus_status"] == "REWORK"
        assert live["item_status"] == "REWORK"
        assert live["rework_cycles"] == 1
        assert live["rework_started_at"] is not None


def test_a_recall_returns_an_embargoed_program_to_active(api):
    """PRD §3.13: "A `PlatformAdmin` recalls the engagement out of
    `QUALITY_EMBARGO` when its accepted accuracy variant has recovered to at or
    above `accuracy_floor_pct`, which returns the status to `ACTIVE`, increments
    the `version` by 1, and recomputes `operational_restricted` and
    `open_incident_count` from the engagement's unresolved incidents. A recall
    attempted while accuracy is still below the floor is refused with
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/transitive_cascade/payout_acceptance_embargo_cascade_depth_three
    """
    program, unit, pool, items, commits = setup_pending_embargo(
        accuracy_floor_pct=85, quorum=3, panel_size=2
    )
    pay_commit(commits[0]["id"], 8)
    assert get_program(program["id"])["status"] == "QUALITY_EMBARGO"

    validate_error(
        api_client.program_state(program["id"], {"program_action": "RECALL"}, ADMIN),
        "ERR_INVALID_STATE",
        409,
    )

    # Grading a still-ungraded audit PASSED lifts the accepted variant. The
    # fifth graded audit was the FAILED one; the new PASSED audit is spread
    # onto the second piece so the first piece's weekly rotation counter stays
    # under its limit of three.
    from test_helpers.fixtures import grade_gold_audit

    for offset, piece_index in enumerate((1, 2)):
        gold = create_gold_audit(commits[piece_index], f"gold-{offset + 6:06d}")
        grade_gold_audit(gold["id"], "PASSED", items[piece_index]["id"])
    # Six PASSED of seven graded audits is 85.71, at or above the 85 floor.
    assert get_program(program["id"])["accepted_accuracy_pct"] == pytest.approx(85.71)

    recalled = get_success_data(
        api_client.program_state(program["id"], {"program_action": "RECALL"}, ADMIN), 200
    )
    assert recalled["status"] == "ACTIVE"


def test_the_embargo_fires_only_when_the_denominator_is_non_empty(api):
    """PRD §3.13: "When a payout record is accepted on an engagement whose accepted
    accuracy variant is strictly below its `accuracy_floor_pct`, and whose
    `accuracy_denominator_count` is at least 1 so that an empty denominator never
    triggers the embargo"

    Design: Difficulty/transitive_cascade/payout_acceptance_embargo_cascade_depth_three
    """
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=1, commitment_quorum=1, accuracy_floor_pct=85
    )
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    read = get_program(program["id"])
    assert read["accuracy_denominator_count"] == 0
    assert read["accepted_accuracy_pct"] == pytest.approx(0.0)

    pay_commit(commit["id"], 8)

    read = get_program(program["id"])
    assert read["status"] == "ACTIVE", "an empty denominator never triggers the embargo"


def test_the_embargo_alone_does_not_restrict_the_program_operationally(api):
    """PRD §2.5: "`operational_restricted` is true while any incident on that
    program has status `OPEN` *and* a severity that is `MAJOR` or `CATASTROPHIC`."

    Design: Difficulty/transitive_cascade/payout_acceptance_embargo_cascade_depth_three
    """
    program, unit, pool, items, commits = setup_pending_embargo(
        accuracy_floor_pct=85, quorum=3, panel_size=2
    )
    pay_commit(commits[0]["id"], 8)

    read = get_program(program["id"])
    assert read["status"] == "QUALITY_EMBARGO"
    assert read["operational_restricted"] is False, "the embargo alone raises no safety restriction"