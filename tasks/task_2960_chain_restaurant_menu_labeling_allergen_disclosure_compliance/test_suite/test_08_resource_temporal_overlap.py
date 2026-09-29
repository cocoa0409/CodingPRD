"""Two booked resources under deliberately opposite interval semantics.

A board's display slot is keyed by establishment and board type and is booked
with half-open instants; a brand's relief slot is keyed by brand, authority and
requirement code and is booked with closed calendar dates plus a cooling buffer.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BOARD_WINDOW_CONFLICT,
    ERR_VARIANCE_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_board_state,
    assert_date_only,
    assert_fields_are_none,
    assert_instant_equals,
    date_plus_days,
    ids_of,
    validate_unpaginated,
)
from test_helpers.constants import (
    BOARD_DRIVE_THRU_BOARD,
    BOARD_PRIMARY_MENU_BOARD,
    EXTRA_REQUIREMENT_SODIUM_WARNING,
    PREEMPTION_VARIANCE_ALLOWED,
    PUBLICATION_DRAFT,
    PUBLICATION_PUBLISHED,
    REQUIREMENT_SODIUM_WARNING,
    REQUIREMENT_SUCCINCT_STATEMENT,
    TIER_ENHANCED,
    VARIANCE_COOLING_DAYS,
    VARIANCE_DECISION_GRANTED,
    VARIANCE_DECISION_OPEN_REVIEW,
    VARIANCE_GRANTED,
    VARIANCE_UNDER_REVIEW,
)
from test_helpers.factories import board_publish_payload, variance_decision_payload
from test_helpers.fixtures import (
    BoardBundle,
    Env,
    ItemBundle,
    add_listing,
    certified_sandwich,
    create_board,
    decide_variance,
    draft_and_publish_packet,
    file_variance,
    listed_board,
    publish_board,
    seed_registry,
)

AUGUST_OPENS = "2026-08-01T00:00:00Z"
AUGUST_CLOSES = "2026-09-01T00:00:00Z"
SEPTEMBER_CLOSES = "2026-09-15T00:00:00Z"
INSIDE_AUGUST_OPENS = "2026-08-15T00:00:00Z"
INSIDE_AUGUST_CLOSES = "2026-08-20T00:00:00Z"
OPEN_ENDED_OPENS = "2026-09-20T00:00:00Z"
AFTER_THE_OPEN_END = "2026-10-01T00:00:00Z"


# ---------------------------------------------------------------------------
# One unit, one live August window, three boards waiting to publish
# ---------------------------------------------------------------------------
def _live_august_window_and_three_drafts(
    api: ApiClient,
) -> Tuple[Env, ItemBundle, BoardBundle, BoardBundle, BoardBundle]:
    env = seed_registry(
        api, code="TX-VAR", name="Texas", unit_label="TX-0001",
        unit_label_prefix="TX-B",
    )
    item = certified_sandwich(env)
    draft_and_publish_packet(env)

    board_a = listed_board(env, item.item_id)
    publish_board(
        env, board_a.board_id, effective_from=AUGUST_OPENS, effective_to=AUGUST_CLOSES
    )
    board_b = listed_board(env, item.item_id)
    board_c = listed_board(env, item.item_id)
    return env, item, board_a, board_b, board_c


def test_a_window_beginning_at_a_live_windows_exclusive_end_is_accepted(api):
    """PRD §3.7: "a window includes its `effective_from` instant and excludes its
    `effective_to` instant, so a window that begins exactly at another window's
    `effective_to` is accepted, with no buffer required between them."

    Design: Difficulty/resource_temporal_overlap/board_display_windows_half_open_per_establishment_and_board_type
    """
    env, _item, _board_a, board_b, _board_c = _live_august_window_and_three_drafts(api)

    published = validate_unpaginated(
        env.api.publish_menu_board(
            board_b.board_id,
            board_publish_payload(
                effective_from=AUGUST_CLOSES, effective_to=SEPTEMBER_CLOSES
            ),
            env.publisher,
        )
    )

    assert published["publication_status"] == PUBLICATION_PUBLISHED
    assert_instant_equals(published["effective_from"], AUGUST_CLOSES, "effective_from")
    assert_instant_equals(published["effective_to"], SEPTEMBER_CLOSES, "effective_to")


def test_a_window_strictly_inside_a_live_window_is_refused(api):
    """PRD §2.6 rung 32: "The requested display window does not overlap the
    window of another published board of the same establishment and board type,
    else `ERR_BOARD_WINDOW_CONFLICT`. Applies to board publication."

    Design: Difficulty/resource_temporal_overlap/board_display_windows_half_open_per_establishment_and_board_type
    """
    env, _item, _board_a, _board_b, board_c = _live_august_window_and_three_drafts(api)

    validate_error(
        env.api.publish_menu_board(
            board_c.board_id,
            board_publish_payload(
                effective_from=INSIDE_AUGUST_OPENS, effective_to=INSIDE_AUGUST_CLOSES
            ),
            env.publisher,
        ),
        ERR_BOARD_WINDOW_CONFLICT,
        409,
    )

    refused = env.read_board(board_c.board_id)
    assert_board_state(refused, publication_status=PUBLICATION_DRAFT)
    assert_fields_are_none(
        refused, ["effective_from", "effective_to"], "the refused board"
    )


def test_the_identical_window_on_another_board_type_is_a_separate_slot(api):
    """PRD §3.7: "if the resulting window overlaps the window of another board of
    the same establishment and the same `board_type` whose `publication_status`
    is `PUBLISHED`, it fails with `ERR_BOARD_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/board_display_windows_half_open_per_establishment_and_board_type
    """
    env, item, _board_a, _board_b, _board_c = _live_august_window_and_three_drafts(api)

    drive_thru = create_board(env, board_type=BOARD_DRIVE_THRU_BOARD)
    add_listing(env, drive_thru.board_id, item.item_id)

    published = validate_unpaginated(
        env.api.publish_menu_board(
            drive_thru.board_id,
            board_publish_payload(
                effective_from=AUGUST_OPENS, effective_to=AUGUST_CLOSES
            ),
            env.publisher,
        )
    )

    assert published["board_type"] == BOARD_DRIVE_THRU_BOARD
    assert published["publication_status"] == PUBLICATION_PUBLISHED
    assert_instant_equals(published["effective_from"], AUGUST_OPENS, "effective_from")


def test_an_open_ended_window_closes_the_slot_to_every_later_window(api):
    """PRD §3.7: "a null or omitted `effective_to` means an open-ended window,
    and once such a window exists no later window can be published on the same
    `establishment_id` and `board_type`."

    Design: Difficulty/resource_temporal_overlap/board_display_windows_half_open_per_establishment_and_board_type
    """
    env, item, _board_a, board_b, board_c = _live_august_window_and_three_drafts(api)
    publish_board(
        env, board_b.board_id, effective_from=AUGUST_CLOSES,
        effective_to=SEPTEMBER_CLOSES,
    )

    open_ended = validate_unpaginated(
        env.api.publish_menu_board(
            board_c.board_id,
            board_publish_payload(effective_from=OPEN_ENDED_OPENS),
            env.publisher,
        )
    )
    assert_instant_equals(
        open_ended["effective_from"], OPEN_ENDED_OPENS, "effective_from"
    )
    assert open_ended["effective_to"] is None

    fifth = listed_board(env, item.item_id)
    validate_error(
        env.api.publish_menu_board(
            fifth.board_id,
            board_publish_payload(effective_from=AFTER_THE_OPEN_END),
            env.publisher,
        ),
        ERR_BOARD_WINDOW_CONFLICT,
        409,
    )

    rows, _meta = validate_paginated(
        env.api.list_menu_boards(
            env.officer,
            params={
                "establishment_id": env.establishment_id,
                "board_type": BOARD_PRIMARY_MENU_BOARD,
                "publication_status": PUBLICATION_PUBLISHED,
            },
        )
    )
    assert len(rows) == 3
    assert fifth.board_id not in ids_of(rows)


# ---------------------------------------------------------------------------
# One relief slot per requirement code, with a cooling buffer between grants
# ---------------------------------------------------------------------------
RELIEF_ONE_STARTS = "2026-09-01"
RELIEF_ONE_ENDS = "2026-09-30"
RELIEF_TWO_STARTS_TOO_SOON = "2026-10-07"
RELIEF_TWO_STARTS_CLEAR = "2026-10-08"
RELIEF_TWO_ENDS = "2026-10-31"
SODIUM_RELIEF_STARTS = "2026-09-15"
SODIUM_RELIEF_ENDS = "2026-09-20"


def _one_grant_and_two_reviews(api: ApiClient) -> Dict[str, Any]:
    """A granted September statement relief, plus two requests under review."""
    env = seed_registry(
        api,
        code="NY-VAR",
        name="New York",
        preemption_mode=PREEMPTION_VARIANCE_ALLOWED,
        extra_requirement=EXTRA_REQUIREMENT_SODIUM_WARNING,
        enforcement_tier=TIER_ENHANCED,
        unit_count=1,
        unit_label="NY-0001",
        sodium_warning_threshold_mg=2300,
    )
    first = file_variance(
        env,
        REQUIREMENT_SUCCINCT_STATEMENT,
        requested_start_date=RELIEF_ONE_STARTS,
        requested_end_date=RELIEF_ONE_ENDS,
        justification="September wording transition",
    )
    decide_variance(env, first["id"], VARIANCE_DECISION_OPEN_REVIEW)
    decide_variance(env, first["id"], VARIANCE_DECISION_GRANTED)

    second = file_variance(
        env,
        REQUIREMENT_SUCCINCT_STATEMENT,
        requested_start_date=RELIEF_TWO_STARTS_TOO_SOON,
        requested_end_date=RELIEF_TWO_ENDS,
        justification="Extension of the wording transition into October",
    )
    decide_variance(env, second["id"], VARIANCE_DECISION_OPEN_REVIEW)

    third = file_variance(
        env,
        REQUIREMENT_SODIUM_WARNING,
        requested_start_date=SODIUM_RELIEF_STARTS,
        requested_end_date=SODIUM_RELIEF_ENDS,
        justification="Icon artwork reprint pending for the sodium warning",
    )
    decide_variance(env, third["id"], VARIANCE_DECISION_OPEN_REVIEW)

    return {"env": env, "first": first, "second": second, "third": third}


def _attempt_grant(env: Env, variance_id: str, starts: str, ends: str, note: str):
    return env.api.decide_variance_request(
        variance_id,
        variance_decision_payload(
            decision=VARIANCE_DECISION_GRANTED,
            decision_note=note,
            effective_start_date=starts,
            effective_end_date=ends,
        ),
        env.regulator,
    )


def test_a_grant_defaults_its_covered_interval_from_the_request(api):
    """PRD §3.8: "The granted window is written from `effective_start_date` and
    `effective_end_date` in the decision payload, each defaulting to the
    corresponding `requested_start_date` or `requested_end_date` when omitted".

    Design: Difficulty/resource_temporal_overlap/variance_windows_closed_with_seven_day_cooling_buffer_per_requirement
    """
    world = _one_grant_and_two_reviews(api)
    env = world["env"]

    granted = env.read_variance(world["first"]["id"])
    assert granted["status"] == VARIANCE_GRANTED
    assert_date_only(granted["effective_start_date"], RELIEF_ONE_STARTS)
    assert_date_only(granted["effective_end_date"], RELIEF_ONE_ENDS)


def test_a_start_exactly_seven_days_after_the_prior_end_is_refused(api):
    """PRD §3.8: "for every other variance request of the same `brand_id`, the
    same `jurisdiction_id` and the same `requirement_code` whose `status` is
    `GRANTED`, the new grant's `effective_start_date` must fall" more than seven
    days after that request's `effective_end_date`. "A start exactly seven days
    after an existing grant's end is refused with `ERR_VARIANCE_WINDOW_CONFLICT`;
    eight days after is accepted."

    Design: Difficulty/resource_temporal_overlap/variance_windows_closed_with_seven_day_cooling_buffer_per_requirement
    """
    world = _one_grant_and_two_reviews(api)
    env = world["env"]

    assert date_plus_days(RELIEF_ONE_ENDS, VARIANCE_COOLING_DAYS) == (
        RELIEF_TWO_STARTS_TOO_SOON
    )
    validate_error(
        _attempt_grant(
            env,
            world["second"]["id"],
            RELIEF_TWO_STARTS_TOO_SOON,
            RELIEF_TWO_ENDS,
            "Extension as requested",
        ),
        ERR_VARIANCE_WINDOW_CONFLICT,
        409,
    )

    refused = env.read_variance(world["second"]["id"])
    assert refused["status"] == VARIANCE_UNDER_REVIEW
    assert_fields_are_none(
        refused,
        ["effective_start_date", "effective_end_date"],
        "the refused variance request",
    )


def test_a_contained_window_under_another_requirement_code_is_a_separate_slot(api):
    """PRD §3.8: "consecutive grants must be separated by a cooling buffer."
    The buffer is scoped to "the same `brand_id`, the same `jurisdiction_id` and
    the same `requirement_code`".

    Design: Difficulty/resource_temporal_overlap/variance_windows_closed_with_seven_day_cooling_buffer_per_requirement
    """
    world = _one_grant_and_two_reviews(api)
    env = world["env"]

    granted = validate_unpaginated(
        env.api.decide_variance_request(
            world["third"]["id"],
            variance_decision_payload(
                decision=VARIANCE_DECISION_GRANTED,
                decision_note="Sodium icon relief granted",
            ),
            env.regulator,
        )
    )

    assert granted["requirement_code"] == REQUIREMENT_SODIUM_WARNING
    assert granted["status"] == VARIANCE_GRANTED
    assert_date_only(granted["effective_start_date"], SODIUM_RELIEF_STARTS)
    assert_date_only(granted["effective_end_date"], SODIUM_RELIEF_ENDS)


def test_one_more_day_clears_the_cooling_buffer(api):
    """PRD §3.8: "A start exactly seven days after an existing grant's end is
    refused with `ERR_VARIANCE_WINDOW_CONFLICT`; eight days after is accepted."

    Design: Difficulty/resource_temporal_overlap/variance_windows_closed_with_seven_day_cooling_buffer_per_requirement
    """
    world = _one_grant_and_two_reviews(api)
    env = world["env"]
    validate_error(
        _attempt_grant(
            env,
            world["second"]["id"],
            RELIEF_TWO_STARTS_TOO_SOON,
            RELIEF_TWO_ENDS,
            "Extension as requested",
        ),
        ERR_VARIANCE_WINDOW_CONFLICT,
        409,
    )
    decide_variance(env, world["third"]["id"], VARIANCE_DECISION_GRANTED)

    granted = validate_unpaginated(
        _attempt_grant(
            env,
            world["second"]["id"],
            RELIEF_TWO_STARTS_CLEAR,
            RELIEF_TWO_ENDS,
            "Extension shifted one day to clear the cooling buffer",
        )
    )
    assert granted["status"] == VARIANCE_GRANTED
    assert_date_only(granted["effective_start_date"], RELIEF_TWO_STARTS_CLEAR)
    assert_date_only(granted["effective_end_date"], RELIEF_TWO_ENDS)

    rows, _meta = validate_paginated(
        env.api.list_brand_variance_requests(
            env.brand_id, env.officer, params={"status": VARIANCE_GRANTED}
        )
    )
    assert len(rows) == 3
    assert set(ids_of(rows)) == {
        world["first"]["id"],
        world["second"]["id"],
        world["third"]["id"],
    }
