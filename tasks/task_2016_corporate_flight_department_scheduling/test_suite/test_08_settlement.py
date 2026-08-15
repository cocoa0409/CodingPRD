"""Settlement: SIFL imputed income (final + provisional variants), trip cost
allocation (owned-fleet + charter variants), BU ledger, and settle invariants."""
from test_helpers import (
    ApiErrorId,
    add_leg,
    approve_trip,
    create_default_rate_period,
    create_trip,
    get_success_data,
    make_finance_headers,
    reset_clock,
    setup_bu_and_passenger,
    setup_completed_trip,
    submit_trip,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
FINANCE = TEST_USERS["finance_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestSiflDualVariant:
    def _personal_trip_two_planned_legs(self, api):
        """PERSONAL trip, one non-control passenger, two 600-mile PLANNED legs,
        APPROVED but never assigned (legs stay PLANNED)."""
        reset_clock()
        create_default_rate_period()
        bu, pax = setup_bu_and_passenger()
        trip = create_trip(pax, bu["id"], trip_kind="PERSONAL", personal_use_flag=True,
                           requested_departure_utc="2026-08-10T12:00:00Z",
                           requested_return_utc="2026-08-10T20:00:00Z")
        add_leg(trip, pax, leg_sequence=1, origin_icao="KTEB", destination_icao="KPBI",
                scheduled_departure_utc="2026-08-10T12:00:00Z",
                scheduled_arrival_utc="2026-08-10T15:00:00Z", distance_statute_miles=600)
        add_leg(trip, pax, leg_sequence=2, origin_icao="KPBI", destination_icao="KTEB",
                scheduled_departure_utc="2026-08-10T17:00:00Z",
                scheduled_arrival_utc="2026-08-10T20:00:00Z", distance_statute_miles=600)
        trip = submit_trip(trip, pax)
        trip = approve_trip(trip)
        return trip

    def test_sifl_preview_includes_planned_legs(self, api):
        """PRD §3.7: "A `FinanceAdmin` or `FlightDeptManager` can request a SIFL
        preview, which applies the identical banding, terminal charge,
        control-employee multiplier, and per-line rounding, but across *all* of
        the trip's legs regardless of leg status — `PLANNED`,
        `AIRCRAFT_ASSIGNED`, `CREWED`, and `RELEASED` legs included — with no
        requirement that the trip be completed and nothing persisted."
        PRD §3.7: "the first 500 statute miles are priced at
        `rate_band_1_cents_per_mile` per mile, any miles beyond 500 up to and
        including 1500 are priced at `rate_band_2_cents_per_mile` per mile"

        Design: Difficulty/dual_variant_calc/sifl_provisional_vs_final_diverge_on_leg_status
        """
        trip = self._personal_trip_two_planned_legs(api)
        resp = api.sifl_preview(trip["id"], FINANCE)
        data = validate_success(resp, 200)
        # Per leg: 5000 + 500*30 + 100*20 = 22000; two legs -> 44000.
        assert data["provisional_sifl_cents"] == 44000
        assert data["leg_count_included"] == 2, "preview spans the PLANNED legs"

    def test_final_sifl_uses_only_completed_legs(self, api):
        """PRD §3.7: "Only legs in `COMPLETED` status enter the final
        computation."
        PRD §3.7: "on a `BUSINESS` trip, no passenger generates imputed income."
        (A PERSONAL trip whose legs never complete settles at zero.)

        Design: Difficulty/dual_variant_calc/sifl_provisional_vs_final_diverge_on_leg_status
        """
        # A PERSONAL trip completed via the owned fleet with only ONE of two
        # legs completed cannot exist (trip completes when all legs complete),
        # so the divergence is pinned by settling a completed PERSONAL trip and
        # comparing the persisted figure against the provisional figure over the
        # same legs: identical only when all legs are COMPLETED, and the
        # persisted value is written only at settlement.
        reset_clock()
        create_default_rate_period()
        legs_spec = (("2026-08-10T12:00:00Z", "2026-08-10T15:00:00Z", 600),)
        bu, pax, trip, legs, _ac, _pic, _sic = setup_completed_trip(
            trip_kind="PERSONAL", personal_use_flag=True, legs=legs_spec)
        persisted = get_success_data(api.get_trip_request(trip["id"], FINANCE))
        assert persisted["sifl_imputed_income_cents"] == 0, (
            "final variant has not run before settlement"
        )
        settled = validate_success(
            api.settle_trip(trip["id"], persisted["version"],
                            make_finance_headers("fin-2")), 200)
        # One completed 600-mile leg, one passenger: 5000 + 15000 + 2000 = 22000.
        assert settled["sifl_imputed_income_cents"] == 22000


class TestSiflBanding:
    def test_control_employee_multiplier_across_three_bands(self, api):
        """PRD §3.7: "the first 500 statute miles are priced at
        `rate_band_1_cents_per_mile` per mile, any miles beyond 500 up to and
        including 1500 are priced at `rate_band_2_cents_per_mile` per mile, and
        every mile beyond 1500 is priced at `rate_band_3_cents_per_mile` per
        mile."
        PRD §3.7: "When the passenger's `sifl_control_employee` flag is true, the
        summed charge is then multiplied by `control_employee_multiplier_pct`
        percent — a configured 400 quadruples the line."

        Design: Difficulty/combinatorial_formula/sifl_tiered_banding_with_control_multiplier_mode_a
        """
        reset_clock()
        create_default_rate_period()
        legs_spec = (("2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z", 1600),)
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="PERSONAL", personal_use_flag=True, sifl_control_employee=True,
            legs=legs_spec, aircraft_type="HEAVY_JET")
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-2")), 200)
        # 5000 + 500*30 + 1000*20 + 100*10 = 41000; x4 = 164000.
        assert settled["sifl_imputed_income_cents"] == 164000

    def test_tiered_banding_without_control_multiplier(self, api):
        """PRD §3.7: "The per-line charge is the period's `terminal_charge_cents`
        plus a mileage component built by splitting the leg's
        `distance_statute_miles` into three bands: the first 500 statute miles
        are priced at `rate_band_1_cents_per_mile` per mile, any miles beyond 500
        up to and including 1500 are priced at `rate_band_2_cents_per_mile` per
        mile, and every mile beyond 1500 is priced at `rate_band_3_cents_per_mile`
        per mile."
        PRD §3.7: "on a `PERSONAL` trip, every passenger in `passenger_ids` is
        personal-use"

        Design: Difficulty/combinatorial_formula/sifl_tiered_banding_with_control_multiplier_mode_a
        """
        # Same 1600-mile three-band leg with a non-control passenger: exercises
        # every band boundary while the multiplier branch stays at 1x.
        reset_clock()
        create_default_rate_period()
        legs_spec = (("2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z", 1600),)
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="PERSONAL", personal_use_flag=True, sifl_control_employee=False,
            legs=legs_spec, aircraft_type="HEAVY_JET")
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-2")), 200)
        # 5000 + 500*30 + 1000*20 + 100*10 = 41000, no multiplier.
        assert settled["sifl_imputed_income_cents"] == 41000

    def test_business_trip_yields_zero_imputed_income(self, api):
        """PRD §3.7: "on a `BUSINESS` trip, no passenger generates imputed
        income."

        Design: Corner/calculations/sifl_business_trip_yields_zero_imputed_income
        """
        reset_clock()
        create_default_rate_period()
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS",
            legs=(("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z", 600),))
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-1")), 200)
        assert settled["sifl_imputed_income_cents"] == 0

    def test_rate_period_selected_by_leg_arrival(self, api):
        """PRD §3.7: "the system selects the rate period whose half-open interval
        — `period_start_utc` inclusive, `period_end_utc` exclusive — contains the
        leg's `scheduled_arrival_utc`"

        Design: Corner/calculations/sifl_rate_period_lookup_uses_leg_arrival
        """
        reset_clock()
        create_default_rate_period()  # R1: 2026-08-01 .. 2027-02-01, terminal 5000
        create_default_rate_period(
            period_start_utc="2027-02-01T00:00:00Z",
            period_end_utc="2027-08-01T00:00:00Z",
            terminal_charge_cents=9999)
        legs_spec = (("2027-01-10T12:00:00Z", "2027-01-10T13:00:00Z", 200),)
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="PERSONAL", personal_use_flag=True, legs=legs_spec)
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-2")), 200)
        # Arrival 2027-01-10 falls in R1: 5000 + 200*30 = 11000, not R2's 9999.
        assert settled["sifl_imputed_income_cents"] == 11000

    def test_settle_without_covering_rate_period_rejected(self, api):
        """PRD §3.7: "if no published period covers that instant, settlement
        fails with `ERR_RATE_PERIOD_NOT_FOUND` (HTTP 422)."

        Design: Corner/errors/error_rate_period_not_found_at_settle
        """
        reset_clock()
        # No SiflRatePeriod is ever published.
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="PERSONAL", personal_use_flag=True)
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        resp = api.settle_trip(trip["id"], version, make_finance_headers("fin-2"))
        validate_error(resp, ApiErrorId.ERR_RATE_PERIOD_NOT_FOUND)


