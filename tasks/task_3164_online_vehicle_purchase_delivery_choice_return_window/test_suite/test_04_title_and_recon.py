"""Tests for title registration timelines (PRD §3.6) and recon intake workflows (PRD §3.1)."""
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
)


class TestRegistrationTimelineDualVariant:
    """IN_STATE vs OUT_OF_STATE timelines (PRD §3.6)."""

    def test_in_state_ga_gets_30_day_tag_10_day_commitment(self, api):
        """PRD §3.6: "when the order's state_code is GA — the platform's home state — the
        registration's processing_mode is IN_STATE; for any other supported state it is
        OUT_OF_STATE. ... Filing records filed_at and computes registration_due_at as ten
        days after filed_at for the IN_STATE variant or twenty-one days after for
        OUT_OF_STATE ... temp_tag_expires_at is set thirty days out when the order is
        processed in-state or forty-five days out when out-of-state."

        Design: Difficulty/dual_variant_calc/registration_in_state_vs_out_of_state_timeline
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=30100)
        title_list = get_success_data(
            api.get_order_title_registration(order["id"], TEST_USERS["registration_clerk_headers"])
        )
        tr = title_list[0]
        resp = api.file_title_registration(tr["id"], TEST_USERS["registration_clerk_headers"])
        tr_after = validate_success(resp, 200)
        assert tr_after["processing_mode"] == "IN_STATE"
        assert_same_instant(tr_after["temp_tag_expires_at"], "2026-10-01T00:00:00Z")
        assert_same_instant(tr_after["registration_due_at"], "2026-09-11T00:00:00Z")

    def test_out_of_state_tx_gets_45_day_tag_21_day_commitment(self, api):
        """PRD §3.6: "when the order's state_code is GA — the platform's home state — the
        registration's processing_mode is IN_STATE; for any other supported state it is
        OUT_OF_STATE. ... Filing records filed_at and computes registration_due_at as ten
        days after filed_at for the IN_STATE variant or twenty-one days after for
        OUT_OF_STATE ... temp_tag_expires_at is set thirty days out when the order is
        processed in-state or forty-five days out when out-of-state."

        Design: Difficulty/dual_variant_calc/registration_in_state_vs_out_of_state_timeline
        """
        cust, cust_headers = create_customer(state_code="TX")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=31100)
        title_list = get_success_data(
            api.get_order_title_registration(order["id"], TEST_USERS["registration_clerk_headers"])
        )
        tr = title_list[0]
        resp = api.file_title_registration(tr["id"], TEST_USERS["registration_clerk_headers"])
        tr_after = validate_success(resp, 200)
        assert tr_after["processing_mode"] == "OUT_OF_STATE"
        assert_same_instant(tr_after["temp_tag_expires_at"], "2026-10-16T00:00:00Z")
        assert_same_instant(tr_after["registration_due_at"], "2026-09-22T00:00:00Z")


class TestReconIntakeListingGate:
    """Listing blocked by open intake; released when intake completes (PRD §3.1, §3.2)."""

    def test_list_blocked_by_open_intake(self, api):
        """PRD §3.2: "Listing itself is performed by a ReconOperator, requires every linked
        ReconIntake for the vehicle to be in COMPLETE or CANCELLED (any intake still in
        flight rejects the listing with ERR_DEPENDENCY_NOT_READY), clears the vehicle's
        center_id to null as the vehicle leaves the center, and increments the vehicle's
        version."

        Design: Corner/state_machines/vehicle_list_blocked_by_open_intake
        """
        center_resp = api_client.create_center(
            {"name": "RC List Block", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        center = get_success_data(center_resp)
        vehicle_resp = api_client.create_vehicle(
            {
                "vin": "3GNKBERS4JS500604",
                "make": "Chevrolet",
                "model": "Equinox",
                "year": 2020,
                "mileage": 38000,
                "base_price_cents": 2000000,
                "market_code": "ATL-A",
                "center_id": center["id"],
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        intakes = get_success_data(
            api_client.get_vehicle_recon_intakes(vehicle["id"], TEST_USERS["recon_operator_headers"])
        )
        intake = intakes[0]
        api_client.arrive_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        api_client.start_work_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        resp = api_client.list_vehicle(vehicle["id"], TEST_USERS["recon_operator_headers"])
        validate_error(resp, ApiErrorId.ERR_DEPENDENCY_NOT_READY, 409)
        vehicle_after = get_success_data(api_client.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "IN_RECON"

    def test_list_succeeds_after_intake_complete(self, api):
        """PRD §3.1: "Completing an intake moves it from IN_WORK to COMPLETE and requires
        the vehicle to currently be in IN_RECON." PRD §3.2: "requires every linked
        ReconIntake for the vehicle to be in COMPLETE or CANCELLED ... clears the vehicle's
        center_id to null as the vehicle leaves the center."

        Design: Corner/cross_cutting_layers/cascading_side_effects_listing_blocked_by_intake
        """
        center_resp = api_client.create_center(
            {"name": "RC Casc", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        center = get_success_data(center_resp)
        vehicle_resp = api_client.create_vehicle(
            {
                "vin": "1G1ZD5ST0LF000805",
                "make": "Chevrolet",
                "model": "Malibu",
                "year": 2020,
                "mileage": 43000,
                "base_price_cents": 2000000,
                "market_code": "ATL-A",
                "center_id": center["id"],
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        intakes = get_success_data(
            api_client.get_vehicle_recon_intakes(vehicle["id"], TEST_USERS["recon_operator_headers"])
        )
        intake = intakes[0]
        api_client.arrive_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        api_client.start_work_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        api_client.complete_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        intake_after = get_success_data(
            api_client.get_recon_intake(intake["id"], TEST_USERS["recon_operator_headers"])
        )
        assert intake_after["status"] == "COMPLETE"
        resp = api_client.list_vehicle(vehicle["id"], TEST_USERS["recon_operator_headers"])
        vehicle_after = validate_success(resp, 200)
        assert vehicle_after["status"] == "LISTED"
        assert vehicle_after["listed_price_cents"] == 2000000
        assert vehicle_after["center_id"] is None


class TestReconCapacity:
    """Daily capacity and slot count (PRD §3.1)."""

    def test_daily_capacity_exhausted_then_resets_next_day(self, api):
        """PRD §3.1: "Starting work on a received intake moves it from RECEIVED to IN_WORK
        and the vehicle from INTAKE (or RETURN_INBOUND) to IN_RECON. This transition is
        permitted only when the count of vehicles in IN_WORK at the center for the current
        UTC calendar day is below the center's daily_capacity; otherwise the request is
        rejected with ERR_RECON_CAPACITY_FULL. The same daily-capacity and slot-count
        checks guard the direct INTAKE to IN_RECON transition a ReconOperator performs on
        a vehicle outside the intake workflow — at transition time the vehicle's center_id
        must reference an existing center, the day's IN_WORK count must be below
        daily_capacity, and the co-resident INTAKE-plus-IN_RECON count must be below
        slot_count."

        Design: Corner/validations/recon_daily_capacity_and_slot_count
        """
        center_resp = api_client.create_center(
            {"name": "RC Cap", "market_code": "ATL-A", "daily_capacity": 1, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        )
        center = get_success_data(center_resp)
        for vin in ("1G1ZD5ST0LF000801", "1G1ZD5ST0LF000802"):
            api_client.create_vehicle(
                {
                    "vin": vin,
                    "make": "Chevrolet",
                    "model": "Malibu",
                    "year": 2020,
                    "mileage": 41000,
                    "base_price_cents": 2000000,
                    "market_code": "ATL-A",
                    "center_id": center["id"],
                },
                TEST_USERS["platform_admin_headers"],
            )
        vehicles = get_success_data(
            api_client.list_vehicles(TEST_USERS["platform_admin_headers"], params={"center_id": center["id"]})
        )
        v1, v2 = vehicles[0], vehicles[1]
        api_client.start_recon(v1["id"], TEST_USERS["recon_operator_headers"])
        resp = api_client.start_recon(v2["id"], TEST_USERS["recon_operator_headers"])
        validate_error(resp, ApiErrorId.ERR_RECON_CAPACITY_FULL, 409)
        api_client.set_clock("2026-09-02T00:00:00Z", TEST_USERS["platform_admin_headers"])
        resp = api_client.start_recon(v2["id"], TEST_USERS["recon_operator_headers"])
        v2_after = validate_success(resp, 200)
        assert v2_after["status"] == "IN_RECON"
        v1_after = get_success_data(api_client.get_vehicle(v1["id"], TEST_USERS["platform_admin_headers"]))
        assert v1_after["status"] == "IN_RECON"
