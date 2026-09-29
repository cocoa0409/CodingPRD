"""Which rows a calculation is allowed to read, and which constants it applies.

Every figure here is decided by an input set rather than by arithmetic: a cancelled
booking, a suspended contract, a late signing and a seat count each change what the
formula is fed rather than how it divides.
"""

from test_helpers import (
    ApiErrorId,
    ROSTER_LOCK_AT,
    api_client,
    assert_instant_equals,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_performance_support_headers,
    make_scout_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _summary(contract_id):
    return validate_success(
        api_client.get_contract_obligation_summary(
            contract_id, make_performance_support_headers()
        )
    )


def test_cancelling_a_block_returns_both_its_minutes_and_its_room_slot():
    """420 minutes become 240, the freed interval is immediately rebookable, and the total returns.

    PRD: "An attendee's **scheduled minutes** for that week are the sum of `duration_minutes` over every
    block, in any team house of any organization, whose `block_status` is `SCHEDULED` or `HELD` and whose
    `starts_at` falls inside that week window and which lists that attendee — cancelled blocks are
    excluded, and the candidate block being booked is included in the sum."
    PRD: "Once a block is cancelled its minutes leave every attendee's weekly arithmetic and its interval
    stops occupying the room, so cancelling and rebooking is a legitimate way to resolve a conflict."
    PRD: "**Room conflict** pads the candidate — and only the candidate — by the facility's
    `turnaround_buffer_minutes` at each end, then compares that padded interval against the raw,
    unpadded intervals of every `SCHEDULED` or `HELD` block in the same team house."
    PRD: "Blocks may be listed with any combination of `organization_id`, `team_house_id`, `block_type`,
    `block_status`, and the interval filters `starts_from` and `starts_to`, which bound the block's
    `starts_at`."

    Design: Corner/calculations/cancelled_blocks_leave_the_weekly_total_and_free_the_room_slot
    """
    ctx = fixtures.setup_signed_player(with_team_house=True)
    coach_headers = make_coaching_staff_headers()
    fixtures.set_clock("2026-08-10T00:00:00Z")
    block_a = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-10T10:00:00Z",
        "2026-08-10T14:00:00Z",
        [ctx["player"]["id"]],
    )
    block_b = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-10T20:00:00Z",
        "2026-08-10T23:00:00Z",
        [ctx["player"]["id"]],
        block_type="REVIEW",
    )

    first = _summary(ctx["contract"]["id"])
    assert first["scheduled_minutes_this_week"] == 420
    assert first["cap_minutes"] == 2700
    assert first["streaming_minutes_this_week"] == 0
    assert first["burnout_score"] == 0

    cancelled = validate_success(
        api_client.cancel_practice_block(
            block_b["id"], {"cancel_reason": "COACH_CANCELLED"}, coach_headers
        )
    )
    assert cancelled["block_status"] == "CANCELLED"
    assert cancelled["duration_minutes"] == 180

    assert _summary(ctx["contract"]["id"])["scheduled_minutes_this_week"] == 240

    replacement = validate_success(
        api_client.create_practice_block(
            {
                "organization_id": ctx["org"]["id"],
                "team_house_id": ctx["house"]["id"],
                "block_type": "REVIEW",
                "starts_at": "2026-08-10T20:00:00Z",
                "ends_at": "2026-08-10T23:00:00Z",
                "participant_player_ids": [ctx["player"]["id"]],
            },
            coach_headers,
        ),
        201,
    )
    assert replacement["block_status"] == "SCHEDULED"
    assert replacement["duration_minutes"] == 180

    assert _summary(ctx["contract"]["id"])["scheduled_minutes_this_week"] == 420

    rows, meta = validate_paginated(
        api_client.list_practice_blocks(
            coach_headers,
            params={
                "team_house_id": ctx["house"]["id"],
                "block_status": "SCHEDULED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {block_a["id"], replacement["id"]}


def test_the_waterfall_reads_only_active_contracts_signed_before_the_event():
    """Three contracts, one eligible row, and a weight total of 4000 rather than 13500.

    PRD: "Step three fixes the eligible population: exactly those player contracts of the distributing
    organization whose `contract_status` is `ACTIVE` and whose `effective_at` is at or before the
    distribution's `tournament_end_at`."
    PRD: "Suspended contracts, terminated contracts and contracts signed after the event are all
    excluded, which changes the weight total and therefore every surviving row's share."
    PRD: "A row's `withholding_rate_bp` is 1500 when the contract's `tax_residency_code` equals the
    paying organization's `tax_jurisdiction_code` and 3000 when it does not; `withholding_cents` is
    `gross_share_cents` multiplied by that rate, divided by 10000 and rounded half up."
    PRD: "`committed_salary_cents` is the sum of `provisional_cap_charge_cents` across every one of the
    organization's player contracts whose `contract_status` is `ACTIVE` or `SUSPENDED`; because only
    frozen integers are summed, no rounding takes place."
    PRD: "The *prorated remaining term* variant first counts `remaining_season_days` as the number of
    whole days from the contract's `effective_at` to the league's `season_end_at`, discarding any
    fractional day; it then multiplies `base_salary_cents` by that day count, divides by the 365-day
    season, rounds the result half up to a whole cent, and finally adds `signing_bonus_cents` in full —
    the bonus is never prorated."

    Design: Corner/calculations/prize_allocation_input_set_excludes_suspended_and_late_effective_contracts
    """
    ctx = fixtures.setup_league_and_org()
    finance_headers = make_finance_officer_headers()
    eligible_player = fixtures.create_player(full_name="Rin Adachi")
    suspended_player = fixtures.create_player(
        full_name="Dana Whitfield", birth_date="1999-11-02"
    )
    late_player = fixtures.create_player(full_name="Ji-ho Park", birth_date="2000-07-19")

    fixtures.set_clock("2026-08-04T00:00:00Z")
    eligible_offer = fixtures.create_offer(
        ctx["org"]["id"],
        eligible_player["id"],
        base_salary_cents=4000000,
        prize_split_player_pct_bp=4000,
    )
    suspended_offer = fixtures.create_offer(
        ctx["org"]["id"],
        suspended_player["id"],
        base_salary_cents=4000000,
        prize_split_player_pct_bp=4500,
    )
    late_offer = fixtures.create_offer(
        ctx["org"]["id"],
        late_player["id"],
        base_salary_cents=4000000,
        prize_split_player_pct_bp=5000,
    )

    fixtures.set_clock("2026-08-05T00:00:00Z")
    eligible_contract = fixtures.accept_offer(
        eligible_offer["id"], eligible_player["id"], effective_at="2026-08-05T00:00:00Z"
    )
    suspended_contract = fixtures.accept_offer(
        suspended_offer["id"], suspended_player["id"], effective_at="2026-08-05T00:00:00Z"
    )
    late_contract = fixtures.accept_offer(
        late_offer["id"], late_player["id"], effective_at="2026-08-20T00:00:00Z"
    )
    assert eligible_contract["provisional_cap_charge_cents"] == 3945205
    assert suspended_contract["provisional_cap_charge_cents"] == 3945205
    assert late_contract["provisional_cap_charge_cents"] == 3780822
    fixtures.suspend_contract(suspended_contract["id"])

    distribution = fixtures.create_distribution(
        ctx["org"]["id"],
        ctx["league"]["id"],
        tournament_end_at="2026-08-10T00:00:00Z",
    )
    calculated = validate_success(
        api_client.calculate_prize_distribution(distribution["id"], finance_headers)
    )
    assert calculated["association_levy_cents"] == 250000
    assert calculated["org_share_cents"] == 3412500
    assert calculated["allocated_cents"] == 6337500
    assert calculated["unallocated_cents"] == 0
    assert calculated["withholding_total_cents"] == 950625
    assert calculated["escrow_total_cents"] == 0

    rows, meta = validate_paginated(
        api_client.list_prize_allocations(
            distribution["id"], finance_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["contract_id"] == eligible_contract["id"]
    assert row["weight_bp"] == 4000
    assert row["gross_share_cents"] == 6337500
    assert row["withholding_rate_bp"] == 1500
    assert row["withholding_cents"] == 950625
    assert row["escrow_holdback_cents"] == 0
    assert row["net_cents"] == 5386875
    assert row["allocation_status"] == "CALCULATED"

    for excluded in (suspended_contract["id"], late_contract["id"]):
        _rows, excluded_meta = validate_paginated(
            api_client.list_contract_prize_allocations(
                excluded, finance_headers, params={"limit": 10, "offset": 0}
            )
        )
        assert excluded_meta["total_count"] == 0

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], finance_headers)
    )
    assert cap_summary["prize_payable_cents"] == 3412500
    assert cap_summary["committed_salary_cents"] == 3945205 + 3945205 + 3780822


def _three_seat_candidate(ctx):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": "TRYOUT",
            "starts_at": "2026-08-10T10:00:00Z",
            "ends_at": "2026-08-10T14:00:00Z",
            "participant_player_ids": [
                ctx["player_a"]["id"],
                ctx["player_b"]["id"],
                ctx["player_c"]["id"],
            ],
        },
        make_coaching_staff_headers(),
    )