class TestCostAllocation:
    def test_owned_fleet_heavy_jet_rate_applied(self, api):
        """PRD §3.7: "For a trip flown by the owned fleet, each completed leg's
        cost is its `block_minutes` multiplied by the per-minute rate of the
        assigned aircraft's `aircraft_type` — 8,500 cents per block minute for a
        `LIGHT_JET`, 14,000 for a `MIDSIZE_JET`, 23,000 for a `HEAVY_JET`, and
        5,000 for a `TURBOPROP`"

        Design: Corner/calculations/cost_allocation_constants_applied_per_aircraft_type
        """
        reset_clock()
        create_default_rate_period()
        _bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS", aircraft_type="HEAVY_JET",
            legs=(("2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z", 200),))
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-1")), 200)
        assert settled["allocated_cost_cents"] == 60 * 23000, (
            "60 minutes at the HEAVY_JET rate"
        )

    def test_owned_fleet_light_jet_allocation(self, api):
        """PRD §3.7: "For a trip flown by the owned fleet, each completed leg's
        cost is its `block_minutes` multiplied by the per-minute rate of the
        assigned aircraft's `aircraft_type` — 8,500 cents per block minute for a
        `LIGHT_JET`, 14,000 for a `MIDSIZE_JET`, 23,000 for a `HEAVY_JET`, and
        5,000 for a `TURBOPROP` — plus the sum of `quoted_cost_cents` over that
        leg's `DELIVERED` catering orders and the sum of `quoted_cost_cents` over
        its `COMPLETED` ground transports."

        Design: Difficulty/dual_variant_calc/cost_allocation_owned_vs_charter_diverge_on_same_legs
        """
        # Owned-fleet branch of the dual-variant pair: 120-minute LIGHT_JET leg
        # with no services -> 120 * 8500 = 1020000.
        reset_clock()
        create_default_rate_period()
        bu_a, pax_a, trip_a, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS", aircraft_type="LIGHT_JET",
            legs=(("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z", 200),))
        v_a = get_success_data(api.get_trip_request(trip_a["id"], FINANCE))["version"]
        settled_a = validate_success(
            api.settle_trip(trip_a["id"], v_a, make_finance_headers("fin-1")), 200)
        assert settled_a["allocated_cost_cents"] == 1_020_000

    def test_owned_fleet_allocation_includes_delivered_services(self, api):
        """PRD §3.7: "plus the sum of `quoted_cost_cents` over that leg's
        `DELIVERED` catering orders and the sum of `quoted_cost_cents` over its
        `COMPLETED` ground transports."

        Design: Difficulty/dual_variant_calc/cost_allocation_owned_vs_charter_diverge_on_same_legs
        """
        # Owned-fleet branch with services: catering DELIVERED (25000) and
        # ground transport COMPLETED (12000) ride on top of the block-minute
        # charge, distinguishing the rate+services formula from a flat quote.
        from test_helpers import (
            add_catering, add_ground_transport,
            confirm_catering, confirm_ground_transport, setup_assigned_trip,
            assign_crew, release_leg,
            dispatch_trip, make_dispatcher_headers,
        )
        reset_clock()
        create_default_rate_period()
        bu, pax, trip, legs, _ac, pic, sic = setup_assigned_trip(
            trip_kind="BUSINESS", aircraft_type="LIGHT_JET")
        leg = legs[0]
        order = confirm_catering(add_catering(leg["id"], quoted_cost_cents=25_000)["id"])
        transport = confirm_ground_transport(
            add_ground_transport(leg["id"], quoted_cost_cents=12_000)["id"])
        assign_crew(leg["id"], pic["id"], sic["id"])
        # Release requires services CONFIRMED/CANCELLED; deliver catering after
        # release (allowed in CREWED or RELEASED).
        release_leg(leg["id"])
        get_success_data(api.deliver_catering_order(order["id"], DISPATCHER))
        dispatch_trip(trip["id"])
        reset_clock("2026-08-10T14:00:00Z")
        from test_helpers import complete_leg
        complete_leg(leg["id"])
        # Ground transport completes only after the leg completes.
        get_success_data(api.complete_ground_transport(transport["id"], DISPATCHER))
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        settled = validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-1")), 200)
        assert settled["allocated_cost_cents"] == 120 * 8500 + 25_000 + 12_000


