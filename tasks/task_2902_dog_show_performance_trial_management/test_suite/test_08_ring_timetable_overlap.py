"""Two resources contended on the same timetable, with deliberately opposite
geometries: the ring is half-open and adjacency-friendly, the judge is not."""

from test_helpers import ApiErrorId, api_client, validate_error, validate_paginated, validate_success
from test_helpers.assertions import assert_instant_equals
from test_helpers.factories import create_ring_block_payload
from test_helpers.fixtures import (
    SS_HEADERS,
    plan_ring_block,
    read_class,
    read_ring_block,
    read_show_version,
    read_slot,
    setup_scheduling_ready_show,
)


def _three_classes_on_three_judges_with_ring_one_taken_until_nine_oh_eight():
    """Three separately judged breed classes, the first already planned in ring 1."""
    context = setup_scheduling_ready_show(
        num_classes=3, judges=3, dogs_per_class=[3, 2, 2]
    )
    context["block_one"] = plan_ring_block(
        context["show"], context["classes"][0], context["slots"][0],
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
    )
    return context


def test_a_block_starting_at_the_exact_instant_another_ends_takes_the_ring():
    """Touching endpoints are legal because ring intervals are half-open.

    PRD: "A conflict exists when the candidate starts strictly before the other
    block ends and the other block starts strictly before the candidate ends;
    touching endpoints are therefore legal, and a candidate starting at exactly the
    instant another block ends is not a conflict."

    Design: Difficulty/resource_temporal_overlap/ring_occupancy_half_open_adjacency_allowed
    """
    context = _three_classes_on_three_judges_with_ring_one_taken_until_nine_oh_eight()
    assert_instant_equals(
        read_ring_block(context["block_one"])["block_end_at"],
        "2026-09-12T09:08:00Z",
        "block_end_at of the first block",
    )

    response = api_client.create_ring_block(
        create_ring_block_payload(
            context["show"]["id"], context["classes"][1]["id"], context["slots"][1]["id"],
            read_show_version(context["show"]),
            ring_number=1, block_start_at="2026-09-12T09:08:00Z",
        ),
        SS_HEADERS,
    )
    block = validate_success(response, 201)
    assert_instant_equals(block["block_start_at"], "2026-09-12T09:08:00Z", "block_start_at")
    assert block["judging_minutes_estimate"] == 5
    assert_instant_equals(block["block_end_at"], "2026-09-12T09:13:00Z", "block_end_at")
    assert block["block_status"] == "PLANNED"


def test_a_block_starting_inside_an_occupied_span_is_refused_and_leaves_its_class_open():
    """Four minutes into the adjacent block's span is a genuine intersection.

    PRD: "A conflict is refused with `ERR_RING_BLOCK_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/ring_occupancy_half_open_adjacency_allowed
    """
    context = _three_classes_on_three_judges_with_ring_one_taken_until_nine_oh_eight()
    plan_ring_block(
        context["show"], context["classes"][1], context["slots"][1],
        ring_number=1, block_start_at="2026-09-12T09:08:00Z",
    )

    response = api_client.create_ring_block(
        create_ring_block_payload(
            context["show"]["id"], context["classes"][2]["id"], context["slots"][2]["id"],
            read_show_version(context["show"]),
            ring_number=1, block_start_at="2026-09-12T09:12:00Z",
        ),
        SS_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_RING_BLOCK_OVERLAP, 409)

    rows, meta = validate_paginated(
        api_client.list_ring_blocks(
            SS_HEADERS, {"show_id": context["show"]["id"], "ring_number": 1}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert read_class(context["classes"][2])["status"] == "OPEN"


def _one_judge_two_slots_with_a_block_running_to_nine_oh_eight():
    """The same judge holds both slots and is loaded to exactly five dogs for the day."""
    context = setup_scheduling_ready_show(
        num_classes=2, judges=1, dogs_per_class=[3, 2],
        judge_overrides={"max_daily_dog_count": 5},
    )
    context["block_one"] = plan_ring_block(
        context["show"], context["classes"][0], context["slots"][0],
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
    )
    context["pinned_version"] = read_show_version(context["show"])
    return context


def test_a_twenty_nine_minute_gap_between_two_blocks_of_one_judge_is_a_violation():
    """The judge cushion is measured at or after the other block's end plus 30 minutes.

    PRD: "Two blocks are properly separated when the candidate starts at or after
    the other block's end plus 30 minutes, or the other block starts at or after the
    candidate's end plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/judge_rest_buffer_closed_interval_and_daily_dog_capacity
    """
    context = _one_judge_two_slots_with_a_block_running_to_nine_oh_eight()

    response = api_client.create_ring_block(
        create_ring_block_payload(
            context["show"]["id"], context["classes"][1]["id"], context["slots"][1]["id"],
            context["pinned_version"],
            ring_number=2, block_start_at="2026-09-12T09:37:00Z",
        ),
        SS_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_JUDGE_REST_BUFFER_VIOLATION, 409)


def test_a_gap_of_exactly_thirty_minutes_is_accepted_on_the_version_the_refusal_did_not_consume():
    """One minute later the cushion is exactly 30 minutes, which the rule allows.

    PRD: "Anything less is a violation reported as
    `ERR_JUDGE_REST_BUFFER_VIOLATION`: a gap of exactly 30 minutes is legal, a gap
    of 29 minutes is not, and two adjacent blocks with no gap at all are a violation
    even though that same adjacency is perfectly legal for ring occupancy."

    Design: Difficulty/resource_temporal_overlap/judge_rest_buffer_closed_interval_and_daily_dog_capacity
    """
    context = _one_judge_two_slots_with_a_block_running_to_nine_oh_eight()
    api_client.create_ring_block(
        create_ring_block_payload(
            context["show"]["id"], context["classes"][1]["id"], context["slots"][1]["id"],
            context["pinned_version"],
            ring_number=2, block_start_at="2026-09-12T09:37:00Z",
        ),
        SS_HEADERS,
    )

    block = validate_success(
        api_client.create_ring_block(
            create_ring_block_payload(
                context["show"]["id"], context["classes"][1]["id"],
                context["slots"][1]["id"], context["pinned_version"],
                ring_number=2, block_start_at="2026-09-12T09:38:00Z",
            ),
            SS_HEADERS,
        ),
        201,
    )
    assert_instant_equals(block["block_start_at"], "2026-09-12T09:38:00Z", "block_start_at")
    assert block["judging_minutes_estimate"] == 5
    assert_instant_equals(block["block_end_at"], "2026-09-12T09:43:00Z", "block_end_at")
    assert block["ring_number"] == 2

    rows, meta = validate_paginated(
        api_client.list_ring_blocks(
            SS_HEADERS,
            {"show_id": context["show"]["id"], "slot_id": context["slots"][1]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_both_slots_of_the_capped_judge_carry_the_judges_own_daily_ceiling():
    """Capacity is the smaller of the judge's ceiling and the system-wide 175.

    PRD: "`assigned_dog_capacity` set to the smaller of the judge's
    `max_daily_dog_count` and the system-wide ceiling of 175 dogs per judge per day."

    Design: Difficulty/resource_temporal_overlap/judge_rest_buffer_closed_interval_and_daily_dog_capacity
    """
    context = _one_judge_two_slots_with_a_block_running_to_nine_oh_eight()

    assert read_slot(context["slots"][0])["assigned_dog_capacity"] == 5
    assert read_slot(context["slots"][1])["assigned_dog_capacity"] == 5
