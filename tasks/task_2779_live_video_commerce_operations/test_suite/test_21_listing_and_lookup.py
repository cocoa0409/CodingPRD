"""Reverse-lookup collections, their windows and their single-resource reads."""

from test_helpers import (
    CLOCK_EPOCH,
    MERCHANDISER,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_lineup_slot,
    build_scenario,
    create_offer,
    create_slot,
    read_slot,
    set_clock,
    validate_error,
    validate_paginated,
)


def _show_with_three_segments():
    """A DRAFT show whose lineup holds three segments on the same product."""
    scenario = build_scenario(
        with_booking=False,
        with_disclosure=False,
        slots=[
            {
                "slot_sequence": 1,
                "planned_start_at": "2026-08-10T18:05:00Z",
                "planned_end_at": "2026-08-10T18:35:00Z",
                "planned_qty": 20,
            }
        ],
        offers=[],
        channels=[],
    )
    second = create_slot(
        scenario.show_id,
        scenario.product_id,
        slot_sequence=2,
        planned_start_at="2026-08-10T18:40:00Z",
        planned_end_at="2026-08-10T18:50:00Z",
        planned_qty=5,
    )
    third = create_slot(
        scenario.show_id,
        scenario.product_id,
        slot_sequence=3,
        planned_start_at="2026-08-10T18:55:00Z",
        planned_end_at="2026-08-10T19:05:00Z",
        planned_qty=5,
    )
    scenario.slots.extend([second, third])
    return scenario


def test_first_page_of_a_shows_lineup_reports_rows_beyond_the_window(api):
    """Asking for two segments of a three-segment lineup returns two rows, still
    counts all three, and says more remain.

    PRD 2.3: "List responses populate four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values used for the query,
    `total_count` is the number of rows matching the filters before the window is
    applied, and `has_more` is true when rows remain beyond the returned window."
    PRD 2.6: "lineup slots by `show_id` and `product_id`"

    Design: Corner/entities/lineup_slots_listing_paginates_by_show
    """
    scenario = _show_with_three_segments()

    rows, meta = validate_paginated(
        api.list_lineup_slots(
            MERCHANDISER, params={"show_id": scenario.show_id, "limit": 2, "offset": 0}
        )
    )

    assert len(rows) == 2, "the window returns exactly two of the three segments"
    assert meta["limit"] == 2, "limit echoes the effective value"
    assert meta["offset"] == 0, "offset echoes the effective value"
    assert meta["total_count"] == 3, "total_count counts matches before the window"
    assert meta["has_more"] is True, "one segment remains beyond the window"
    for row in rows:
        assert_lineup_slot(row)
        assert row["show_id"] == scenario.show_id


def test_second_page_of_a_shows_lineup_closes_the_collection(api):
    """The remaining segment arrives on the next window, with nothing left after
    it, and no segment is served twice across the two pages.

    PRD 2.3: "`total_count` is the number of rows matching the filters before the
    window is applied, and `has_more` is true when rows remain beyond the
    returned window."
    PRD 2.3: "Ordering is applied before the window, so `offset` and `limit`
    slice a stable sequence."

    Design: Corner/entities/lineup_slots_listing_paginates_by_show
    """
    scenario = _show_with_three_segments()
    expected_ids = {slot["id"] for slot in scenario.slots}

    first_rows, _ = validate_paginated(
        api.list_lineup_slots(
            MERCHANDISER, params={"show_id": scenario.show_id, "limit": 2, "offset": 0}
        )
    )
    second_rows, second_meta = validate_paginated(
        api.list_lineup_slots(
            MERCHANDISER, params={"show_id": scenario.show_id, "limit": 2, "offset": 2}
        )
    )

    assert len(second_rows) == 1, "only one segment sits beyond the first window"
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "nothing remains after the last segment"
    assert second_rows[0]["show_id"] == scenario.show_id

    seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(seen) == 3
    assert set(seen) == expected_ids, "every segment appears exactly once over the pages"
    assert len(set(seen)) == 3, "no segment is served on both pages"


