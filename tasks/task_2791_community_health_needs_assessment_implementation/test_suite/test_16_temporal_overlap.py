"""Temporal resources: the facilitator's exclusive buffer and the pledge's per-instant cap."""

from test_helpers import (
    ApiErrorId,
    CommitmentStatus,
    FundingState,
    InterviewStatus,
    Sector,
    add_agreement,
    add_commitment,
    add_internal_party,
    add_interview,
    add_partner_party,
    build_scenario,
    execute_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def _partner_with_executed_agreement(api, sc):
    """A partner party plus an agreement both sides have signed."""
    party_id = add_partner_party(api)["id"]
    agreement_id = add_agreement(api, sc.cycle_id, party_id)["id"]
    execute_agreement(api, agreement_id, party_id)
    return {"party_id": party_id, "agreement_id": agreement_id}



def test_a_session_butting_onto_an_existing_one_conflicts_but_thirty_minutes_later_does_not(api):
    """PRD §3.3: "Both comparisons are strict, which fixes the boundary precisely:
    a requested session beginning exactly at the instant an existing session ends
    does conflict, and so does one beginning 29 minutes later, while a requested
    session beginning exactly 30 minutes after an existing session ends does not
    conflict and is accepted."

    Design: Difficulty/resource_temporal_overlap/interview_adjacent_window_rejected_by_thirty_minute_facilitator_buffer
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")

    validate_error(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                sc.facilitator_party_id,
                organization_name="Eastside Public Health District",
                sector=Sector.PUBLIC_HEALTH_AGENCY,
                starts_at="2026-04-06T15:00:00Z",
                ends_at="2026-04-06T16:00:00Z",
            )
        ),
        ApiErrorId.FACILITATOR_WINDOW_CONFLICT,
    )

    accepted = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Eastside Public Health District",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-06T15:30:00Z",
        ends_at="2026-04-06T16:30:00Z",
    )
    assert accepted["status"] == InterviewStatus.SCHEDULED


def test_the_buffer_is_scoped_to_one_facilitator_and_to_every_one_of_its_sessions(api):
    """PRD §3.3: "The occupancy set for a facilitator is every session sharing the
    requested `facilitator_party_id` whose `status` is `SCHEDULED` or `COMPLETED`,
    taken across every cycle and not merely the cycle being scheduled; cancelled
    sessions leave the set entirely and free their slot."

    Design: Difficulty/resource_temporal_overlap/interview_adjacent_window_rejected_by_thirty_minute_facilitator_buffer
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")
    second_facilitator = add_internal_party(api, name="Eastside Field Team")["id"]

    add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Eastside Public Health District",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-06T15:30:00Z",
        ends_at="2026-04-06T16:30:00Z",
    )

    # The window rejected for the first facilitator is free for another party.
    other = add_interview(
        api,
        sc.cycle_id,
        second_facilitator,
        organization_name="Riverbend Unified School District",
        sector=Sector.SCHOOL_DISTRICT,
        starts_at="2026-04-06T15:00:00Z",
        ends_at="2026-04-06T16:00:00Z",
    )
    assert other["status"] == InterviewStatus.SCHEDULED

    # 16:59 leaves 29 minutes after the 15:30-16:30 session, which is not enough.
    validate_error(
        api.create_interview(
            F.interview_payload(
                sc.cycle_id,
                sc.facilitator_party_id,
                organization_name="Riverbend Interfaith Council",
                sector=Sector.FAITH_BASED,
                starts_at="2026-04-06T16:59:00Z",
                ends_at="2026-04-06T17:59:00Z",
            )
        ),
        ApiErrorId.FACILITATOR_WINDOW_CONFLICT,
    )

    rows, _meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id))
    assert len(rows) == 3
    assert sc.cycle()["completed_interview_count"] == 0


