"""Fleet, routes, batches, and production (PRD sections 3.2/3.3/3.5)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_batch_payload,
    create_beef_delivery_payload,
    create_open_store_with_manager,
    create_operational_commissary,
    create_production_run_payload,
    create_route_payload,
    create_shift_payload,
    create_truck_payload,
    get_success_data,
    hr_poster_headers,
    planner_headers,
    real_estate_headers,
    receive_beef,
    scd_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestNotFound:
    def test_truck_get_unknown_id_returns_not_found(self, api):
        """PRD section 2.5: "4. **Path existence** — every identifier in the
        URL path exists, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/truck_get_unknown_id_returns_not_found
        """
        set_clock()
        resp = api.get_truck(NON_EXISTENT_UUID, planner_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404


class TestBeefReceivingBoundaries:
    def test_cold_chain_exactly_at_limit_accepted(self, api):
        """PRD section 3.3: "Confirming receipt enforces the cold chain:
        `transit_temp_celsius` must be less than or equal to 4.0 degrees; any
        strictly greater reading is rejected with `ERR_COLD_CHAIN_VIOLATION`
        (HTTP 422) and the shipment cannot be received. A successful
        confirmation moves the delivery to `RECEIVED` and credits the
        commissary's `raw_beef_lbs_on_hand` by the delivery's `raw_beef_lbs`"

        Design: Difficulty/boundary_precision_check/cold_chain_exactly_at_limit_accepted
        """
        set_clock()
        env = create_operational_commissary()
        bd_ok = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=500,
                                         transit_temp_celsius=4.0),
            planner_headers()))
        bd_hot = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=500,
                                         transit_temp_celsius=4.1,
                                         shipped_at="2026-09-01T07:00:00Z"),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd_ok["id"], planner_headers()))
        get_success_data(api.ship_beef_delivery(bd_hot["id"], planner_headers()))
        received = validate_success(api.confirm_receiving(
            bd_ok["id"], planner_headers()))
        assert received["status"] == "RECEIVED"
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["raw_beef_lbs_on_hand"] == 500
        resp = api.confirm_receiving(bd_hot["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_VIOLATION)
        assert resp.status_code == 422

    def test_state_beats_cold_chain_safety(self, api):
        """PRD section 2.5: "8. **State preconditions** — the target entity is
        in a state that permits the transition"
        PRD section 2.5: "9. **Business safety, then referential, then
        temporal, then fiscal rules, then remaining business constraints** —
        cold-chain and audit-freshness checks (`ERR_COLD_CHAIN_VIOLATION`,
        `ERR_SUPPLIER_AUDIT_STALE`) precede supplier-approval and cross-entity
        linkage checks"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_cold_chain_safety
        """
        set_clock()
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         raw_beef_lbs=500,
                                         transit_temp_celsius=9.0),
            planner_headers()))
        # Never shipped: still SCHEDULED, so the state tier fires before the
        # cold-chain safety tier even though 9.0 would violate it.
        resp = api.confirm_receiving(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE)
        assert resp.status_code == 409
        delivery = get_success_data(api.get_beef_delivery(bd["id"], planner_headers()))
        assert delivery["status"] == "SCHEDULED"

    def test_ship_already_in_transit_returns_invalid_state(self, api):
        """PRD section 3.3: "A scheduled delivery moves from `SCHEDULED` to
        `IN_TRANSIT` when shipped — allowed only while the supplier is
        `APPROVED` and audit-fresh"
        PRD section 3.3: "Wrong-state delivery actions are rejected with
        `ERR_DELIVERY_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_cold_chain_safety
        """
        # Companion state-gate observation on the same endpoint family: an
        # already IN_TRANSIT delivery cannot be shipped again, even though
        # its recorded transit temperature is cold-compliant.
        set_clock()
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         transit_temp_celsius=2.0),
            planner_headers()))
        get_success_data(api.ship_beef_delivery(bd["id"], planner_headers()))
        resp = api.ship_beef_delivery(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_DELIVERY_INVALID_STATE)
        assert resp.status_code == 409
        delivery = get_success_data(api.get_beef_delivery(bd["id"], planner_headers()))
        assert delivery["status"] == "IN_TRANSIT"


    def test_ship_blocked_once_audit_goes_stale(self, api):
        """PRD section 3.1: "a supplier is eligible only while it is
        `APPROVED` **and** that day count is less than or equal to its
        `audit_frequency_days`."
        PRD section 3.3: "A scheduled delivery moves from `SCHEDULED` to
        `IN_TRANSIT` when shipped — allowed only while the supplier is
        `APPROVED` and audit-fresh"

        Design: Difficulty/boundary_precision_check/cold_chain_exactly_at_limit_accepted
        """
        # Companion coverage of the same freshness rule at the dispatch end:
        # a cold-compliant delivery still cannot ship once the audit is
        # stale, and the freshness gate (not the cold-chain gate) fires.
        set_clock("2026-09-01T00:00:00Z")
        env = create_operational_commissary()
        bd = get_success_data(api.create_beef_delivery(
            create_beef_delivery_payload(env["commissary"]["id"],
                                         env["supplier"]["id"],
                                         transit_temp_celsius=4.0),
            planner_headers()))
        set_clock("2026-10-02T00:00:00Z")
        resp = api.ship_beef_delivery(bd["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_SUPPLIER_AUDIT_STALE)
        assert resp.status_code == 422


class TestTruckRouteWindowCommitment:
    def test_truck_day_commitment_disjoint_dates(self, api):
        """PRD section 3.5: "temporal exclusivity must hold, so the truck may
        not already be committed to another `FINALIZED` route on the same
        `service_date`, nor may any store on the stop list already be visited
        by another `FINALIZED` route that day — routes on adjacent days never
        conflict — with violations rejected as `ERR_ROUTE_WINDOW_CONFLICT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/truck_day_commitment_disjoint_dates
        """
        env = create_open_store_with_manager()
        com = env["commissary"]
        store = env["store"]
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(plate="TRK-RT2"),
            planner_headers()))
        route1 = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-03T00:00:00Z", [store["id"]]),
            planner_headers()))
        get_success_data(api.finalize_route(route1["id"], planner_headers()))
        route2 = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-03T00:00:00Z", [store["id"]]),
            planner_headers()))
        route3 = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-04T00:00:00Z", [store["id"]]),
            planner_headers()))
        resp = api.finalize_route(route2["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT)
        assert resp.status_code == 422
        finalized = validate_success(api.finalize_route(route3["id"], planner_headers()))
        assert finalized["status"] == "FINALIZED"

    def test_adjacent_day_routes_for_same_truck_both_finalize(self, api):
        """PRD section 3.5: "routes on adjacent days never conflict"

        Design: Difficulty/resource_temporal_overlap/truck_day_commitment_disjoint_dates
        """
        env = create_open_store_with_manager()
        com = env["commissary"]
        store = env["store"]
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(), planner_headers()))
        routes = []
        for date in ("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z"):
            route = get_success_data(api.create_route(
                create_route_payload(com["id"], truck["id"], date,
                                     [store["id"]]),
                planner_headers()))
            finalized = validate_success(api.finalize_route(
                route["id"], planner_headers()))
            assert finalized["status"] == "FINALIZED"
            routes.append(finalized["id"])
        assert len(set(routes)) == 2


class TestRouteCompletion:
    def test_route_complete_requires_all_batches_delivered(self, api):
        """PRD section 3.5: "Completing a route requires it to be `FINALIZED`
        and every batch riding it to be `DELIVERED`
        (`ERR_BATCHES_NOT_DELIVERED` otherwise), moving it to `COMPLETED`."

        Design: Corner/endpoints/route_complete_requires_all_batches_delivered
        """
        # A FINALIZED route carrying one LOADED (not yet delivered) batch.
        env2 = create_open_store_with_manager()
        com = env2["commissary"]
        store = env2["store"]
        store_v = get_success_data(api.get_store(store["id"], planner_headers()))["version"]
        batch = get_success_data(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-02T00:00:00Z"),
            planner_headers()))
        run = get_success_data(api.create_production_run(
            com["id"], create_production_run_payload(), planner_headers()))
        get_success_data(api.complete_production_run(run["id"], planner_headers()))
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(), planner_headers()))
        route = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-02T00:00:00Z", [store["id"]]),
            planner_headers()))
        get_success_data(api.load_batch(
            batch["id"], {"production_run_id": run["id"],
                          "route_id": route["id"]}, planner_headers()))
        get_success_data(api.finalize_route(route["id"], planner_headers()))
        resp = api.complete_route(route["id"], planner_headers())
        validate_error(resp, ApiErrorId.ERR_BATCHES_NOT_DELIVERED)
        assert resp.status_code == 409
        get_success_data(api.deliver_batch(batch["id"], planner_headers()))
        completed = validate_success(api.complete_route(route["id"], planner_headers()))
        assert completed["status"] == "COMPLETED"


class TestCommissaryDecommissionCascade:
    def test_commissary_decommission_cascades_trucks_and_routes(self, api):
        """PRD section 3.2: "it cascades by retiring every `ACTIVE` truck of
        the commissary to `INACTIVE` and cancelling every `DRAFT` route of
        the commissary (routes already `FINALIZED` or `COMPLETED` are
        untouched), and it too recomputes `regional_entry_open` to false."
        PRD section 3.2: "Decommissioning moves `OPERATIONAL` to the terminal
        `DECOMMISSIONED` state and is permitted only when every store
        supplied by the commissary is already `CLOSED`"

        Design: Corner/endpoints/commissary_decommission_cascades_trucks_and_routes
        """
        env = create_open_store_with_manager()
        com = env["commissary"]
        store = env["store"]
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(plate="TRK-E2"), planner_headers()))
        route = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-05T00:00:00Z", []),
            planner_headers()))
        get_success_data(api.close_store(store["id"], real_estate_headers()))
        decommissioned = validate_success(api.decommission_commissary(
            com["id"], scd_headers()))
        assert decommissioned["status"] == "DECOMMISSIONED"
        truck_after = get_success_data(api.get_truck(truck["id"], planner_headers()))
        assert truck_after["status"] == "INACTIVE"
        route_after = get_success_data(api.get_route(route["id"], planner_headers()))
        assert route_after["status"] == "CANCELLED"


class TestProductionRunLedger:
    def test_plan_cancel_restores_raw_beef(self, api):
        """PRD section 3.2: "The raw-beef ledger on the commissary is
        conserved: `raw_beef_lbs_on_hand` is credited when a beef delivery's
        receipt is confirmed and debited when a production run is planned,
        and a cancelled production run restores its debit exactly. Nothing
        else may move this balance."
        PRD section 3.3: "That requirement is recorded on the run as
        `beef_lbs_required`: the planned patties divided by the standard
        patties-per-pound yield, rounded up to a whole pound."

        Design: Difficulty/compensating_invariant/run_plan_cancel_restores_beef
        """
        set_clock()
        env = create_operational_commissary()
        receive_beef(env["commissary"], env["supplier"], raw_beef_lbs=500)
        run = get_success_data(api.create_production_run(
            env["commissary"]["id"],
            create_production_run_payload(patties_planned=1000,
                                          buns_planned=100,
                                          produce_units_planned=100,
                                          run_date="2026-09-02T00:00:00Z"),
            planner_headers()))
        # Reference rounding: with the standard yield, 1000 patties round up
        # to 334 whole pounds (999 would divide evenly; 1000 needs one more).
        assert run["beef_lbs_required"] == 334
        mid = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert mid["raw_beef_lbs_on_hand"] == 500 - 334
        cancelled = validate_success(api.cancel_production_run(
            run["id"], planner_headers()))
        assert cancelled["status"] == "CANCELLED"
        final = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert final["raw_beef_lbs_on_hand"] == 500

    def test_planning_debits_whole_pounds_rounded_up(self, api):
        """PRD section 3.3: "That requirement is recorded on the run as
        `beef_lbs_required`: the planned patties divided by the standard
        patties-per-pound yield, rounded up to a whole pound. Planning a run
        immediately debits `beef_lbs_required` from the commissary's raw-beef
        ledger and increments the commissary's `version`."

        Design: Corner/calculations/production_run_beef_requirement_ceil
        """
        set_clock()
        env = create_operational_commissary()
        receive_beef(env["commissary"], env["supplier"], raw_beef_lbs=500)
        run = get_success_data(api.create_production_run(
            env["commissary"]["id"],
            create_production_run_payload(patties_planned=1000,
                                          buns_planned=50,
                                          produce_units_planned=13,
                                          run_date="2026-09-02T00:00:00Z"),
            planner_headers()))
        assert run["beef_lbs_required"] == 334
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["raw_beef_lbs_on_hand"] == 166


    def test_planning_debit_blocks_runs_beyond_remaining_beef(self, api):
        """PRD section 3.3: "Four capacity gates guard planning, all
        surfacing `ERR_CAPACITY_EXCEEDED` (HTTP 422): planned patties may not
        exceed `daily_patty_capacity`, planned buns may not exceed
        `daily_bun_capacity`, planned produce may not exceed
        `daily_produce_capacity`, and the run's raw-beef requirement may not
        exceed the commissary's `raw_beef_lbs_on_hand`."

        Design: Difficulty/compensating_invariant/run_plan_cancel_restores_beef
        """
        # Companion ledger observation: the debit is what makes a second,
        # oversized run fail the raw-beef capacity gate.
        set_clock()
        env = create_operational_commissary()
        receive_beef(env["commissary"], env["supplier"], raw_beef_lbs=500)
        get_success_data(api.create_production_run(
            env["commissary"]["id"],
            create_production_run_payload(patties_planned=1000,
                                          buns_planned=100,
                                          produce_units_planned=100,
                                          run_date="2026-09-02T00:00:00Z"),
            planner_headers()))
        com = get_success_data(api.get_commissary(
            env["commissary"]["id"], scd_headers()))
        assert com["raw_beef_lbs_on_hand"] == 166
        resp = api.create_production_run(
            env["commissary"]["id"],
            create_production_run_payload(patties_planned=1000,
                                          buns_planned=10,
                                          produce_units_planned=10,
                                          run_date="2026-09-03T00:00:00Z"),
            planner_headers())
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        assert resp.status_code == 422


class TestStoreCloseCascade:
    def test_store_close_cascades_batches_routes_shifts(self, api):
        """PRD section 3.4: "A successful close cascades: every `PLANNED`
        delivery batch of the store moves to `CANCELLED` (loaded or delivered
        batches are untouched); every delivery route listing the store in its
        `store_ids` that is `DRAFT` or `FINALIZED` moves to `CANCELLED`, each
        cancelled route's `version` incrementing; and every `SCHEDULED` shift
        assignment of the store moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/store_close_cascades_batches_routes_shifts
        """
        env = create_open_store_with_manager()
        com = env["commissary"]
        store = env["store"]
        store_v = get_success_data(api.get_store(store["id"], planner_headers()))["version"]
        batch = get_success_data(api.create_batch(
            create_batch_payload(store["id"], store_v, "2026-09-03T00:00:00Z",
                                 patty_count=100, bun_count=60,
                                 produce_units=60),
            planner_headers()))
        truck = get_success_data(api.create_truck(
            com["id"], create_truck_payload(plate="TRK-TC1"), planner_headers()))
        route = get_success_data(api.create_route(
            create_route_payload(com["id"], truck["id"],
                                 "2026-09-03T00:00:00Z", [store["id"]]),
            planner_headers()))
        get_success_data(api.finalize_route(route["id"], planner_headers()))
        closed = validate_success(api.close_store(store["id"], real_estate_headers()))
        assert closed["status"] == "CLOSED"
        batch_after = get_success_data(api.get_batch(batch["id"], planner_headers()))
        assert batch_after["status"] == "CANCELLED"
        route_after = get_success_data(api.get_route(route["id"], planner_headers()))
        assert route_after["status"] == "CANCELLED"

    def test_store_close_cancels_scheduled_shifts(self, api):
        """PRD section 3.4: "every `SCHEDULED` shift assignment of the store
        moves to `CANCELLED`."
        PRD section 3.4: "Closing a store — a `RealEstatePlanner` action from
        `OPEN` to the terminal `CLOSED` — is blocked while any shift of the
        store remains `SCHEDULED` with a `shift_end` later than the logical
        clock (`ERR_OPEN_SHIFTS_EXIST`, HTTP 409)."

        Design: Difficulty/transitive_cascade/store_close_cascades_batches_routes_shifts
        """
        env = create_open_store_with_manager()
        store = env["store"]
        # A shift that ended in the past relative to the close clock — past
        # shifts do not block closing.
        past = get_success_data(api.create_shift(
            store["id"],
            create_shift_payload(env["manager"]["id"],
                                 "2026-08-31T16:00:00Z", "2026-08-31T23:00:00Z"),
            hr_poster_headers()))
        assert past["status"] == "SCHEDULED"
        closed = validate_success(api.close_store(store["id"], real_estate_headers()))
        assert closed["status"] == "CLOSED"
        shift_after = get_success_data(api.get_shift(past["id"], hr_poster_headers()))
        assert shift_after["status"] == "CANCELLED"
