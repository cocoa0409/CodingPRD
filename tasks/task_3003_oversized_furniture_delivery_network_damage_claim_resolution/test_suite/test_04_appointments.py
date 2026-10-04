"""Delivery appointments: window validation boundaries, OCC stale-version
rejection, half-open crew overlap, and the no-show rebooking path."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_shipment_at_hub,
    setup_routed_network_order,
    create_item,
    create_freight_lane,
    create_linehaul,
    place_order,
    get_shipment_for_order,
    book_appointment,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["network_admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]


def _fresh_version(api, shipment_id):
    return validate_success(api.get_shipment(shipment_id, ADMIN))["version"]


class TestAppointmentWindowTwoHourDurationBoundary:
    def test_short_and_empty_windows_rejected_then_two_hours_accepted(self, api):
        """PRD §3.5: "The window itself must satisfy three temporal
        conditions: `window_start` strictly before `window_end`, a duration
        of at least 2 hours, and a `window_start` that is not before the
        logical clock's current instant; any violation is rejected with
        `ERR_INVALID_APPOINTMENT_WINDOW`."

        Design: Difficulty/boundary_precision_check/appointment_window_two_hour_duration_boundary
        """
        refs = setup_shipment_at_hub()
        version = _fresh_version(api, refs["shipment"]["id"])

        short = api.create_appointment(
            {
                "shipment_id": refs["shipment"]["id"],
                "window_start": "2026-09-12T14:00:00Z",
                "window_end": "2026-09-12T15:59:00Z",
                "crew_id": "CREW-2",
                "expected_shipment_version": version,
            },
            HUB_OP,
        )
        validate_error(short, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)

        empty = api.create_appointment(
            {
                "shipment_id": refs["shipment"]["id"],
                "window_start": "2026-09-13T09:00:00Z",
                "window_end": "2026-09-13T09:00:00Z",
                "crew_id": "CREW-2",
                "expected_shipment_version": version,
            },
            HUB_OP,
        )
        validate_error(empty, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)

        # Failed bookings leave the shipment AT_HUB with version unchanged.
        assert _fresh_version(api, refs["shipment"]["id"]) == version
        ok = api.create_appointment(
            {
                "shipment_id": refs["shipment"]["id"],
                "window_start": "2026-09-12T09:00:00Z",
                "window_end": "2026-09-12T11:00:00Z",  # exactly 2 hours
                "crew_id": "CREW-1",
                "expected_shipment_version": version,
            },
            HUB_OP,
        )
        data = validate_success(ok, 201)
        assert data["status"] == "BOOKED"

    def test_exactly_two_hours_is_accepted(self, api):
        """PRD §3.5: "The window itself must satisfy three temporal
        conditions: `window_start` strictly before `window_end`, a duration
        of at least 2 hours, and a `window_start` that is not before the
        logical clock's current instant; any violation is rejected with
        `ERR_INVALID_APPOINTMENT_WINDOW`."

        Design: Difficulty/boundary_precision_check/appointment_window_two_hour_duration_boundary
        """
        refs = setup_shipment_at_hub()
        appt = book_appointment(
            api_client.get_shipment(refs["shipment"]["id"], ADMIN).json()["data"],
            window_start="2026-09-12T09:00:00Z",
            window_end="2026-09-12T11:00:00Z",
        )
        assert appt["status"] == "BOOKED"


class TestStaleShipmentVersionOnBooking:
    def test_stale_shipment_version_on_booking_returns_412(self, api):
        """PRD §2.8: "A booking request must carry
        `expected_shipment_version`, a non-optional field whose value is the
        `version` of the target `Shipment` as the client last observed it. If
        the value does not match the shipment's current `version` — because
        another writer has booked or cancelled an appointment against the
        same shipment and thereby legitimately advanced its version — the
        booking is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        appointment is created."

        Design: Corner/errors/stale_shipment_version_on_booking_returns_412
        """
        refs = setup_shipment_at_hub()
        v0 = _fresh_version(api, refs["shipment"]["id"])
        appt = book_appointment(refs["shipment"])
        validate_success(api.cancel_appointment(appt["id"], HUB_OP), 200)
        v2 = _fresh_version(api, refs["shipment"]["id"])
        assert v2 == v0 + 2, "one version bump per write: book, then cancel"

        stale = api.create_appointment(
            {
                "shipment_id": refs["shipment"]["id"],
                "window_start": "2026-09-14T09:00:00Z",
                "window_end": "2026-09-14T12:00:00Z",
                "crew_id": "CREW-1",
                "expected_shipment_version": v0,
            },
            HUB_OP,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = api.create_appointment(
            {
                "shipment_id": refs["shipment"]["id"],
                "window_start": "2026-09-14T09:00:00Z",
                "window_end": "2026-09-14T12:00:00Z",
                "crew_id": "CREW-1",
                "expected_shipment_version": v2,
            },
            HUB_OP,
        )
        data = validate_success(fresh, 201)
        assert data["status"] == "BOOKED"


class TestCrewWindowHalfOpenOverlap:
    def _setup_two_shipments_at_hub(self, api):
        """Two ROOM_OF_CHOICE shipments at the same hub, both AT_HUB."""
        refs = setup_shipment_at_hub(service_level="ROOM_OF_CHOICE")
        appt1 = book_appointment(
            refs["shipment"],
            window_start="2026-09-12T09:00:00Z",
            window_end="2026-09-12T12:00:00Z",
            crew_id="CREW-1",
        )
        refs["appt1"] = appt1
        lh_b = create_linehaul(
            refs["hub"]["id"], planned_arrival_date="2026-09-11",
            origin_ship_date="2026-09-08", capacity=10,
        )
        order2 = place_order(refs["customer"], refs["item"]["id"], "ROOM_OF_CHOICE")
        ship2 = get_shipment_for_order(order2["id"])
        validate_success(
            api_client.depart_shipment(ship2["id"], TEST_USERS["carrier_rep_headers"]), 200
        )
        validate_success(api_client.depart_linehaul(lh_b["id"], ADMIN), 200)
        validate_success(api_client.arrive_linehaul(lh_b["id"], HUB_OP), 200)
        refs["ship2"] = validate_success(api.get_shipment(ship2["id"], ADMIN))
        return refs

    def test_overlapping_booking_rejected(self, api):
        """PRD §3.5: "Then, for `ROOM_OF_CHOICE` service, the new booking must
        not overlap any existing `BOOKED` appointment on the same (`hub_id`,
        `crew_id`) pair, where windows are half-open intervals — the start is
        inclusive and the end is exclusive — so a back-to-back booking whose
        start equals the previous window's end is allowed. An overlap is
        rejected with `ERR_APPOINTMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap
        """
        refs = self._setup_two_shipments_at_hub(api)
        overlap = api.create_appointment(
            {
                "shipment_id": refs["ship2"]["id"],
                "window_start": "2026-09-12T11:00:00Z",
                "window_end": "2026-09-12T14:00:00Z",
                "crew_id": "CREW-1",
                "expected_shipment_version": refs["ship2"]["version"],
            },
            HUB_OP,
        )
        validate_error(overlap, ApiErrorId.ERR_APPOINTMENT_OVERLAP)

    def test_back_to_back_booking_allowed(self, api):
        """PRD §3.5: "windows are half-open intervals — the start is inclusive
        and the end is exclusive — so a back-to-back booking whose start
        equals the previous window's end is allowed."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap
        """
        refs = self._setup_two_shipments_at_hub(api)
        back_to_back = api.create_appointment(
            {
                "shipment_id": refs["ship2"]["id"],
                "window_start": "2026-09-12T12:00:00Z",
                "window_end": "2026-09-12T15:00:00Z",
                "crew_id": "CREW-1",
                "expected_shipment_version": refs["ship2"]["version"],
            },
            HUB_OP,
        )
        data = validate_success(back_to_back, 201)
        assert data["status"] == "BOOKED"


class TestNoShowRebooking:
    def test_no_show_keeps_shipment_out_for_delivery_and_allows_rebooking(self, api):
        """PRD §3.5: "A `HubOperator` recording a customer no-show moves the
        appointment to `NO_SHOW` while the shipment stays `OUT_FOR_DELIVERY`,
        and a replacement appointment may subsequently be booked."

        Design: Corner/state_machines/no_show_keeps_shipment_out_for_delivery_and_allows_rebooking
        """
        refs = setup_shipment_at_hub()
        appt = book_appointment(refs["shipment"])
        result = validate_success(
            api.mark_appointment_no_show(appt["id"], HUB_OP), 200
        )
        assert result["status"] == "NO_SHOW"
        shipment = validate_success(api.get_shipment(refs["shipment"]["id"], ADMIN))
        assert shipment["current_state"] == "OUT_FOR_DELIVERY", (
            "no-show does not revert the shipment to AT_HUB"
        )
        rebooked = book_appointment(
            shipment,
            window_start="2026-09-13T09:00:00Z",
            window_end="2026-09-13T12:00:00Z",
            crew_id="CREW-1",
        )
        assert rebooked["status"] == "BOOKED"


class TestOrderParallelDimensions:
    def test_appointment_booking_advances_dimensions_independently(self, api):
        """PRD §3.5: "Booking advances the shipment from `AT_HUB` to
        `OUT_FOR_DELIVERY`, advances the order's `order_state` from
        `IN_TRANSIT` to `OUT_FOR_DELIVERY`, moves the order's
        `fulfillment_state` from `NONE` to `SCHEDULED`, and increments the
        shipment's `version` by one"
        PRD §3.3: "An order carries two parallel state dimensions that evolve
        independently."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
        """
        refs = setup_shipment_at_hub()
        appt = book_appointment(refs["shipment"])
        order_mid = validate_success(api.get_order(refs["order"]["id"], ADMIN))
        assert order_mid["order_state"] == "OUT_FOR_DELIVERY"
        assert order_mid["fulfillment_state"] == "SCHEDULED"

        validate_success(api.complete_appointment(appt["id"], HUB_OP), 200)
        order_end = validate_success(api.get_order(refs["order"]["id"], ADMIN))
        assert order_end["order_state"] == "DELIVERED"
        assert order_end["fulfillment_state"] == "FULFILLED"

    def test_cancelled_parcel_order_keeps_fulfillment_none(self, api):
        """PRD §3.3: "Cancelling moves the order to `CANCELLED`, moves its
        shipment to `EXCEPTION`, decrements the bound linehaul's
        `committed_count` by one to release the slot, and leaves
        `fulfillment_state` at `NONE`."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
        """
        refs = setup_routed_network_order()
        # Parcel branch: small PARCEL_ELIGIBLE item with a PARCEL lane.
        create_freight_lane(
            leg_mode="PARCEL", dest_zone="ZONE_NE",
            base_rate_cents=1500, per_lb_rate_cents=10, transit_days=2,
        )
        item_par = create_item(
            refs["supplier"]["id"], sku="SKU-PAR-1",
            dim_length_in=20, dim_width_in=16, dim_height_in=12,
            weight_lb=12, declared_value_cents=9000, white_glove_eligible=False,
        )
        order_b = place_order(refs["customer"], item_par["id"], "THRESHOLD")
        from test_helpers import make_customer_headers

        resp = api.cancel_order(
            order_b["id"], make_customer_headers(refs["customer"]["id"])
        )
        validate_success(resp, 200)
        order_cancel = validate_success(api.get_order(order_b["id"], ADMIN))
        assert order_cancel["order_state"] == "CANCELLED"
        assert order_cancel["fulfillment_state"] == "NONE", (
            "the fulfillment axis is untouched by a commercial cancel"
        )