def test_reading_an_offer_that_does_not_exist_is_a_flash_offer_not_found(api):
    """A flash-offer id no row carries is a not-found on the offer family, not an
    empty success envelope.

    PRD 2.6: "Path identifiers are resolved strictly left to right, and the first
    identifier that does not resolve determines the response."
    PRD 2.6: "Each maps to its own not-found code — `ERR_HOST_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_VIEWER_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`,
    `ERR_STREAM_CHANNEL_NOT_FOUND`, `ERR_HOST_BOOKING_NOT_FOUND`,
    `ERR_LINEUP_SLOT_NOT_FOUND`, `ERR_FLASH_OFFER_NOT_FOUND`,
    `ERR_DISCLOSURE_RECORD_NOT_FOUND`, `ERR_CART_NOT_FOUND`,
    `ERR_CART_ITEM_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and
    `ERR_INTERACTION_NOT_FOUND` — each returned with HTTP 404."

    Design: Corner/entities/flash_offer_unknown_id_returns_not_found
    """
    set_clock(CLOCK_EPOCH)

    resp = api.get_flash_offer(NON_EXISTENT_UUID, MERCHANDISER)
    error = validate_error(resp, ApiErrorId.ERR_FLASH_OFFER_NOT_FOUND)

    assert isinstance(error.get("message"), str) and error["message"], (
        "the error carries a human-readable message"
    )


def _slot_with_two_generations_of_offers():
    """One lineup slot repriced by a second, non-touching offer window."""
    scenario = build_scenario(
        with_booking=False,
        with_disclosure=False,
        offers=[
            {
                "offer_price_cents": 3500,
                "window_start_at": "2026-08-10T18:00:00Z",
                "window_end_at": "2026-08-10T18:30:00Z",
                "max_qty": 10,
            }
        ],
        channels=[],
    )
    older = scenario.offer
    newer = create_offer(
        scenario.slot_id,
        read_slot(scenario.slot_id)["version"],
        offer_price_cents=3300,
        window_start_at="2026-08-10T18:35:00Z",
        window_end_at="2026-08-10T19:00:00Z",
        max_qty=8,
    )
    return scenario, older, newer


def test_superseded_offers_are_reachable_through_the_offer_that_replaced_them(api):
    """The repricing history of a lineup segment stays auditable: filtering by the
    replacing offer returns exactly the offer it displaced.

    PRD 3.5: "Any offer already standing on the same lineup slot in status
    `SCHEDULED` transitions `SCHEDULED → SUPERSEDED`, has its
    `superseded_by_offer_id` set to the new offer's `id`, and has its own
    `version` incremented — this self-referential link is how the pricing history
    of a slot stays auditable"
    PRD 2.6: "flash offers by `lineup_slot_id`, `superseded_by_offer_id` and
    `status`"

    Design: Corner/entities/flash_offers_filtered_by_superseded_by_offer_id
    """
    _scenario, older, newer = _slot_with_two_generations_of_offers()

    rows, meta = validate_paginated(
        api.list_flash_offers(MERCHANDISER, params={"superseded_by_offer_id": newer["id"]})
    )

    assert meta["total_count"] == 1, "exactly one offer was displaced"
    assert len(rows) == 1
    assert rows[0]["id"] == older["id"]
    assert rows[0]["status"] == "SUPERSEDED"
    assert rows[0]["superseded_by_offer_id"] == newer["id"]


def test_only_the_standing_offer_answers_the_scheduled_filter_on_the_slot(api):
    """After a reprice, the segment has exactly one offer still standing, and it
    carries the new allotment.

    PRD 3.5: "A successful create enters `SCHEDULED` with `held_qty` and
    `sold_qty` at zero and `remaining_qty` equal to `max_qty`, and `activated_at`
    null."
    PRD 2.6: "flash offers by `lineup_slot_id`, `superseded_by_offer_id` and
    `status`"

    Design: Corner/entities/flash_offers_filtered_by_superseded_by_offer_id
    """
    scenario, older, newer = _slot_with_two_generations_of_offers()

    rows, meta = validate_paginated(
        api.list_flash_offers(
            MERCHANDISER,
            params={"lineup_slot_id": scenario.slot_id, "status": "SCHEDULED"},
        )
    )

    assert meta["total_count"] == 1, "the displaced offer no longer counts as scheduled"
    assert len(rows) == 1
    assert rows[0]["id"] == newer["id"]
    assert rows[0]["id"] != older["id"]
    assert rows[0]["status"] == "SCHEDULED"
    assert rows[0]["remaining_qty"] == 8
    assert rows[0]["held_qty"] == 0
    assert rows[0]["sold_qty"] == 0
