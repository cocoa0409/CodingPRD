"""The consistency model: what one accepted write is allowed to touch, what a
read is allowed to see, and what a refused write is allowed to leave behind.

The versions asserted here are per-row write counters, so each test names the
writes that produced them; an implementation that shares one global counter, that
bumps a row it only read, or that half-applies a refused write fails.
"""
from test_helpers import (
    DISPATCHER,
    add_robot,
    create_delivery_mission_payload,
    mission_transition_payload,
    read_mission,
    read_order,
    read_plan,
    read_robot,
    read_zone,
    setup_active_route_plan,
    setup_en_route_mission,
    setup_received_order,
    validate_error,
    validate_paginated,
    validate_success,
)

#: S1 320.0 + S2 14.0 + S3 260.0 + S5 180.0, the canonical corridor.
CORRIDOR_LENGTH_M = 774.0
#: S2 is the corridor's only `CROSSING` element.
CORRIDOR_CROSSINGS = 1
BASE_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


class TestEachAcceptedWriteBumpsOneVersionPerTouchedRow:
    def test_the_departure_writes_the_mission_and_the_order_and_nothing_else(self, api):
        """PRD §3.7: "Departure stamps `departed_at_utc` with the current instant, adds
        the active plan's `total_length_m` to the mission's `traveled_distance_m` and its
        `crossing_count` to `traversed_crossing_count`, and carries the order from
        `DISPATCHED` to `IN_TRANSIT`."
        PRD §2.4: "`version` (integer): 1 immediately after creation, and increased by
        exactly 1 on every mutation of that row."
        PRD §3.6: "`crossing_count` is the number of elements whose `segment_type` is
        `CROSSING`."

        The mission was written four times — its creation, the handoff, the activation
        that repointed `active_route_plan_id` and this departure — while the order was
        written three: its intake, its dispatch and this departure.

        Design: Corner/consistency_model/each_accepted_write_bumps_one_version_on_each_touched_row
        """
        ctx = setup_active_route_plan()

        departed = validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("DEPART"), DISPATCHER
            )
        )

        order = read_order(ctx["o"])
        assert departed["mission_state"] == "EN_ROUTE"
        assert departed["version"] == 4
        assert departed["departed_at_utc"] == BASE_CLOCK_UTC
        assert departed["traveled_distance_m"] == CORRIDOR_LENGTH_M
        assert departed["traversed_crossing_count"] == CORRIDOR_CROSSINGS
        assert order["order_state"] == "IN_TRANSIT"
        assert order["version"] == 3

    def test_the_three_rows_the_departure_only_reads_keep_their_versions(self, api):
        """PRD §2.4: "A read never changes a `version`, and a mutation always refreshes
        `updated_at` alongside it."
        PRD §3.7: "It requires `active_route_plan_id` to be non-null and that plan to be
        in `plan_state` `ACTIVE`, the zone to still be in `permit_state` `PERMITTED`, or
        the request is refused with `ERR_ZONE_NOT_PERMITTED`, and the robot's
        `health_state` to be `NOMINAL` or `DEGRADED`, or the request is refused with
        `ERR_ROBOT_HEALTH_BLOCKED` — a robot quarantined between load and departure never
        leaves."

        The robot's four writes are its registration, its staging, its availability and
        the dispatch; the plan's three are its creation, its validation and its
        activation; the zone's four are its creation, its permit activation, the dispatch
        and the handoff. The departure consults all three and writes none of them.

        Design: Corner/consistency_model/each_accepted_write_bumps_one_version_on_each_touched_row
        """
        ctx = setup_active_route_plan()
        robot_before = read_robot(ctx["r"])
        plan_before = read_plan(ctx["p"])
        zone_before = read_zone(ctx["z"])

        validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("DEPART"), DISPATCHER
            )
        )

        robot = read_robot(ctx["r"])
        plan = read_plan(ctx["p"])
        zone = read_zone(ctx["z"])
        assert (robot_before["version"], plan_before["version"], zone_before["version"]) == (
            4,
            3,
            4,
        )
        assert robot["duty_state"] == "ON_MISSION"
        assert robot["version"] == 4
        assert plan["plan_state"] == "ACTIVE"
        assert plan["version"] == 3
        assert zone["version"] == 4


