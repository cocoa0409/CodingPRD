"""The ecommerce feed is the only door into matchback, and it is guarded.

One unresolvable `housefile_segment_id` sitting in the middle of a three-order
batch is enough to refuse the call, and the same two survivors are then accepted on
their own, counted and echoed back. Both survivors fall inside the thirty-day window
behind the drop's single mail contact, so the run that follows credits every cent of
both orders to the drop that mailed them, and a second run over the same feed
supersedes the first while moving the drop's version twice in total.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    NON_EXISTENT_UUID,
    assert_matchback_run,
    create_matchback_run_payload,
    fetch_drop,
    ingest_orders,
    ingest_orders_payload,
    iso_utc,
    online_order,
    set_clock,
    setup_mailed_drop,
    validate_error,
    validate_paginated,
    validate_success,
)

FEED_CLOCK = iso_utc("2026-09-25")


def _a_mailed_drop_with_the_clock_past_both_orders() -> dict:
    """Mailing the drop on its 2026-09-15 in-home date logs the drop's mail contact
    against S_A; the clock then moves to 2026-09-25 so both feed orders sit in the
    past."""
    world = setup_mailed_drop()
    set_clock(FEED_CLOCK)
    return world


def _the_two_good_orders(segment_id) -> list:
    """40000 cents on the in-home date itself and 30000 cents five days later."""
    return [
        online_order("OK-1", segment_id, iso_utc("2026-09-15"), 40000),
        online_order("OK-3", segment_id, iso_utc("2026-09-20"), 30000),
    ]


def _open_a_run(api, drop_id, window_days=30) -> dict:
    """A LAST_TOUCH_MAIL run pinned to the drop's current version."""
    expected = fetch_drop(drop_id, ANALYST)["version"]
    return validate_success(
        api.create_matchback_run(
            drop_id,
            create_matchback_run_payload(expected, "LAST_TOUCH_MAIL", window_days),
            ANALYST,
        ),
        201,
    )


class TestTheFeedRefusesAnUnresolvableSegment:
    def test_one_bad_segment_id_in_the_middle_refuses_the_batch(self, api):
        """PRD §3.9: "Those orders originate in an external ecommerce system and no
        business workflow in this service creates them, so a `PlatformAdmin` feeds them
        in: the ingest capability accepts an `orders` array whose elements each carry an
        `external_order_id`, a `housefile_segment_id` that must resolve to an existing
        segment (otherwise `ERR_SEGMENT_NOT_FOUND`), an `order_date`, and a
        `demand_cents` amount."

        Design: Corner/endpoints/the_order_feed_ingest_is_all_or_nothing_across_the_batch
        """
        world = _a_mailed_drop_with_the_clock_past_both_orders()
        segment_id = world["segment"]["id"]

        response = api.ingest_online_orders(
            ingest_orders_payload(
                [
                    online_order("OK-1", segment_id, iso_utc("2026-09-15"), 40000),
                    online_order(
                        "BAD-2", NON_EXISTENT_UUID, iso_utc("2026-09-16"), 10000
                    ),
                    online_order("OK-3", segment_id, iso_utc("2026-09-20"), 30000),
                ]
            ),
            ADMIN,
        )
        validate_error(response, "ERR_SEGMENT_NOT_FOUND", 404)


class TestTheAcceptedFeedIsCountedAndEchoed:
    def test_the_response_reports_the_count_and_the_accepted_external_ids(self, api):
        """PRD §3.9: "The response reports an `ingested_count` and the
        `external_order_ids` accepted."

        Design: Corner/endpoints/the_order_feed_ingest_is_all_or_nothing_across_the_batch
        """
        world = _a_mailed_drop_with_the_clock_past_both_orders()

        accepted = ingest_orders(_the_two_good_orders(world["segment"]["id"]))
        assert accepted["ingested_count"] == 2
        assert sorted(accepted["external_order_ids"]) == ["OK-1", "OK-3"]


class TestTheFeedIsWhatAttributionWalks:
    def test_both_orders_credit_the_drop_that_mailed_their_segment(self, api):
        """PRD §3.9: "Under `LAST_TOUCH_MAIL`, only mail can take credit and only the
        freshest mail touch: the qualifying contacts are narrowed to those whose
        `channel` is `MAIL`, and if none remain the order is unattributed; otherwise the
        winner is the mail contact with the greatest `contact_date`, with the smallest
        `created_at` breaking a tie, and the order's entire `demand_cents` is credited to
        that contact's `drop_id`."
        PRD §3.9: "`attributed_order_count` is the number of ingested orders that
        credited at least one cent to *this* run's drop, and `attributed_demand_cents` is
        the total cents credited to this drop."

        Design: Corner/endpoints/the_order_feed_ingest_is_all_or_nothing_across_the_batch
        """
        world = _a_mailed_drop_with_the_clock_past_both_orders()
        ingest_orders(_the_two_good_orders(world["segment"]["id"]))

        run = _open_a_run(api, world["drop"]["id"])
        assert_matchback_run(run)
        assert run["attributed_order_count"] == 2
        assert run["attributed_demand_cents"] == 70000

    def test_every_fed_order_of_a_contacted_segment_counts_as_matched(self, api):
        """PRD §3.9: "`matched_order_count` is the number of ingested orders whose
        segment matches a segment this drop contacted, counted regardless of whether the
        window admitted any contact or which drop ultimately won the credit.
        `unmatched_order_count` is `matched_order_count` less
        `attributed_order_count`."

        Design: Corner/endpoints/the_order_feed_ingest_is_all_or_nothing_across_the_batch
        """
        world = _a_mailed_drop_with_the_clock_past_both_orders()
        ingest_orders(_the_two_good_orders(world["segment"]["id"]))

        run = _open_a_run(api, world["drop"]["id"])
        assert run["matched_order_count"] == 2
        assert run["unmatched_order_count"] == 0
        assert run["unmatched_order_count"] == (
            run["matched_order_count"] - run["attributed_order_count"]
        )


class TestASecondRunOverTheSameFeed:
    def test_the_earlier_run_is_superseded_and_the_drop_moves_twice(self, api):
        """PRD §3.9: "A drop already in `MATCHBACK_OPEN` takes a self-loop: every
        existing run of that drop in status `OPEN` or `FINALIZED` moves to `SUPERSEDED`
        with its own `version` incremented by one, and a fresh run is created in `OPEN`.
        A drop in `MATCHBACK_CLOSED` accepts no new run at all and is rejected with
        `ERR_INVALID_MEASUREMENT_STATE` — reaching the closed state does not unlock a
        re-read. Either way the drop's `version` increments by one."

        Design: Corner/endpoints/the_order_feed_ingest_is_all_or_nothing_across_the_batch
        """
        world = _a_mailed_drop_with_the_clock_past_both_orders()
        drop_id = world["drop"]["id"]
        ingest_orders(_the_two_good_orders(world["segment"]["id"]))
        before = fetch_drop(drop_id, ANALYST)["version"]

        first = _open_a_run(api, drop_id)
        assert first["status"] == "OPEN"
        after_first = fetch_drop(drop_id, ANALYST)
        assert after_first["version"] == before + 1
        assert after_first["measurement_status"] == "MATCHBACK_OPEN"

        second = _open_a_run(api, drop_id)
        assert second["status"] == "OPEN"
        assert second["attributed_demand_cents"] == 70000
        after_second = fetch_drop(drop_id, ANALYST)
        assert after_second["version"] == before + 2
        assert after_second["measurement_status"] == "MATCHBACK_OPEN"

        rows, meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[first["id"]]["version"] == first["version"] + 1
        assert by_id[second["id"]]["status"] == "OPEN"
