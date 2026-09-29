"""Field failure determinations and erection crews: the recall chain, the crew
gate ladder, the tier envelope, the decertification cascade and the logical clock."""

import pytest
from test_helpers import (
    ADMIN,
    assert_detached_order,
    assert_empty_load_totals,
    assert_instant_equals,
    assert_no_such_field,
    assert_version_advanced_by,
    assign_crew,
    assign_crew_payload,
    attach_order,
    cancel_order,
    create_design,
    create_design_under_review,
    determine_failure,
    drive_failure_to_determination,
    open_field_failure,
    place_confirmed_order,
    place_order,
    plan_freight_load,
    read_crew,
    read_dealer,
    read_design,
    read_failure,
    read_load,
    read_order,
    register_crew,
    set_clock,
    set_clock_payload,
    setup_crew_conflict_pair,
    setup_recall_cascade_chain,
    setup_reference_data,
    start_failure_analysis,
    validate_error,
    validate_success,
)


class TestStructuralUnderdesignRecallChain:
    def test_the_four_hops_run_from_one_determination_and_empty_the_trailer(self, api):
        """PRD §3.9: "Third, a `SIDEWALL_BUCKLE` or a `ROOF_COLLAPSE` yields
        `STRUCTURAL_UNDERDESIGN` when the `structural_verdict` is `WITHIN_DESIGN` — the bin failed
        under a load the design claimed to carry, so the design is at fault — and `OVERLOAD_MISUSE`
        when the verdict is `EXCEEDS_DESIGN`, since the operator loaded it beyond what was sold."
        PRD §3.9: "`STRUCTURAL_UNDERDESIGN` recalls the design: a design in `SEALED` or in
        `UNDER_REVIEW` moves to `RECALLED`, which is the first hop."
        PRD §3.9: "The second hop, caused by the design entering `RECALLED`, moves every order against
        that design whose `production_status` is `QUEUED` or `KITTED` into `HOLD_ENGINEERING`."
        PRD §3.9: "The fourth hop cancels any load left with `order_count` 0."
        PRD §3.8: "When the attached set is empty the load charges nothing: `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` are all
        0, and the trailer's base linehaul is explicitly **not** charged to a load carrying nothing."

        Design: Difficulty/transitive_cascade/structural_underdesign_determination_cascades_design_recall_to_order_hold_to_load_detach_to_load_cancel
        """
        env = setup_recall_cascade_chain()
        ref, design, order, load = env["ref"], env["design"], env["order"], env["load"]
        opened = read_failure(env["failure"]["id"])
        # 20.0 is not strictly above the governing demand 28.518, and 10.0 is not
        # strictly above the C3 loss limit 40.0.
        assert opened["structural_verdict"] == "WITHIN_DESIGN"
        assert opened["corrosion_verdict"] == "WITHIN_CLASS"
        assert read_design(design["id"])["governing_demand_kpa"] == pytest.approx(
            28.518, abs=1e-9
        )
        before = read_load(load["id"])
        assert before["order_count"] == 1
        assert before["assigned_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert before["assigned_cube_m3"] == pytest.approx(18.45, abs=0.0005)
        assert before["cube_utilization_pct"] == pytest.approx(29.76, abs=0.005)
        assert before["linehaul_cost_cents"] == 164231
        staged = read_order(order["id"])
        assert staged["allocated_freight_cents"] == 164231
        assert staged["freight_sequence"] == 1

        determined = determine_failure(env["failure"])
        assert determined["status"] == "DETERMINED"
        assert determined["determined_cause"] == "STRUCTURAL_UNDERDESIGN"

        # Hop 1.
        assert read_design(design["id"])["status"] == "RECALLED"
        # Hop 2.
        held = read_order(order["id"])
        assert held["production_status"] == "HOLD_ENGINEERING"
        # Hop 3.
        assert_detached_order(held)
        # Hop 4.
        emptied = read_load(load["id"])
        assert emptied["status"] == "CANCELLED"
        assert_empty_load_totals(emptied)

        dealer = read_dealer(ref["alpha"]["id"])
        assert dealer["staged_kit_count"] == 0
        # HOLD_ENGINEERING is not a cancellation, so the credit hold survives.
        assert dealer["credit_committed_cents"] == 1999734
        assert held["financial_status"] == "AWAITING_DEPOSIT"
        assert held["installation_readiness"] == "UNASSIGNED"

    def test_a_second_kit_on_the_trailer_stops_the_chain_at_the_third_hop(self, api):
        """PRD §3.9: "The third hop, caused by each of those orders leaving the shippable set rather
        than by the determination request, detaches any such order that sits on a load still in
        `PLANNED` — clearing `freight_load_id`, zeroing `allocated_freight_cents` and nulling
        `freight_sequence` — and then re-derives that load's `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` and
        re-runs the linehaul split over the orders that remain, renumbering their `freight_sequence`
        in ascending `created_at` order."
        PRD §3.9: "The fourth hop cancels any load left with `order_count` 0."
        PRD §3.9: "The second hop, caused by the design entering `RECALLED`, moves every order against
        that design whose `production_status` is `QUEUED` or `KITTED` into `HOLD_ENGINEERING`."
        PRD §3.9: "The design's `version`, every held order's `version` and every touched load's
        `version` all advance by 1, as does the investigation's own."

        Design: Difficulty/transitive_cascade/structural_underdesign_determination_cascades_design_recall_to_order_hold_to_load_detach_to_load_cancel
        """
        ref = setup_reference_data()
        doomed_design = create_design_under_review(ref)
        spared_design = create_design_under_review(ref)
        doomed_order = place_confirmed_order(ref, doomed_design)
        spared_order = place_confirmed_order(ref, spared_design)
        load = plan_freight_load(
            ref,
            trailer_type="FLATBED",
            allocation_basis="WEIGHT",
            yard_window_start="2026-09-10T00:00:00Z",
            yard_window_end="2026-09-12T00:00:00Z",
        )
        attach_order(load, doomed_order)
        load = attach_order(load, spared_order)
        assert load["order_count"] == 2
        assert load["linehaul_cost_cents"] == 183462

        failure = open_field_failure(
            doomed_order,
            failure_mode="SIDEWALL_BUCKLE",
            observed_load_kpa=20.0,
            measured_coating_loss_pct=10.0,
            service_years=3.0,
        )
        start_failure_analysis(failure)
        determine_failure(failure)

        assert read_design(doomed_design["id"])["status"] == "RECALLED"
        # Only orders against the recalled design are held.
        assert read_design(spared_design["id"])["status"] == "UNDER_REVIEW"
        assert read_order(spared_order["id"])["production_status"] == "QUEUED"
        held = read_order(doomed_order["id"])
        assert held["production_status"] == "HOLD_ENGINEERING"
        assert_detached_order(held)

        # Hop 4 is conditional on order_count reaching 0, and it did not.
        survivor_load = read_load(load["id"])
        assert survivor_load["status"] == "PLANNED"
        assert survivor_load["order_count"] == 1
        assert survivor_load["assigned_weight_kg"] == pytest.approx(6410.4, abs=0.005)
        assert survivor_load["assigned_cube_m3"] == pytest.approx(18.45, abs=0.0005)
        assert survivor_load["cube_utilization_pct"] == pytest.approx(29.76, abs=0.005)
        assert survivor_load["linehaul_cost_cents"] == 164231
        promoted = read_order(spared_order["id"])
        assert promoted["freight_sequence"] == 1
        assert promoted["allocated_freight_cents"] == 164231
        assert_version_advanced_by(survivor_load, load, 1, "load")

        dealer = read_dealer(ref["alpha"]["id"])
        # Both holds survive: HOLD_ENGINEERING and QUEUED both commit credit.
        assert dealer["credit_committed_cents"] == 3999468
        assert dealer["staged_kit_count"] == 1


class TestCrewGateOrder:
    def test_the_tier_envelope_is_reported_before_the_wrong_dealership(self, api):
        """PRD §3.9: "Then, in this order, the design's `diameter_m` must be no greater than the
        crew's `max_diameter_m` — otherwise `ERR_CREW_TIER_INSUFFICIENT`; the crew's `dealer_id` must
        equal the order's `dealer_id` — otherwise `ERR_CREW_DEALER_MISMATCH`; and the current logical
        clock must be at or before the crew's `certified_until` — otherwise
        `ERR_CREW_CERTIFICATION_EXPIRED`."
        PRD §3.9: "The tier fixes the crew's diameter envelope, written onto the row as
        `max_diameter_m`: a `T1` crew may erect bins up to 9.5 metres, a `T2` crew up to 15.5 metres,
        and a `T3` crew up to 30.0 metres."
        PRD §2.11: "12. Crew tier diameter envelope, on crew assignment —
        `ERR_CREW_TIER_INSUFFICIENT`, 422."
        PRD §2.11: "16. Crew-to-dealership match, on crew assignment — `ERR_CREW_DEALER_MISMATCH`,
        422."

        Design: Difficulty/priority_pair_validation_conflict/crew_tier_safety_error_precedes_crew_dealer_referential_error_on_installation_assignment
        """
        env = setup_crew_conflict_pair()
        design, order = env["design"], env["order"]
        small, large = env["small_crew"], env["large_crew"]
        assert design["diameter_m"] == pytest.approx(15.5, abs=1e-9)
        assert small["max_diameter_m"] == pytest.approx(9.5, abs=1e-9)
        assert large["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)
        assert order["installation_readiness"] == "UNASSIGNED"

        # Both defects are live in this one request: the T1 envelope is too small
        # AND the crew belongs to Pinnacle while the order belongs to Alpha.
        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(small["id"]), ADMIN
            ),
            "ERR_CREW_TIER_INSUFFICIENT",
            422,
        )
        # Repairing only the tier defect exposes the referential one.
        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(large["id"]), ADMIN
            ),
            "ERR_CREW_DEALER_MISMATCH",
            422,
        )

        untouched = read_order(order["id"])
        assert untouched["installation_readiness"] == "UNASSIGNED"
        assert untouched["installation_crew_id"] is None
        assert untouched["version"] == order["version"]

    def test_the_tier_check_is_independent_of_the_dealership_it_shares_a_status_with(
        self, api
    ):
        """PRD §3.9: "Then, in this order, the design's `diameter_m` must be no greater than the
        crew's `max_diameter_m` — otherwise `ERR_CREW_TIER_INSUFFICIENT`; the crew's `dealer_id` must
        equal the order's `dealer_id` — otherwise `ERR_CREW_DEALER_MISMATCH`; and the current logical
        clock must be at or before the crew's `certified_until` — otherwise
        `ERR_CREW_CERTIFICATION_EXPIRED`."
        PRD §3.9: "Assigning a crew to an order is a `PlantAdmin` action naming the crew with
        `installation_crew_id`, and it moves that order's `installation_readiness` from `UNASSIGNED`
        to `ASSIGNED`, bumping the order's `version` by 1."
        PRD §3.9: "The comparison against a design is inclusive, so a bin of exactly 15.5 metres is
        admissible for a `T2` crew."

        Design: Difficulty/priority_pair_validation_conflict/crew_tier_safety_error_precedes_crew_dealer_referential_error_on_installation_assignment
        """
        env = setup_crew_conflict_pair()
        ref, order = env["ref"], env["order"]
        # A crew on the RIGHT dealership but the wrong tier still fails at step 12,
        # which shows the envelope is checked on its own.
        own_small = register_crew(
            ref, dealer="alpha", crew_name="Alpha Erectors T1", certification_tier="T1"
        )
        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(own_small["id"]), ADMIN
            ),
            "ERR_CREW_TIER_INSUFFICIENT",
            422,
        )
        assert read_order(order["id"])["version"] == order["version"]

        own_large = register_crew(
            ref, dealer="alpha", crew_name="Alpha Erectors T3", certification_tier="T3"
        )
        assigned = validate_success(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(own_large["id"]), ADMIN
            )
        )
        assert assigned["installation_readiness"] == "ASSIGNED"
        assert assigned["installation_crew_id"] == own_large["id"]
        assert_version_advanced_by(assigned, order, 1, "order")
        # The two rejections wrote nothing, so exactly one mutation stands.
        assert assigned["production_status"] == "DRAFT"