class TestReadsReflectWritesImmediately:
    def test_the_single_read_agrees_with_the_transition_and_repeats_itself(self, api):
        """PRD §3.7: "Arrival is a `FleetDispatcher` action carrying the mission from
        `EN_ROUTE` to `HANDOFF_READY`, and it is gated on the intervention set: no event
        of this mission may still be in `REQUESTED`, `ACKNOWLEDGED`, `ACTIVE` or
        `ESCALATED`, or the arrival is refused with `ERR_TAKEOVER_REQUIRED`."
        PRD §2.4: "A read never changes a `version`, and a mutation always refreshes
        `updated_at` alongside it."
        PRD §2.1: "`MerchantOperator` is the one exception: when `X-User-Role` is
        `MerchantOperator`, `X-User-ID` is the `id` of the acting `Merchant` row, and
        ownership checks on any resource that references a merchant compare that reference
        to `X-User-ID`."

        The mission reached five writes: its creation, the handoff, the plan activation,
        the departure and this arrival.

        Design: Corner/consistency_model/reads_reflect_writes_immediately_on_every_read_path
        """
        ctx = setup_en_route_mission()

        arrived = validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("ARRIVE"), DISPATCHER
            )
        )
        owner_read = validate_success(
            api.get_delivery_mission(ctx["mi"], ctx["merchant_headers"])
        )
        repeated = validate_success(api.get_delivery_mission(ctx["mi"], DISPATCHER))

        assert arrived["mission_state"] == "HANDOFF_READY"
        assert arrived["version"] == 5
        assert owner_read["mission_state"] == "HANDOFF_READY"
        assert owner_read["version"] == 5
        assert repeated["version"] == 5
        assert repeated["updated_at"] == arrived["updated_at"]

    def test_every_filtered_listing_agrees_with_the_transition_at_once(self, api):
        """PRD §2.3: "Both are echoed back to the caller together with the size of the
        unpaginated result set and a boolean indicating whether more rows follow: the
        `meta` object of a list response carries `limit`, `offset`, `total_count` and
        `has_more`."
        PRD §2.9: "Orders and robots expose their missions through `order_id` and
        `robot_id`."
        PRD §4: "List delivery missions, filtered by `order_id`, `robot_id` and
        `mission_state`."

        Design: Corner/consistency_model/reads_reflect_writes_immediately_on_every_read_path
        """
        ctx = setup_en_route_mission()
        arrived = validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("ARRIVE"), DISPATCHER
            )
        )

        ready, ready_meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"mission_state": "HANDOFF_READY"})
        )
        stale, stale_meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"mission_state": "EN_ROUTE"})
        )
        by_robot, robot_meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"robot_id": ctx["r"]})
        )

        assert [row["id"] for row in ready] == [ctx["mi"]]
        assert ready_meta["total_count"] == 1
        assert stale == []
        assert stale_meta["total_count"] == 0
        assert [row["id"] for row in by_robot] == [ctx["mi"]]
        assert robot_meta["total_count"] == 1
        assert by_robot[0]["version"] == arrived["version"]
        assert read_mission(ctx["mi"])["version"] == 5


def _one_available_robot_and_one_that_was_never_staged() -> dict:
    """A `RECEIVED` order, the eligible robot of the scenario and a second robot
    left in `OFFLINE` because nobody staged it."""
    ctx = setup_received_order()
    offline = add_robot(ctx["z"], asset_tag="RBT-OFF", stage=False, make_available=False)
    ctx["roff"] = offline["id"]
    ctx["offline_robot"] = offline
    return ctx


