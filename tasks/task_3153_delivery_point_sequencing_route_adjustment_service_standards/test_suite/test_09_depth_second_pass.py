"""Second-pass depth tests: rounding boundary, COA axis independence, cascade
internals, recollection re-entry, relief release paths, transfer renumber order."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjustment_in_state,
    approve_auxiliary,
    create_auxiliary,
    create_carrier,
    create_point,
    create_point_payload,
    create_route,
    create_unit,
    create_facility,
    evaluation_consulted,
    evaluation_in_data_collection,
    get_adjustment,
    get_auxiliary,
    get_coa,
    get_evaluation,
    get_point,
    get_route,
    get_success_data,
    list_sequence_entries,
    make_carrier_headers,
    reset_clock,
    set_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    submit_counts_payload,
    validate_error,
    validate_success,
    activate_point,
    create_coa,
)

SUP = TEST_USERS["supervisor_headers"]
PM = TEST_USERS["postmaster_headers"]
CSR = TEST_USERS["csr_headers"]
AMS = TEST_USERS["ams_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

COUNTS = dict(letters_count_total=3600, flats_count_total=900, parcels_count_total=40,
              actual_street_minutes_total=2160, office_minutes_total=1440)


class TestRoundingPinnedOrder:

    def test_nested_rounding_half_up_edges_visible(self, api):
        """PRD §3.6: "Casing minutes are the letters total divided by the casing
        rate of 18 letters per minute, rounded half-up to two decimals, plus the
        flats total divided by the flat casing rate of 8 flats per minute, rounded
        half-up to two decimals."
        PRD §3.6: "The rounding order is fixed: each division rounds to two
        decimals first, then the weighted sum forms, then the final integer
        rounding".

        Design: Difficulty/combinatorial_formula/modeled_street_time_nested_rounding_order_pinned
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="MINI_SURVEY")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        # letters 3033 -> 168.5 exactly (3033/18 = 168.5); flats 901 -> 112.63
        # (112.625 rounds half-up); pull-down 3934/70 = 56.2 exactly; base 100.0.
        # 100.0 + 231.53 * 0.62 + 56.20 = 299.7486 -> 300? No: casing is the SUM
        # 168.50 + 112.63 = 281.13; 281.13 * 0.62 = 174.3006; + 156.20 = 330.5006
        # -> round half-up = 331. Sum-then-round yields 330.
        data = get_success_data(api.submit_counts(
            unit_id, route_id, ev,
            submit_counts_payload(letters_count_total=3033, flats_count_total=901,
                                  parcels_count_total=40,
                                  actual_street_minutes_total=1000,
                                  office_minutes_total=800), SUP))
        assert data["modeled_street_minutes_total"] == 331