class TestVerdictStrictness:
    def test_both_comparisons_fall_benign_on_equality_and_the_branch_ignores_the_other_axis(
        self, api
    ):
        """PRD §3.9: "The `structural_verdict` is `EXCEEDS_DESIGN` when the `observed_load_kpa` is
        strictly greater than the design's `governing_demand_kpa`, and `WITHIN_DESIGN` otherwise — an
        observed load exactly equal to the governing demand is `WITHIN_DESIGN`."
        PRD §3.9: "The `corrosion_verdict` is `EXCEEDS_CLASS` when the `measured_coating_loss_pct` is
        strictly greater than the loss limit for the design's coating class, and `WITHIN_CLASS`
        otherwise; the limits are 25.0 percent for `C2`, 40.0 for `C3`, 55.0 for `C4` and 70.0 for
        `C5`, and a loss exactly equal to the limit is `WITHIN_CLASS`."
        PRD §3.9: "First, a `CORROSION_PERFORATION` yields `COATING_INADEQUATE` when the
        `corrosion_verdict` is `EXCEEDS_CLASS`, and `OVERLOAD_MISUSE` otherwise."
        PRD §3.9: "The investigation begins in `INTAKE` with `structural_verdict`,
        `corrosion_verdict` and `determined_cause` all null."
        PRD §3.9: "`OVERLOAD_MISUSE` is the quiet branch: the plant's design, coil and crews are all
        exonerated, no cross-entity effect fires at all, and only the investigation row itself changes
        — `determined_cause`, `status` and `version`."

        Design: Corner/calculations/both_failure_verdict_comparisons_are_strict_and_the_branch_order_ignores_the_other_axis
        """
        ref = setup_reference_data()
        assert ref["coating_specs"]["G115"]["corrosion_class"] == "C3"
        design = create_design(ref)
        assert design["governing_demand_kpa"] == pytest.approx(28.518, abs=1e-9)
        first_order, second_order = place_order(ref, design), place_order(ref, design)

        # Failure A sits exactly ON both limits.
        first = open_field_failure(
            first_order,
            failure_mode="CORROSION_PERFORATION",
            observed_load_kpa=28.518,
            measured_coating_loss_pct=40.0,
            service_years=9.0,
        )
        assert first["status"] == "INTAKE"
        assert first["bin_design_id"] == design["id"]
        assert first["structural_verdict"] is None
        assert first["corrosion_verdict"] is None
        assert first["determined_cause"] is None

        analysed = start_failure_analysis(first)
        assert analysed["status"] == "ANALYSIS_IN_PROGRESS"
        assert analysed["structural_verdict"] == "WITHIN_DESIGN"
        assert analysed["corrosion_verdict"] == "WITHIN_CLASS"
        settled = determine_failure(first)
        assert settled["status"] == "DETERMINED"
        assert settled["determined_cause"] == "OVERLOAD_MISUSE"

        # Failure B exceeds both, but branch 3a is reserved for corrosion holes.
        second = open_field_failure(
            second_order,
            failure_mode="SIDEWALL_BUCKLE",
            observed_load_kpa=28.519,
            measured_coating_loss_pct=40.1,
            service_years=9.0,
        )
        beyond = start_failure_analysis(second)
        assert beyond["structural_verdict"] == "EXCEEDS_DESIGN"
        assert beyond["corrosion_verdict"] == "EXCEEDS_CLASS"
        overloaded = determine_failure(second)
        assert overloaded["determined_cause"] == "OVERLOAD_MISUSE"

        # The quiet branch fires nothing: the design was never recalled.
        assert read_design(design["id"])["status"] == "DRAFT"
        assert read_order(first_order["id"])["production_status"] == "DRAFT"
        assert read_order(second_order["id"])["production_status"] == "DRAFT"


