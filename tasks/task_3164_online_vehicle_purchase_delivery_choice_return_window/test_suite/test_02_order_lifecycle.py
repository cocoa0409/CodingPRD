"""Tests for order lifecycle: appointment, no-show, cancel cascades (PRD §3.5)."""
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
    create_appointment_set_order,
    create_completed_order,
    create_prequalification,
)


class TestParallelStatusDimensions:
    """PurchaseOrder status, payment_status, delivery_status evolve independently."""

    def test_no_show_reverts_order_to_structured(self, api):
        """PRD §3.5: "A CustomerAdvocate may mark a SCHEDULED appointment as NO_SHOW once
        the logical clock has passed its end_at. ... Either way, the appointment moves to
        its terminal state and the order regresses from APPOINTMENT_SET back to STRUCTURED
        with delivery_status returning to NOT_SCHEDULED, so the customer must re-book."

        Design: Difficulty/non_linear_state_machine/purchase_order_parallel_status_dimensions
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, appt = create_appointment_set_order(
            cust["id"],
            vehicle["id"],
            appointment_overrides={
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
        )
        api.set_clock("2026-09-03T00:00:00Z", TEST_USERS["platform_admin_headers"])
        resp = api.no_show_appointment(appt["id"], TEST_USERS["customer_advocate_headers"])
        appt_after = validate_success(resp, 200)
        assert appt_after["status"] == "NO_SHOW"
        order_after = get_success_data(api.get_order(order["id"], TEST_USERS["platform_admin_headers"]))
        assert order_after["status"] == "STRUCTURED"
        assert order_after["delivery_status"] == "NOT_SCHEDULED"
        assert order_after["payment_status"] == "UNPAID"

    def test_no_show_keeps_payment_status_unchanged(self, api):
        """PRD §3.5: "the order regresses from APPOINTMENT_SET back to STRUCTURED with
        delivery_status returning to NOT_SCHEDULED" — payment_status is not mentioned and
        remains UNPAID for a cash order that never reached completion.

        Design: Difficulty/non_linear_state_machine/purchase_order_parallel_status_dimensions
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, appt = create_appointment_set_order(
            cust["id"],
            vehicle["id"],
            appointment_overrides={
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
        )
        api.set_clock("2026-09-03T00:00:00Z", TEST_USERS["platform_admin_headers"])
        api.no_show_appointment(appt["id"], TEST_USERS["customer_advocate_headers"])
        order_after = get_success_data(api.get_order(order["id"], TEST_USERS["platform_admin_headers"]))
        assert order_after["status"] == "STRUCTURED"
        assert order_after["delivery_status"] == "NOT_SCHEDULED"
        assert order_after["payment_status"] == "UNPAID"


class TestCancellationCascade:
    """Order cancel fires compensation chain (PRD §3.5)."""

    def test_cancel_structured_releases_lock_and_deletes_title(self, api):
        """PRD §3.5: "When the order had been structured with financing, the locked
        prequalification is released from LOCKED back to PREQUALIFIED per §3.4. When the
        order was STRUCTURED or APPOINTMENT_SET, the linked TitleRegistration still in
        PENDING is deleted outright."

        Design: Difficulty/transitive_cascade/order_cancellation_cascade_depth3
        """
        cust, cust_headers = create_customer(state_code="GA")
        pq = create_prequalification(cust["id"], annual_income_cents=8000000, credit_band="A")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order = create_structured_order(
            cust["id"], vehicle["id"], financing_id=pq["id"], down_payment_cents=300000
        )
        resp = api.cancel_order(order["id"], cust_headers)
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "CANCELLED"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "LISTED"
        pq_after = get_success_data(api.get_prequal(pq["id"], cust_headers))
        assert pq_after["status"] == "PREQUALIFIED"
        assert pq_after["locked_order_id"] is None
        title_list = get_success_data(
            api.get_order_title_registration(order["id"], TEST_USERS["registration_clerk_headers"])
        )
        assert title_list == []

    def test_cancel_structured_by_admin_releases_lock(self, api):
        """PRD §3.5: "When the order had been structured with financing, the locked
        prequalification is released from LOCKED back to PREQUALIFIED per §3.4."

        Design: Difficulty/transitive_cascade/order_cancellation_cascade_depth3
        """
        cust, cust_headers = create_customer(state_code="GA")
        pq = create_prequalification(cust["id"], annual_income_cents=8000000, credit_band="A")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order = create_structured_order(
            cust["id"], vehicle["id"], financing_id=pq["id"], down_payment_cents=300000
        )
        resp = api.cancel_order(order["id"], TEST_USERS["platform_admin_headers"])
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "CANCELLED"
        pq_after = get_success_data(api.get_prequal(pq["id"], cust_headers))
        assert pq_after["status"] == "PREQUALIFIED"
        assert pq_after["locked_order_id"] is None

    def test_cancel_appointment_set_releases_lock_and_cancels_appointment(self, api):
        """PRD §3.5: "When the order was APPOINTMENT_SET, the linked SCHEDULED appointment
        transitions to CANCELLED. ... When the order had been structured with financing,
        the locked prequalification is released from LOCKED back to PREQUALIFIED per §3.4.
        When the order was STRUCTURED or APPOINTMENT_SET, the linked TitleRegistration
        still in PENDING is deleted outright."

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_inventory_and_locks
        """
        cust, cust_headers = create_customer(state_code="GA")
        pq = create_prequalification(cust["id"], annual_income_cents=8000000, credit_band="A")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, appt = create_appointment_set_order(
            cust["id"],
            vehicle["id"],
            financing_id=pq["id"],
            down_payment_cents=300000,
            appointment_overrides={
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
        )
        resp = api.cancel_order(order["id"], TEST_USERS["platform_admin_headers"])
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "CANCELLED"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "LISTED"
        pq_after = get_success_data(api.get_prequal(pq["id"], cust_headers))
        assert pq_after["status"] == "PREQUALIFIED"
        assert pq_after["locked_order_id"] is None
        appt_after = get_success_data(api.get_appointment(appt["id"], TEST_USERS["platform_admin_headers"]))
        assert appt_after["status"] == "CANCELLED"
        title_list = get_success_data(
            api.get_order_title_registration(order["id"], TEST_USERS["registration_clerk_headers"])
        )
        assert title_list == []

    def test_cancel_appointment_set_by_customer_releases_lock(self, api):
        """PRD §3.5: "Cancellation of the whole order is available to the customer or a
        PlatformAdmin while the order is in RESERVED, STRUCTURED, or APPOINTMENT_SET ...
        When the order had been structured with financing, the locked prequalification is
        released from LOCKED back to PREQUALIFIED per §3.4. When the order was
        APPOINTMENT_SET, the linked SCHEDULED appointment transitions to CANCELLED."

        Design: Difficulty/compensating_invariant/order_cancellation_conserves_inventory_and_locks
        """
        cust, cust_headers = create_customer(state_code="GA")
        pq = create_prequalification(cust["id"], annual_income_cents=8000000, credit_band="A")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, appt = create_appointment_set_order(
            cust["id"],
            vehicle["id"],
            financing_id=pq["id"],
            down_payment_cents=300000,
            appointment_overrides={
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
        )
        resp = api.cancel_order(order["id"], cust_headers)
        order_after = validate_success(resp, 200)
        assert order_after["status"] == "CANCELLED"
        pq_after = get_success_data(api.get_prequal(pq["id"], cust_headers))
        assert pq_after["status"] == "PREQUALIFIED"
        assert pq_after["locked_order_id"] is None
        appt_after = get_success_data(api.get_appointment(appt["id"], TEST_USERS["platform_admin_headers"]))
        assert appt_after["status"] == "CANCELLED"
