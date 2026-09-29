"""Off-by-one probes on three different comparisons.

A weekly minute count, a rounded wellness index and an eligibility instant: each
one is checked at the boundary value and at the value one step beyond it, so a
comparison written with the wrong strictness fails exactly one of the pair.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_performance_support_headers,
    validate_error,
    validate_success,
)


def _week_with_300_spare_minutes():
    """2400 booked minutes of a 2700-minute cap, and a room that frees up at 17:00."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["block_a"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-10T00:00:00Z",
        "2026-08-11T16:00:00Z",
        [ctx["player"]["id"]],
    )
    return ctx


def _spare_minute_candidate(ctx, ends_at):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": "REVIEW",
            "starts_at": "2026-08-11T17:00:00Z",
            "ends_at": ends_at,
            "participant_player_ids": [ctx["player"]["id"]],
        },
        make_coaching_staff_headers(),
    )


def test_the_cap_admits_the_exact_minute_and_refuses_the_next_one():
    """2700 committed minutes are legal; 2701 are not, and the two requests differ by a minute.

    PRD: "The comparison is strictly greater-than, so committed minutes exactly equal to the cap are
    admitted and only one minute more is a violation."
    PRD: "On insertion the server derives `duration_minutes` as the number of whole minutes between
    `starts_at` and `ends_at`, stamps the booking coach's identifier into `coach_user_id`, sets
    `block_status` to `SCHEDULED` and leaves `cancel_reason` null."
    PRD: "For a player who is not a minor it is simply the league's `adult_max_weekly_minutes` —
    2,700 minutes, or forty-five hours, by default."

    Design: Difficulty/boundary_precision_check/weekly_committed_minutes_exactly_at_cap_is_admitted_one_minute_over_is_not
    """
    ctx = _week_with_300_spare_minutes()

    one_too_many = _spare_minute_candidate(ctx, "2026-08-11T22:01:00Z")
    validate_error(one_too_many, ApiErrorId.ERR_WEEKLY_HOUR_CAP_EXCEEDED.value, 422)

    exactly_at_cap = validate_success(
        _spare_minute_candidate(ctx, "2026-08-11T22:00:00Z"), 201
    )
    assert exactly_at_cap["duration_minutes"] == 300
    assert exactly_at_cap["block_status"] == "SCHEDULED"


def test_the_summary_reports_the_week_sitting_exactly_on_its_cap():
    """After the boundary booking the charged minutes and the cap are the same number.

    PRD: "A week runs from the most recent Monday at midnight UTC at or before the instant being
    examined, and spans the following seven days as a half-open window that includes its Monday and
    excludes the next."
    PRD: "A block is attributed in its entirety to the week that contains its `starts_at`, even if
    it runs past midnight on Sunday."
    PRD: "Note that the streaming figure reported here is the one the cap arithmetic actually
    charged, which is zero for a player who is not a minor."

    Design: Difficulty/boundary_precision_check/weekly_committed_minutes_exactly_at_cap_is_admitted_one_minute_over_is_not
    """
    ctx = _week_with_300_spare_minutes()
    validate_success(_spare_minute_candidate(ctx, "2026-08-11T22:00:00Z"), 201)

    # The summary charges the week that contains the instant being examined, and with no
    # candidate block that instant is the current one. Both bookings start inside the
    # Monday-anchored window [2026-08-10, 2026-08-17), so the clock has to sit in that
    # week for the summary to report them.
    fixtures.set_clock("2026-08-11T23:00:00Z")

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )
    assert summary["scheduled_minutes_this_week"] == 2700
    assert summary["cap_minutes"] == 2700
    assert summary["streaming_minutes_this_week"] == 0


def _one_held_block_of_1080_minutes():
    """1080 HELD minutes inside the rolling window, clock parked at 2026-08-11T15:00Z."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    ctx["blocks"] = fixtures.setup_held_blocks(
        ctx["org"]["id"],
        ctx["house"]["id"],
        [ctx["player"]["id"]],
        [("2026-08-10T06:00:00Z", "2026-08-11T00:00:00Z")],
        complete_at="2026-08-11T15:00:00Z",
    )
    return ctx


def _report(ctx, load, streaming_minutes):
    return api_client.file_wellness_report(
        ctx["contract"]["id"],
        {
            "last_self_reported_load": load,
            "reported_streaming_minutes_7d": streaming_minutes,
        },
        make_performance_support_headers(),
    )


def test_a_score_of_69_stays_compliant_and_70_escalates():
    """One minute short of the threshold rounds to 69 and leaves the dimension alone.

    PRD: "The three weighted components are summed at full precision, multiplied by 100, and only
    then rounded half up exactly once to a whole integer."
    PRD: "Escalation compares the rounded rolling score against two thresholds using
    greater-than-or-equal."
    PRD: "A contract sitting in `COMPLIANT` whose refreshed score is at least 70 but strictly below
    85 moves to `WARNED`."

    Design: Difficulty/boundary_precision_check/burnout_score_69_stays_compliant_and_70_escalates_to_warned
    """
    ctx = _one_held_block_of_1080_minutes()

    below = validate_success(_report(ctx, 10, 570))
    assert below["burnout_score"] == 69
    assert below["obligation_status"] == "COMPLIANT"
    assert below["wellness_hold_until"] is None

    at_threshold = validate_success(_report(ctx, 10, 600))
    assert at_threshold["burnout_score"] == 70
    assert at_threshold["obligation_status"] == "WARNED"


def test_the_threshold_escalation_stamps_neither_hold_nor_flag():
    """Crossing 70 is a warning only, so the two breach-only side effects stay absent.

    PRD: "Only entry into `BREACH` additionally stamps `wellness_hold_until` at the current instant
    plus seven days and increases the organization's `wellness_flag_count` by 1; a `WARNED`
    escalation stamps neither."
    PRD: "the streaming component contributes one fifth of the weight and is
    `reported_streaming_minutes_7d` divided by the contract's committed streaming minutes, which are
    `streaming_hours_per_week` multiplied by 60, again capped at 1, and taken as zero outright
    whenever the committed streaming minutes are zero."

    Design: Difficulty/boundary_precision_check/burnout_score_69_stays_compliant_and_70_escalates_to_warned
    """
    ctx = _one_held_block_of_1080_minutes()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    validate_success(_report(ctx, 10, 600))

    contract = validate_success(api_client.get_contract(ctx["contract"]["id"], gm_headers))
    assert contract["obligation_status"] == "WARNED"
    assert contract["wellness_hold_until"] is None
    assert contract["contract_status"] == "ACTIVE"

    organization = validate_success(api_client.get_organization(ctx["org"]["id"], gm_headers))
    assert organization["wellness_flag_count"] == 0


def _two_distributions_straddling_the_signing_instant():
    """One contract effective 2026-08-05, plus events ending one second either side of it."""
    ctx = fixtures.setup_signed_player()
    fixtures.set_clock("2026-08-21T00:00:00Z")
    ctx["one_second_early"] = fixtures.create_distribution(
        ctx["org"]["id"],
        ctx["league"]["id"],
        tournament_name="Midsummer Open",
        tournament_end_at="2026-08-04T23:59:59Z",
    )
    ctx["exactly_on_the_instant"] = fixtures.create_distribution(
        ctx["org"]["id"],
        ctx["league"]["id"],
        tournament_name="Summer Invitational",
        tournament_end_at="2026-08-05T00:00:00Z",
    )
    return ctx


def test_an_event_ending_one_second_before_the_signing_has_no_eligible_contracts():
    """The only contract was signed a second too late, so there is nothing to divide.

    PRD: "Step three fixes the eligible population: exactly those player contracts of the
    distributing organization whose `contract_status` is `ACTIVE` and whose `effective_at` is at or
    before the distribution's `tournament_end_at`."
    PRD: "If no contract is eligible there is nothing to divide and the calculation is refused with
    `ERR_NO_ELIGIBLE_CONTRACTS` (HTTP 422)."
    PRD: "A new distribution has `distribution_status` of `DRAFT`, `unallocated_cents` equal to the
    whole `gross_prize_cents`, and `association_levy_cents`, `org_share_cents`, `allocated_cents`,
    `withholding_total_cents` and `escrow_total_cents` all at 0, with `calculated_by_user_id`,
    `approved_by_user_id` and `void_reason` all null."

    Design: Difficulty/boundary_precision_check/prize_eligibility_instant_is_inclusive_at_tournament_end_at
    """
    ctx = _two_distributions_straddling_the_signing_instant()
    finance_headers = make_finance_officer_headers()

    refused = api_client.calculate_prize_distribution(
        ctx["one_second_early"]["id"], finance_headers
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_CONTRACTS.value, 422)

    stored = validate_success(
        api_client.get_prize_distribution(ctx["one_second_early"]["id"], finance_headers)
    )
    assert stored["distribution_status"] == "DRAFT"
    assert stored["allocated_cents"] == 0
    assert stored["unallocated_cents"] == 10000000
    assert stored["calculated_by_user_id"] is None


def test_an_event_ending_exactly_on_the_signing_instant_pays_the_contract():
    """The comparison is inclusive, so the same contract takes the entire player pool.

    PRD: "Step three fixes the eligible population: exactly those player contracts of the
    distributing organization whose `contract_status` is `ACTIVE` and whose `effective_at` is at or
    before the distribution's `tournament_end_at`."
    PRD: "Each row's floor share is the player pool multiplied by that row's weight, divided by the
    weight total, with the fraction discarded."
    PRD: "The remainder is the player pool less the sum of all those floor shares, and the entire
    remainder is handed to exactly one row: the eligible contract with the largest floor share, with
    ties broken by the earlier `created_at` of the contract."
    PRD: "`net_cents` is `gross_share_cents` less `withholding_cents` less
    `escrow_holdback_cents`."

    Design: Difficulty/boundary_precision_check/prize_eligibility_instant_is_inclusive_at_tournament_end_at
    """
    ctx = _two_distributions_straddling_the_signing_instant()
    finance_headers = make_finance_officer_headers()

    calculated = validate_success(
        api_client.calculate_prize_distribution(
            ctx["exactly_on_the_instant"]["id"], finance_headers
        )
    )
    assert calculated["distribution_status"] == "CALCULATED"
    assert calculated["association_levy_cents"] == 250000
    assert calculated["org_share_cents"] == 3412500
    assert calculated["allocated_cents"] == 6337500
    assert calculated["unallocated_cents"] == 0

    rows = validate_success(
        api_client.list_prize_allocations(
            ctx["exactly_on_the_instant"]["id"], finance_headers
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["contract_id"] == ctx["contract"]["id"]
    assert row["weight_bp"] == 4000
    assert row["gross_share_cents"] == 6337500
    assert row["withholding_rate_bp"] == 1500
    assert row["withholding_cents"] == 950625
    assert row["escrow_holdback_cents"] == 0
    assert row["net_cents"] == 5386875
