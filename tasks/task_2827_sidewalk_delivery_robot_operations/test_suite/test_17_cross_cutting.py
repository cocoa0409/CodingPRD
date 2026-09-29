"""Layers that cross the whole model: parent-version pinning, the logical clock
and the zone ledgers that four different producers write.

Each test drives one flow that touches several layers at once and then reads the
rows back, so an implementation that pins the wrong row, that stamps wall-clock
time, or that keeps a zone ledger in only one of its producers is falsified.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OPERATOR,
    api_client,
    assert_instant_format,
    get_success_data,
    build_scenario,
    create_bay_reservation_payload,
    create_delivery_mission_payload,
    create_merchant_payload,
    file_incident,
    add_depot_bay,
    dispatch_mission,
    integration_transition_payload,
    load_mission,
    read_bay,
    read_incident,
    read_mission,
    read_merchant,
    read_order,
    read_robot,
    read_zone,
    remedy_payload,
    reserve_bay,
    set_clock,
    setup_available_robot,
    setup_exception_order,
    setup_received_order,
    validate_error,
    validate_paginated,
    validate_success,
    SUPPORT,
)

#: The first booking: a whole hour inside the operating window.
FIRST_WINDOW = {
    "window_start_utc": "2026-08-03T10:00:00.000Z",
    "window_end_utc": "2026-08-03T11:00:00.000Z",
}
#: A second hour two clear hours later, so the 15-minute turnaround buffer on
#: either side of the first booking cannot reach it.
SECOND_WINDOW = {
    "window_start_utc": "2026-08-03T13:00:00.000Z",
    "window_end_utc": "2026-08-03T14:00:00.000Z",
}
#: A 90-minute charge window, used to make the zone ledger distinguishable from
#: the hour every other test books.
NINETY_MINUTE_WINDOW = {
    "window_start_utc": "2026-08-03T12:00:00.000Z",
    "window_end_utc": "2026-08-03T13:30:00.000Z",
}
STALE_BAY_VERSION = 1
MERCHANT_CREATED_CLOCK_UTC = "2026-08-04T14:30:00.000Z"
MERCHANT_ACTIVATED_CLOCK_UTC = "2026-08-05T08:00:00.000Z"
ZONE_CREATED_CLOCK_UTC = "2026-08-03T09:00:00.000Z"


def _an_open_charge_bay_holding_one_hour() -> dict:
    """One `OPEN` charge bay whose first booking has already taken it to version
    two, with the version-one token the client read before that booking."""
    ctx = setup_available_robot()
    bay = add_depot_bay(ctx["z"], "BAY-1", bay_type="CHARGE", power_kw=22.0, state="OPEN")
    ctx["b"] = bay["id"]
    ctx["bay_at_creation"] = bay
    ctx["first"] = reserve_bay(bay, ctx["r"], **FIRST_WINDOW)
    return ctx


class TestBayReservationPinsTheParentBayVersion:
    def test_a_non_overlapping_window_on_a_stale_token_is_refused(self, api):
        """PRD §2.5: "`POST /bay-reservations` requires `expected_depot_bay_version`,
        carrying the client's last observed `version` of the parent `DepotBay`. A
        non-overlapping window on the same bay is legitimate on its own merits, so
        pinning the version is the only way to guarantee that the client reasoned about
        the bay's real committed-minutes ledger. A mismatch is rejected with
        `ERR_STALE_BAY_VERSION` (HTTP 412)."
        PRD §3.4: "Creating a reservation books its minutes into two denormalized
        ledgers at once: the bay's `committed_minutes` increases by `window_minutes` and
        the zone's `reserved_bay_minutes` increases by the same amount, with the
        `version` of the bay, the zone and the new reservation each advancing by one."
        PRD §3.4: "From that window the server derives `window_minutes` as the number
        of whole minutes from start to end, discarding any partial minute, and that
        value is frozen for the life of the reservation even though the window fields
        themselves are also immutable."

        Design: Corner/cross_cutting_complexity_layers/bay_reservation_create_rejects_a_stale_bay_version
        """
        ctx = _an_open_charge_bay_holding_one_hour()
        assert ctx["bay_at_creation"]["version"] == STALE_BAY_VERSION
        assert ctx["first"]["state"] == "HELD"
        assert ctx["first"]["window_minutes"] == 60
        assert read_bay(ctx["b"])["committed_minutes"] == 60
        assert read_bay(ctx["b"])["version"] == 2

        refused = api.create_bay_reservation(
            create_bay_reservation_payload(
                ctx["b"], ctx["r"], STALE_BAY_VERSION, **SECOND_WINDOW
            ),
            DISPATCHER,
        )

        validate_error(refused, "ERR_STALE_BAY_VERSION", 412)
        assert read_bay(ctx["b"])["committed_minutes"] == 60
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 60

    def test_the_identical_window_commits_once_the_client_re_reads_the_version(self, api):
        """PRD §3.4: "A conflict therefore exists when the requested
        `window_start_utc` is earlier than the existing reservation's `window_end_utc`
        advanced by 15 minutes, and at the same time the requested `window_end_utc`
        advanced by 15 minutes is later than the existing reservation's
        `window_start_utc`."
        PRD §3.4: "Those two ledgers are conserved quantities."
        PRD §3.4: "At every instant a bay's `committed_minutes` equals the sum of
        `window_minutes` over that bay's reservations whose `state` is `HELD` or
        `ACTIVE`, and a zone's `reserved_bay_minutes` equals the sum of
        `committed_minutes` over that zone's bays, which is the same as the sum of
        `window_minutes` over every live reservation anywhere in the zone."

        Design: Corner/cross_cutting_complexity_layers/bay_reservation_create_rejects_a_stale_bay_version
        """
        ctx = _an_open_charge_bay_holding_one_hour()
        validate_error(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["b"], ctx["r"], STALE_BAY_VERSION, **SECOND_WINDOW
                ),
                DISPATCHER,
            ),
            "ERR_STALE_BAY_VERSION",
        )

        re_read = read_bay(ctx["b"])
        second = validate_success(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["b"], ctx["r"], re_read["version"], **SECOND_WINDOW
                ),
                DISPATCHER,
            ),
            201,
        )

        _rows, meta = validate_paginated(
            api.list_bay_reservations(DISPATCHER, {"bay_id": ctx["b"]})
        )
        bay = read_bay(ctx["b"])
        assert re_read["version"] == 2
        assert second["window_minutes"] == 60
        assert second["state"] == "HELD"
        assert bay["committed_minutes"] == 120
        assert bay["version"] == 3
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 120
        assert meta["total_count"] == 2


def _a_redelivered_order_three_writes_past_its_first_read() -> dict:
    """An order dispatched, aborted into an exception and put back into the
    pipeline by a `REDELIVER`, so the version the client first read is stale."""
    ctx = setup_exception_order("DISPATCH_CANCELLED")
    ctx["remedy"] = get_success_data(
        api_client.issue_order_remedy(ctx["o"], remedy_payload("REDELIVER"), SUPPORT)
    )
    ctx["order"] = read_order(ctx["o"])
    return ctx


class TestMissionCreatePinsTheParentOrderVersion:
    def test_a_redispatch_on_the_first_read_version_is_refused(self, api):
        """PRD §2.5: "`POST /delivery-missions` requires
        `expected_delivery_order_version`, carrying the client's last observed `version`
        of the parent `DeliveryOrder`. A redelivery mission legitimately supersedes an
        aborted predecessor, so a create carrying a stale order version can
        double-dispatch an order whose state the client has not observed. A mismatch is
        rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."
        PRD §3.8: "A `REDELIVER` charges nothing at all, records a
        `remedy_amount_cents` of 0, and is the only kind that puts the order back into
        the pipeline: it is permitted only from `EXCEPTION` and carries the order back to
        `RECEIVED`, clearing `exception_reason` to null so a later failure of the same
        order may latch a different reason."
        PRD §3.8: "A `REDELIVER` touches neither `remedy_spent_cents` nor the remaining
        budget and therefore can never be refused for budget reasons."

        Design: Corner/cross_cutting_complexity_layers/mission_create_rejects_a_stale_order_version
        """
        ctx = _a_redelivered_order_three_writes_past_its_first_read()
        assert ctx["o_v"] == 1
        assert ctx["order"]["order_state"] == "RECEIVED"
        assert ctx["order"]["exception_reason"] is None
        assert ctx["order"]["remedy_kind"] == "REDELIVER"
        assert ctx["order"]["remedy_amount_cents"] == 0

        refused = api.create_delivery_mission(
            create_delivery_mission_payload(ctx["o"], ctx["r"], ctx["o_v"]),
            DISPATCHER,
        )

        _rows, meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"order_id": ctx["o"]})
        )
        order = read_order(ctx["o"])
        validate_error(refused, "ERR_STALE_ORDER_VERSION", 412)
        assert order["order_state"] == "RECEIVED"
        assert order["dispatch_attempt_count"] == 1
        assert meta["total_count"] == 1
        assert read_zone(ctx["z"])["remedy_spent_cents"] == 0

    def test_the_second_dispatch_lands_once_the_client_reads_version_four(self, api):
        """PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order that
        is dispatched a second time shows a count of two."
        PRD §3.6: "The robot moves from `AVAILABLE` to `ON_MISSION` and its
        `active_mission_id` is pointed at the new mission."
        PRD §3.6: "The zone's `on_mission_robot_count` advances by one."
        PRD §2.4: "`version` (integer): 1 immediately after creation, and increased by
        exactly 1 on every mutation of that row."

        The order was written three times after the client's first read — the dispatch,
        the abort and the redelivery — so the version it must now pin is four.

        Design: Corner/cross_cutting_complexity_layers/mission_create_rejects_a_stale_order_version
        """
        ctx = _a_redelivered_order_three_writes_past_its_first_read()
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], ctx["o_v"]),
                DISPATCHER,
            ),
            "ERR_STALE_ORDER_VERSION",
        )

        re_read = read_order(ctx["o"])
        second = validate_success(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], re_read["version"]),
                DISPATCHER,
            ),
            201,
        )

        order = read_order(ctx["o"])
        robot = read_robot(ctx["r"])
        assert re_read["version"] == 4
        assert second["mission_state"] == "PLANNED"
        assert order["order_state"] == "DISPATCHED"
        assert order["dispatch_attempt_count"] == 2
        assert robot["duty_state"] == "ON_MISSION"
        assert robot["active_mission_id"] == second["id"]
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 1


class TestDerivedInstantsFollowTheLogicalClock:
    def test_a_row_created_after_a_clock_jump_carries_the_new_instant(self, api):
        """PRD §2.4: "`created_at` (string): the instant the row was created, as an ISO
        8601 UTC timestamp with exactly three fractional digits and a trailing `Z`, for
        example `2026-08-03T09:00:00.000Z`."
        PRD §2.4: "All temporal reasoning reads a logical clock rather than wall-clock
        time."
        PRD §2.4: "The clock's startup default is `2026-08-01T00:00:00Z`, it never
        advances on its own, and it moves only when a caller sets it explicitly by
        supplying a `current_utc` instant; that operation touches no entity row and
        increments no `version`."
        PRD §3.3: "A new merchant lands in `integration_state` `PENDING` with
        `escrowed_fee_cents`, `recognized_fee_cents`, `released_fee_cents`,
        `settlement_variance_cents` and `exception_count` all at zero, and it cannot
        receive orders in that state."

        Design: Corner/cross_cutting_complexity_layers/derived_instants_follow_the_logical_clock
        """
        ctx = build_scenario("permitted")
        set_clock(MERCHANT_CREATED_CLOCK_UTC)

        merchant = validate_success(
            api.create_merchant(create_merchant_payload(ctx["z"]), ADMIN), 201
        )

        assert_instant_format(merchant["created_at"], "merchant.created_at")
        assert_instant_format(merchant["updated_at"], "merchant.updated_at")
        assert merchant["created_at"] == MERCHANT_CREATED_CLOCK_UTC
        assert merchant["updated_at"] == MERCHANT_CREATED_CLOCK_UTC
        assert merchant["version"] == 1
        assert merchant["integration_state"] == "PENDING"

    def test_a_later_transition_moves_only_updated_at(self, api):
        """PRD §2.4: "`updated_at` (string): the instant the row was last mutated, in
        the same format."
        PRD §2.4: "A read never changes a `version`, and a mutation always refreshes
        `updated_at` alongside it."
        PRD §3.3: "Activation carries the merchant from `PENDING` to `ACTIVE` and
        requires the merchant's zone to be in `permit_state` `PERMITTED`; a merchant in a
        `PROVISIONED`, `RESTRICTED` or `REVOKED` zone cannot be activated and the attempt
        is refused with `ERR_ZONE_NOT_PERMITTED`."
        PRD §3.3: "Each transition advances the merchant's `version` by one."

        The zone was created before both jumps, so neither jump may rewrite its
        `created_at`.

        Design: Corner/cross_cutting_complexity_layers/derived_instants_follow_the_logical_clock
        """
        ctx = build_scenario("permitted")
        set_clock(MERCHANT_CREATED_CLOCK_UTC)
        merchant = validate_success(
            api.create_merchant(create_merchant_payload(ctx["z"]), ADMIN), 201
        )
        set_clock(MERCHANT_ACTIVATED_CLOCK_UTC)

        activated = validate_success(
            api.merchant_integration_transition(
                merchant["id"], integration_transition_payload("ACTIVATE"), ADMIN
            )
        )

        zone = read_zone(ctx["z"])
        assert activated["integration_state"] == "ACTIVE"
        assert activated["version"] == 2
        assert activated["updated_at"] == MERCHANT_ACTIVATED_CLOCK_UTC
        assert activated["created_at"] == MERCHANT_CREATED_CLOCK_UTC
        assert read_merchant(merchant["id"])["created_at"] == MERCHANT_CREATED_CLOCK_UTC
        assert zone["created_at"] == ZONE_CREATED_CLOCK_UTC
        assert_instant_format(zone["created_at"], "zone.created_at")


def _one_flow_through_all_four_zone_producers() -> dict:
    """Dispatch, container handoff, depot reservation and incident filing, in
    that order, against one zone that started every ledger at zero."""
    ctx = setup_received_order()
    bay = add_depot_bay(ctx["z"], "BAY-1", bay_type="CHARGE", power_kw=22.0, state="OPEN")
    ctx["b"] = bay["id"]
    ctx["mission"] = dispatch_mission(ctx["order"], ctx["r"])
    ctx["mi"] = ctx["mission"]["id"]
    ctx["mission"] = load_mission(ctx["mi"], ctx["m"], 22.0)
    ctx["reservation"] = reserve_bay(bay, ctx["r"], **NINETY_MINUTE_WINDOW)
    ctx["report"] = file_incident(
        ctx["z"],
        ctx["r"],
        OPERATOR,
        mission_id=ctx["mi"],
        category="OBSTRUCTION",
        severity="MINOR",
        narrative="wheelie bin left across the walkway",
        estimated_damage_cents=0,
    )
    ctx["ir"] = ctx["report"]["id"]
    return ctx


class TestZoneCountersAreWrittenByEveryProducer:
    def test_four_ledgers_on_one_zone_row_move_in_four_different_layers(self, api):
        """PRD §3.6: "The zone's `on_mission_robot_count` advances by one."
        PRD §3.7: "A successful handoff carries the mission from `PLANNED` to `LOADED`,
        stores `actual_payload_liters` and mints the lid access code from a per-zone
        monotonic counter: the zone's `lid_code_sequence` advances by one, and
        `lid_access_code` becomes the six-digit zero-padded decimal representation of
        100000 plus the new value of that sequence, so the first code minted in a zone is
        100001."
        PRD §3.4: "Creating a reservation books its minutes into two denormalized
        ledgers at once: the bay's `committed_minutes` increases by `window_minutes` and
        the zone's `reserved_bay_minutes` increases by the same amount, with the `version`
        of the bay, the zone and the new reservation each advancing by one."
        PRD §3.9: "The report is created in `report_state` `DRAFT`, `filed_by_user_id`
        latches the calling user so the later submission can enforce separation of duties,
        and the zone's `open_incident_count` advances by one along with the zone's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/zone_counters_are_written_by_every_producer
        """
        ctx = _one_flow_through_all_four_zone_producers()

        zone = read_zone(ctx["z"])
        assert zone["on_mission_robot_count"] == 1
        assert zone["lid_code_sequence"] == 1
        assert read_mission(ctx["mi"])["lid_access_code"] == "100001"
        assert zone["reserved_bay_minutes"] == 90
        assert read_bay(ctx["b"])["committed_minutes"] == 90
        assert zone["open_incident_count"] == 1

    def test_the_zone_version_counts_producers_and_the_incident_freezes_two_fields(
        self, api
    ):
        """PRD §2.4: "`version` (integer): 1 immediately after creation, and increased
        by exactly 1 on every mutation of that row."
        PRD §3.9: "`insurer_notification_required` is true when the `severity` is
        `CRITICAL`, or when `estimated_damage_cents` is at or above the zone's
        `insurer_notify_threshold_cents`; the damage comparison is inclusive, so with the
        default threshold of 25000 cents a damage estimate of exactly 25000 does require
        the insurer branch."
        PRD §3.9: "`municipal_due_by_utc` is the filing deadline and applies only to
        reports that the municipality must see: for a `SERIOUS` or `CRITICAL` report it is
        the report's `created_at` advanced by the fixed platform constant of 72 filing
        hours, and for a `MINOR` report it is null."
        PRD §3.9: "Two fields are computed at creation and then frozen."

        Six writes reached the zone row: its creation, the permit activation and then
        the four producers of the ledgers above.

        Design: Corner/cross_cutting_complexity_layers/zone_counters_are_written_by_every_producer
        """
        ctx = _one_flow_through_all_four_zone_producers()

        report = read_incident(ctx["ir"])
        assert read_zone(ctx["z"])["version"] == 6
        assert report["report_state"] == "DRAFT"
        assert report["filed_by_user_id"] == OPERATOR["X-User-ID"]
        assert report["insurer_notification_required"] is False
        assert report["municipal_due_by_utc"] is None