def test_the_same_pledge_funds_two_adjacent_disjoint_windows(api):
    """PRD §3.6: "Two windows overlap when the requested `effective_from` falls
    strictly before a sibling's `effective_to` *and* that sibling's
    `effective_from` falls strictly before the requested `effective_to`; there is
    no buffer, so exactly adjacent windows — one beginning on the very day another
    ends — do not overlap and do not accumulate, and the same pledge may
    legitimately be spent again in a later, disjoint window."

    Design: Difficulty/resource_temporal_overlap/partnership_pledge_reused_across_disjoint_windows_but_capped_within_overlap
    """
    sc = build_scenario(
        api, stage="STRATEGY_WITH_OBJECTIVE", strategy_overrides={"authorized_budget_cents": 9000000}
    )
    partner = _partner_with_executed_agreement(api, sc)

    first = add_commitment(
        api,
        sc.strategy_id,
        partner["party_id"],
        partner["agreement_id"],
        fte_bp=1000,
        funding_cents=1500000,
        effective_from="2026-10-01",
        effective_to="2027-01-01",
    )
    assert first["status"] == CommitmentStatus.PENDING

    # Starts exactly on the first window's exclusive end, so the two are disjoint.
    second = add_commitment(
        api,
        sc.strategy_id,
        partner["party_id"],
        partner["agreement_id"],
        fte_bp=1000,
        funding_cents=1500000,
        effective_from="2027-01-01",
        effective_to="2027-04-01",
    )
    assert second["status"] == CommitmentStatus.PENDING

    agreement = validate_success(api.get_agreement(partner["agreement_id"]))
    assert agreement["pledged_cents"] == C.PLEDGED_CENTS
    assert agreement["funded_cents"] == 0
    assert agreement["funding_state"] == FundingState.PLEDGED


def test_a_window_straddling_both_siblings_exceeds_the_pledge(api):
    """PRD §3.6: "taking every sibling commitment on the same agreement whose
    `status` is `PENDING` or `COMMITTED` and whose window overlaps the requested
    one, the requested `funding_cents` plus the sum of those siblings'
    `funding_cents` must not exceed the agreement's `pledged_cents`, or the create
    fails with `ERR_PARTNERSHIP_PLEDGE_WINDOW_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/partnership_pledge_reused_across_disjoint_windows_but_capped_within_overlap
    """
    sc = build_scenario(
        api, stage="STRATEGY_WITH_OBJECTIVE", strategy_overrides={"authorized_budget_cents": 9000000}
    )
    partner = _partner_with_executed_agreement(api, sc)
    for effective_from, effective_to in (
        ("2026-10-01", "2027-01-01"),
        ("2027-01-01", "2027-04-01"),
    ):
        add_commitment(
            api,
            sc.strategy_id,
            partner["party_id"],
            partner["agreement_id"],
            fte_bp=1000,
            funding_cents=1500000,
            effective_from=effective_from,
            effective_to=effective_to,
        )

    # 600000 + 1500000 + 1500000 = 3600000 against a 2000000 pledge.
    validate_error(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id,
                partner["party_id"],
                partner["agreement_id"],
                fte_bp=1000,
                funding_cents=600000,
                effective_from="2026-12-01",
                effective_to="2027-02-01",
            )
        ),
        ApiErrorId.PARTNERSHIP_PLEDGE_WINDOW_EXCEEDED,
    )

    # A later disjoint window is accepted again: the cap is per instant.
    later = add_commitment(
        api,
        sc.strategy_id,
        partner["party_id"],
        partner["agreement_id"],
        fte_bp=1000,
        funding_cents=500000,
        effective_from="2027-04-01",
        effective_to="2027-07-01",
    )
    assert later["status"] == CommitmentStatus.PENDING

    assert sc.strategy()["budget_available_cents"] == 5500000
    assert validate_success(api.get_party(partner["party_id"]))["committed_fte_bp"] == 3000
    rows, _meta = validate_paginated(api.list_commitments(strategy_id=sc.strategy_id))
    assert len(rows) == 3


def test_a_commitment_end_past_the_day_after_term_end_escapes_the_term(api):
    """PRD §3.6: "`effective_from` must be on or after `term_start`, and
    `effective_to` must be on or before the day *after* `term_end`, because
    `term_end` is an inclusive covered day while `effective_to` is exclusive."

    Design: Difficulty/resource_temporal_overlap/partnership_pledge_reused_across_disjoint_windows_but_capped_within_overlap
    """
    sc = build_scenario(
        api, stage="STRATEGY_WITH_OBJECTIVE", strategy_overrides={"authorized_budget_cents": 9000000}
    )
    partner = _partner_with_executed_agreement(api, sc)

    # term_end is 2027-08-31, so 2027-09-01 is the last acceptable exclusive end.
    validate_error(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id,
                partner["party_id"],
                partner["agreement_id"],
                fte_bp=1000,
                funding_cents=100000,
                effective_from="2027-08-01",
                effective_to="2027-09-02",
            )
        ),
        ApiErrorId.COMMITMENT_OUTSIDE_TERM,
    )

    accepted = add_commitment(
        api,
        sc.strategy_id,
        partner["party_id"],
        partner["agreement_id"],
        fte_bp=1000,
        funding_cents=100000,
        effective_from="2027-08-01",
        effective_to="2027-09-01",
    )
    assert accepted["effective_to"] == "2027-09-01"
