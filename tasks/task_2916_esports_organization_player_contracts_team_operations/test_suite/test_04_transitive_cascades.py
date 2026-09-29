"""One request, several links, each one caused by the link above it.

Completing a practice block can reach as far as a sibling booking three days
away, and executing a release reaches all the way into a sponsor's fulfilment
count.
"""

from test_helpers import (
    api_client,
    assert_instant_equals,
    fixtures,
    make_coaching_staff_headers,
    make_general_manager_headers,
    make_performance_support_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_success,
)


def _block_about_to_escalate():
    """A 1080-minute block ready to complete, a future 180-minute sibling, score at 50."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    ctx["block_a"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-10T06:00:00Z",
        "2026-08-11T00:00:00Z",
        [ctx["player"]["id"]],
    )
    ctx["block_c"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-14T10:00:00Z",
        "2026-08-14T13:00:00Z",
        [ctx["player"]["id"]],
        block_type="REVIEW",
    )
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["report"] = fixtures.file_wellness_report(
        ctx["contract"]["id"], last_self_reported_load=10, reported_streaming_minutes_7d=600
    )
    fixtures.set_clock("2026-08-11T15:00:00Z")
    return ctx


def test_completing_one_block_walks_the_whole_three_link_chain():
    """Minutes, then the escalation, then the cancellation of a booking three days out.

    PRD: "Completion moves `block_status` `SCHEDULED` → `HELD`, records any `coach_note`, and then
    runs a four-link cascade: for every attendee holding an `ACTIVE` contract, that contract's
    `season_practice_minutes` increases by the block's `duration_minutes`; because the season total
    and the trailing seven-day window have both changed, that contract's `burnout_score` is
    recomputed by the rolling method of §3.6; because the score may have crossed a threshold, the
    contract's `obligation_status` escalates to `WARNED` at 70 or to `BREACH` at 85; and because the
    obligation dimension left `COMPLIANT`, every block still `SCHEDULED` whose `starts_at` is
    strictly later than the current instant and which lists that player is cancelled with
    `cancel_reason` of `WELLNESS_HOLD`."
    PRD: "The other two reasons, `WELLNESS_HOLD` and `CONTRACT_SUSPENDED`, are written only by the
    cascades described in this section and in §3.6 and are never accepted from a client."

    Design: Difficulty/transitive_cascade/block_completion_escalates_obligation_and_cancels_future_sibling_block
    """
    ctx = _block_about_to_escalate()
    assert ctx["report"]["burnout_score"] == 50
    assert ctx["report"]["obligation_status"] == "COMPLIANT"

    held = fixtures.complete_practice_block(ctx["block_a"]["id"])
    assert held["block_status"] == "HELD"

    contract = validate_success(
        api_client.get_contract(
            ctx["contract"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert contract["season_practice_minutes"] == 1080
    assert contract["burnout_score"] == 70
    assert contract["obligation_status"] == "WARNED"
    assert contract["wellness_hold_until"] is None

    sibling = validate_success(
        api_client.get_practice_block(ctx["block_c"]["id"], make_coaching_staff_headers())
    )
    assert sibling["block_status"] == "CANCELLED"
    assert sibling["cancel_reason"] == "WELLNESS_HOLD"


def test_the_completed_block_survives_the_cancellation_sweep_it_caused():
    """The sweep only reaches future SCHEDULED bookings, so the held block keeps its minutes.

    PRD: "Both escalations cancel every block that is still `SCHEDULED` and whose `starts_at` is
    strictly later than the current instant and which lists that player, writing `cancel_reason` of
    `WELLNESS_HOLD` on each."
    PRD: "Once a block is cancelled its minutes leave every attendee's weekly arithmetic and its
    interval stops occupying the room, so cancelling and rebooking is a legitimate way to resolve a
    conflict."
    PRD: "It returns the contract's current `obligation_status`, its rolling `burnout_score` and the
    freshly-derived `season_burnout_score`, the `scheduled_minutes_this_week` and
    `streaming_minutes_this_week` that the weekly arithmetic charges for that player together with
    the resulting `cap_minutes`, the frozen `provisional_cap_charge_cents` next to the recomputed
    `final_cap_charge_cents`, and the current `wellness_hold_until`."

    Design: Difficulty/transitive_cascade/block_completion_escalates_obligation_and_cancels_future_sibling_block
    """
    ctx = _block_about_to_escalate()
    fixtures.complete_practice_block(ctx["block_a"]["id"])

    completed = validate_success(
        api_client.get_practice_block(ctx["block_a"]["id"], make_coaching_staff_headers())
    )
    assert completed["block_status"] == "HELD"
    assert completed["cancel_reason"] is None

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )
    assert summary["obligation_status"] == "WARNED"
    assert summary["scheduled_minutes_this_week"] == 1080
    assert summary["cap_minutes"] == 2700
    assert summary["streaming_minutes_this_week"] == 0


def _fulfilled_deal_and_an_approved_release():
    """Two contracts, a FULFILLED two-deliverable deal, and an APPROVED release of the second."""
    ctx = fixtures.setup_two_signed_players()
    deal_state = fixtures.setup_fulfilled_deal(
        ctx["org"]["id"],
        [ctx["contract_one"]["id"], ctx["contract_two"]["id"]],
        [ctx["player_one"]["id"], ctx["player_two"]["id"]],
    )
    ctx["deal"] = deal_state["deal"]
    ctx["assignment_one"], ctx["assignment_two"] = deal_state["assignments"]
    fixtures.set_clock("2026-08-20T00:00:00Z")
    ctx["move"] = fixtures.setup_approved_move(
        ctx["org"]["id"],
        ctx["player_two"]["id"],
        "RELEASE",
        ctx["contract_two"]["id"],
        effective_at="2026-08-20T00:00:00Z",
    )
    return ctx


def test_release_execution_terminates_the_contract_and_frees_the_player_and_the_cap():
    """Links one and two: the employment ends, the player is a free agent, the budget reopens.

    PRD: "First, the named contract's `contract_status` becomes `TERMINATED`, whether it was
    `ACTIVE` or `SUSPENDED` beforehand."
    PRD: "Second, because the contract terminated, the player's `player_status` becomes
    `FREE_AGENT`, their `current_organization_id` is cleared to null, their
    `free_agency_window_ends_at` is stamped at the current instant plus the league's
    `free_agency_cooldown_days` days, and their `last_release_organization_id` is set to the
    releasing organization — the pair that will later block a re-signing by that same organization
    while allowing any other organization to sign the player immediately."
    PRD: "A `RELEASE` runs step seven only, so its `buyout_credit_cents`, `commission_tier_bp`,
    `agent_commission_cents` and `net_to_org_cents` all stay 0 while its `released_cap_cents` is
    populated."

    Design: Difficulty/transitive_cascade/release_execution_terminates_contract_voids_deliverable_and_reverts_fulfilled_deal
    """
    ctx = _fulfilled_deal_and_an_approved_release()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])

    executed = validate_success(api_client.execute_roster_move(ctx["move"]["id"], gm_headers))
    assert executed["move_status"] == "EXECUTED"
    assert executed["buyout_credit_cents"] == 0
    assert executed["commission_tier_bp"] == 0
    assert executed["agent_commission_cents"] == 0
    assert executed["net_to_org_cents"] == 0
    assert executed["released_cap_cents"] == 9863014

    released = validate_success(api_client.get_contract(ctx["contract_two"]["id"], gm_headers))
    assert released["contract_status"] == "TERMINATED"
    kept = validate_success(api_client.get_contract(ctx["contract_one"]["id"], gm_headers))
    assert kept["contract_status"] == "ACTIVE"

    player = validate_success(
        api_client.get_player(ctx["player_two"]["id"], make_scout_headers())
    )
    assert player["player_status"] == "FREE_AGENT"
    assert player["current_organization_id"] is None
    assert player["last_release_organization_id"] == ctx["org"]["id"]
    assert_instant_equals(
        player["free_agency_window_ends_at"],
        "2026-09-03T00:00:00Z",
        "player.free_agency_window_ends_at",
    )

    organization = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert organization["committed_salary_cents"] == 12328767
    assert organization["uncommitted_salary_cents"] == 37671233
    assert organization["active_roster_count"] == 1


def test_release_execution_voids_that_contracts_deliverable_and_unfulfils_the_deal():
    """Links three and four: the void is contract-scoped and drags the deal back to ACTIVE.

    PRD: "Fourth, because the contract terminated, every one of its deliverable assignments in
    `ASSIGNED`, `SUBMITTED`, `APPROVED` or `REJECTED` moves to `VOIDED`, dropping each affected
    deal's `assigned_count` and, for previously approved rows, its `approved_count`, which reverts a
    `FULFILLED` deal to `ACTIVE`."
    PRD: "Fulfilment also bubbles back down: when a contract termination voids an approved
    deliverable and drops `approved_count` below `deliverable_count_required`, a `FULFILLED` deal
    reverts to `ACTIVE`."
    PRD: "Its `fee_share_cents` is frozen at creation as the deal's `total_fee_cents` divided by its
    `deliverable_count_required` with the fractional remainder discarded."

    Design: Difficulty/transitive_cascade/release_execution_terminates_contract_voids_deliverable_and_reverts_fulfilled_deal
    """
    ctx = _fulfilled_deal_and_an_approved_release()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    sponsor_headers = make_sponsorship_manager_headers(ctx["org"]["id"])

    assert ctx["deal"]["deal_status"] == "FULFILLED"
    assert ctx["deal"]["assigned_count"] == 2
    assert ctx["deal"]["approved_count"] == 2
    assert ctx["assignment_one"]["fee_share_cents"] == 500000
    assert ctx["assignment_two"]["fee_share_cents"] == 500000

    validate_success(api_client.execute_roster_move(ctx["move"]["id"], gm_headers))

    voided = validate_success(
        api_client.get_deliverable_assignment(ctx["assignment_two"]["id"], sponsor_headers)
    )
    assert voided["assignment_status"] == "VOIDED"
    untouched = validate_success(
        api_client.get_deliverable_assignment(ctx["assignment_one"]["id"], sponsor_headers)
    )
    assert untouched["assignment_status"] == "APPROVED"

    deal = validate_success(
        api_client.get_sponsorship_deal(ctx["deal"]["id"], sponsor_headers)
    )
    assert deal["deal_status"] == "ACTIVE"
    assert deal["assigned_count"] == 1
    assert deal["approved_count"] == 1
