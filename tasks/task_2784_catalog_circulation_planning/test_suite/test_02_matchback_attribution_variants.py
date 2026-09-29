"""The two attribution variants of a matchback run.

One fixture — a single online order with three qualifying contacts, one of
them the mail touch of the drop under measurement — is measured twice. The
last-touch model hands the drop the whole order; the fractional model hands it
an equal share plus the whole remainder, because its mail touch is the
earliest qualifying contact rather than the last.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    assert_drop,
    assert_matchback_run,
    create_matchback_run_payload,
    drop_version,
    fetch_drop,
    fetch_segment,
    get_success_data,
    ingest_orders,
    iso_utc,
    new_contact_event,
    online_order,
    set_clock,
    setup_mailed_drop,
    validate_paginated,
)

ORDER_INSTANT = iso_utc("2026-10-05", 12)


def _measured_world() -> dict:
    """A mailed 64-page drop, three contacts on its segment and one ingested
    20000-cent online order dated inside the attribution window."""
    set_clock(CLOCK_START)
    world = setup_mailed_drop(
        segment_overrides={"segment_code": "S_PREMIUM"},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"in_home_date": iso_utc("2026-09-20")},
    )
    set_clock(ORDER_INSTANT)
    segment_id = world["segment"]["id"]
    new_contact_event(segment_id, iso_utc("2026-10-01"), "EMAIL")
    new_contact_event(segment_id, iso_utc("2026-10-03"), "DIGITAL")
    world["ingest"] = ingest_orders(
        [online_order("O-1", segment_id, ORDER_INSTANT, 20000)]
    )
    world["segment"] = fetch_segment(segment_id)
    world["drop"] = fetch_drop(world["drop"]["id"])
    return world


def _open_run(api, drop_id, variant):
    return get_success_data(
        api.create_matchback_run(
            drop_id,
            create_matchback_run_payload(
                drop_version(drop_id), variant, 30
            ),
            ANALYST,
        )
    )


class TestMatchbackAttributionVariants:
    def test_last_touch_mail_credits_the_whole_order_to_the_mail_touch(self, api):
        """PRD §3.9: "Under `LAST_TOUCH_MAIL`, only mail can take credit and only
        the freshest mail touch: the qualifying contacts are narrowed to those
        whose `channel` is `MAIL`, and if none remain the order is unattributed;
        otherwise the winner is the mail contact with the greatest
        `contact_date`, with the smallest `created_at` breaking a tie, and the
        order's entire `demand_cents` is credited to that contact's `drop_id`."

        Design: Difficulty/dual_variant_calc/matchback_last_touch_vs_fractional_credit_same_drop_differently
        """
        world = _measured_world()
        assert world["segment"]["fatigue_score"] == 48
        assert world["segment"]["contact_strategy"] == "PREMIUM_FULL"
        assert world["drop"]["cost_per_book_cents"] == 221

        run = _open_run(api, world["drop"]["id"], "LAST_TOUCH_MAIL")
        assert_matchback_run(run)
        assert run["attribution_variant"] == "LAST_TOUCH_MAIL"
        assert run["status"] == "OPEN"
        assert run["matched_order_count"] == 1
        assert run["attributed_order_count"] == 1
        assert run["unmatched_order_count"] == 0
        assert run["attributed_demand_cents"] == 20000

        drop = fetch_drop(world["drop"]["id"])
        assert_drop(drop)
        assert drop["measurement_status"] == "MATCHBACK_OPEN"
        assert drop["production_status"] == "MAILED"

    def test_fractional_multi_touch_pays_a_share_plus_the_whole_remainder(self, api):
        """PRD §3.9: "the share is the order's `demand_cents` divided by the
        number of qualifying contacts, floored, and each qualifying contact's
        `drop_id` is credited that share; the whole remainder — the order's
        `demand_cents` less the share multiplied by the contact count — is then
        credited additionally to the contact with the **earliest**
        `contact_date`, with the smallest `created_at` breaking a tie."

        Design: Difficulty/dual_variant_calc/matchback_last_touch_vs_fractional_credit_same_drop_differently
        """
        world = _measured_world()
        drop_id = world["drop"]["id"]

        last_touch = _open_run(api, drop_id, "LAST_TOUCH_MAIL")
        fractional = _open_run(api, drop_id, "FRACTIONAL_MULTI_TOUCH")
        assert_matchback_run(fractional)
        assert fractional["attribution_variant"] == "FRACTIONAL_MULTI_TOUCH"
        assert fractional["attributed_demand_cents"] == 6668
        assert fractional["attributed_order_count"] == 1
        assert fractional["unmatched_order_count"] == 0
        assert (
            last_touch["attributed_demand_cents"]
            != fractional["attributed_demand_cents"]
        )

        runs, _meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        by_id = {row["id"]: row for row in runs}
        assert by_id[last_touch["id"]]["status"] == "SUPERSEDED"
        assert by_id[fractional["id"]]["status"] == "OPEN"

        drop = fetch_drop(drop_id)
        assert drop["measurement_status"] == "MATCHBACK_OPEN"
        assert drop["production_status"] == "MAILED"