class TestARejectedWriteAdvancesNoVersionAnywhere:
    def test_dispatching_an_offline_robot_leaves_all_three_rows_untouched(self, api):
        """PRD §3.6: "Its `duty_state` must be `AVAILABLE`, or the dispatch is refused
        with `ERR_ROBOT_NOT_AVAILABLE` (HTTP 409) — a robot that is `OFFLINE`, `STAGING`,
        already `ON_MISSION`, `CHARGING`, in `MAINTENANCE` or `RETIRED` is out."
        PRD §3.4: "A newly registered robot has `duty_state` `OFFLINE`, `health_state`
        `NOMINAL`, `battery_pct` 100.0, `odometer_m` 0.0, `yield_event_count` 0,
        `tamper_flag` false, `lifetime_mission_count`, `lifetime_intervention_count`,
        `lifetime_escalation_count` and `clean_mission_count` all zero, both
        `rolling_autonomy_index` and `lifetime_autonomy_index` at 100, and
        `active_mission_id` and `current_bay_reservation_id` both null."
        PRD §3.3: "The order itself lands in `order_state` `RECEIVED`, with
        `settled_fee_cents`, `exception_reason`, `remedy_kind`, `remedy_reason_code` and
        `remedy_amount_cents` all null and `dispatch_attempt_count` at zero."

        Design: Corner/consistency_model/a_rejected_write_advances_no_version_anywhere
        """
        ctx = _one_available_robot_and_one_that_was_never_staged()
        order_before = read_order(ctx["o"])
        offline_before = read_robot(ctx["roff"])
        zone_before = read_zone(ctx["z"])

        refused = api.create_delivery_mission(
            create_delivery_mission_payload(ctx["o"], ctx["roff"], order_before["version"]),
            DISPATCHER,
        )

        _rows, meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"order_id": ctx["o"]})
        )
        order = read_order(ctx["o"])
        offline = read_robot(ctx["roff"])
        zone = read_zone(ctx["z"])
        validate_error(refused, "ERR_ROBOT_NOT_AVAILABLE", 409)
        assert order["order_state"] == "RECEIVED"
        assert order["version"] == order_before["version"]
        assert order["dispatch_attempt_count"] == 0
        assert offline["duty_state"] == "OFFLINE"
        assert offline["version"] == offline_before["version"]
        assert zone["version"] == zone_before["version"]
        assert zone["on_mission_robot_count"] == 0
        assert meta["total_count"] == 0

    def test_the_same_dispatch_on_the_available_robot_moves_all_three_at_once(self, api):
        """PRD §3.6: "A successful dispatch writes four rows."
        PRD §3.6: "The robot moves from `AVAILABLE` to `ON_MISSION` and its
        `active_mission_id` is pointed at the new mission."
        PRD §3.6: "The zone's `on_mission_robot_count` advances by one."
        PRD §3.6: "All four rows advance their `version` by one."

        Design: Corner/consistency_model/a_rejected_write_advances_no_version_anywhere
        """
        ctx = _one_available_robot_and_one_that_was_never_staged()
        order_before = read_order(ctx["o"])
        zone_before = read_zone(ctx["z"])
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o"], ctx["roff"], order_before["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ROBOT_NOT_AVAILABLE",
        )

        mission = validate_success(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o"], ctx["r"], order_before["version"]
                ),
                DISPATCHER,
            ),
            201,
        )

        order = read_order(ctx["o"])
        robot = read_robot(ctx["r"])
        zone = read_zone(ctx["z"])
        assert mission["mission_state"] == "PLANNED"
        assert mission["version"] == 1
        assert order["order_state"] == "DISPATCHED"
        assert order["version"] == order_before["version"] + 1
        assert robot["duty_state"] == "ON_MISSION"
        assert robot["active_mission_id"] == mission["id"]
        assert zone["on_mission_robot_count"] == 1
        assert zone["version"] == zone_before["version"] + 1
        assert read_robot(ctx["roff"])["duty_state"] == "OFFLINE"