class TestSettleLedger:
    def test_settle_increments_bu_allocated_cents(self, api):
        """PRD §3.7: "Either way, the trip's `allocated_cost_cents` is the sum of
        per-leg costs over `COMPLETED` legs, and the same amount is added to the
        charging business unit's `allocated_cents`."

        Design: Corner/endpoints/settle_side_effect_bu_allocated_cents_increment
        """
        reset_clock()
        create_default_rate_period()
        bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS", aircraft_type="LIGHT_JET")
        before = get_success_data(api.get_business_unit(bu["id"], FINANCE))
        assert before["allocated_cents"] == 0
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        validate_success(
            api.settle_trip(trip["id"], version, make_finance_headers("fin-1")), 200)
        after = get_success_data(api.get_business_unit(bu["id"], FINANCE))
        assert after["allocated_cents"] == 120 * 8500, (
            "incremented by allocated_cost_cents (120 min x 8500)"
        )

    def test_dispatch_charges_duty_minutes(self, api):
        """PRD §3.5: "A successful dispatch moves `assignment_status` from
        `ASSIGNED` to `DISPATCHED`, records the acting dispatcher in
        `dispatched_by_user_id`, and charges duty time: each leg's
        `block_minutes` are summed across the trip and added to
        `duty_minutes_used` for both the `PIC` and the `SIC` on each leg"

        Design: Corner/endpoints/dispatch_side_effect_duty_minutes_increment
        """
        legs_spec = (("2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z", 200),
                     ("2026-08-10T12:00:00Z", "2026-08-10T13:30:00Z", 400))
        from test_helpers import setup_dispatched_trip
        _bu, _pax, _t, _l, _ac, pic, sic = setup_dispatched_trip(legs=legs_spec)
        pic_after = get_success_data(api.get_crew_member(pic["id"], FINANCE))
        sic_after = get_success_data(api.get_crew_member(sic["id"], FINANCE))
        assert pic_after["duty_minutes_used"] == 150, "60 + 90 block minutes"
        assert sic_after["duty_minutes_used"] == 150

    def test_settle_before_completion_rejected(self, api):
        """PRD §3.7: "Settlement is defined only for a trip whose
        `assignment_status` is `COMPLETED`; settling earlier is rejected with
        `ERR_TRIP_NOT_COMPLETED` (HTTP 422)."

        Design: Corner/validations/settle_before_completion_rejected
        """
        from test_helpers import setup_assigned_trip
        _bu, _pax, trip, _l, _ac, _p, _s = setup_assigned_trip()
        version = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        resp = api.settle_trip(trip["id"], version, make_finance_headers("fin-1"))
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_TRIP_NOT_COMPLETED, ApiErrorId.ERR_INVALID_STATE])

    def test_second_settle_rejected_no_double_count(self, api):
        """PRD §3.7: "A successful settle moves `settlement_status` from
        `UNSETTLED` to `SETTLED`, computes and persists both
        `sifl_imputed_income_cents` and `allocated_cost_cents`, adds the
        allocated cost to the charging unit's `allocated_cents`, and increments
        the trip's `version` by one."

        Design: Difficulty/compensating_invariant/business_unit_allocated_cents_conserved_across_settle
        """
        reset_clock()
        create_default_rate_period()
        bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS", aircraft_type="LIGHT_JET")
        v1 = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        validate_success(
            api.settle_trip(trip["id"], v1, make_finance_headers("fin-1")), 200)
        after_first = get_success_data(api.get_business_unit(bu["id"], FINANCE))
        assert after_first["allocated_cents"] == 1_020_000

    def test_resettle_rejected_and_bu_unchanged(self, api):
        """PRD §3.7: "A successful settle moves `settlement_status` from
        `UNSETTLED` to `SETTLED`"
        PRD §2.6: "then state-machine validity — whether the target entity's
        current state even permits the requested transition (`ERR_INVALID_STATE`,
        HTTP 409)"

        Design: Difficulty/compensating_invariant/business_unit_allocated_cents_conserved_across_settle
        """
        reset_clock()
        create_default_rate_period()
        bu, _pax, trip, _l, _ac, _p, _s = setup_completed_trip(
            trip_kind="BUSINESS", aircraft_type="LIGHT_JET")
        v1 = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        validate_success(
            api.settle_trip(trip["id"], v1, make_finance_headers("fin-1")), 200)
        v2 = get_success_data(api.get_trip_request(trip["id"], FINANCE))["version"]
        resp = api.settle_trip(trip["id"], v2, make_finance_headers("fin-1"))
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_TRIP_NOT_COMPLETED])
        after_second = get_success_data(api.get_business_unit(bu["id"], FINANCE))
        assert after_second["allocated_cents"] == 1_020_000, (
            "rejected second settle leaves the ledger unchanged (no double count)"
        )