class TestCrewTierEnvelope:
    def test_the_envelope_admits_its_own_maximum_and_the_assignment_is_not_repeatable(
        self, api
    ):
        """PRD §3.9: "The tier fixes the crew's diameter envelope, written onto the row as
        `max_diameter_m`: a `T1` crew may erect bins up to 9.5 metres, a `T2` crew up to 15.5 metres,
        and a `T3` crew up to 30.0 metres."
        PRD §3.9: "The comparison against a design is inclusive, so a bin of exactly 15.5 metres is
        admissible for a `T2` crew."
        PRD §3.9: "A new crew's `status` is `CERTIFIED`."
        PRD §3.9: "The order must not already have an `installation_crew_id`, and its
        `production_status` must be neither `CANCELLED` nor `SHIPPED`; either condition is refused with
        `ERR_ORDER_STATE_INVALID`."

        Design: Corner/calculations/crew_tier_envelope_is_inclusive_at_the_tier_maximum_and_exclusive_one_step_above
        """
        ref = setup_reference_data()
        design = create_design(ref, diameter_m=15.5, eave_height_m=12.0)
        assert design["diameter_m"] == pytest.approx(15.5, abs=1e-9)
        order = place_order(ref, design)
        tiers = {
            tier: register_crew(
                ref, crew_name=f"Alpha Erectors {tier}", certification_tier=tier
            )
            for tier in ("T1", "T2", "T3")
        }
        assert tiers["T1"]["max_diameter_m"] == pytest.approx(9.5, abs=1e-9)
        assert tiers["T2"]["max_diameter_m"] == pytest.approx(15.5, abs=1e-9)
        assert tiers["T3"]["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)
        assert all(crew["status"] == "CERTIFIED" for crew in tiers.values())

        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(tiers["T1"]["id"]), ADMIN
            ),
            "ERR_CREW_TIER_INSUFFICIENT",
            422,
        )
        pending = read_order(order["id"])
        assert pending["installation_crew_id"] is None
        assert pending["installation_readiness"] == "UNASSIGNED"

        # 15.5 <= 15.5 is admissible.
        assigned = validate_success(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(tiers["T2"]["id"]), ADMIN
            )
        )
        assert assigned["installation_readiness"] == "ASSIGNED"
        assert assigned["installation_crew_id"] == tiers["T2"]["id"]

        validate_error(
            api.assign_crew_to_order(
                order["id"], assign_crew_payload(tiers["T3"]["id"]), ADMIN
            ),
            "ERR_ORDER_STATE_INVALID",
            409,
        )
        assert read_order(order["id"])["installation_crew_id"] == tiers["T2"]["id"]