def test_seat_capacity_counts_the_candidates_own_attendees_and_admits_equality():
    """Three attendees in an empty two-seat room are refused; the same payload fits three seats.

    PRD: "Finally, the number of entries in `participant_player_ids` must not exceed the facility's
    `concurrent_seat_capacity`; a count exactly equal to capacity is allowed, and anything larger is
    refused with `ERR_FACILITY_CAPACITY_EXCEEDED` (HTTP 422)."
    PRD: "The buffer is the mandatory changeover time padded around every booking in that room; the
    seat capacity is the largest number of participants a single booking there may hold."
    PRD: "An operations manager may later adjust the facility's `name`, `turnaround_buffer_minutes` or
    `concurrent_seat_capacity`; later bookings are judged against the new values while bookings already
    on the calendar are never re-validated, and the facility's `version` advances."
    PRD: "Booking a `TRYOUT` block does double duty as a scouting action: every attendee whose
    `player_status` is `PROSPECT` or `FREE_AGENT` moves to `TRYOUT_INVITED` as the block is created."
    PRD: "The rule is deliberately permissive at the edges: a participant who owns no `PlayerContract`
    at all — a prospect or a free agent invited in to try out — is admitted without further contract
    checks, and that is exactly what makes tryout blocks for unsigned players possible."

    Design: Corner/calculations/facility_capacity_is_a_seat_count_and_not_an_interval_check
    """
    ctx = fixtures.setup_league_and_org()
    ctx["house"] = fixtures.create_team_house(
        ctx["org"]["id"], concurrent_seat_capacity=2, turnaround_buffer_minutes=60
    )
    ctx["player_a"] = fixtures.create_player(full_name="Rin Adachi")
    ctx["player_b"] = fixtures.create_player(
        full_name="Dana Whitfield", birth_date="1999-11-02"
    )
    ctx["player_c"] = fixtures.create_player(
        full_name="Ji-ho Park", birth_date="2000-07-19"
    )
    coach_headers = make_coaching_staff_headers()

    validate_error(
        _three_seat_candidate(ctx), ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED.value, 422
    )

    _rows, meta = validate_paginated(
        api_client.list_practice_blocks(
            coach_headers,
            params={"team_house_id": ctx["house"]["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0

    widened = validate_success(
        api_client.update_team_house(
            ctx["house"]["id"],
            {"concurrent_seat_capacity": 3},
            make_ops_manager_headers(ctx["org"]["id"]),
        )
    )
    assert widened["concurrent_seat_capacity"] == 3
    assert widened["turnaround_buffer_minutes"] == 60
    assert widened["version"] > ctx["house"]["version"]

    admitted = validate_success(_three_seat_candidate(ctx), 201)
    assert admitted["duration_minutes"] == 240
    assert len(admitted["participant_player_ids"]) == 3
    assert admitted["block_status"] == "SCHEDULED"

    for player in (ctx["player_a"], ctx["player_b"], ctx["player_c"]):
        refreshed = validate_success(
            api_client.get_player(player["id"], make_scout_headers())
        )
        assert refreshed["player_status"] == "TRYOUT_INVITED"


def test_the_roster_lock_flag_is_already_true_on_the_boundary_instant():
    """False at 23:59:59, true at the lock instant itself, and the league is never written.

    PRD: "`roster_lock_active` is true exactly when the current instant has reached `roster_lock_at`,
    and false while the current instant is still earlier than that."
    PRD: "It is never stored as a client-settable value; it is evaluated fresh on every read and at the
    start of every operation that a league window governs."
    PRD: "Moving the clock mutates no entity eagerly: offers do not become expired at the moment the
    clock passes their deadline, wellness holds do not lift by themselves, and no counter is recomputed
    until the next request touches the affected resource."

    Design: Corner/calculations/roster_lock_flag_flips_exactly_at_roster_lock_at
    """
    admin_headers = make_league_admin_headers()
    fixtures.set_clock("2026-08-01T00:00:00Z")
    league = fixtures.create_league(roster_lock_at=ROSTER_LOCK_AT)
    assert_instant_equals(league["roster_lock_at"], ROSTER_LOCK_AT, "League.roster_lock_at")
    baseline_version = league["version"]

    def read_flag():
        body = validate_success(api_client.get_league(league["id"], admin_headers))
        assert body["version"] == baseline_version
        return body["roster_lock_active"]

    assert read_flag() is False

    fixtures.set_clock("2026-09-14T23:59:59Z")
    assert read_flag() is False

    fixtures.set_clock("2026-09-15T00:00:00Z")
    assert read_flag() is True

    fixtures.set_clock("2026-09-16T00:00:00Z")
    assert read_flag() is True


def test_the_eighteenth_birthday_itself_already_counts_as_an_adult_year():
    """Born 2008-08-01 is 18 and not a minor; born one day later is 17 until the clock moves.

    PRD: "`age_years` is the number of whole years between the player's `birth_date` and the current
    instant, counting an anniversary falling exactly on the current date as reached — so a player whose
    eighteenth birthday is today has `age_years` of 18."
    PRD: "`is_minor` is true exactly when `age_years` is strictly less than the governing league's
    `minor_age_threshold_years`, which is 18 by default; the league used for that comparison is the
    league of the organization named in `current_organization_id` when the player has one, and otherwise
    the league of the organization named in the request being evaluated."
    PRD: "Both figures, and the consent status derived alongside them, are re-evaluated on every read or
    write that touches a player, an offer or a contract, which means a prospect scouted at 17 silently
    becomes an adult when the logical clock is moved past their birthday."
    PRD: "`guardian_consent_status` follows directly from that derivation: it is `NOT_REQUIRED` for a
    player who is not a minor, `REQUIRED` for a minor with no consent on file, and `GRANTED` once a
    guardian has recorded consent."

    Design: Corner/calculations/minor_status_boundary_is_the_eighteenth_birthday_itself
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    fixtures.create_league()
    scout_headers = make_scout_headers()

    exactly_eighteen = fixtures.create_player(
        full_name="Exactly Eighteen", birth_date="2008-08-01", region_code="US"
    )
    assert exactly_eighteen["age_years"] == 18
    assert exactly_eighteen["is_minor"] is False
    assert exactly_eighteen["guardian_consent_status"] == "NOT_REQUIRED"

    one_day_short = fixtures.create_player(
        full_name="One Day Short", birth_date="2008-08-02", region_code="US"
    )
    assert one_day_short["age_years"] == 17
    assert one_day_short["is_minor"] is True
    assert one_day_short["guardian_consent_status"] == "REQUIRED"

    fixtures.set_clock("2026-08-02T00:00:00Z")
    grown_up = validate_success(
        api_client.get_player(one_day_short["id"], scout_headers)
    )
    assert grown_up["age_years"] == 18
    assert grown_up["is_minor"] is False
    assert grown_up["guardian_consent_status"] == "NOT_REQUIRED"
    assert grown_up["version"] == one_day_short["version"]
