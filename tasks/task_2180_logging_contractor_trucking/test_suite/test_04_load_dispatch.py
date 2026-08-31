"""Dispatching a load against mill quota, and the guards that stand in its way."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_load,
    build_network,
    cancel_load,
    declare_shutdown,
    depart_load,
    dispatch_load,
    lift_shutdown,
    load_at_mill,
    read_load,
    read_mill_contract,
    read_tract,
    read_truck,
    reject_ticket,
    suspend_carrier,
    reinstate_carrier,
    record_finding,
    read_haul_contractor,
    validate_error,
    validate_success,
    write_ticket,
)


class TestDispatchAdmission:
    def test_a_dispatched_load_starts_on_both_status_axes(self, api, ops_headers):
        """PRD §3.6: "On admission, the load is created with `dispatch_status` of
        `DISPATCHED`, `settlement_status` of `UNSETTLED`, and `rehaul_status` of
        `NONE`."
        PRD §3.6: "The truck's owning carrier is copied onto the load as
        `haul_contractor_id` and never changed thereafter, which is what makes
        ownership checks on departure and arrival, and eligibility for settlement,
        resolvable from the load alone."
        PRD §3.6: "The load's `rehaul_of_load_id` stays null unless the system itself
        later creates the load as a rehaul."

        Design: Corner/state_machines/load_starts_dispatched_and_unsettled_on_both_axes
        """
        scn = build_network()

        response = api.create_load(
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
        load = validate_success(response, 201)

        assert_load(load)
        assert load["dispatch_status"] == "DISPATCHED"
        assert load["settlement_status"] == "UNSETTLED"
        assert load["rehaul_status"] == "NONE"
        assert load.get("rehaul_of_load_id") is None
        assert load["haul_contractor_id"] == scn["hc_id"]
        assert load["provisional_haul_pay_cents"] == 32_590

    def test_dispatch_naming_an_unknown_mill_contract_returns_contract_not_found(
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

        Design: Corner/entities/dispatch_with_unknown_mill_contract_id_returns_contract_not_found
        """
        scn = build_network()

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": UNKNOWN_UUID,
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
        validate_error(response, ApiErrorId.ERR_MILL_CONTRACT_NOT_FOUND.value, 404)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )

    def test_declaring_a_species_the_contract_does_not_buy_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.6: "Then the physical and referential constraints: the truck's permit
        rank must be at least the route's required permit rank
        (`ERR_PERMIT_CLASS_INSUFFICIENT`), the route must connect this tract to this
        contract's mill (`ERR_ROUTE_TRACT_MILL_MISMATCH`), and the load's declared
        species and grade must equal the contract's `species` and `grade` exactly
        (`ERR_SPECIES_GRADE_MISMATCH`)."

        Design: Corner/validations/dispatching_a_species_the_contract_does_not_buy_is_rejected
        """
        scn = build_network()

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "RED_ALDER",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_SPECIES_GRADE_MISMATCH.value, 422)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(500.00, abs=0.005)

    def test_a_route_ending_at_another_mill_cannot_carry_this_contracts_wood(
        self, api, admin_headers, ops_headers
    ):
        """PRD §2.8: "A haul route is a directed pairing of one tract with one mill,
        and a load may only travel a route whose `tract_id` equals the load's own
        `tract_id` and whose `mill_id` equals the `mill_id` of the mill contract the
        load draws against; a route that connects some other pair is refused with
        `ERR_ROUTE_TRACT_MILL_MISMATCH`."

        Design: Corner/validations/route_that_does_not_reach_the_contracts_mill_is_rejected
        """
        scn = build_network()
        mill_b = validate_success(
            api.create_mill(
                {"name": "Coast Mill B", "state_code": "OR", "receiving_status": "OPEN"},
                admin_headers,
            ),
            201,
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

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": route_b["id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 26.5,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_ROUTE_TRACT_MILL_MISMATCH.value, 422)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )

    def test_a_closed_mill_yard_blocks_dispatch_against_its_open_contract(
        self, api, admin_headers, ops_headers
    ):
        """PRD §3.6: "Then the cross-entity states are checked in this order — the
        tract must be `ACTIVE` (`ERR_TRACT_NOT_ACTIVE`), the mill contract must be
        `OPEN` (`ERR_INVALID_MILL_CONTRACT_STATE`), the mill owning that contract must
        have `receiving_status` of `OPEN` (`ERR_MILL_NOT_RECEIVING`), the haul route
        must be `OPEN` or `POSTED_RESTRICTED` and never `CLOSED`
        (`ERR_ROUTE_NOT_OPEN`), and the truck must not derive `OUT_OF_SERVICE`
        (`ERR_TRUCK_OUT_OF_SERVICE`)."

        Design: Corner/validations/dispatching_to_a_mill_whose_yard_is_closed_is_rejected
        """
        scn = build_network()
        validate_success(
            api.patch_mill(scn["mill_a_id"], {"receiving_status": "CLOSED"}, admin_headers)
        )

        response = api.create_load(
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
        validate_error(response, ApiErrorId.ERR_MILL_NOT_RECEIVING.value, 409)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["status"] == "OPEN"
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)

    def test_a_closed_haul_route_blocks_dispatch(self, api, ops_headers):
        """PRD §3.6: "Then the cross-entity states are checked in this order — the
        tract must be `ACTIVE` (`ERR_TRACT_NOT_ACTIVE`), the mill contract must be
        `OPEN` (`ERR_INVALID_MILL_CONTRACT_STATE`), the mill owning that contract must
        have `receiving_status` of `OPEN` (`ERR_MILL_NOT_RECEIVING`), the haul route
        must be `OPEN` or `POSTED_RESTRICTED` and never `CLOSED`
        (`ERR_ROUTE_NOT_OPEN`), and the truck must not derive `OUT_OF_SERVICE`
        (`ERR_TRUCK_OUT_OF_SERVICE`)."

        Design: Corner/validations/dispatching_over_a_closed_haul_route_is_rejected
        """
        scn = build_network(route={"status": "CLOSED"})

        response = api.create_load(
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
        validate_error(response, ApiErrorId.ERR_ROUTE_NOT_OPEN.value, 409)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )

    def test_dispatch_outside_the_contracts_closed_period_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.1: "The contract is live only between `period_start` and
        `period_end`, two `YYYY-MM-DD` dates that form a closed interval — a load
        dispatched on a clock date before `period_start` or after `period_end` is
        refused with `ERR_CONTRACT_PERIOD_CLOSED`."

        Design: Corner/validations/dispatching_after_the_contract_period_has_closed_is_rejected
        """
        scn = build_network(
            contract={"period_start": "2026-06-01", "period_end": "2026-07-31"}
        )

        response = api.create_load(
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
        validate_error(response, ApiErrorId.ERR_CONTRACT_PERIOD_CLOSED.value, 422)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["status"] == "OPEN"
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)

    def test_a_standard_truck_cannot_run_a_longer_combination_route(
        self, api, ops_headers
    ):
        """PRD §2.10: "Truck **permit class** is one of `STANDARD`,
        `DIVISIBLE_LOAD_PERMIT` or `LONGER_COMBINATION`, and the three are strictly
        ranked in that order — `STANDARD` ranks 1, `DIVISIBLE_LOAD_PERMIT` ranks 2 and
        `LONGER_COMBINATION` ranks 3."
        PRD §3.6: "Then the physical and referential constraints: the truck's permit
        rank must be at least the route's required permit rank
        (`ERR_PERMIT_CLASS_INSUFFICIENT`), the route must connect this tract to this
        contract's mill (`ERR_ROUTE_TRACT_MILL_MISMATCH`), and the load's declared
        species and grade must equal the contract's `species` and `grade` exactly
        (`ERR_SPECIES_GRADE_MISMATCH`)."

        Design: Corner/validations/a_standard_truck_cannot_run_a_longer_combination_route
        """
        scn = build_network(route={"permit_class_required": "LONGER_COMBINATION"})

        response = api.create_load(
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
        validate_error(response, ApiErrorId.ERR_PERMIT_CLASS_INSUFFICIENT.value, 422)

        assert read_haul_contractor(scn["hc_id"])["compliance_score"] == 100
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )


