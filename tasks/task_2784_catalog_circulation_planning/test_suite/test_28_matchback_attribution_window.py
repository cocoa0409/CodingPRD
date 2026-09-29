"""Which website orders the mail is allowed to take credit for.

Four ingested orders separate three counters a naive implementation collapses into
one. A contact exactly on the order date qualifies; a contact exactly
attribution_window_days before it does not; and an order for a segment this drop
never contacted is not even matched. The single mail touch this drop produced
therefore wins two orders out of three matched, and one of the four never enters
the arithmetic at all.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_START,
    assert_matchback_run,
    create_matchback_run_payload,
    drop_version,
    fetch_drop,
    ingest_orders,
    iso_utc,
    new_segment,
    online_order,
    set_clock,
    setup_mailed_drop,
    validate_success,
)

INGEST_CLOCK = iso_utc("2026-10-20")

UNCIRCULATED_SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 20000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}


def _a_mailed_drop_read_back_against_four_online_orders(api) -> dict:
    """The mailed drop's cascade leaves exactly one MAIL contact for S_A dated
    2026-09-15. S_Z exists in the same season but this drop never circulated it.
    Four orders are then ingested and read back over a 30-day look-back."""
    set_clock(CLOCK_START)
    world = setup_mailed_drop()
    circulated = world["segment"]
    uncirculated = new_segment(
        world["season"]["id"], segment_code="S_Z", **UNCIRCULATED_SCORING
    )

    set_clock(INGEST_CLOCK)
    ingested = ingest_orders(
        [
            online_order("O1", circulated["id"], iso_utc("2026-09-15"), 40000),
            online_order("O2", circulated["id"], iso_utc("2026-10-15"), 50000),
            online_order("O3", circulated["id"], iso_utc("2026-10-14"), 30000),
            online_order("O4", uncirculated["id"], iso_utc("2026-09-20"), 90000),
        ],
        ADMIN,
    )
    assert ingested["ingested_count"] == 4

    drop_id = world["drop"]["id"]
    version_before = drop_version(drop_id, ANALYST)
    run = validate_success(
        api.create_matchback_run(
            drop_id,
            create_matchback_run_payload(version_before, "LAST_TOUCH_MAIL", 30),
            ANALYST,
        ),
        201,
    )
    world["uncirculated"] = uncirculated
    world["run"] = run
    world["version_before"] = version_before
    return world


class TestTheLookBackWindowIsHalfOpen:
    def test_a_contact_on_the_older_bound_does_not_qualify(self, api):
        """PRD §3.9: "For each order, the qualifying contacts are the contact events
        for that order's `housefile_segment_id` whose `contact_date` falls inside a
        half-open window: strictly later than the order date minus the run's
        `attribution_window_days` whole days, and at or before the order date itself.
        A contact landing exactly on the order date therefore qualifies, while a
        contact landing exactly `attribution_window_days` before the order date does
        not."

        Design: Corner/calculations/matchback_attribution_window_is_half_open_on_the_older_edge
        """
        world = _a_mailed_drop_read_back_against_four_online_orders(api)
        run = world["run"]

        assert run["attribution_window_days"] == 30
        assert run["attributed_order_count"] == 2
        assert run["attributed_order_count"] != 3


class TestTheThreeOrderCounters:
    def test_matched_counts_the_segment_while_attributed_counts_the_window(self, api):
        """PRD §3.9: "`attributed_order_count` is the number of ingested orders that
        credited at least one cent to *this* run's drop, and `attributed_demand_cents`
        is the total cents credited to this drop. `matched_order_count` is the number
        of ingested orders whose segment matches a segment this drop contacted,
        counted regardless of whether the window admitted any contact or which drop
        ultimately won the credit."

        Design: Corner/calculations/matchback_attribution_window_is_half_open_on_the_older_edge
        """
        world = _a_mailed_drop_read_back_against_four_online_orders(api)
        run = world["run"]

        assert_matchback_run(run)
        assert run["matched_order_count"] == 3
        assert run["attributed_order_count"] == 2
        assert run["unmatched_order_count"] == 1
        assert run["unmatched_order_count"] == (
            run["matched_order_count"] - run["attributed_order_count"]
        )

    def test_the_single_mail_touch_takes_the_whole_demand_of_what_it_won(self, api):
        """PRD §3.9: "Under `LAST_TOUCH_MAIL`, only mail can take credit and only the
        freshest mail touch: the qualifying contacts are narrowed to those whose
        `channel` is `MAIL`, and if none remain the order is unattributed; otherwise
        the winner is the mail contact with the greatest `contact_date`, with the
        smallest `created_at` breaking a tie, and the order's entire `demand_cents` is
        credited to that contact's `drop_id`."

        Design: Corner/calculations/matchback_attribution_window_is_half_open_on_the_older_edge
        """
        world = _a_mailed_drop_read_back_against_four_online_orders(api)
        run = world["run"]

        assert run["attributed_demand_cents"] == 70000
        assert run["attributed_demand_cents"] == 40000 + 30000
        assert run["attributed_demand_cents"] != 160000
        assert run["attribution_variant"] == "LAST_TOUCH_MAIL"


class TestOpeningTheMeasurementDimension:
    def test_the_first_run_opens_a_pending_drop_without_touching_production(
        self, api
    ):
        """PRD §3.9: "On the measurement dimension, a drop in `PENDING` moves
        `PENDING → MATCHBACK_OPEN` and the run is created in status `OPEN`."

        Design: Corner/calculations/matchback_attribution_window_is_half_open_on_the_older_edge
        """
        world = _a_mailed_drop_read_back_against_four_online_orders(api)

        assert world["run"]["status"] == "OPEN"
        assert world["run"]["finalized_at"] is None

        drop = fetch_drop(world["drop"]["id"], ANALYST)
        assert drop["measurement_status"] == "MATCHBACK_OPEN"
        assert drop["production_status"] == "MAILED"