class TestCrewReferentialAndTemporalGates:
    def test_the_wrong_dealership_is_refused_and_the_expiry_is_at_or_before(self, api):
        """PRD §3.9: "Then, in this order, the design's `diameter_m` must be no greater than the
        crew's `max_diameter_m` — otherwise `ERR_CREW_TIER_INSUFFICIENT`; the crew's `dealer_id` must
        equal the order's `dealer_id` — otherwise `ERR_CREW_DEALER_MISMATCH`; and the current logical
        clock must be at or before the crew's `certified_until` — otherwise
        `ERR_CREW_CERTIFICATION_EXPIRED`."
        PRD §2.11: "20. Crew certification expiry against the logical clock, on crew assignment —
        `ERR_CREW_CERTIFICATION_EXPIRED`, 422."
        PRD §2.4: "A `PlantAdmin` may move the clock forward or backward by supplying a `to_iso8601`
        instant; the response reports the new value as `current_utc`."
        PRD §3.9: "A `PlantAdmin` registers a crew under a dealership with `dealer_id`, a `crew_name`,
        a `certification_tier` of `T1`, `T2` or `T3`, and a `certified_until` instant after which the
        certification is expired for assignment purposes."

        Design: Corner/validations/crew_assignment_checks_the_dealer_match_and_the_certificate_expiry_inclusively
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert design["diameter_m"] == pytest.approx(12.0, abs=1e-9)
        first, second = place_order(ref, design), place_order(ref, design)
        own = register_crew(ref, dealer="alpha", certified_until="2027-12-31T00:00:00Z")
        other = register_crew(
            ref,
            dealer="pinnacle",
            crew_name="Pinnacle Erectors T3",
            certified_until="2027-12-31T00:00:00Z",
        )
        # Both crews clear the 12.0 m bin, so only the later gates can fire.
        assert own["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)
        assert other["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)

        validate_error(
            api.assign_crew_to_order(
                first["id"], assign_crew_payload(other["id"]), ADMIN
            ),
            "ERR_CREW_DEALER_MISMATCH",
            422,
        )

        # Exactly at certified_until: at-or-before admits equality.
        set_clock("2027-12-31T00:00:00Z")
        assigned = validate_success(
            api.assign_crew_to_order(first["id"], assign_crew_payload(own["id"]), ADMIN)
        )
        assert assigned["installation_readiness"] == "ASSIGNED"

        set_clock("2027-12-31T00:00:01Z")
        validate_error(
            api.assign_crew_to_order(
                second["id"], assign_crew_payload(own["id"]), ADMIN
            ),
            "ERR_CREW_CERTIFICATION_EXPIRED",
            422,
        )
        stranded = read_order(second["id"])
        assert stranded["installation_crew_id"] is None
        assert stranded["installation_readiness"] == "UNASSIGNED"
        # Expiry is a clock comparison, not a state transition.
        assert read_crew(own["id"])["status"] == "CERTIFIED"


class TestInstallationDefectDecertification:
    def test_the_downgrade_is_one_tier_deep_and_blocks_only_the_crew_s_live_orders(
        self, api
    ):
        """PRD §3.9: "Second, an `ANCHOR_PULLOUT` always yields `INSTALLATION_DEFECT`."
        PRD §3.9: "A crew whose `certification_tier` is `T2` or `T3` drops exactly one step, `T3`
        becoming `T2` and `T2` becoming `T1`, has its `max_diameter_m` recomputed from the new tier, and
        moves from `CERTIFIED` to `PROBATION`."
        PRD §3.9: "every order holding that crew in `installation_crew_id` whose `production_status` is
        neither `CANCELLED` nor `SHIPPED` moves its `installation_readiness` from `ASSIGNED` to
        `BLOCKED`."
        PRD §3.9: "The crew's `status` must be `CERTIFIED`; a crew in `PROBATION` or `REVOKED` is
        refused with `ERR_CREW_NOT_CERTIFIED` and HTTP 409."

        Design: Corner/state_machines/installation_defect_decertifies_the_crew_and_blocks_only_its_live_orders
        """
        ref = setup_reference_data()
        design = create_design(ref)
        crew = register_crew(ref, certification_tier="T3")
        live, doomed, spare = (
            place_order(ref, design),
            place_order(ref, design),
            place_order(ref, design),
        )
        assign_crew(live, crew)
        assign_crew(doomed, crew)
        cancelled = cancel_order(ref, doomed)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["installation_readiness"] == "ASSIGNED"
        before = read_order(live["id"])

        failure = drive_failure_to_determination(
            live,
            failure_mode="ANCHOR_PULLOUT",
            observed_load_kpa=1.0,
            measured_coating_loss_pct=0.0,
            service_years=1.0,
        )
        # Verdicts are benign on both axes, yet branch 2 still fires.
        assert failure["structural_verdict"] == "WITHIN_DESIGN"
        assert failure["corrosion_verdict"] == "WITHIN_CLASS"
        assert failure["determined_cause"] == "INSTALLATION_DEFECT"

        downgraded = read_crew(crew["id"])
        assert downgraded["status"] == "PROBATION"
        assert downgraded["certification_tier"] == "T2"
        assert downgraded["max_diameter_m"] == pytest.approx(15.5, abs=1e-9)
        assert_version_advanced_by(downgraded, crew, 1, "crew")

        blocked = read_order(live["id"])
        assert blocked["installation_readiness"] == "BLOCKED"
        assert blocked["installation_crew_id"] == crew["id"]
        assert blocked["production_status"] == "DRAFT"
        assert_version_advanced_by(blocked, before, 1, "live order")
        # The cancelled order is outside the live set the hop touches.
        assert read_order(doomed["id"])["installation_readiness"] == "ASSIGNED"

        validate_error(
            api.assign_crew_to_order(
                spare["id"], assign_crew_payload(crew["id"]), ADMIN
            ),
            "ERR_CREW_NOT_CERTIFIED",
            409,
        )
        untouched = read_order(spare["id"])
        assert untouched["installation_crew_id"] is None
        assert untouched["installation_readiness"] == "UNASSIGNED"
        # Branch 2 exonerates the design entirely.
        assert read_design(design["id"])["status"] == "DRAFT"

    def test_a_t1_crew_has_no_lower_tier_and_is_revoked_outright(self, api):
        """PRD §3.9: "A crew already at `T1` has no lower tier to fall to, so its
        `certification_tier` stays `T1` and it moves from `CERTIFIED` to `REVOKED`, which is terminal."
        PRD §3.9: "Both outcomes are first hops, and both trigger the same second hop, caused by the
        crew leaving `CERTIFIED`: every order holding that crew in `installation_crew_id` whose
        `production_status` is neither `CANCELLED` nor `SHIPPED` moves its `installation_readiness` from
        `ASSIGNED` to `BLOCKED`."
        PRD §3.9: "The tier fixes the crew's diameter envelope, written onto the row as
        `max_diameter_m`: a `T1` crew may erect bins up to 9.5 metres, a `T2` crew up to 15.5 metres,
        and a `T3` crew up to 30.0 metres."

        Design: Corner/state_machines/installation_defect_decertifies_the_crew_and_blocks_only_its_live_orders
        """
        ref = setup_reference_data()
        small = create_design(ref, diameter_m=6.0, eave_height_m=6.0)
        crew = register_crew(ref, crew_name="Alpha Erectors T1", certification_tier="T1")
        assert crew["max_diameter_m"] == pytest.approx(9.5, abs=1e-9)
        order = place_order(ref, small)
        assigned = assign_crew(order, crew)
        assert assigned["installation_readiness"] == "ASSIGNED"

        failure = drive_failure_to_determination(
            order,
            failure_mode="ANCHOR_PULLOUT",
            observed_load_kpa=400.0,
            measured_coating_loss_pct=95.0,
            service_years=30.0,
        )
        assert failure["determined_cause"] == "INSTALLATION_DEFECT"

        revoked = read_crew(crew["id"])
        assert revoked["status"] == "REVOKED"
        assert revoked["certification_tier"] == "T1"
        assert revoked["max_diameter_m"] == pytest.approx(9.5, abs=1e-9)
        assert_version_advanced_by(revoked, crew, 1, "crew")

        held = read_order(order["id"])
        assert held["installation_readiness"] == "BLOCKED"
        assert_version_advanced_by(held, assigned, 1, "order")
        assert read_design(small["id"])["status"] == "DRAFT"


class TestLogicalClockEndpoint:
    def test_the_clock_returns_a_bare_timestamp_and_moves_in_both_directions(self, api):
        """PRD §2.4: "A `PlantAdmin` may move the clock forward or backward by supplying a
        `to_iso8601` instant; the response reports the new value as `current_utc`."
        PRD §2.4: "This is a test-driving capability, and the plant treats it as configuration rather
        than as a business event: moving the clock fires no cascades on its own, but it changes the
        outcome of every subsequent comparison."
        PRD §3.9: "the current logical clock must be at or before the crew's `certified_until` —
        otherwise `ERR_CREW_CERTIFICATION_EXPIRED`."

        Design: Corner/endpoints/the_logical_clock_endpoint_returns_a_bare_timestamp_and_moves_in_both_directions
        """
        ref = setup_reference_data()
        design = create_design(ref)
        crew = register_crew(ref, certified_until="2026-08-15T00:00:00Z")
        first, second = place_order(ref, design), place_order(ref, design)
        opened = assign_crew(first, crew)
        assert opened["installation_readiness"] == "ASSIGNED"
        before = read_order(second["id"])

        forward = validate_success(
            api.set_clock(set_clock_payload("2026-08-15T00:00:01Z"), ADMIN)
        )
        assert_instant_equals(forward["current_utc"], "2026-08-15T00:00:01Z", "clock")
        # The clock is configuration, not an entity: no row identity is minted.
        assert_no_such_field(forward, "id")
        assert_no_such_field(forward, "version")
        assert_no_such_field(forward, "created_at")

        validate_error(
            api.assign_crew_to_order(
                second["id"], assign_crew_payload(crew["id"]), ADMIN
            ),
            "ERR_CREW_CERTIFICATION_EXPIRED",
            422,
        )
        # Moving the clock fired no sweep over the already-assigned order or the crew.
        settled = read_order(first["id"])
        assert settled["installation_readiness"] == "ASSIGNED"
        assert settled["installation_crew_id"] == crew["id"]
        unchanged = read_crew(crew["id"])
        assert unchanged["status"] == "CERTIFIED"
        assert_instant_equals(
            unchanged["certified_until"], "2026-08-15T00:00:00Z", "certified_until"
        )
        assert unchanged["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)

        backward = validate_success(
            api.set_clock(set_clock_payload("2026-07-20T00:00:00Z"), ADMIN)
        )
        assert_instant_equals(backward["current_utc"], "2026-07-20T00:00:00Z", "clock")
        assert_no_such_field(backward, "id")

        # The identical request now succeeds: the clock is not monotonic.
        admitted = validate_success(
            api.assign_crew_to_order(
                second["id"], assign_crew_payload(crew["id"]), ADMIN
            )
        )
        assert admitted["installation_readiness"] == "ASSIGNED"
        assert admitted["installation_crew_id"] == crew["id"]
        assert_version_advanced_by(admitted, before, 1, "second order")
