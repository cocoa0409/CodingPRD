"""Tests for the seven-day return window and refund (PRD §3.7)."""
from test_helpers import (
    api_client,
    TEST_USERS,
    make_customer_headers,
    validate_success,
    validate_error,
    get_success_data,
    assert_same_instant,
    ApiErrorId,
    create_customer,
    create_listed_vehicle,
    create_completed_order,
    create_returned_order_with_transit,
)


class TestReturnAcceptanceCascade:
    """Depth-4 cascade on ACCEPT (PRD §3.7)."""

    def test_accept_cascade_completes_order_and_refunds(self, api):
        """PRD §3.7: "On ACCEPT, the order moves from RETURN_INITIATED to the terminal
        RETURN_COMPLETED state. The refund is computed as the order's total_due_cents —
        everything the customer paid or financed — minus an excess-wear fee of 50000 cents
        when the intake inspection flags excess_wear as true, floored at zero; the result
        is stored in refund_amount_cents along with the recorded return_inspection_result,
        and the invariant holds that refund_amount_cents plus the excess-wear fee equals
        total_due_cents whenever the base covers the fee. The payment_status moves from
        REFUND_PENDING to REFUNDED and refund_processed_at is set. The vehicle returns
        from RETURN_INBOUND to INTAKE, and the system creates a ReconIntake in
        PENDING_ARRIVAL to place it at the center serving the vehicle's original market —
        the selector picks the center whose market_code equals the vehicle's market_code,
        breaking ties toward the center with the earliest created_at ... Any defect claims
        on the order still in FILED or UNDER_REVIEW are auto-denied with review_note set
        to 'order returned'. The transit moves to the terminal INTAKE_DONE, and a BLOCKED
        title registration is deleted."

        Design: Difficulty/transitive_cascade/return_acceptance_cascade_depth4
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, appt = create_completed_order(
            cust["id"], vehicle["id"], odometer_at_delivery=15100
        )
        claim_resp = api.create_defect_claim(
            {"order_id": order["id"], "defect_description": "rattle", "defect_area": "dashboard", "current_mileage": 15150},
            cust_headers,
        )
        claim = get_success_data(claim_resp)
        api.review_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"])
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        api.return_order(
            order["id"],
            {"return_mileage": 15300, "reason_code": "CHANGED_MIND"},
            cust_headers,
        )
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-06T09:00:00Z", "end_at": "2026-09-06T10:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        api.create_center(
            {"name": "ATL RC", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        resp = api.return_intake(
            order["id"],
            {"inspection_result": "ACCEPT", "excess_wear": False},
            advocate,
        )
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "RETURN_COMPLETED"
        assert order_after["payment_status"] == "REFUNDED"
        assert order_after["refund_amount_cents"] == 2140000
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "INTAKE"
        intakes = get_success_data(
            api.get_vehicle_recon_intakes(vehicle["id"], TEST_USERS["recon_operator_headers"])
        )
        assert any(i["status"] == "PENDING_ARRIVAL" for i in intakes)
        claim_after = get_success_data(api.get_defect_claim(claim["id"], TEST_USERS["warranty_admin_headers"]))
        assert claim_after["status"] == "DENIED"
        assert claim_after["review_note"] == "order returned"
        transits = get_success_data(api.get_return_transit(order["id"], advocate))
        assert transits[0]["status"] == "INTAKE_DONE"

    def test_accept_cascade_places_vehicle_at_market_center(self, api):
        """PRD §3.7: "the system creates a ReconIntake in PENDING_ARRIVAL to place it at
        the center serving the vehicle's original market — the selector picks the center
        whose market_code equals the vehicle's market_code, breaking ties toward the
        center with the earliest created_at."

        Design: Difficulty/transitive_cascade/return_acceptance_cascade_depth4
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=15100)
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        api.return_order(
            order["id"],
            {"return_mileage": 15300, "reason_code": "CHANGED_MIND"},
            cust_headers,
        )
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-06T09:00:00Z", "end_at": "2026-09-06T10:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        api.create_center(
            {"name": "ATL RC", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        resp = api.return_intake(
            order["id"],
            {"inspection_result": "ACCEPT", "excess_wear": False},
            advocate,
        )
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "RETURN_COMPLETED"
        assert order_after["payment_status"] == "REFUNDED"
        intakes = get_success_data(
            api.get_vehicle_recon_intakes(vehicle["id"], TEST_USERS["recon_operator_headers"])
        )
        assert any(i["status"] == "PENDING_ARRIVAL" for i in intakes)

    def test_accept_with_excess_wear_fee(self, api):
        """PRD §3.7: "The refund is computed as the order's total_due_cents ... minus an
        excess-wear fee of 50000 cents when the intake inspection flags excess_wear as
        true, floored at zero; ... the invariant holds that refund_amount_cents plus the
        excess-wear fee equals total_due_cents whenever the base covers the fee."

        Design: Difficulty/compensating_invariant/return_refund_conserves_customer_payment
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=44100)
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        api.return_order(
            order["id"],
            {"return_mileage": 44300, "reason_code": "CHANGED_MIND"},
            cust_headers,
        )
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-06T09:00:00Z", "end_at": "2026-09-06T10:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        api.create_center(
            {"name": "ATL RC", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        resp = api.return_intake(
            order["id"],
            {"inspection_result": "ACCEPT", "excess_wear": True},
            advocate,
        )
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "RETURN_COMPLETED"
        assert order_after["payment_status"] == "REFUNDED"
        assert order_after["refund_amount_cents"] == 2090000
        assert order_after["refund_amount_cents"] + 50000 == order_after["total_due_cents"]


class TestReturnRejection:
    """REJECT branch restores the sale (PRD §3.7)."""

    def test_reject_restores_payment_and_removes_vehicle(self, api):
        """PRD §3.7: "On REJECT — for example when the intake inspection finds undisclosed
        damage — the sale is restored. The order returns from RETURN_INITIATED to
        COMPLETED; payment_status moves from REFUND_PENDING back to its original funding
        state, PAID for a cash purchase or FINANCED for a financed one; the stored
        return_requested_mileage and return_reason_code are cleared. The vehicle moves
        from RETURN_INBOUND to REMOVED from sale pending disposition."

        Design: Difficulty/compensating_invariant/return_refund_conserves_customer_payment
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=44100)
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        api.return_order(
            order["id"],
            {"return_mileage": 44300, "reason_code": "CHANGED_MIND"},
            cust_headers,
        )
        advocate = TEST_USERS["customer_advocate_headers"]
        api.schedule_pickup(
            order["id"],
            {"start_at": "2026-09-06T09:00:00Z", "end_at": "2026-09-06T10:00:00Z"},
            advocate,
        )
        api.transit_pickup(order["id"], advocate)
        api.transit_arrive(order["id"], advocate)
        resp = api.return_intake(
            order["id"],
            {"inspection_result": "REJECT"},
            advocate,
        )
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "COMPLETED"
        assert order_after["payment_status"] == "PAID"
        assert order_after["refund_amount_cents"] is None
        assert order_after["return_requested_mileage"] is None
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "REMOVED"


class TestReturnMileageBoundary:
    """Boundary precision on the 400-mile return limit (PRD §3.7)."""

    def test_exactly_400_miles_allowed(self, api):
        """PRD §3.7: "the distance driven, return_mileage minus odometer_at_delivery, must
        not exceed 400 miles — exactly 400 is permitted, 401 is rejected with
        ERR_MILEAGE_LIMIT_EXCEEDED."

        Design: Difficulty/boundary_precision_check/return_mileage_exactly_400_vs_401
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=10000)
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        resp = api.return_order(
            order["id"],
            {"return_mileage": 10400, "reason_code": "BOUNDARY_OK"},
            cust_headers,
        )
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "RETURN_INITIATED"
        assert_same_instant(order_after["return_deadline"], "2026-09-08T00:00:00Z")

    def test_401_miles_rejected(self, api):
        """PRD §3.7: "the distance driven, return_mileage minus odometer_at_delivery, must
        not exceed 400 miles — exactly 400 is permitted, 401 is rejected with
        ERR_MILEAGE_LIMIT_EXCEEDED."

        Design: Difficulty/boundary_precision_check/return_mileage_exactly_400_vs_401
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=10000)
        api.set_clock("2026-09-05T00:00:00Z", TEST_USERS["platform_admin_headers"])
        resp = api.return_order(
            order["id"],
            {"return_mileage": 10401, "reason_code": "BOUNDARY_OVER"},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MILEAGE_LIMIT_EXCEEDED, 422)
        order_after = get_success_data(api.get_order(order["id"], TEST_USERS["platform_admin_headers"]))
        assert order_after["status"] == "COMPLETED"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "SOLD"


class TestReturnWindowBoundary:
    """Return window closed after deadline (PRD §3.7)."""

    def test_return_after_deadline_rejected(self, api):
        """PRD §3.7: "the current instant must not be after the order's return_deadline —
        the window is inclusive of the deadline instant itself, and a later initiation is
        rejected with ERR_RETURN_WINDOW_CLOSED."

        Design: Corner/validations/return_window_closed_after_deadline
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=6100)
        api.set_clock("2026-09-08T00:00:01Z", TEST_USERS["platform_admin_headers"])
        resp = api.return_order(
            order["id"],
            {"return_mileage": 6200, "reason_code": "TOO_LATE"},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED, 422)
        order_after = get_success_data(api.get_order(order["id"], TEST_USERS["platform_admin_headers"]))
        assert order_after["status"] == "COMPLETED"
        assert order_after["payment_status"] == "PAID"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "SOLD"