class TestCoaAxesIndependence:

    def test_activate_now_while_unverified_fails_cross_entity_state(self, api):
        """PRD §3.9: "activation — automatic when the logical clock reaches the
        `begin_date`, or forced same-day through an explicit activation action —
        requires the order to be `VERIFIED`; activating an unverified order is
        rejected with `ERR_CROSS_ENTITY_STATE`."

        Design: Difficulty/non_linear_state_machine/coa_parallel_dimensions_evolve_independently
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa = create_coa(unit_id, point_id, new_address_line1="99 Palm St",
                         new_city="Tucson", new_state_code="AZ",
                         new_zip11="85701000100", move_kind="FAMILY",
                         move_type="TEMPORARY", begin_date="2026-09-01",
                         end_date="2026-10-01")
        resp = api.activate_coa_now(unit_id, coa["id"], CSR)
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)
        mid = get_coa(unit_id, coa["id"])
        assert mid["forwarding_status"] == "PENDING"
        assert mid["validation_status"] == "UNVERIFIED"


class TestEffectiveCascadeInternals:

    def _transfer_ctx(self, api, proposed=545, effective="2026-09-08"):
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        car_b = create_carrier(unit_id)
        route_b = create_route(unit_id, car_b["id"])
        ctx["route_b"] = route_b
        ctx = evaluation_consulted(ctx, outcome="CONCURRED", counts=COUNTS,
                                   kind="FULL_COUNT")
        ctx = adjustment_in_state(
            ctx, state="APPROVED", proposed_minutes=proposed,
            transfers=[{"delivery_point_id": ctx["points"][1]["id"],
                        "to_route_id": route_b["id"]}],
            effective_date=effective)
        return ctx

    def test_before_effective_date_no_cascade_fires(self, api):
        """PRD §3.7: "Until that cascade fires, an approved adjustment sits in
        `APPROVED` and the route remains under adjustment".

        Design: Difficulty/transitive_cascade/adjustment_effective_cascades_through_points_sequences_evaluation
        """
        ctx = self._transfer_ctx(api)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        set_clock("2026-09-07T00:00:00Z")
        adj = get_adjustment(unit_id, route_id, ctx["evaluation"]["id"],
                             ctx["adjustment"]["id"])
        assert adj["status"] == "APPROVED"
        route = get_route(unit_id, route_id)
        assert route["status"] == "UNDER_ADJUSTMENT"
        assert route["current_evaluated_minutes"] == 480
        p2 = get_point(unit_id, ctx["points"][1]["id"])
        assert p2["active_route_id"] == route_id
        ev = get_evaluation(unit_id, route_id, ctx["evaluation"]["id"])
        assert ev["status"] == "CONSULTED"


class TestSuspendCascadeDetails:

    def test_discontinue_drops_count_and_unblocks_suspend(self, api):
        """PRD §3.4: "On discontinuation, the point's sequence entry is removed
        from its route and the route re-sequenced per the renumber cascade, the
        route's `active_delivery_point_count` is recomputed".
        PRD §3.3: "suspension requires `active_delivery_point_count` to be zero".

        Design: Difficulty/transitive_cascade/route_suspend_cascades_through_auxiliary_relief
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        point = ctx["points"][0]
        get_success_data(api.mark_vacant(unit_id, point["id"],
                                         make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-30T00:00:00Z")
        get_success_data(api.discontinue_point(unit_id, point["id"], AMS))
        route = get_route(unit_id, route_id)
        assert route["active_delivery_point_count"] == 0
        entries = list_sequence_entries(unit_id, route_id)
        assert entries == []
        data = get_success_data(api.suspend_route(unit_id, route_id, PM))
        assert data["status"] == "SUSPENDED"


class TestCoaActivationGate:

    def test_verify_does_not_consume_or_alter_validation_axis(self, api):
        """PRD §3.9: "Validation and forwarding are two independent dimensions."
        PRD §3.9: "activation — automatic when the logical clock reaches the
        `begin_date`, or forced same-day through an explicit activation action —
        requires the order to be `VERIFIED`; activating an unverified order is
        rejected with `ERR_CROSS_ENTITY_STATE`."

        Design: Difficulty/cross_entity_state_dependency/coa_activation_gated_on_validation_dimension
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, point_id = ctx["unit"]["id"], ctx["points"][0]["id"]
        coa = create_coa(unit_id, point_id, move_type="PERMANENT",
                         move_kind="INDIVIDUAL", end_date=None,
                         new_address_line1="1 Desert Rd", new_city="Phoenix",
                         new_state_code="AZ", new_zip11="85001000100")
        get_success_data(api.verify_coa(unit_id, coa["id"], CSR))
        mid = get_coa(unit_id, coa["id"])
        assert mid["validation_status"] == "VERIFIED"
        assert mid["forwarding_status"] == "PENDING"
        data = get_success_data(api.activate_coa_now(unit_id, coa["id"], CSR))
        assert data["forwarding_status"] == "ACTIVE"
        after = get_coa(unit_id, coa["id"])
        assert after["validation_status"] == "VERIFIED"


class TestReliefReleasePaths:

    def test_curtail_releases_relief_same_as_complete(self, api):
        """PRD §3.8: "A `RouteSupervisor` then either completes the assignment
        (`ACTIVE → COMPLETED`) when the work is done or curtails it (`ACTIVE →
        CURTAILED`); both release the accrued relief by subtracting
        `scheduled_minutes` from the route's `auxiliary_relief_minutes`."

        Design: Difficulty/compensating_invariant/auxiliary_relief_minutes_net_zero_after_complete
        """
        set_clock("2026-11-30T00:00:00Z")
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-12-01", 120, seasonal_surge_flag=True)
        approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        set_clock("2026-12-01T00:00:00Z")
        get_success_data(api.curtail_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                                               aux["id"], SUP))
        assert get_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                             aux["id"])["status"] == "CURTAILED"
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 0


class TestTransferRenumberOrder:

    def test_donor_route_renumbers_gapless_after_transfer(self, api):
        """PRD §3.5: "surviving entries are renumbered into a contiguous 1..N
        permutation preserving relative order" and "the donor route is renumbered
        before the receiving route, and within the receiving route incoming points
        are appended in ascending order of their prior line-of-travel position on
        the donor".

        Design: Difficulty/compensating_invariant/point_transfer_preserves_unit_wide_active_point_count
        """
        reset_clock()
        ctx = setup_route_with_active_points(3)
        unit_id, route_a = ctx["unit"]["id"], ctx["route"]
        p1, p2, p3 = ctx["points"]
        car_b = create_carrier(unit_id)
        route_b = create_route(unit_id, car_b["id"])
        ctx = evaluation_consulted(ctx, outcome="CONCURRED", counts=COUNTS,
                                   kind="MINI_SURVEY")
        ctx = adjustment_in_state(
            ctx, state="APPROVED", proposed_minutes=545,
            transfers=[{"delivery_point_id": p2["id"], "to_route_id": route_b["id"]}],
            effective_date="2026-09-08")
        set_clock("2026-09-08T00:00:00Z")
        entries_a = list_sequence_entries(unit_id, route_a["id"])
        # Survivors keep relative order and renumber gaplessly: [P1, P3] at [1, 2].
        assert [e["delivery_point_id"] for e in entries_a] == [p1["id"], p3["id"]]
        assert [e["line_of_travel_order"] for e in entries_a] == [1, 2]
        entries_b = list_sequence_entries(unit_id, route_b["id"])
        assert [e["delivery_point_id"] for e in entries_b] == [p2["id"]]
        assert entries_b[0]["line_of_travel_order"] == 1


class TestDuplicateKeys:

    def test_duplicate_zip11_rejected_system_wide(self, api):
        """PRD §3.4: "an eleven-digit `zip11` delivery-point barcode key that is
        unique system-wide".
        PRD §2.9: "then uniqueness (`ERR_DUPLICATE_KEY`, 409)".

        Design: Corner/validations/duplicate_zip11_rejected
        """
        reset_clock()
        fac = create_facility()
        unit_a = create_unit(fac["id"], code="DU38A")
        unit_b = create_unit(fac["id"], code="DU38B")
        create_point(unit_a["id"], zip11="90230010380")
        resp = api.create_point(
            unit_b["id"],
            create_point_payload("90230010380", address_line1="9 Other St",
                                 city="Venice", point_kind="BUSINESS"), AMS)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)