class TestQuotaGate:
    def test_a_request_one_hundredth_above_the_available_tonnage_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.6: "The fiscal gate is strict but admits exact equality: the
        requested `estimated_net_tons` must not be greater than the contract's
        `available_tons`. A request for more is refused with `ERR_QUOTA_EXCEEDED`; a
        request for exactly the available figure is admitted and drives
        `available_tons` to exactly 0.00, which immediately sends the contract
        `OPEN → FILLED`."

        Design: Difficulty/boundary_precision_check/quota_available_tons_exact_equality_admits_dispatch_but_one_hundredth_more_fails
        """
        scn = build_network(contract={"quota_tons": 30.0})
        dispatch_load(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        assert read_mill_contract(scn["mc_a_id"])["available_tons"] == pytest.approx(
            10.00, abs=0.005
        )

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 10.01,
                "scheduled_depart_at": "2026-08-04T08:00:00Z",
                "scheduled_arrive_at": "2026-08-04T10:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_QUOTA_EXCEEDED.value, 422)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(20.00, abs=0.005)
        assert contract["status"] == "OPEN"

    def test_a_request_for_exactly_the_available_tonnage_fills_the_contract(
        self, api, ops_headers
    ):
        """PRD §3.6: "The fiscal gate is strict but admits exact equality: the
        requested `estimated_net_tons` must not be greater than the contract's
        `available_tons`. A request for more is refused with `ERR_QUOTA_EXCEEDED`; a
        request for exactly the available figure is admitted and drives
        `available_tons` to exactly 0.00, which immediately sends the contract
        `OPEN → FILLED`."

        Design: Difficulty/boundary_precision_check/quota_available_tons_exact_equality_admits_dispatch_but_one_hundredth_more_fails
        """
        scn = build_network(contract={"quota_tons": 30.0})
        dispatch_load(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )

        exact = dispatch_load(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-05T08:00:00Z",
            scheduled_arrive_at="2026-08-05T10:00:00Z",
        )

        assert read_load(exact["id"])["dispatch_status"] == "DISPATCHED"
        assert exact["estimated_net_tons"] == pytest.approx(10.00, abs=0.005)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(30.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["status"] == "FILLED"

    def test_reserved_tons_counts_only_the_three_reserving_dispatch_statuses(
        self, api, ops_headers
    ):
        """PRD §3.1: "`reserved_tons` is the sum of `estimated_net_tons` over every
        load on this contract whose `dispatch_status` is `DISPATCHED`, `IN_TRANSIT` or
        `AT_MILL`."
        PRD §3.1: "Cancelled and rejected loads contribute to neither sum, and there is
        no date filter on either sum — the status filters just given are the complete
        inclusion rule."

        Design: Corner/calculations/quota_position_excludes_cancelled_and_rejected_loads
        """
        scn = build_network(contract={"quota_tons": 100})
        cancelled = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        surviving = dispatch_load(
            scn,
            estimated_net_tons=20.0,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )
        cancel_load(scn, cancelled["id"], reason="skidder down")

        rejected = load_at_mill(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-05T08:00:00Z",
            scheduled_arrive_at="2026-08-05T10:00:00Z",
        )
        ticket = write_ticket(
            scn, rejected["id"], gross_weight_lbs=55000, defect_deduction_pct=0.0
        )
        reject_ticket(scn, ticket["id"], reject_reason="CONTAMINATION")

        assert read_load(cancelled["id"])["dispatch_status"] == "CANCELLED"
        assert read_load(surviving["id"])["dispatch_status"] == "DISPATCHED"
        rejected_row = read_load(rejected["id"])
        assert rejected_row["dispatch_status"] == "REJECTED"
        assert rejected_row["rehaul_status"] == "NO_ALTERNATE"

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(20.00, abs=0.005)
        assert contract["delivered_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(80.00, abs=0.005)
        assert contract["status"] == "OPEN"


class TestTruckOccupation:
    def test_a_load_departing_at_the_prior_arrival_instant_collides(
        self, api, ops_headers
    ):
        """PRD §3.6: "A proposed load conflicts with an existing one on the same truck
        — considering only that truck's loads whose `dispatch_status` is `DISPATCHED`,
        `IN_TRANSIT` or `AT_MILL` — when the proposed `scheduled_depart_at` falls at or
        before the existing load's `scheduled_arrive_at` **and** the proposed
        `scheduled_arrive_at` falls at or after the existing load's
        `scheduled_depart_at`. Intervals that merely touch at an endpoint therefore
        conflict."

        Design: Difficulty/resource_temporal_overlap/truck_haul_interval_is_closed_so_touching_endpoints_collide
        """
        scn = build_network()
        dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 10.0,
                "scheduled_depart_at": "2026-08-03T10:00:00Z",
                "scheduled_arrive_at": "2026-08-03T12:00:00Z",
            },
            ops_headers,
        )
        validate_error(response, ApiErrorId.ERR_TRUCK_WINDOW_CONFLICT.value, 409)

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(26.50, abs=0.005)

    def test_a_load_departing_one_second_later_is_admitted(self, api, ops_headers):
        """PRD §3.6: "Truck occupation is treated as a **closed** interval with no
        buffer, unlike the half-open crew window with its two-day tail."
        PRD §3.6: "A proposed load conflicts with an existing one on the same truck —
        considering only that truck's loads whose `dispatch_status` is `DISPATCHED`,
        `IN_TRANSIT` or `AT_MILL` — when the proposed `scheduled_depart_at` falls at or
        before the existing load's `scheduled_arrive_at` **and** the proposed
        `scheduled_arrive_at` falls at or after the existing load's
        `scheduled_depart_at`. Intervals that merely touch at an endpoint therefore
        conflict."

        Design: Difficulty/resource_temporal_overlap/truck_haul_interval_is_closed_so_touching_endpoints_collide
        """
        scn = build_network()
        dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )

        second = dispatch_load(
            scn,
            estimated_net_tons=10.0,
            scheduled_depart_at="2026-08-03T10:00:01Z",
            scheduled_arrive_at="2026-08-03T12:00:00Z",
        )

        assert read_load(second["id"])["dispatch_status"] == "DISPATCHED"
        assert second["scheduled_depart_at"].startswith("2026-08-03T10:00:01")

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(36.50, abs=0.005)
        assert contract["available_tons"] == pytest.approx(463.50, abs=0.005)


class TestAdmissionLadderPrecedence:
    def test_a_suspended_tract_outranks_a_quota_overdraw_on_the_same_request(
        self, api, ops_headers
    ):
        """PRD §2.7: "Requests are admitted through a strictly ordered ladder of
        checks. The first check that fails determines the response; later checks are
        never reached, and their failure conditions are therefore invisible on that
        request. When two conditions on a single request would both fail, the earlier
        rung wins."
        PRD §2.7: "**Cross-entity state.** The related resources are in states that
        admit the operation: `ERR_TRACT_NOT_ACTIVE`, `ERR_INVALID_MILL_CONTRACT_STATE`
        for a dispatch against a contract that is not `OPEN`, `ERR_MILL_NOT_RECEIVING`,
        `ERR_ROUTE_NOT_OPEN`, `ERR_TRUCK_OUT_OF_SERVICE`, `ERR_NO_ELIGIBLE_CREW` and
        `ERR_LOADS_STILL_OPEN`."
        PRD §2.7: "**Fiscal limits.** `ERR_QUOTA_EXCEEDED`,
        `ERR_OVERRUN_TOLERANCE_EXCEEDED` and `ERR_NO_SETTLEABLE_LOADS`."

        Design: Difficulty/priority_pair_validation_conflict/suspended_tract_state_error_outranks_quota_overdraw_on_dispatch
        """
        scn = build_network(contract={"quota_tons": 10.0})
        declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=88)

        response = api.create_load(
            {
                "tract_id": scn["tract_id"],
                "mill_contract_id": scn["mc_a_id"],
                "haul_route_id": scn["route_a_id"],
                "truck_id": scn["truck_id"],
                "declared_species": "DOUGLAS_FIR",
                "declared_grade": "SAWLOG_1",
                "estimated_net_tons": 40.0,
                "scheduled_depart_at": "2026-08-03T08:00:00Z",
                "scheduled_arrive_at": "2026-08-03T10:00:00Z",
            },
            ops_headers,
        )
        error = validate_error(response, ApiErrorId.ERR_TRACT_NOT_ACTIVE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_QUOTA_EXCEEDED.value

    def test_the_blocked_overdraw_leaves_the_quota_position_untouched(
        self, api, ops_headers
    ):
        """PRD §2.7: "When two conditions on a single request would both fail, the
        earlier rung wins."
        PRD §3.5: "Hop one creates the order and moves the tract
        `ACTIVE → SUSPENDED`, incrementing the tract's `suspension_count` by 1."

        Design: Difficulty/priority_pair_validation_conflict/suspended_tract_state_error_outranks_quota_overdraw_on_dispatch
        """
        scn = build_network(contract={"quota_tons": 10.0})
        declare_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=88)

        validate_error(
            api.create_load(
                {
                    "tract_id": scn["tract_id"],
                    "mill_contract_id": scn["mc_a_id"],
                    "haul_route_id": scn["route_a_id"],
                    "truck_id": scn["truck_id"],
                    "declared_species": "DOUGLAS_FIR",
                    "declared_grade": "SAWLOG_1",
                    "estimated_net_tons": 40.0,
                    "scheduled_depart_at": "2026-08-03T08:00:00Z",
                    "scheduled_arrive_at": "2026-08-03T10:00:00Z",
                },
                ops_headers,
            ),
            ApiErrorId.ERR_TRACT_NOT_ACTIVE.value,
            409,
        )

        assert read_tract(scn["tract_id"])["status"] == "SUSPENDED"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(10.00, abs=0.005)

    def test_the_compliance_score_gate_outranks_the_permit_class_constraint(
        self, api, ops_headers
    ):
        """PRD §3.6: "Then the carrier's rolling-window `compliance_score` must be at
        least 70 (`ERR_COMPLIANCE_SCORE_TOO_LOW`)."
        PRD §2.7: "**Safety and compliance thresholds.**
        `ERR_COMPLIANCE_SCORE_TOO_LOW`, `ERR_INSURANCE_COVERAGE_INCOMPLETE`,
        `ERR_WET_THRESHOLD_NOT_MET` and `ERR_WET_THRESHOLD_STILL_MET`."
        PRD §2.7: "**Physical and referential constraints.**
        `ERR_PERMIT_CLASS_INSUFFICIENT`, `ERR_ROUTE_TRACT_MILL_MISMATCH`,
        `ERR_SPECIES_GRADE_MISMATCH`, `ERR_OVERWEIGHT_LOAD` and `ERR_ZERO_NET_TONS`."

        Design: Difficulty/priority_pair_validation_conflict/compliance_score_safety_gate_outranks_permit_class_constraint
        """
        scn = build_network(route={"permit_class_required": "LONGER_COMBINATION"})
        record_finding(
            scn,
            severity="MINOR",
            points=38,
            occurred_on="2026-08-01",
            note="repeated logbook errors",
        )

        response = api.create_load(
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
        error = validate_error(
            response, ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_PERMIT_CLASS_INSUFFICIENT.value

    def test_a_minor_finding_can_drop_the_score_without_moving_the_status(
        self, api, ops_headers
    ):
        """PRD §3.2: "A `MINOR` finding costs points but changes no status."
        PRD §3.2: "From that base the system subtracts the sum of `points` over every
        safety finding on the carrier whose `occurred_on` falls inside the scoring
        window, both endpoints inclusive; subtracts 25 points for each of the three
        required coverage types that has no certificate deriving `ACTIVE` at the clock
        date; and subtracts 3 points for each load of that carrier whose
        `dispatch_status` is `REJECTED` and whose `rejected_on` falls inside the
        scoring window, again with both endpoints inclusive."

        Design: Difficulty/priority_pair_validation_conflict/compliance_score_safety_gate_outranks_permit_class_constraint
        """
        scn = build_network(route={"permit_class_required": "LONGER_COMBINATION"})
        record_finding(
            scn,
            severity="MINOR",
            points=38,
            occurred_on="2026-08-01",
            note="repeated logbook errors",
        )

        carrier = read_haul_contractor(scn["hc_id"])
        assert carrier["compliance_score"] == 62
        assert carrier["compliance_status"] == "COMPLIANT"

        validate_error(
            api.create_load(
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
            ),
            ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW.value,
            422,
        )
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )


class TestCrossAggregateGates:
    def test_dispatch_is_refused_while_the_tract_aggregate_is_suspended(
        self, api, ops_headers
    ):
        """PRD §3.6: "Then the cross-entity states are checked in this order — the
        tract must be `ACTIVE` (`ERR_TRACT_NOT_ACTIVE`), the mill contract must be
        `OPEN` (`ERR_INVALID_MILL_CONTRACT_STATE`), the mill owning that contract must
        have `receiving_status` of `OPEN` (`ERR_MILL_NOT_RECEIVING`), the haul route
        must be `OPEN` or `POSTED_RESTRICTED` and never `CLOSED`
        (`ERR_ROUTE_NOT_OPEN`), and the truck must not derive `OUT_OF_SERVICE`
        (`ERR_TRUCK_OUT_OF_SERVICE`)."

        Design: Difficulty/cross_entity_state_dependency/load_dispatch_is_gated_by_the_tract_status_of_a_different_aggregate
        """
        scn = build_network()
        declare_shutdown(scn, reason="FIRE_DANGER", soil_moisture_index=20)

        response = api.create_load(
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
        validate_error(response, ApiErrorId.ERR_TRACT_NOT_ACTIVE.value, 409)
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )

    def test_lifting_the_shutdown_admits_the_identical_dispatch_body(
        self, api, ops_headers
    ):
        """PRD §3.5: "Because the order was lifted and no other `ACTIVE` order remains
        on the tract, the tract returns `SUSPENDED → ACTIVE`; because the tract
        returned to `ACTIVE`, every crew assignment on it in `STOOD_DOWN` returns to
        `WORKING`; and because those assignments returned to `WORKING`, their crews
        return `STOOD_DOWN → ON_TRACT`."
        PRD §3.6: "Dispatch also adds the estimated tonnage to the contract's
        `reserved_tons`, recomputes `available_tons`, increments the contract's
        `version` by 1, and may auto-transition the contract to `FILLED` as described
        above."

        Design: Difficulty/cross_entity_state_dependency/load_dispatch_is_gated_by_the_tract_status_of_a_different_aggregate
        """
        scn = build_network()
        order = declare_shutdown(scn, reason="FIRE_DANGER", soil_moisture_index=20)
        validate_error(
            api.create_load(
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
            ),
            ApiErrorId.ERR_TRACT_NOT_ACTIVE.value,
            409,
        )

        lift_shutdown(scn, order["id"], soil_moisture_index=20)
        load = dispatch_load(scn)

        tract = read_tract(scn["tract_id"])
        assert tract["status"] == "ACTIVE"
        assert tract["suspension_count"] == 1
        assert read_load(load["id"])["dispatch_status"] == "DISPATCHED"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["available_tons"] == pytest.approx(473.50, abs=0.005)

    def test_a_suspended_carrier_surfaces_as_a_compliance_failure_not_equipment(
        self, api, ops_headers
    ):
        """PRD §2.7: "**Carrier compliance status.** On load dispatch, the owning
        carrier's `compliance_status` is `COMPLIANT` or `WARNED`, yielding
        `ERR_CONTRACTOR_NOT_COMPLIANT` (HTTP 422) otherwise. This rung sits
        deliberately **above** the truck-status rung, so a suspended carrier is
        reported as a compliance failure rather than as an equipment failure, even
        though the suspension is also what put its trucks out of service."

        Design: Difficulty/cross_entity_state_dependency/load_dispatch_is_gated_by_the_compliance_status_of_the_carrier_aggregate
        """
        scn = build_network()
        suspend_carrier(scn, reason="missed corrective action deadline")

        response = api.create_load(
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
        error = validate_error(
            response, ApiErrorId.ERR_CONTRACTOR_NOT_COMPLIANT.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_TRUCK_OUT_OF_SERVICE.value

    def test_reinstatement_restores_dispatchability_with_an_unchanged_body(
        self, api, ops_headers
    ):
        """PRD §3.2: "A `SafetyOfficer` may return a `SUSPENDED` carrier to
        `COMPLIANT`, supplying an optional `note`, but only when each of
        `GENERAL_LIABILITY`, `AUTO_LIABILITY` and `WORKERS_COMP` has at least one
        certificate deriving `ACTIVE`; attempting it while any required coverage is
        uncovered is refused with `ERR_INSURANCE_COVERAGE_INCOMPLETE`."
        PRD §3.1: "Its `status` is entirely derived and never set: a truck reads
        `OUT_OF_SERVICE` whenever its owning carrier's `compliance_status` is
        `SUSPENDED`; otherwise it reads `DISPATCHED` whenever at least one load on that
        truck has a `dispatch_status` of `DISPATCHED`, `IN_TRANSIT` or `AT_MILL`;
        otherwise it reads `AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/load_dispatch_is_gated_by_the_compliance_status_of_the_carrier_aggregate
        """
        scn = build_network()
        suspend_carrier(scn, reason="missed corrective action deadline")
        validate_error(
            api.create_load(
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
            ),
            ApiErrorId.ERR_CONTRACTOR_NOT_COMPLIANT.value,
            422,
        )

        reinstate_carrier(scn, note="corrective action closed")
        assert read_haul_contractor(scn["hc_id"])["compliance_status"] == "COMPLIANT"

        load = dispatch_load(scn)
        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "DISPATCHED"
        assert load_row["haul_contractor_id"] == scn["hc_id"]
        assert read_truck(scn["hc_id"], scn["truck_id"])["status"] == "DISPATCHED"


class TestPhysicalAxisTransitions:
    def test_departing_a_load_that_is_already_in_transit_is_refused(
        self, api, ops_headers
    ):
        """PRD §3.7: "Recording the loaded truck leaving the landing advances the load
        `DISPATCHED → IN_TRANSIT` and stamps `departed_at` with the logical clock; it
        requires that the caller's `X-User-ID` equal the load's `haul_contractor_id`
        and that the truck not derive `OUT_OF_SERVICE`."
        PRD §3.7: "Attempting either while the load is in the wrong `dispatch_status`
        is refused with `ERR_INVALID_LOAD_STATE`."

        Design: Corner/state_machines/departing_an_in_transit_load_a_second_time_returns_invalid_load_state
        """
        scn = build_network()
        load = dispatch_load(scn)
        depart_load(scn, load["id"])

        response = api.depart_load(load["id"], scn["carrier_headers"])
        validate_error(response, ApiErrorId.ERR_INVALID_LOAD_STATE.value, 409)

        assert read_load(load["id"])["dispatch_status"] == "IN_TRANSIT"
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            26.50, abs=0.005
        )

    def test_cancelling_the_only_load_returns_a_filled_contract_to_open(
        self, api, ops_headers
    ):
        """PRD §3.7: "Cancellation moves the load to the terminal `CANCELLED`, causes
        its mill contract to lose the load's `estimated_net_tons` from `reserved_tons`
        and recompute `available_tons`, and returns a `FILLED` contract to `OPEN` when
        the freed tons push the available figure above zero."

        Design: Corner/state_machines/cancelling_the_only_load_returns_a_filled_contract_to_open
        """
        scn = build_network(contract={"quota_tons": 26.5})
        load = dispatch_load(scn)
        assert read_mill_contract(scn["mc_a_id"])["status"] == "FILLED"

        validate_success(
            api.cancel_load(
                load["id"], {"reason": "truck breakdown at the landing"}, ops_headers
            )
        )

        assert read_load(load["id"])["dispatch_status"] == "CANCELLED"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["available_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["status"] == "OPEN"

    def test_a_load_standing_at_the_mill_can_no_longer_be_cancelled(
        self, api, ops_headers
    ):
        """PRD §3.7: "An `OperationsManager` may cancel a load that is still
        `DISPATCHED` or `IN_TRANSIT`, supplying a `reason`; a load that has already
        reached `AT_MILL` or any terminal state cannot be cancelled."
        PRD §2.7: "**Own-resource state.** The status of the resource named in the path
        admits the requested transition: `ERR_INVALID_TRACT_STATE`,
        `ERR_INVALID_LOAD_STATE`, `ERR_INVALID_TICKET_STATE`,
        `ERR_INVALID_STATEMENT_STATE`, `ERR_INVALID_SHUTDOWN_ORDER_STATE`,
        `ERR_INVALID_PLAN_STATE` and `ERR_INVALID_MILL_CONTRACT_STATE` all live on this
        rung."

        Design: Corner/state_machines/cancelling_a_load_that_is_already_at_the_mill_returns_invalid_load_state
        """
        scn = build_network()
        load = load_at_mill(scn)

        response = api.cancel_load(
            load["id"], {"reason": "operator changed their mind"}, ops_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_LOAD_STATE.value, 409)

        assert read_load(load["id"])["dispatch_status"] == "AT_MILL"
        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(26.50, abs=0.005)
        assert contract["available_tons"] == pytest.approx(473.50, abs=0.005)
