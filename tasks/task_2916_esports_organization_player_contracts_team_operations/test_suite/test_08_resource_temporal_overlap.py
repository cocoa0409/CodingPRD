"""Two contended resources, two different interval rules.

The room pads the candidate by its changeover on both sides; the person pads
nothing at all and is contended across every house in the league. The same pair of
instants is therefore illegal for a room and legal for a player.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_coaching_staff_headers,
    make_performance_support_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _house_occupied_until_noon():
    """Two signed players and one 10:00-to-12:00 block in a 60-minute-buffer house."""
    ctx = fixtures.setup_two_signed_players(with_team_house=True)
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["block_a"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-12T10:00:00Z",
        "2026-08-12T12:00:00Z",
        [ctx["player_one"]["id"]],
        block_type="INDIVIDUAL",
    )
    return ctx


def _room_candidate(ctx, starts_at, ends_at):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house"]["id"],
            "block_type": "INDIVIDUAL",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_player_ids": [ctx["player_two"]["id"]],
        },
        make_coaching_staff_headers(),
    )


def test_the_room_needs_the_whole_buffer_and_grants_it_on_the_boundary_minute():
    """12:59 conflicts because its padded start precedes the existing end; 13:00 does not.

    PRD: "**Room conflict** pads the candidate — and only the candidate — by the facility's
    `turnaround_buffer_minutes` at each end, then compares that padded interval against the raw,
    unpadded intervals of every `SCHEDULED` or `HELD` block in the same team house."
    PRD: "An overlap exists when the padded interval starts strictly before an existing block ends
    and that existing block starts strictly before the padded interval ends; where it does, the
    booking is refused with `ERR_FACILITY_SLOT_CONFLICT` (HTTP 409)."
    PRD: "Padding only the candidate is intentional — padding both sides would double-count the
    changeover — so a block that starts exactly `turnaround_buffer_minutes` after another block in
    that room ends is allowed, while one minute earlier conflicts."

    Design: Difficulty/resource_temporal_overlap/team_house_slot_needs_full_turnaround_buffer_between_blocks
    """
    ctx = _house_occupied_until_noon()

    one_minute_early = _room_candidate(ctx, "2026-08-12T12:59:00Z", "2026-08-12T14:59:00Z")
    validate_error(one_minute_early, ApiErrorId.ERR_FACILITY_SLOT_CONFLICT.value, 409)

    on_the_boundary = validate_success(
        _room_candidate(ctx, "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z"), 201
    )
    assert on_the_boundary["block_status"] == "SCHEDULED"
    assert on_the_boundary["duration_minutes"] == 120
    assert on_the_boundary["team_house_id"] == ctx["house"]["id"]


def test_the_refused_room_candidate_left_the_house_calendar_untouched():
    """Only two bookings exist in the room, and neither of them lists the incumbent's partner.

    PRD: "Blocks may be listed with any combination of `organization_id`, `team_house_id`,
    `block_type`, `block_status`, and the interval filters `starts_from` and `starts_to`, which bound
    the block's `starts_at`."
    PRD: "**Participant conflict** applies no padding whatsoever, because the changeover belongs to
    the room and not to the person: an attendee may not already appear on a `SCHEDULED` or `HELD`
    block, in any house of any organization, whose raw interval overlaps the candidate's raw interval
    on the same strictly-before comparison, and if one does the booking is refused with
    `ERR_PLAYER_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/team_house_slot_needs_full_turnaround_buffer_between_blocks
    """
    ctx = _house_occupied_until_noon()
    validate_error(
        _room_candidate(ctx, "2026-08-12T12:59:00Z", "2026-08-12T14:59:00Z"),
        ApiErrorId.ERR_FACILITY_SLOT_CONFLICT.value,
        409,
    )
    accepted = validate_success(
        _room_candidate(ctx, "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z"), 201
    )

    rows, _meta = validate_paginated(
        api_client.list_practice_blocks(
            make_coaching_staff_headers(),
            params={"team_house_id": ctx["house"]["id"]},
        )
    )
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {ctx["block_a"]["id"], accepted["id"]}
    assert accepted["participant_player_ids"] == [ctx["player_two"]["id"]]


def _player_busy_until_noon_in_house_one():
    """One signed player, two 60-minute-buffer houses, one 10:00-to-12:00 block in house one."""
    ctx = fixtures.setup_signed_player(with_team_house=True)
    ctx["house_two"] = fixtures.create_team_house(ctx["org"]["id"], name="Vanguard Annex")
    fixtures.set_clock("2026-08-09T00:00:00Z")
    ctx["block_a"] = fixtures.create_practice_block(
        ctx["org"]["id"],
        ctx["house"]["id"],
        "2026-08-12T10:00:00Z",
        "2026-08-12T12:00:00Z",
        [ctx["player"]["id"]],
        block_type="INDIVIDUAL",
    )
    return ctx


def _second_house_candidate(ctx, starts_at, ends_at):
    return api_client.create_practice_block(
        {
            "organization_id": ctx["org"]["id"],
            "team_house_id": ctx["house_two"]["id"],
            "block_type": "REVIEW",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_player_ids": [ctx["player"]["id"]],
        },
        make_coaching_staff_headers(),
    )


def test_the_player_is_contended_across_houses_but_may_go_back_to_back():
    """One overlapping minute in another house is refused; starting exactly at noon is not.

    PRD: "**Participant conflict** applies no padding whatsoever, because the changeover belongs to
    the room and not to the person: an attendee may not already appear on a `SCHEDULED` or `HELD`
    block, in any house of any organization, whose raw interval overlaps the candidate's raw interval
    on the same strictly-before comparison, and if one does the booking is refused with
    `ERR_PLAYER_DOUBLE_BOOKED` (HTTP 409)."
    PRD: "Back-to-back blocks where one starts exactly as the other ends are therefore fine for a
    player even when the same pair would violate the room's buffer."
    PRD: "A player's cap is global, not per organization."

    Design: Difficulty/resource_temporal_overlap/player_double_booking_uses_exact_intervals_across_houses_with_no_buffer
    """
    ctx = _player_busy_until_noon_in_house_one()

    overlapping = _second_house_candidate(ctx, "2026-08-12T11:59:00Z", "2026-08-12T13:59:00Z")
    validate_error(overlapping, ApiErrorId.ERR_PLAYER_DOUBLE_BOOKED.value, 409)

    back_to_back = validate_success(
        _second_house_candidate(ctx, "2026-08-12T12:00:00Z", "2026-08-12T14:00:00Z"), 201
    )
    assert back_to_back["block_status"] == "SCHEDULED"
    assert back_to_back["team_house_id"] == ctx["house_two"]["id"]
    assert back_to_back["duration_minutes"] == 120


def test_both_of_the_players_blocks_are_charged_to_the_same_week():
    """The two adjacent bookings sit in different rooms and in one weekly window.

    PRD: "An attendee's **scheduled minutes** for that week are the sum of `duration_minutes` over
    every block, in any team house of any organization, whose `block_status` is `SCHEDULED` or `HELD`
    and whose `starts_at` falls inside that week window and which lists that attendee — cancelled
    blocks are excluded, and the candidate block being booked is included in the sum."
    PRD: "For a player who is not a minor it is simply the league's `adult_max_weekly_minutes` —
    2,700 minutes, or forty-five hours, by default."

    Design: Difficulty/resource_temporal_overlap/player_double_booking_uses_exact_intervals_across_houses_with_no_buffer
    """
    ctx = _player_busy_until_noon_in_house_one()
    validate_error(
        _second_house_candidate(ctx, "2026-08-12T11:59:00Z", "2026-08-12T13:59:00Z"),
        ApiErrorId.ERR_PLAYER_DOUBLE_BOOKED.value,
        409,
    )
    validate_success(
        _second_house_candidate(ctx, "2026-08-12T12:00:00Z", "2026-08-12T14:00:00Z"), 201
    )

    # The summary charges the week that contains the instant being examined, and with no
    # candidate block that instant is the current one. Both bookings start inside the
    # Monday-anchored window [2026-08-10, 2026-08-17), so the clock has to sit in that
    # week for the summary to report them.
    fixtures.set_clock("2026-08-12T09:00:00Z")

    summary = validate_success(
        api_client.get_contract_obligation_summary(
            ctx["contract"]["id"], make_performance_support_headers()
        )
    )
    assert summary["scheduled_minutes_this_week"] == 240
    assert summary["cap_minutes"] == 2700
