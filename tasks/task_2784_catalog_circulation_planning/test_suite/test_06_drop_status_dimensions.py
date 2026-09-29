"""A drop's production dimension and its measurement dimension.

The two statuses on one drop row move on disjoint triggers: opening and
finalizing a matchback run never touch the production side, delivery never
touches the measurement side, and neither dimension is derivable from the
other.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    assert_drop,
    assert_instant_equals,
    assert_matchback_run,
    create_matchback_run_payload,
    deliver_drop,
    drop_version,
    fetch_drop,
    get_success_data,
    ingest_orders,
    iso_utc,
    online_order,
    set_clock,
    setup_mailed_drop,
    validate_error,
    validate_paginated,
)

MAIL_INSTANT = iso_utc("2026-09-20")


def _mailed_world_with_one_order() -> dict:
    """A mailed 20000-book drop with one ingested online order dated hours
    after the in-home date."""
    set_clock(CLOCK_START)
    world = setup_mailed_drop(
        segment_overrides={"segment_code": "S_PREMIUM"},
        plan_overrides={"plan_code": "P1"},
        drop_overrides={"in_home_date": MAIL_INSTANT},
    )
    ingest_orders(
        [
            online_order(
                "O-1", world["segment"]["id"], iso_utc("2026-09-20", 6), 20000
            )
        ]
    )
    world["drop"] = fetch_drop(world["drop"]["id"])
    return world


class TestDropDimensionsAdvanceIndependently:
    def test_opening_and_finalizing_a_run_leave_the_production_status_alone(self, api):
        """PRD §3.9: "The drop's `production_status` must be `MAILED` or
        `DELIVERED`, otherwise `ERR_INVALID_DROP_STATE` — this is the single
        guard that couples the drop's two dimensions, and it reads
        `production_status` without changing it."

        Design: Difficulty/non_linear_state_machine/drop_production_and_measurement_dimensions_advance_independently
        """
        world = _mailed_world_with_one_order()
        drop_id = world["drop"]["id"]
        version_after_mail = world["drop"]["version"]

        run = get_success_data(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    version_after_mail, "LAST_TOUCH_MAIL", 30
                ),
                ANALYST,
            )
        )
        assert_matchback_run(run)
        assert run["attributed_demand_cents"] == 20000

        opened = fetch_drop(drop_id)
        assert_drop(opened)
        assert opened["measurement_status"] == "MATCHBACK_OPEN"
        assert opened["production_status"] == "MAILED"

        delivered = deliver_drop(drop_id)
        assert delivered["production_status"] == "DELIVERED"
        assert delivered["measurement_status"] == "MATCHBACK_OPEN"

        get_success_data(api.finalize_matchback_run(run["id"], ANALYST))
        runs, _meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        finalized = next(row for row in runs if row["id"] == run["id"])
        assert finalized["status"] == "FINALIZED"
        assert_instant_equals(finalized["finalized_at"], MAIL_INSTANT, "finalized_at")

        closed = fetch_drop(drop_id)
        assert closed["measurement_status"] == "MATCHBACK_CLOSED"
        assert closed["production_status"] == "DELIVERED"
        assert closed["version"] > delivered["version"] > version_after_mail

    def test_a_closed_measurement_dimension_refuses_a_new_run(self, api):
        """PRD §3.9: "A drop in `MATCHBACK_CLOSED` accepts no new run at all and
        is rejected with `ERR_INVALID_MEASUREMENT_STATE` — reaching the closed
        state does not unlock a re-read."

        Design: Difficulty/non_linear_state_machine/drop_production_and_measurement_dimensions_advance_independently
        """
        world = _mailed_world_with_one_order()
        drop_id = world["drop"]["id"]

        run = get_success_data(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    drop_version(drop_id, PLANNER), "LAST_TOUCH_MAIL", 30
                ),
                ANALYST,
            )
        )
        deliver_drop(drop_id)
        get_success_data(api.finalize_matchback_run(run["id"], ANALYST))

        response = api.create_matchback_run(
            drop_id,
            create_matchback_run_payload(
                drop_version(drop_id, PLANNER), "LAST_TOUCH_MAIL", 30
            ),
            ANALYST,
        )
        validate_error(
            response, ApiErrorId.ERR_INVALID_MEASUREMENT_STATE.value, 409
        )

        drop = fetch_drop(drop_id)
        assert drop["production_status"] == "DELIVERED"
        assert drop["measurement_status"] == "MATCHBACK_CLOSED"
