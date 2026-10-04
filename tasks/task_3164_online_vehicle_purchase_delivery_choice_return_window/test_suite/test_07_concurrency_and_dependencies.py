"""Tests for optimistic concurrency control (PRD §2.8) and cross-entity state dependencies."""
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
)


class TestStaleVehicleVersionOnReserve:
    """OCC on reserve (PRD §2.8)."""

    def test_stale_version_after_annotation_rejected(self, api):
        """PRD §2.8: "Reserving a purchase order against a vehicle requires the request to
        carry expected_vehicle_version, holding the version of the Vehicle the client last
        observed. If the vehicle's current version has advanced since that observation —
        because another writer has listed it, annotated it, retracted an annotation,
        reserved it, or otherwise mutated it — the reservation is rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/endpoints/occ_stale_vehicle_version_on_reserve
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        # Client observed version 2 (after list). Add an annotation to bump to 3.
        api.create_annotation(
            vehicle["id"],
            {"area": "door", "severity": "MINOR", "deduction_cents": 30000, "image_count": 2},
            TEST_USERS["recon_operator_headers"],
        )
        resp = api.reserve_order(
            order["id"],
            {"expected_vehicle_version": vehicle["version"]},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["status"] == "DRAFT"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "LISTED"
        assert vehicle_after["version"] == 4

    def test_stale_version_after_retraction_rejected(self, api):
        """PRD §2.8: "If the vehicle's current version has advanced since that observation —
        because another writer has listed it, annotated it, retracted an annotation,
        reserved it, or otherwise mutated it — the reservation is rejected with
        ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/endpoints/occ_stale_vehicle_version_on_reserve
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        ann_resp = api.create_annotation(
            vehicle["id"],
            {"area": "door", "severity": "MINOR", "deduction_cents": 30000, "image_count": 2},
            TEST_USERS["recon_operator_headers"],
        )
        ann = get_success_data(ann_resp)
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        # Client observed version 3 (after annotation). Retract to bump to 4.
        api.retract_annotation(ann["id"], TEST_USERS["platform_admin_headers"])
        vehicle_mid = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        resp = api.reserve_order(
            order["id"],
            {"expected_vehicle_version": vehicle_mid["version"] - 1},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["status"] == "DRAFT"


class TestStaleOrderVersionOnAppointment:
    """OCC on appointment booking (PRD §2.8)."""

    def test_stale_order_version_after_fulfillment_switch_rejected(self, api):
        """PRD §2.8: "Booking a delivery appointment against a purchase order requires the
        request to carry expected_order_version, holding the version of the PurchaseOrder
        the client last observed. If the order's current version has advanced since that
        observation — because another writer has restructured it, changed its fulfillment
        choice, or otherwise mutated it — the booking is rejected with ERR_STALE_VERSION
        (HTTP 412)."

        Design: Corner/endpoints/occ_stale_order_version_on_appointment_booking
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        # Client observes the order's version at RESERVED; restructuring then advances it.
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        vehicle_now = get_success_data(api.get_vehicle(vehicle["id"], cust_headers))
        reserved = get_success_data(api.reserve_order(
            order["id"], {"expected_vehicle_version": vehicle_now["version"]}, cust_headers
        ))
        observed_version = reserved["version"]
        structured = get_success_data(api.structure_order(order["id"], {}, cust_headers))
        assert structured["version"] > observed_version
        resp = api.book_appointment(
            order["id"],
            {
                "expected_order_version": observed_version,
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        appts = get_success_data(api.list_appointments(TEST_USERS["platform_admin_headers"], params={"order_id": order["id"]}))
        assert appts == []
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["delivery_status"] == "NOT_SCHEDULED"

    def test_fresh_order_version_succeeds(self, api):
        """PRD §2.8: "Booking a delivery appointment against a purchase order requires the
        request to carry expected_order_version ... If the order's current version has
        advanced since that observation ... the booking is rejected with ERR_STALE_VERSION."

        Design: Corner/endpoints/occ_stale_order_version_on_appointment_booking
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order = create_structured_order(cust["id"], vehicle["id"])
        resp = api.book_appointment(
            order["id"],
            {
                "expected_order_version": order["version"],
                "market_code": "ATL-A",
                "address_region": "ATL-CORE",
                "start_at": "2026-09-02T10:00:00Z",
                "end_at": "2026-09-02T11:00:00Z",
            },
            cust_headers,
        )
        appt = validate_success(resp, 201)
        assert appt["status"] == "SCHEDULED"


class TestReserveRequiresVehicleListed:
    """Reserve requires vehicle LISTED (PRD §3.5)."""

    def test_reserve_in_recon_vehicle_rejected(self, api):
        """PRD §3.5: "Reserving the vehicle moves the order from DRAFT to RESERVED and the
        vehicle from LISTED to RESERVED in one step. Reservation requires the vehicle to
        currently be LISTED ..."

        Design: Difficulty/cross_entity_state_dependency/reserve_requires_vehicle_listed
        """
        cust, cust_headers = create_customer(state_code="GA")
        center = get_success_data(api.create_center(
            {"name": "C", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        ))
        vehicle_resp = api.create_vehicle(
            {
                "vin": "KNDC34LA6M5008801",
                "make": "Kia",
                "model": "Seltos",
                "year": 2023,
                "mileage": 9000,
                "base_price_cents": 2000000,
                "market_code": "ATL-A",
                "center_id": center["id"],
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        recon_resp = api.start_recon(vehicle["id"], TEST_USERS["recon_operator_headers"])
        vehicle = get_success_data(recon_resp)
        assert vehicle["status"] == "IN_RECON"
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        resp = api.reserve_order(
            order["id"],
            {"expected_vehicle_version": vehicle["version"]},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["status"] == "DRAFT"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "IN_RECON"

    def test_reserve_intake_vehicle_rejected(self, api):
        """PRD §3.5: "Reservation requires the vehicle to currently be LISTED ..."

        Design: Difficulty/cross_entity_state_dependency/reserve_requires_vehicle_listed
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle_resp = api.create_vehicle(
            {
                "vin": "KNDC34LA6M5008802",
                "make": "Kia",
                "model": "Seltos",
                "year": 2023,
                "mileage": 9000,
                "base_price_cents": 2000000,
                "market_code": "ATL-A",
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        resp = api.reserve_order(
            order["id"],
            {"expected_vehicle_version": vehicle["version"]},
            cust_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["status"] == "DRAFT"
