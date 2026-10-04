"""Tests for envelope, defaults, initial states, listed price, trade-in, RBAC, ownership, clock."""
from test_helpers import (
    api_client,
    TEST_USERS,
    make_customer_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_same_instant,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_customer_payload,
    create_vehicle_payload,
    create_trade_in_payload,
    create_customer,
    create_listed_vehicle,
    create_structured_order,
    create_completed_order,
)


class TestResponseEnvelope:
    """Success and error envelope shapes (PRD §2.2)."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this
        standard envelope format ... The response_type is either 'object' for a single
        resource or 'array' for a list of resources. ... The data field contains the
        resource object or an array of resource objects."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        cust, _ = create_customer(state_code="GA")
        resp = api.get_customer(cust["id"], TEST_USERS["platform_admin_headers"])
        data = validate_success(resp, 200)
        assert data["id"] == cust["id"]
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format ... The meta object for error responses contains only
        api_request_id and api_request_timestamp. ... The error_id is a unique,
        machine-readable string that identifies the specific error. ... The message
        provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        resp = api.get_customer(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err["message"], str) and err["message"]

    def test_list_envelope_pagination_fields(self, api):
        """PRD §2.2: "Pagination-related fields in meta (limit, offset, total_count,
        has_more) are included for list endpoints."

        Design: Corner/endpoints/response_envelope_success_and_error_shape
        """
        create_customer(state_code="GA")
        resp = api.list_customers(TEST_USERS["platform_admin_headers"])
        data, meta = validate_paginated(resp)
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)


class TestCustomerDefaults:
    """Customer registration defaults (PRD §3.5)."""

    def test_default_fulfillment_choice_home_delivery(self, api):
        """PRD §3.5: "Customers are registered by a PlatformAdmin with a full_name, a
        contact email (unique across all customers), a state_code naming the two-letter US
        state of the registration address, and an optional default_fulfillment_choice of
        HOME_DELIVERY or VENDING_MACHINE which defaults to HOME_DELIVERY when omitted."

        Design: Corner/endpoints/customer_registration_default_fulfillment_choice
        """
        resp = api.create_customer(
            {"full_name": "Dflt U", "email": "dflt@example.com", "state_code": "TX"},
            TEST_USERS["platform_admin_headers"],
        )
        cust = validate_success(resp, 201)
        assert cust["default_fulfillment_choice"] == "HOME_DELIVERY"
        assert cust["version"] == 1
        assert cust["state_code"] == "TX"
        assert cust["created_at"] == "2026-09-01T00:00:00.000Z"


class TestUnsupportedState:
    """State membership validation (PRD §2.7)."""

    def test_customer_with_unsupported_state_rejected(self, api):
        """PRD §2.7: "A customer registration, an order creation, or an order structuring
        that presents a state_code outside this five-state table is rejected with
        ERR_UNSUPPORTED_STATE (HTTP 422)."

        Design: Corner/endpoints/customer_unsupported_state_rejected
        """
        resp = api.create_customer(
            {"full_name": "Bad St", "email": "badst@example.com", "state_code": "ZZ"},
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNSUPPORTED_STATE, 422)


class TestTradeInCalculations:
    """Trade-in initial offer and adjustment (PRD §3.3)."""

    def test_initial_offer_mid_clean(self, api):
        """PRD §3.3: "The computation starts from a band base of 1200000 cents for ECONOMY,
        2000000 for MID, or 3200000 for PREMIUM. ... For mileage, the amount by which the
        declared odometer exceeds 60000 miles — never below zero — is divided by 1000
        using integer floor division, and each whole thousand-mile step subtracts a
        further 1200 cents. Finally, the offer is floored at 50000 cents."

        Design: Corner/endpoints/trade_in_initial_offer_computed_from_questionnaire
        """
        cust, cust_headers = create_customer(state_code="GA")
        resp = api.create_trade_in(
            {
                "vin": "1HGCV1F30LA000001",
                "questionnaire": {
                    "vehicle_band": "MID",
                    "accident_history": False,
                    "mechanical_issues": False,
                    "tire_condition": "GOOD",
                    "odometer": 45000,
                    "smoker_vehicle": False,
                },
            },
            cust_headers,
        )
        offer = validate_success(resp, 201)
        assert offer["initial_offer_cents"] == 2000000
        assert offer["status"] == "OFFERED"
        assert offer["created_at"] == "2026-09-01T00:00:00.000Z"
        assert_same_instant(offer["expires_at"], "2026-09-08T00:00:00Z")

    def test_adjustment_severe_band_haircut(self, api):
        """PRD §3.3: "When there are three or more mismatches, the severe band applies
        instead: the adjusted offer is seventy percent of the initial offer computed with
        integer floor, again floored at 50000 cents."

        Design: Corner/endpoints/trade_in_adjustment_severe_haircut_band
        """
        cust, cust_headers = create_customer(state_code="GA")
        offer_resp = api.create_trade_in(
            {
                "vin": "1HGCV1F30LA000002",
                "questionnaire": {
                    "vehicle_band": "ECONOMY",
                    "accident_history": False,
                    "mechanical_issues": False,
                    "tire_condition": "GOOD",
                    "odometer": 30000,
                    "smoker_vehicle": False,
                },
            },
            cust_headers,
        )
        offer = get_success_data(offer_resp)
        resp = api.inspect_trade_in(
            offer["id"],
            {
                "accident_history_found": True,
                "mechanical_issues_found": True,
                "smoker_detected": True,
                "tire_condition_observed": "GOOD",
            },
            TEST_USERS["customer_advocate_headers"],
        )
        offer_after = validate_success(resp, 200)
        assert offer_after["status"] == "INSPECTED"
        assert offer_after["adjusted_offer_cents"] == 840000


class TestListedPriceLifecycle:
    """Listed price recomputation on annotation lifecycle (PRD §3.2)."""

    def test_listed_price_recomputed_on_annotation_and_retraction(self, api):
        """PRD §3.2: "The vehicle's listed_price_cents is a computed field: it equals
        base_price_cents minus the sum of deduction_cents over the vehicle's ACTIVE
        annotations, floored at 100000 cents ... The vehicle's annotation_count is the
        count of those ACTIVE annotations and starts at 0. The listed price is computed
        when the vehicle transitions from IN_RECON to LISTED, and it is recomputed whenever
        an annotation is created, updated, or retracted on a vehicle that is currently
        LISTED; each such recomputation stores the new listed_price_cents and
        annotation_count and increments the vehicle's version by one. RETRACTED annotations
        contribute nothing to either figure."

        Design: Corner/entities/listed_price_recomputed_on_annotation_lifecycle
        """
        center = get_success_data(api.create_center(
            {"name": "C", "market_code": "ATL-A", "daily_capacity": 5, "slot_count": 10},
            TEST_USERS["platform_admin_headers"],
        ))
        vehicle_resp = api.create_vehicle(
            {
                "vin": "1N4BL4EV4KC100501",
                "make": "Nissan",
                "model": "Altima",
                "year": 2019,
                "mileage": 55000,
                "base_price_cents": 200000,
                "market_code": "ATL-A",
                "center_id": center["id"],
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        recon_headers = TEST_USERS["recon_operator_headers"]
        intakes = get_success_data(api.get_vehicle_recon_intakes(vehicle["id"], recon_headers))
        intake = intakes[0]
        get_success_data(api.arrive_recon_intake(intake["id"], recon_headers))
        get_success_data(api.start_work_recon_intake(intake["id"], recon_headers))
        ann1_resp = api.create_annotation(
            vehicle["id"],
            {"area": "bumper", "severity": "MODERATE", "deduction_cents": 60000, "image_count": 4},
            TEST_USERS["recon_operator_headers"],
        )
        ann1 = get_success_data(ann1_resp)
        get_success_data(api.complete_recon_intake(intake["id"], recon_headers))
        list_resp = api.list_vehicle(vehicle["id"], TEST_USERS["recon_operator_headers"])
        assert get_success_data(list_resp)["status"] == "LISTED"
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["listed_price_cents"] == 140000
        assert vehicle_after["annotation_count"] == 1
        api.create_annotation(
            vehicle["id"],
            {"area": "roof", "severity": "MAJOR", "deduction_cents": 90000, "image_count": 6},
            TEST_USERS["platform_admin_headers"],
        )
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["listed_price_cents"] == 100000
        assert vehicle_after["annotation_count"] == 2
        api.retract_annotation(ann1["id"], TEST_USERS["platform_admin_headers"])
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["listed_price_cents"] == 110000
        assert vehicle_after["annotation_count"] == 1


class TestInitialStates:
    """Fresh entities land in declared initial states (PRD §3.1, §3.3, §3.5)."""

    def test_vehicle_order_trade_in_initial_states(self, api):
        """PRD §3.1: "The vehicle is created in INTAKE." PRD §3.5: "The order is created in
        DRAFT ... with payment_status UNPAID and delivery_status NOT_SCHEDULED." PRD §3.3:
        "The resulting TradeInOffer is created in OFFERED with an expires_at set exactly
        seven days after creation."

        Design: Corner/state_machines/initial_states_on_creation
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle_resp = api.create_vehicle(
            {
                "vin": "3GNKBERS4JS500603",
                "make": "Chevrolet",
                "model": "Equinox",
                "year": 2020,
                "mileage": 38000,
                "base_price_cents": 2000000,
                "market_code": "ATL-A",
            },
            TEST_USERS["platform_admin_headers"],
        )
        vehicle = get_success_data(vehicle_resp)
        assert vehicle["status"] == "INTAKE"
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        assert order["status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"
        assert order["delivery_status"] == "NOT_SCHEDULED"
        ti_resp = api.create_trade_in(
            {
                "vin": "1HGCV1F30LA000099",
                "questionnaire": {
                    "vehicle_band": "ECONOMY",
                    "accident_history": True,
                    "mechanical_issues": False,
                    "tire_condition": "FAIR",
                    "odometer": 72000,
                    "smoker_vehicle": False,
                },
            },
            cust_headers,
        )
        ti = get_success_data(ti_resp)
        assert ti["status"] == "OFFERED"
        assert ti["initial_offer_cents"] == 1005600


class TestNoShowTiming:
    """NO_SHOW only after end_at (PRD §3.5)."""

    def test_no_show_before_end_rejected(self, api):
        """PRD §3.5: "A CustomerAdvocate may mark a SCHEDULED appointment as NO_SHOW once
        the logical clock has passed its end_at."

        Design: Corner/state_machines/appointment_no_show_before_end_rejected
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order = create_structured_order(cust["id"], vehicle["id"])
        appt_resp = api.book_appointment(
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
        appt = get_success_data(appt_resp)
        resp = api.no_show_appointment(appt["id"], TEST_USERS["customer_advocate_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        appt_after = get_success_data(api.get_appointment(appt["id"], TEST_USERS["platform_admin_headers"]))
        assert appt_after["status"] == "SCHEDULED"
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["status"] == "APPOINTMENT_SET"


class TestTerminalStateLockdown:
    """COMPLETED orders cannot be cancelled (PRD §3.5)."""

    def test_cancel_completed_order_rejected(self, api):
        """PRD §3.5: "Cancellation of the whole order is available to the customer or a
        PlatformAdmin while the order is in RESERVED, STRUCTURED, or APPOINTMENT_SET, and
        it fires a full compensation chain."

        Design: Corner/state_machines/terminal_state_lockdown_completed_order_cannot_cancel
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order, _ = create_completed_order(cust["id"], vehicle["id"], odometer_at_delivery=38100)
        resp = api.cancel_order(order["id"], TEST_USERS["platform_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        order_after = get_success_data(api.get_order(order["id"], TEST_USERS["platform_admin_headers"]))
        assert order_after["status"] == "COMPLETED"
        assert order_after["payment_status"] == "PAID"


class TestOwnership:
    """Ownership checks (PRD §2.1)."""

    def test_foreign_customer_structure_rejected(self, api):
        """PRD §2.1: "ownership checks on any resource that references a customer (a
        purchase order, a trade-in offer, a financing prequalification, a defect claim
        reached through its order) compare the resource's customer_id field to X-User-ID,
        and a mismatch on an endpoint that requires ownership is rejected with
        ERR_FORBIDDEN_OWNERSHIP (HTTP 403)."

        Design: Corner/errors/ownership_forbidden_on_foreign_resource
        """
        cust_a, cust_a_headers = create_customer(state_code="GA")
        cust_b, cust_b_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_a_headers,
        )
        order = get_success_data(order_resp)
        api.reserve_order(order["id"], {"expected_vehicle_version": vehicle["version"]}, cust_a_headers)
        resp = api.structure_order(order["id"], {}, cust_b_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        order_after = get_success_data(api.get_order(order["id"], cust_a_headers))
        assert order_after["status"] == "RESERVED"


class TestUnauthenticated:
    """Missing or unknown role header (PRD §2.1)."""

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or whose role value is not one of
        these six, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/errors/unauthenticated_missing_role_header
        """
        resp = api.list_vehicles({"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or whose role value is not one of
        these six, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/errors/unauthenticated_missing_role_header
        """
        resp = api.list_vehicles({"X-User-ID": "someone", "X-User-Role": "UnknownRole"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRBAC:
    """Role-exclusive endpoint denials (PRD §2.1, §4)."""

    def test_warranty_admin_cannot_create_order(self, api):
        """PRD §4: "POST /vehicle-hub/orders | Create a purchase order in DRAFT | Customer"

        Design: Corner/rbac/role_exclusive_denials
        """
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            TEST_USERS["warranty_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_customer_cannot_set_clock(self, api):
        """PRD §4: "POST /vehicle-hub/_clock/set_current_utc | Advance the logical server
        clock | PlatformAdmin"

        Design: Corner/rbac/role_exclusive_denials
        """
        cust, cust_headers = create_customer(state_code="GA")
        resp = api.set_clock("2026-09-02T00:00:00Z", cust_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_customer_cannot_list_vehicle_transition(self, api):
        """PRD §4: "POST /vehicle-hub/vehicles/{id}/list | Move vehicle from IN_RECON to
        LISTED | ReconOperator"

        Design: Corner/rbac/role_exclusive_denials
        """
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        cust, cust_headers = create_customer(state_code="GA")
        resp = api.list_vehicle(vehicle["id"], cust_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestClockDefault:
    """Logical clock startup default (PRD §2.5)."""

    def test_created_at_matches_default_clock(self, api):
        """PRD §2.5: "On startup the clock reads exactly 2026-09-01T00:00:00Z, and until it
        is explicitly advanced it continues to read that instant — it never falls back to
        wall-clock time."

        Design: Corner/endpoints/clock_default_startup_value
        """
        resp = api.create_customer(
            {"full_name": "Clk U", "email": "clk@example.com", "state_code": "GA"},
            TEST_USERS["platform_admin_headers"],
        )
        cust = validate_success(resp, 201)
        assert cust["created_at"] == "2026-09-01T00:00:00.000Z"


class TestTradeInDeclineCompensation:
    """Declining a trade-in clears order reference and recomputes total (PRD §3.3)."""

    def test_decline_clears_reference_and_recomputes(self, api):
        """PRD §3.3: "Declining moves it from INSPECTED to DECLINED and, on every such
        referencing order, clears the trade_in_offer_id and recomputes total_due_cents
        without trade credit."

        Design: Corner/cross_cutting_layers/trade_in_decline_clears_order_reference_and_recomputes
        """
        cust, cust_headers = create_customer(state_code="GA")
        ti_resp = api.create_trade_in(
            {
                "vin": "1HGCV1F30LA000010",
                "questionnaire": {
                    "vehicle_band": "MID",
                    "accident_history": False,
                    "mechanical_issues": False,
                    "tire_condition": "GOOD",
                    "odometer": 45000,
                    "smoker_vehicle": False,
                },
            },
            cust_headers,
        )
        ti = get_success_data(ti_resp)
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY", "trade_in_offer_id": ti["id"]},
            cust_headers,
        )
        order = get_success_data(order_resp)
        api.reserve_order(order["id"], {"expected_vehicle_version": vehicle["version"]}, cust_headers)
        api.inspect_trade_in(
            ti["id"],
            {
                "accident_history_found": True,
                "mechanical_issues_found": False,
                "smoker_detected": False,
                "tire_condition_observed": "GOOD",
            },
            TEST_USERS["customer_advocate_headers"],
        )
        resp = api.decline_trade_in(ti["id"], cust_headers)
        ti_after = validate_success(resp, 200)
        assert ti_after["status"] == "DECLINED"
        assert ti_after["adjusted_offer_cents"] == 1960000
        order_after = get_success_data(api.get_order(order["id"], cust_headers))
        assert order_after["trade_in_offer_id"] is None
        assert order_after["total_due_cents"] == 2140000
        assert order_after["status"] == "RESERVED"


class TestImmediateConsistency:
    """Atomic mutations visible on immediate re-read (PRD §2.4, §3.5)."""

    def test_reserve_response_and_reread_match(self, api):
        """PRD §2.4: "version is an integer starting at the value assigned at creation and
        incremented by exactly one on every mutation of the entity." PRD §3.5: "Reserving
        the vehicle moves the order from DRAFT to RESERVED and the vehicle from LISTED to
        RESERVED in one step. ... Both the order's and the vehicle's version increment."

        Design: Corner/consistency_model/immediate_consistency_after_mutations
        """
        cust, cust_headers = create_customer(state_code="GA")
        vehicle = create_listed_vehicle(base_price_cents=2000000, market_code="ATL-A")
        order_resp = api.create_order(
            {"vehicle_id": vehicle["id"], "fulfillment_choice": "HOME_DELIVERY"},
            cust_headers,
        )
        order = get_success_data(order_resp)
        reserve_resp = api.reserve_order(
            order["id"],
            {"expected_vehicle_version": vehicle["version"]},
            cust_headers,
        )
        order_after = validate_success(reserve_resp, 200)
        assert order_after["status"] == "RESERVED"
        assert order_after["version"] == 2
        reread = get_success_data(api.get_order(order["id"], cust_headers))
        assert reread["status"] == "RESERVED"
        assert reread["version"] == 2
        vehicle_after = get_success_data(api.get_vehicle(vehicle["id"], TEST_USERS["platform_admin_headers"]))
        assert vehicle_after["status"] == "RESERVED"
        assert vehicle_after["version"] == 4
