"""Standing up the network: mills, quota contracts, fleets, roads and the clock.

Covers registration defaults, the derived-status guard on a quota contract, the
list envelope, the logical clock's startup instant, and the 404 that every
unresolved path or body foreign key must raise.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_instant_equals,
    assert_mill,
    assert_mill_contract,
    build_network,
    create_haul_contractor_payload,
    create_tract,
    create_mill_payload,
    create_truck_payload,
    deliver_load,
    dispatch_load,
    file_all_coverages,
    list_trucks,
    make_scaler_headers,
    read_load,
    read_mill,
    read_mill_contract,
    read_tract,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReferenceRegistration:
    def test_mill_registers_with_receiving_status_defaulting_to_open(
        self, api, admin_headers
    ):
        """PRD §3.1: "A mill also carries a `receiving_status` of either `OPEN` or
        `CLOSED`, defaulting to `OPEN` when the registration omits it; the yard may
        be opened or closed later by either a `PlatformAdmin` or the mill's own
        `MillScaler`, and closing the yard blocks new dispatch against every quota
        contract that mill owns."
        PRD §3.1: "Registering a receiving mill captures its trade `name` (1 to 120
        characters, required) and the `state_code` it sits in, which must be exactly
        two upper-case letters."

        Design: Corner/entities/mill_receiving_status_defaults_to_open_when_omitted
        """
        payload = {"name": "Cascade Mill A", "state_code": "OR"}
        response = api.create_mill(payload, admin_headers)
        mill = validate_success(response, 201)

        assert_mill(mill)
        assert mill["receiving_status"] == "OPEN", (
            "an omitted receiving_status defaults to OPEN"
        )
        assert mill["state_code"] == "OR"

    def test_mill_contract_overrun_tolerance_defaults_to_five_percent(
        self, api, admin_headers
    ):
        """PRD §3.1: "An `overrun_tolerance_pct` between 0 and 0.25 inclusive,
        defaulting to 0.05 when omitted, expresses how far certified deliveries may
        run past the committed quota before the scale house must stop certifying."
        PRD §3.1: "All three initialise to a state where nothing is reserved, nothing
        is delivered, and the whole quota is available."

        Design: Corner/entities/mill_contract_overrun_tolerance_defaults_to_five_percent
        """
        mill = validate_success(
            api.create_mill(create_mill_payload(), admin_headers), 201
        )
        payload = {
            "mill_id": mill["id"],
            "species": "WESTERN_HEMLOCK",
            "grade": "PULP",
            "quota_tons": 250,
            "base_rate_cents_per_ton": 2600,
            "period_start": "2026-07-01",
            "period_end": "2026-09-30",
        }
        contract = validate_success(
            api.create_mill_contract(payload, admin_headers), 201
        )

        assert_mill_contract(contract)
        assert contract["overrun_tolerance_pct"] == pytest.approx(0.05)
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["delivered_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(250.00, abs=0.005)
        assert contract["status"] == "OPEN"

    def test_truck_with_an_axle_config_outside_the_enumeration_is_rejected(
        self, api, admin_headers
    ):
        """PRD §3.1: "A truck carries a `unit_number` of 1 to 32 characters, unique
        within its owning carrier; an `axle_config` of `FIVE_AXLE`, `SIX_AXLE` or
        `SEVEN_AXLE`; a `tare_weight_lbs` between 10,000 and 60,000 pounds inclusive,
        being the empty weight of tractor plus trailer; and a `permit_class`."
        PRD §2.7: "**Request schema.** On every write endpoint: every required input
        field present, every enum-typed value a legal member of its enumeration, every
        number inside its declared range, `window_end` strictly after `window_start`,
        `scheduled_arrive_at` strictly after `scheduled_depart_at`, `period_end` on or
        after `period_start`, and any attempt to set a derived-only status value
        (specifically a `MillContract` `status` of `FILLED`) refused. Failure is
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_truck_with_illegal_axle_config_returns_validation
        """
        carrier = validate_success(
            api.create_haul_contractor(create_haul_contractor_payload(), admin_headers),
            201,
        )
        file_all_coverages(carrier["id"])

        response = api.create_truck(
            carrier["id"],
            create_truck_payload(unit_number="T-99", axle_config="EIGHT_AXLE"),
            admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

        units = [truck["unit_number"] for truck in list_trucks(carrier["id"])]
        assert "T-99" not in units, "the rejected truck must not be persisted"

    def test_get_load_with_an_unknown_id_returns_load_not_found(self, api, ops_headers):
        """PRD §2.7: "The 404 raised names the resource type that failed to resolve:
        `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/entities/get_load_with_unknown_id_returns_load_not_found
        """
        response = api.get_load(UNKNOWN_UUID, ops_headers)
        validate_error(response, ApiErrorId.ERR_LOAD_NOT_FOUND.value, 404)


class TestListingsAndTheLogicalClock:
    def test_load_listing_reports_total_count_and_has_more_across_a_window(
        self, api, ops_headers
    ):
        """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may
        be no smaller than 1, and may be no larger than 100."
        PRD §2.3: "The `meta` object on a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of records
        matching the filter before the page window is applied and `has_more` is true
        exactly when records remain beyond the current window."

        Design: Corner/entities/list_loads_returns_pagination_envelope_with_total_count_and_has_more
        """
        scn = build_network()
        dispatch_load(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        dispatch_load(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )
        dispatch_load(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-05T08:00:00Z",
            scheduled_arrive_at="2026-08-05T10:00:00Z",
        )

        response = api.list_loads(
            ops_headers, params={"tract_id": scn["tract_id"], "limit": 2, "offset": 0}
        )
        rows, meta = validate_paginated(response)

        assert len(rows) == 2, "the page window holds exactly the requested 2 rows"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(30.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(470.00, abs=0.005)

    def test_haul_route_listing_filters_independently_by_tract_and_by_mill(
        self, api, admin_headers, ops_headers
    ):
        """PRD §3.1: "Routes may be listed with filters on `tract_id`, `mill_id` and
        `status`."
        PRD §2.3: "Filter parameters are additive: supplying several narrows the
        result set to records matching all of them."

        Design: Corner/endpoints/haul_routes_list_filters_by_tract_and_by_mill
        """
        scn = build_network()
        mill_b = validate_success(
            api.create_mill(create_mill_payload(name="Coast Mill B"), admin_headers), 201
        )
        route_b = validate_success(
            api.create_haul_route(
                {
                    "tract_id": scn["tract_id"],
                    "mill_id": mill_b["id"],
                    "distance_miles": 45,
                    "legal_gross_weight_lbs": 98000,
                    "permit_class_required": "STANDARD",
                    "status": "OPEN",
                },
                admin_headers,
            ),
            201,
        )

        by_mill, mill_meta = validate_paginated(
            api.list_haul_routes(ops_headers, params={"mill_id": mill_b["id"]})
        )
        assert mill_meta["total_count"] == 1
        assert len(by_mill) == 1
        assert by_mill[0]["id"] == route_b["id"]
        assert by_mill[0]["distance_miles"] == 45

        by_tract, tract_meta = validate_paginated(
            api.list_haul_routes(
                ops_headers,
                params={"tract_id": scn["tract_id"], "limit": 10, "offset": 0},
            )
        )
        assert tract_meta["total_count"] == 2
        assert tract_meta["has_more"] is False
        assert {row["id"] for row in by_tract} == {scn["route_a_id"], route_b["id"]}

    def test_logical_clock_starts_at_the_declared_instant_and_stamps_every_event(
        self, api
    ):
        """PRD §2.4: "The server maintains a **logical clock** whose value at startup
        is exactly `2026-08-01T00:00:00Z`, and every date-sensitive rule in this
        document — insurance effectivity and expiry, frost-law postings, seasonal
        access months, mill-contract periods, settlement periods, the 180-day safety
        lookback, and every timestamp the server stamps onto a resource — reads that
        logical clock rather than the host's real time."
        PRD §3.7: "Recording the loaded truck leaving the landing advances the load
        `DISPATCHED → IN_TRANSIT` and stamps `departed_at` with the logical clock; it
        requires that the caller's `X-User-ID` equal the load's `haul_contractor_id`
        and that the truck not derive `OUT_OF_SERVICE`."

        Design: Corner/endpoints/logical_clock_startup_default_stamps_2026_08_01
        """
        scn = build_network()
        load, ticket = deliver_load(scn)

        load_row = read_load(load["id"])
        assert_instant_equals(load_row["departed_at"], "2026-08-01T00:00:00Z", "departed_at")
        assert_instant_equals(load_row["arrived_at"], "2026-08-01T00:00:00Z", "arrived_at")
        assert load_row["wait_minutes"] == 0
        assert load_row["demurrage_cents"] == 0
        assert load_row["settlement_event_on"] == "2026-08-01"

        ticket_row = validate_success(
            api.get_delivery_ticket(ticket["id"], scn["scaler_headers"])
        )
        assert_instant_equals(
            ticket_row["certified_at"], "2026-08-01T00:00:00Z", "certified_at"
        )


class TestReferenceMutation:
    def test_mill_yard_is_closed_by_its_own_scaler_and_reopened_by_the_admin(
        self, api, admin_headers
    ):
        """PRD §3.1: "A mill also carries a `receiving_status` of either `OPEN` or
        `CLOSED`, defaulting to `OPEN` when the registration omits it; the yard may
        be opened or closed later by either a `PlatformAdmin` or the mill's own
        `MillScaler`, and closing the yard blocks new dispatch against every quota
        contract that mill owns."
        PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
        mutation, and `version`, an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that resource."

        Design: Corner/endpoints/patch_mill_receiving_status_reopens_and_closes_the_yard
        """
        mill = validate_success(
            api.create_mill(create_mill_payload(), admin_headers), 201
        )
        scaler = make_scaler_headers(mill["id"])

        validate_success(api.patch_mill(mill["id"], {"receiving_status": "CLOSED"}, scaler))
        closed = validate_success(api.get_mill(mill["id"], admin_headers))
        assert closed["receiving_status"] == "CLOSED"

        reopened = validate_success(
            api.patch_mill(mill["id"], {"receiving_status": "OPEN"}, admin_headers)
        )
        assert reopened["receiving_status"] == "OPEN"
        assert read_mill(mill["id"])["version"] == 3, (
            "creation plus two mutations leaves the mill at version 3"
        )

    def test_quota_contract_suspends_and_resumes_but_never_accepts_filled(
        self, api, admin_headers, ops_headers
    ):
        """PRD §3.1: "A `PlatformAdmin` may move a contract that is `OPEN` or `FILLED`
        to `SUSPENDED`, supplying an optional `reason`, which blocks dispatch while
        leaving existing loads untouched; moving a `SUSPENDED` contract back to `OPEN`
        recomputes `available_tons` on resume and, if the recomputed figure is zero or
        below, immediately auto-transitions the contract to `FILLED`."
        PRD §3.1: "Requesting a status change the contract's current status does not
        admit is refused with `ERR_INVALID_MILL_CONTRACT_STATE`; requesting `FILLED`
        at all is caught earlier, at the schema rung, and is refused with
        `ERR_VALIDATION` because `FILLED` is derived and never settable by a client."
        PRD §3.6: "Then the cross-entity states are checked in this order — the tract
        must be `ACTIVE` (`ERR_TRACT_NOT_ACTIVE`), the mill contract must be `OPEN`
        (`ERR_INVALID_MILL_CONTRACT_STATE`), the mill owning that contract must have
        `receiving_status` of `OPEN` (`ERR_MILL_NOT_RECEIVING`), the haul route must
        be `OPEN` or `POSTED_RESTRICTED` and never `CLOSED` (`ERR_ROUTE_NOT_OPEN`),
        and the truck must not derive `OUT_OF_SERVICE`
        (`ERR_TRUCK_OUT_OF_SERVICE`)."

        Design: Corner/endpoints/mill_contract_patch_suspends_resumes_and_refuses_the_derived_filled_status
        """
        scn = build_network()

        suspended = validate_success(
            api.patch_mill_contract(
                scn["mc_a_id"],
                {"status": "SUSPENDED", "reason": "mill inventory glut"},
                admin_headers,
            )
        )
        assert suspended["status"] == "SUSPENDED"

        blocked = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(
            blocked, ApiErrorId.ERR_INVALID_MILL_CONTRACT_STATE.value, 409
        )

        derived = api.patch_mill_contract(
            scn["mc_a_id"], {"status": "FILLED"}, admin_headers
        )
        validate_error(derived, ApiErrorId.ERR_VALIDATION.value, 400)

        resumed = validate_success(
            api.patch_mill_contract(
                scn["mc_a_id"],
                {"status": "OPEN", "reason": "quota reopened"},
                admin_headers,
            )
        )
        assert resumed["status"] == "OPEN"

        load = dispatch_load(scn)
        assert read_load(load["id"])["dispatch_status"] == "DISPATCHED"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["available_tons"] == pytest.approx(473.50, abs=0.005)


class TestUnresolvedIdentifiers:
    def test_mobilize_with_an_unknown_tract_id_returns_tract_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/mobilize_with_unknown_tract_id_returns_tract_not_found
        """
        response = api.mobilize_tract(UNKNOWN_UUID, ops_headers)
        validate_error(response, ApiErrorId.ERR_TRACT_NOT_FOUND.value, 404)

    def test_approve_with_an_unknown_production_plan_id_returns_plan_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/approve_with_unknown_production_plan_id_returns_plan_not_found
        """
        response = api.approve_production_plan(UNKNOWN_UUID, ops_headers)
        validate_error(response, ApiErrorId.ERR_PRODUCTION_PLAN_NOT_FOUND.value, 404)

    def test_lift_with_an_unknown_shutdown_order_id_returns_shutdown_order_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/lift_with_unknown_shutdown_order_id_returns_shutdown_order_not_found
        """
        response = api.lift_shutdown_order(
            UNKNOWN_UUID, {"soil_moisture_index": 30}, ops_headers
        )
        validate_error(response, ApiErrorId.ERR_SHUTDOWN_ORDER_NOT_FOUND.value, 404)

    def test_revoke_with_an_unknown_certificate_id_returns_certificate_not_found(
        self, api, safety_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/revoke_with_unknown_certificate_id_returns_certificate_not_found
        """
        response = api.revoke_insurance_certificate(
            UNKNOWN_UUID, {"reason": "typo in the id"}, safety_headers
        )
        validate_error(response, ApiErrorId.ERR_INSURANCE_CERTIFICATE_NOT_FOUND.value, 404)

    def test_submit_with_an_unknown_statement_id_returns_statement_not_found(
        self, api, accountant_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/submit_with_unknown_statement_id_returns_statement_not_found
        """
        response = api.submit_settlement_statement(UNKNOWN_UUID, accountant_headers)
        validate_error(response, ApiErrorId.ERR_SETTLEMENT_STATEMENT_NOT_FOUND.value, 404)

    def test_certify_with_an_unknown_ticket_id_returns_delivery_ticket_not_found(
        self, api, scaler_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/certify_with_unknown_ticket_id_returns_ticket_not_found
        """
        response = api.certify_delivery_ticket(UNKNOWN_UUID, scaler_headers)
        validate_error(response, ApiErrorId.ERR_DELIVERY_TICKET_NOT_FOUND.value, 404)

    def test_safety_finding_on_an_unknown_carrier_returns_haul_contractor_not_found(
        self, api, safety_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/safety_finding_on_unknown_carrier_returns_carrier_not_found
        """
        response = api.create_safety_finding(
            UNKNOWN_UUID,
            {"severity": "MINOR", "points": 5, "occurred_on": "2026-08-01"},
            safety_headers,
        )
        validate_error(response, ApiErrorId.ERR_HAUL_CONTRACTOR_NOT_FOUND.value, 404)

    def test_patch_with_an_unknown_mill_id_returns_mill_not_found(
        self, api, admin_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/patch_with_unknown_mill_id_returns_mill_not_found
        """
        response = api.patch_mill(
            UNKNOWN_UUID, {"receiving_status": "CLOSED"}, admin_headers
        )
        validate_error(response, ApiErrorId.ERR_MILL_NOT_FOUND.value, 404)

    def test_get_with_an_unknown_crew_assignment_id_returns_assignment_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/get_with_unknown_crew_assignment_id_returns_assignment_not_found
        """
        response = api.get_crew_assignment(UNKNOWN_UUID, ops_headers)
        validate_error(response, ApiErrorId.ERR_CREW_ASSIGNMENT_NOT_FOUND.value, 404)

    def test_crew_assignment_naming_an_unknown_crew_returns_crew_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."
        PRD §3.3: "A new tract opens in `PLANNED` status with a `suspension_count` of
        0, a `move_in_cost_cents` of 0 and a `produced_tons` of 0."

        Design: Corner/errors/crew_assignment_with_unknown_crew_id_returns_crew_not_found
        """
        tract = create_tract()

        response = api.create_crew_assignment(
            tract["id"],
            {
                "crew_id": UNKNOWN_UUID,
                "move_in_miles": 40,
                "window_start": "2026-08-01",
                "window_end": "2026-10-15",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_CREW_NOT_FOUND.value, 404)
        assert read_tract(tract["id"])["move_in_cost_cents"] == 0

    def test_dispatch_naming_an_unknown_truck_returns_truck_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/dispatch_with_unknown_truck_id_returns_truck_not_found
        """
        scn = build_network()

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": UNKNOWN_UUID,
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_TRUCK_NOT_FOUND.value, 404)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )

    def test_dispatch_naming_an_unknown_haul_route_returns_route_not_found(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Existence.** Path resources resolve left to right along the
        URL, and only then do body foreign keys resolve, in the order they appear in
        the endpoint's declared input list. The 404 raised names the resource type
        that failed to resolve: `ERR_MILL_NOT_FOUND`, `ERR_MILL_CONTRACT_NOT_FOUND`,
        `ERR_HAUL_CONTRACTOR_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
        `ERR_TRUCK_NOT_FOUND`, `ERR_TRACT_NOT_FOUND`, `ERR_PRODUCTION_PLAN_NOT_FOUND`,
        `ERR_CREW_NOT_FOUND`, `ERR_CREW_ASSIGNMENT_NOT_FOUND`,
        `ERR_HAUL_ROUTE_NOT_FOUND`, `ERR_SHUTDOWN_ORDER_NOT_FOUND`,
        `ERR_LOAD_NOT_FOUND`, `ERR_DELIVERY_TICKET_NOT_FOUND` or
        `ERR_SETTLEMENT_STATEMENT_NOT_FOUND`."

        Design: Corner/errors/dispatch_with_unknown_haul_route_id_returns_route_not_found
        """
        scn = build_network()

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": UNKNOWN_UUID,
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_HAUL_ROUTE_NOT_FOUND.value, 404)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )
