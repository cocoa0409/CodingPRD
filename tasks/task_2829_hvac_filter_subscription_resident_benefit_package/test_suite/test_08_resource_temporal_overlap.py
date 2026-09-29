"""
The two temporal-overlap resources: unit occupancy, a closed interval carrying a
three-day turnover buffer, and the shipment cadence window, a half-open interval
carrying none.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUPLICATE_ACTIVE_SUBSCRIPTION,
    ERR_SHIPMENT_WINDOW_OVERLAP,
    ERR_UNIT_OCCUPANCY_CONFLICT,
)
from test_helpers.test_users import OPERATOR


def _occupied_unit_env(api):
    """
    Fixture A with unit A-101 OCCUPIED by Ada's ACTIVE lease 2026-08-01 ->
    2027-07-31, plus a second, distinct resident who wants the same unit.
    """
    env = fx.build_base_env(api)
    ben = fx.create_resident(
        api, full_name="Ben Ortiz", email="ben.ortiz@example.com", allergy_flag=False
    )
    assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "OCCUPIED"
    return env, ben["id"]


def _subscriptions_on_unit(api, unit_id: str) -> list:
    rows, _meta = validate_paginated(api.list_subscriptions(OPERATOR, {"unit_id": unit_id}))
    return rows


class TestUnitOccupancyTurnoverBuffer:
    """A closed interval plus a mandatory three-day buffer on both ends."""

    def test_a_gap_of_exactly_three_days_still_collides(self, api):
        """
        Ada's lease ends 2027-07-31, so a new lease starting 2027-08-03 leaves a
        gap of exactly the three-day buffer — which is refused with
        ERR_UNIT_OCCUPANCY_CONFLICT rather than the duplicate-pair error, because
        the incoming resident is a different person, and nothing is created.

        PRD §3.3: "A gap of exactly three days still conflicts: the earliest legal start against an existing lease is the fourth day after that lease's `lease_end_date`."

        Design: Difficulty/resource_temporal_overlap/unit_occupancy_closed_interval_with_three_day_turnover_buffer
        """
        env, ben_id = _occupied_unit_env(api)

        error = validate_error(
            api.create_subscription(
                f.subscription_payload(
                    ben_id,
                    env.unit_id,
                    enrollment_channel="RESIDENT_PORTAL",
                    lease_start_date="2027-08-03",
                    lease_end_date="2028-07-31",
                ),
                OPERATOR,
            ),
            ERR_UNIT_OCCUPANCY_CONFLICT,
            409,
        )
        assert error["error_id"] != ERR_DUPLICATE_ACTIVE_SUBSCRIPTION

        rows = _subscriptions_on_unit(api, env.unit_id)
        assert [row["id"] for row in rows] == [env.subscription_id]

    def test_the_fourth_day_after_the_lease_end_is_the_first_legal_start(self, api):
        """
        Moving the same request one day later to 2027-08-04 clears the buffer and
        is accepted: the new subscription is priced and left PENDING_SETUP while
        the unit stays OCCUPIED and Ada's subscription is untouched.

        PRD §3.3: "For every existing subscription on that unit whose status is `PENDING_SETUP`, `ACTIVE`, `SUSPENDED` or `TRANSFER_PENDING`, the requested interval is legal only if either the requested `lease_start_date` falls more than three days after that subscription's `lease_end_date`, or the requested `lease_end_date` falls more than three days before that subscription's `lease_start_date`."

        Design: Difficulty/resource_temporal_overlap/unit_occupancy_closed_interval_with_three_day_turnover_buffer
        """
        env, ben_id = _occupied_unit_env(api)
        ada_before = fx.read_subscription(api, env.subscription_id)

        created = validate_success(
            api.create_subscription(
                f.subscription_payload(
                    ben_id,
                    env.unit_id,
                    enrollment_channel="RESIDENT_PORTAL",
                    lease_start_date="2027-08-04",
                    lease_end_date="2028-07-31",
                ),
                OPERATOR,
            ),
            201,
        )
        assert created["status"] == "PENDING_SETUP"
        assert created["lease_start_date"] == "2027-08-04"
        assert created["resident_id"] == ben_id
        assert created["unit_id"] == env.unit_id
        a.assert_cents(created["monthly_fee_cents"], 3546, "monthly_fee_cents")

        assert validate_success(api.get_unit(env.unit_id, OPERATOR))["status"] == "OCCUPIED"
        ada_after = fx.read_subscription(api, env.subscription_id)
        assert ada_after["status"] == "ACTIVE"
        assert ada_after["version"] == ada_before["version"]

        rows = _subscriptions_on_unit(api, env.unit_id)
        assert sorted(row["id"] for row in rows) == sorted(
            [env.subscription_id, created["id"]]
        )


class TestShipmentCadenceWindow:
    """A half-open interval with no buffer, so exact adjacency is legal."""

    def test_the_last_date_inside_the_previous_window_is_refused(self, api):
        """
        The first shipment sits on 2026-08-05 with a 75-day cadence, so its window
        runs to 2026-10-18 inclusive; asking for that last interior date is refused
        with ERR_SHIPMENT_WINDOW_OVERLAP and the sequence counter does not move.

        PRD §3.5: "To test a new date, find the subscription's latest existing shipment — the one with the greatest `scheduled_ship_date` among all shipments whose `status` is `SCHEDULED`, `SHIPPED`, `DELIVERED`, `RETURN_REQUESTED`, `RETURNED` or `UNRETURNED_WRITTEN_OFF`, breaking ties by the greatest `created_at` — and reject the request with `ERR_SHIPMENT_WINDOW_OVERLAP` when the requested date is on or after that shipment's `scheduled_ship_date` and strictly before that date advanced by the cadence."

        Design: Difficulty/resource_temporal_overlap/shipment_cadence_half_open_window_with_no_buffer
        """
        env = fx.build_base_env(api)
        shipment = fx.first_shipment(api, env.subscription_id)
        assert shipment["scheduled_ship_date"] == "2026-08-05"
        before = fx.read_subscription(api, env.subscription_id)
        assert before["ship_cadence_days"] == 75
        assert before["shipment_sequence_counter"] == 1

        validate_error(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-10-18", 2), OPERATOR
            ),
            ERR_SHIPMENT_WINDOW_OVERLAP,
            409,
        )

        rows, _meta = validate_paginated(
            api.list_shipments(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert [row["id"] for row in rows] == [shipment["id"]]
        after = fx.read_subscription(api, env.subscription_id)
        assert after["shipment_sequence_counter"] == 1
        assert after["next_ship_date"] == "2026-08-05"

    def test_exact_adjacency_one_day_later_is_accepted(self, api):
        """
        2026-10-19 is exactly the cadence after 2026-08-05, the first date the
        half-open window excludes, so the shipment is created with sequence_number
        2 on the subscription's current SKU and next_ship_date advances to it.

        PRD §3.5: "Adjacency is explicitly legal: a date exactly `ship_cadence_days` after the previous shipment's date is accepted, leaving a zero-day gap between consecutive windows."

        Design: Difficulty/resource_temporal_overlap/shipment_cadence_half_open_window_with_no_buffer
        """
        env = fx.build_base_env(api)

        created = validate_success(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-10-19", 2), OPERATOR
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["scheduled_ship_date"] == "2026-10-19"
        assert created["sequence_number"] == 2
        assert created["quantity"] == 2
        assert created["sku_id"] == env.sku_id
        assert created["version"] == 1

        after = fx.read_subscription(api, env.subscription_id)
        assert after["shipment_sequence_counter"] == 2
        assert after["next_ship_date"] == "2026-10-19"
