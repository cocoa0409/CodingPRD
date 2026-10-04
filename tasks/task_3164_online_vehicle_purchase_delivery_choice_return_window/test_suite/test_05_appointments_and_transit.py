"""Tests for appointment overlap and return-transit buffering (PRD §3.5, §3.7)."""
from test_helpers import (
    api_client,
    TEST_USERS,
    make_customer_headers,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_customer,
    create_listed_vehicle,
    create_structured_order,
    create_completed_order,
)


class TestHomeDeliveryOverlap:
    """Half-open interval semantics for home-delivery appointments (PRD §3.5)."""

    def test_adjacent_booking_succeeds(self, api):
        """PRD §3.5: "a home-delivery booking's half-open interval must not intersect any
        other SCHEDULED home-delivery appointment in the same market ... edge-touching
        intervals — where one appointment's end_at equals another's start_at — do not
        conflict."

        Design: Difficulty/resource_temporal_overlap/home_delivery_half_open_adjacency
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1 = create_structured_order(cust["id"], v1["id"])
        o2 = create_structured_order(cust["id"], v2["id"])
        appt_payload = {
            "expected_order_version": o1["version"],
            "market_code": "ATL-A",
            "address_region": "ATL-CORE",
            "start_at": "2026-09-02T10:00:00Z",
            "end_at": "2026-09-02T11:00:00Z",
        }
        api.book_appointment(o1["id"], appt_payload, cust_headers)
        appt2_payload = {
            "expected_order_version": o2["version"],
            "market_code": "ATL-A",
            "address_region": "ATL-CORE",
            "start_at": "2026-09-02T11:00:00Z",
            "end_at": "2026-09-02T12:00:00Z",
        }
        resp = api.book_appointment(o2["id"], appt2_payload, cust_headers)
        appt2 = validate_success(resp, 201)
        assert appt2["status"] == "SCHEDULED"
        o2_after = get_success_data(api.get_order(o2["id"], cust_headers))
        assert o2_after["status"] == "APPOINTMENT_SET"

    def test_edge_touching_reverse_order_succeeds(self, api):
        """PRD §3.5: "edge-touching intervals — where one appointment's end_at equals
        another's start_at — do not conflict."

        Design: Difficulty/resource_temporal_overlap/home_delivery_half_open_adjacency
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1 = create_structured_order(cust["id"], v1["id"])
        o2 = create_structured_order(cust["id"], v2["id"])
        api.book_appointment(
            o1["id"],
            {
                "expected_order_version": o1["version"],
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T11:00:00Z",
                "end_at": "2026-09-02T12:00:00Z",
            },
            cust_headers,
        )
        resp = api.book_appointment(
            o2["id"],
            {
                "expected_order_version": o2["version"],
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
            cust_headers,
        )
        appt2 = validate_success(resp, 201)
        assert appt2["status"] == "SCHEDULED"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.5: "a home-delivery booking's half-open interval must not intersect any
        other SCHEDULED home-delivery appointment in the same market ... A violation
        rejects the booking with ERR_APPOINTMENT_CONFLICT."

        Design: Corner/endpoints/appointment_interior_overlap_rejected
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1 = create_structured_order(cust["id"], v1["id"])
        o2 = create_structured_order(cust["id"], v2["id"])
        api.book_appointment(
            o1["id"],
            {
                "expected_order_version": o1["version"],
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
            cust_headers,
        )
        resp = api.book_appointment(
            o2["id"],
            {
                "expected_order_version": o2["version"],
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:30:00Z",
                "end_at": "2026-09-02T11:30:00Z",
            },
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CONFLICT, 409)
        o2_after = get_success_data(api.get_order(o2["id"], cust_headers))
        assert o2_after["status"] == "STRUCTURED"
        assert o2_after["delivery_status"] == "NOT_SCHEDULED"


class TestVendingMachineOverlap:
    """Vending-machine overlap scoped per site (PRD §3.5)."""

    def test_different_site_overlap_succeeds_same_site_rejected(self, api):
        """PRD §3.5: "a vending-machine booking's interval must not intersect any other
        SCHEDULED appointment at the same vending_site_code ... A violation rejects the
        booking with ERR_APPOINTMENT_CONFLICT."

        Design: Corner/endpoints/vending_machine_site_scoped_overlap
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v3 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1 = create_structured_order(cust["id"], v1["id"], fulfillment_choice="VENDING_MACHINE")
        o2 = create_structured_order(cust["id"], v2["id"], fulfillment_choice="VENDING_MACHINE")
        o3 = create_structured_order(cust["id"], v3["id"], fulfillment_choice="VENDING_MACHINE")
        api.book_appointment(
            o1["id"],
            {
                "expected_order_version": o1["version"],
                "market_code": "ATL-A",
                "vending_site_code": "ATL-VM-1",
                "start_at": "2026-09-02T14:00:00Z",
                "end_at": "2026-09-02T15:00:00Z",
            },
            cust_headers,
        )
        resp = api.book_appointment(
            o2["id"],
            {
                "expected_order_version": o2["version"],
                "market_code": "ATL-A",
                "vending_site_code": "ATL-VM-2",
                "start_at": "2026-09-02T14:00:00Z",
                "end_at": "2026-09-02T15:00:00Z",
            },
            cust_headers,
        )
        appt2 = validate_success(resp, 201)
        assert appt2["status"] == "SCHEDULED"
        resp = api.book_appointment(
            o3["id"],
            {
                "expected_order_version": o3["version"],
                "market_code": "ATL-A",
                "vending_site_code": "ATL-VM-1",
                "start_at": "2026-09-02T14:30:00Z",
                "end_at": "2026-09-02T15:30:00Z",
            },
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_CONFLICT, 409)
        o3_after = get_success_data(api.get_order(o3["id"], cust_headers))
        assert o3_after["status"] == "STRUCTURED"


class TestReturnTransitBuffer:
    """120-minute buffered interval for return transit (PRD §3.7)."""

    def test_inside_buffer_rejected_exactly_120_min_succeeds(self, api):
        """PRD §3.7: "the system creates a ReturnTransit in PICKUP_SCHEDULED with the order
        and vehicle references and the market_code copied from the vehicle, and applies a
        mandatory crew turnaround buffer_minutes of 120 minutes — for conflict purposes the
        pickup occupies the interval from start_at through end_at plus the buffer. Within
        a market, that buffered interval must not intersect the buffered interval of any
        other transit in PICKUP_SCHEDULED or PICKED_UP; adjacency is permitted only when
        the gap between intervals is at least the 120-minute buffer. A collision rejects
        the scheduling with ERR_TRANSIT_SLOT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/return_transit_buffered_window_semantics
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1, _ = create_completed_order(cust["id"], v1["id"], fulfillment_choice="VENDING_MACHINE", odometer_at_delivery=33100)
        o2, _ = create_completed_order(cust["id"], v2["id"], fulfillment_choice="VENDING_MACHINE", odometer_at_delivery=33100)
        api.return_order(o1["id"], {"return_mileage": 33200, "reason_code": "X"}, cust_headers)
        api.return_order(o2["id"], {"return_mileage": 33200, "reason_code": "X"}, cust_headers)
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            o1["id"],
            {"start_at": "2026-09-03T09:00:00Z", "end_at": "2026-09-03T10:00:00Z"},
            advocate,
        )
        resp = api.schedule_pickup(
            o2["id"],
            {"start_at": "2026-09-03T11:00:00Z", "end_at": "2026-09-03T12:00:00Z"},
            advocate,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSIT_SLOT_CONFLICT, 409)
        resp = api.schedule_pickup(
            o2["id"],
            {"start_at": "2026-09-03T12:00:00Z", "end_at": "2026-09-03T13:00:00Z"},
            advocate,
        )
        transit2 = validate_success(resp, 201)
        assert transit2["status"] == "PICKUP_SCHEDULED"

    def test_gap_less_than_120_minutes_rejected(self, api):
        """PRD §3.7: "Within a market, that buffered interval must not intersect the
        buffered interval of any other transit in PICKUP_SCHEDULED or PICKED_UP; adjacency
        is permitted only when the gap between intervals is at least the 120-minute buffer.
        A collision rejects the scheduling with ERR_TRANSIT_SLOT_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/return_transit_buffered_window_semantics
        """
        cust, cust_headers = create_customer(state_code="GA")
        v1 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        v2 = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        o1, _ = create_completed_order(cust["id"], v1["id"], fulfillment_choice="VENDING_MACHINE", odometer_at_delivery=33100)
        o2, _ = create_completed_order(cust["id"], v2["id"], fulfillment_choice="VENDING_MACHINE", odometer_at_delivery=33100)
        api.return_order(o1["id"], {"return_mileage": 33200, "reason_code": "X"}, cust_headers)
        api.return_order(o2["id"], {"return_mileage": 33200, "reason_code": "X"}, cust_headers)
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            o1["id"],
            {"start_at": "2026-09-03T09:00:00Z", "end_at": "2026-09-03T10:00:00Z"},
            advocate,
        )
        resp = api.schedule_pickup(
            o2["id"],
            {"start_at": "2026-09-03T11:30:00Z", "end_at": "2026-09-03T12:30:00Z"},
            advocate,
        )
        validate_error(resp, ApiErrorId.ERR_TRANSIT_SLOT_CONFLICT, 409)
