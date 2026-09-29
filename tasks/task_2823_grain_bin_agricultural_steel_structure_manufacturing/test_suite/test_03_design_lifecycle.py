"""The bin design lifecycle: the draft/review/revision loop, the terminal recall,
the licensure and segregation gates, and the initial state of every machine."""

import pytest
from test_helpers import (
    ADMIN,
    PLANNER,
    QUALITY,
    add_analysis,
    build_design_payload,
    cancel_order,
    complete_run,
    confirm_order,
    create_design,
    dealer_headers,
    determine_failure,
    drive_failure_to_determination,
    engineer_headers,
    lapse_engineer,
    make_design_engineer_headers,
    make_sealing_engineer_headers,
    open_field_failure,
    pay_deposit,
    place_order,
    plan_freight_load,
    read_design,
    read_failure,
    read_order,
    read_run,
    receive_coil_lot,
    register_crew,
    request_revision,
    revise_design,
    schedule_run,
    seal_design,
    sealer_headers,
    setup_reference_data,
    start_failure_analysis,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
    void_run,
)


def analyses_of(api, design_id):
    rows, meta = validate_paginated(
        api.list_design_analyses(design_id, ADMIN, {"limit": 10, "offset": 0})
    )
    return rows, meta["total_count"]


class TestRevisionCycleReturnsToDraft:
    def test_the_loop_reruns_the_full_pipeline_and_increments_the_round_counter(self, api):
        """PRD §3.3: "The merged inputs are then run back through the full geometry and
        structural pipeline, refreshing every computed geometry and structural field on the row,
        `revision_round` increases by 1, `author_engineer_id` is overwritten with the acting
        engineer's identifier, `status` returns to `DRAFT`, and `version` bumps by 1."
        PRD §3.3: "A `DesignEngineer` revising a design in `REVISION_REQUIRED` may supply any
        subset of `diameter_m`, `eave_height_m`, `roof_pitch_deg`, `design_wind_speed_mph`,
        `moisture_pct` and `design_method`; every field omitted from the request keeps its
        current stored value."
        PRD §3.3: "The cycle `DRAFT` to `UNDER_REVIEW` to `REVISION_REQUIRED` back to `DRAFT` is
        repeatable without limit, and `revision_round` is its loop counter."

        Design: Difficulty/non_linear_state_machine/bin_design_revision_cycle_returns_to_draft_and_supersedes_analyses
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert design["revision_round"] == 0
        first = add_analysis(ref, design)
        assert first["verdict"] == "PASS"

        assert submit_for_review(ref, design)["status"] == "UNDER_REVIEW"
        returned = request_revision(
            ref, design, revision_note="Raise the eave to 12.8 m and re-check at 17.5 pct moisture."
        )
        assert returned["status"] == "REVISION_REQUIRED"

        revised = revise_design(ref, design, eave_height_m=12.8, moisture_pct=17.5)
        assert revised["status"] == "DRAFT"
        assert revised["revision_round"] == 1
        assert revised["eave_height_m"] == pytest.approx(12.8, abs=1e-9)
        assert revised["moisture_pct"] == pytest.approx(17.5, abs=1e-9)
        # Omitted fields keep their stored values.
        assert revised["diameter_m"] == pytest.approx(12.0, abs=1e-9)
        assert revised["design_method"] == "ASD"
        assert revised["roof_pitch_deg"] == 30
        assert revised["design_wind_speed_mph"] == 105
        # Every computed field was recomputed over the merged inputs.
        assert revised["sheet_courses"] == 16
        assert revised["sidewall_sheet_count"] == 560
        assert revised["capacity_m3"] == pytest.approx(1578.16, abs=1e-9)
        assert revised["grain_demand_kpa"] == pytest.approx(39.213, abs=1e-9)
        assert revised["required_stiffener_count"] == 17
        assert revised["utilization_ratio"] == pytest.approx(0.9662, abs=1e-9)
        assert revised["sheet_gauge_mm"] == pytest.approx(2.0, abs=1e-9)
        assert revised["author_engineer_id"] == ref["author"]["id"]

    def test_revision_supersedes_every_analysis_so_the_design_must_be_re_analysed(self, api):
        """PRD §3.3: "Critically, revision also sets `superseded` to true on **every** analysis
        of that design, moving each of them from the CURRENT condition into the SUPERSEDED
        condition — an analysis whose `superseded` is false is CURRENT, and one whose
        `superseded` is true is SUPERSEDED, and there is no separate status field on an analysis
        — and bumping each analysis row's own `version` by 1."
        PRD §3.3: "Superseded analyses are excluded from the governing-analysis selection, so a
        revised design must be re-analysed before it can be resubmitted."
        PRD §3.3: "Each analysis is stamped with an `analysis_index` that is one greater than the
        highest `analysis_index` already present on that design, so the indices are 1-based and
        dense in creation order, and it begins with `superseded` false."

        Design: Difficulty/non_linear_state_machine/bin_design_revision_cycle_returns_to_draft_and_supersedes_analyses
        """
        ref = setup_reference_data()
        design = create_design(ref)
        add_analysis(ref, design)
        submit_for_review(ref, design)
        request_revision(ref, design)
        revise_design(ref, design, eave_height_m=12.8, moisture_pct=17.5)

        rows, total = analyses_of(api, design["id"])
        assert total == 1
        assert rows[0]["analysis_index"] == 1
        assert rows[0]["superseded"] is True

        validate_error(
            api.submit_design_for_review(design["id"], engineer_headers(ref)),
            "ERR_NO_PASSING_ANALYSIS",
            422,
        )
        assert read_design(design["id"])["status"] == "DRAFT"

        second = add_analysis(ref, design)
        assert second["analysis_index"] == 2
        assert second["superseded"] is False
        assert second["required_stiffener_count"] == 17
        assert second["utilization_ratio"] == pytest.approx(0.9662, abs=1e-9)
        assert second["verdict"] == "PASS"

        resubmitted = submit_for_review(ref, design)
        assert resubmitted["status"] == "UNDER_REVIEW"
        # Re-entering UNDER_REVIEW does not re-increment the loop counter.
        assert resubmitted["revision_round"] == 1

        rows, total = analyses_of(api, design["id"])
        assert total == 2
        assert [row["analysis_index"] for row in rows] == [1, 2]
        assert [row["superseded"] for row in rows] == [True, False]


class TestInitialStates:
    def test_every_stateful_entity_is_born_in_its_declared_initial_state(self, api):
        """PRD §2.5: "Most entities additionally carry `updated_at`, an ISO 8601 UTC timestamp
        with three fractional digits refreshed on every mutation of that row, and `version`, an
        integer that begins at 1 on insert and increases by exactly 1 each time the row is
        mutated."
        PRD §3.2: "the design's `sealed_by_engineer_id`, `sealed_at` and `permit_ready_at` all
        begin null, its `revision_round` begins at 0, its `status` begins at `DRAFT`"
        PRD §3.3: "Each analysis is stamped with an `analysis_index` that is one greater than the
        highest `analysis_index` already present on that design, so the indices are 1-based and
        dense in creation order, and it begins with `superseded` false."
        PRD §3.4: "A fresh order begins with `production_status` `DRAFT`, `financial_status`
        `AWAITING_DEPOSIT` and `installation_readiness` `UNASSIGNED`, with `freight_load_id` and
        `installation_crew_id` both null, `deposit_paid_cents` 0, `allocated_freight_cents` 0 and
        `freight_sequence` null."
        PRD §3.7: "A new lot begins with `reserved_kg`, `consumed_kg` and `scrap_kg` all 0,
        `remaining_kg` equal to `received_kg`, and `status` `AVAILABLE`."
        PRD §3.7: "A newly booked run begins with `status` `SCHEDULED` and with `consumed_kg` and
        `scrap_kg` both 0; nothing has yet been drawn from the coil, only reserved."
        PRD §3.8: "A new load is written with those two capacities and with `assigned_cube_m3`,
        `assigned_weight_kg`, `cube_utilization_pct`, `linehaul_cost_cents` and `order_count` all
        initialised to 0 and `status` `PLANNED`."
        PRD §3.9: "A new crew's `status` is `CERTIFIED`."
        PRD §3.9: "The investigation begins in `INTAKE` with `structural_verdict`,
        `corrosion_verdict` and `determined_cause` all null."
        PRD §2.10: "An engineer's `status` is `ACTIVE` when the row is created and becomes
        `LAPSED` when a `PlantAdmin` marks the licence lapsed; `LAPSED` is terminal."
        PRD §3.6: "Its `credit_available_cents` is the `credit_limit_cents` minus that committed
        sum, and it may legitimately go negative when the limit is lowered beneath the existing
        commitment. The dealership's `status` is `CREDIT_HOLD` whenever `credit_available_cents`
        is below zero and `ACTIVE` otherwise."
        PRD §3.8: "The dealership's `staged_kit_count` mirrors this population directly: it is
        the count of that dealership's loads whose `status` is `PLANNED`, and it is recomputed
        whenever a load enters or leaves that set, bumping the dealership's `version` by 1."
        PRD §3.8: "A `FLATBED` carries `max_cube_m3` 62.0 and `max_weight_kg` 21000; a
        `HIGH_CUBE_VAN` carries 95.0 and 28000; a `STEP_DECK` carries 74.0 and 22500."
        PRD §3.9: "The tier fixes the crew's diameter envelope, written onto the row as
        `max_diameter_m`: a `T1` crew may erect bins up to 9.5 metres, a `T2` crew up to 15.5
        metres, and a `T3` crew up to 30.0 metres."
        PRD §3.7: "The lot's coating designation is copied onto the run as `coating_code` at
        creation and is used thereafter for changeover comparisons rather than re-reading the
        coating specification."
        PRD §3.9: "Intake copies the order's `bin_design_id` onto the investigation and freezes
        it there, so a later revision of the design library cannot move the target of the
        investigation."

        Design: Corner/state_machines/every_stateful_entity_is_born_in_its_declared_initial_state
        """
        ref = setup_reference_data()

        engineer = ref["author"]
        assert engineer["status"] == "ACTIVE"
        assert engineer["version"] == 1

        dealer = ref["alpha"]
        assert dealer["status"] == "ACTIVE"
        assert dealer["credit_committed_cents"] == 0
        assert dealer["credit_available_cents"] == 900000000
        assert dealer["staged_kit_count"] == 0
        assert dealer["version"] == 1

        crew = register_crew(ref)
        assert crew["status"] == "CERTIFIED"
        assert crew["certification_tier"] == "T3"
        assert crew["max_diameter_m"] == pytest.approx(30.0, abs=1e-9)
        assert crew["version"] == 1

        design = create_design(ref)
        assert design["status"] == "DRAFT"
        assert design["revision_round"] == 0
        assert design["sealed_by_engineer_id"] is None
        assert design["sealed_at"] is None
        assert design["permit_ready_at"] is None
        assert design["version"] == 1
        assert design["author_engineer_id"] == engineer["id"]

        analysis = add_analysis(ref, design)
        assert analysis["superseded"] is False
        assert analysis["analysis_index"] == 1
        assert analysis["version"] == 1
        assert "status" not in analysis

        order = place_order(ref, design)
        assert order["production_status"] == "DRAFT"
        assert order["financial_status"] == "AWAITING_DEPOSIT"
        assert order["installation_readiness"] == "UNASSIGNED"
        assert order["freight_load_id"] is None
        assert order["installation_crew_id"] is None
        assert order["freight_sequence"] is None
        assert order["allocated_freight_cents"] == 0
        assert order["deposit_paid_cents"] == 0
        assert order["version"] == 1

        lot = receive_coil_lot(ref)
        assert lot["status"] == "AVAILABLE"
        assert lot["reserved_kg"] == pytest.approx(0.0, abs=1e-9)
        assert lot["consumed_kg"] == pytest.approx(0.0, abs=1e-9)
        assert lot["scrap_kg"] == pytest.approx(0.0, abs=1e-9)
        assert lot["remaining_kg"] == pytest.approx(20000.0, abs=1e-9)
        assert lot["version"] == 1

        run = schedule_run(
            ref, lot, order, "2026-08-03T06:00:00Z", "2026-08-03T14:00:00Z", 6600.0
        )
        assert run["status"] == "SCHEDULED"
        assert run["consumed_kg"] == pytest.approx(0.0, abs=1e-9)
        assert run["scrap_kg"] == pytest.approx(0.0, abs=1e-9)
        assert run["coating_code"] == "G115"
        assert run["version"] == 1

        load = plan_freight_load(
            ref,
            yard_window_start="2026-08-10T00:00:00Z",
            yard_window_end="2026-08-12T00:00:00Z",
        )
        assert load["status"] == "PLANNED"
        assert load["order_count"] == 0
        assert load["assigned_cube_m3"] == pytest.approx(0.0, abs=1e-9)
        assert load["assigned_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert load["cube_utilization_pct"] == pytest.approx(0.0, abs=1e-9)
        assert load["linehaul_cost_cents"] == 0
        assert load["max_cube_m3"] == pytest.approx(62.0, abs=1e-9)
        assert load["max_weight_kg"] == pytest.approx(21000.0, abs=1e-9)
        assert load["version"] == 1

        failure = open_field_failure(
            order,
            failure_mode="SIDEWALL_BUCKLE",
            observed_load_kpa=20.0,
            measured_coating_loss_pct=5.0,
            service_years=3.0,
        )
        assert failure["status"] == "INTAKE"
        assert failure["structural_verdict"] is None
        assert failure["corrosion_verdict"] is None
        assert failure["determined_cause"] is None
        assert failure["bin_design_id"] == design["id"]
        assert failure["version"] == 1


class TestDesignRejectsUndeclaredTriggers:
    def test_each_state_admits_only_its_declared_triggers_and_refusals_bump_nothing(
        self, api
    ):
        """PRD §3.3: "Design state transitions are strict about their entry states, and a
        mismatch is rejected with `ERR_DESIGN_STATE_INVALID`: submission requires `DRAFT`, both
        the revision request and the seal require `UNDER_REVIEW`, revision requires
        `REVISION_REQUIRED`, and `RECALLED` admits nothing at all."
        PRD §2.5: "Most entities additionally carry `updated_at`, an ISO 8601 UTC timestamp with
        three fractional digits refreshed on every mutation of that row, and `version`, an
        integer that begins at 1 on insert and increases by exactly 1 each time the row is
        mutated."

        Design: Corner/state_machines/bin_design_rejects_every_trigger_not_declared_from_its_current_state
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert add_analysis(ref, design)["verdict"] == "PASS"

        draft = read_design(design["id"])
        assert draft["status"] == "DRAFT"
        base_version = draft["version"]

        # DRAFT accepts only submit-review.
        validate_error(
            api.seal_bin_design(design["id"], sealer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.request_design_revision(
                design["id"], {"revision_note": "premature"}, sealer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.revise_bin_design(
                design["id"], {"eave_height_m": 10.4}, engineer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        still_draft = read_design(design["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["version"] == base_version

        under_review = submit_for_review(ref, design)
        assert under_review["status"] == "UNDER_REVIEW"
        assert under_review["version"] == base_version + 1

        # UNDER_REVIEW accepts only request-revision and seal.
        validate_error(
            api.revise_bin_design(
                design["id"], {"eave_height_m": 10.4}, engineer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        assert read_design(design["id"])["version"] == base_version + 1

        returned = request_revision(ref, design, revision_note="add a roof ring detail")
        assert returned["status"] == "REVISION_REQUIRED"
        assert returned["version"] == base_version + 2

        # REVISION_REQUIRED accepts only revise.
        validate_error(
            api.submit_design_for_review(design["id"], engineer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.seal_bin_design(design["id"], sealer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.request_design_revision(
                design["id"], {"revision_note": "again"}, sealer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )

        final = read_design(design["id"])
        assert final["status"] == "REVISION_REQUIRED"
        assert final["revision_round"] == 0
        assert final["version"] == base_version + 2


class TestReplayingCompletedTransitions:
    def test_every_lifecycle_refuses_a_second_run_of_a_transition_it_already_made(self, api):
        """PRD §3.6: "A `DealerPrincipal` confirming its own order moves that order's
        `production_status` from `DRAFT` to `QUEUED`; an order in any other production state is
        refused with `ERR_ORDER_STATE_INVALID`."
        PRD §3.6: "The order's `financial_status` must be `AWAITING_DEPOSIT`; a second attempt
        against an order already in `DEPOSIT_PAID`, `RELEASED` or `VOIDED` is rejected with
        `ERR_DEPOSIT_ALREADY_PAID`."
        PRD §3.7: "Posting a run's outcome requires the run to be in `SCHEDULED`; any other state
        is refused with `ERR_RUN_STATE_INVALID`."
        PRD §3.7: "A run already in `VOIDED` admits nothing and is refused with
        `ERR_RUN_STATE_INVALID`."
        PRD §3.9: "A determination attempted from the wrong state is refused with
        `ERR_FAILURE_STATE_INVALID`, as is starting an analysis on anything other than an `INTAKE`
        investigation."
        PRD §3.6: "A `DealerPrincipal` may cancel an order whose `production_status` is `DRAFT`,
        `QUEUED`, `KITTED`, `HOLD_CREDIT` or `HOLD_ENGINEERING`; an order already in `SHIPPED` or
        `CANCELLED` is refused with `ERR_ORDER_STATE_INVALID`."

        Design: Corner/state_machines/replaying_a_completed_transition_is_rejected_on_every_lifecycle
        """
        ref = setup_reference_data()
        design = create_design(ref)
        add_analysis(ref, design)
        submit_for_review(ref, design)
        sealed = seal_design(ref, design)
        assert sealed["status"] == "SEALED"

        order = place_order(ref, design)
        assert order["required_deposit_cents"] == 499933
        lot = receive_coil_lot(ref)
        run = schedule_run(
            ref, lot, order, "2026-08-03T06:00:00Z", "2026-08-03T14:00:00Z", 6600.0
        )
        failure = open_field_failure(
            order,
            failure_mode="SIDEWALL_BUCKLE",
            observed_load_kpa=40.0,
            measured_coating_loss_pct=5.0,
            service_years=3.0,
        )

        # SEALED is not in the from-set of the seal trigger.
        design_version = read_design(design["id"])["version"]
        validate_error(
            api.seal_bin_design(design["id"], sealer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        assert read_design(design["id"])["version"] == design_version

        queued = confirm_order(ref, order)
        assert queued["production_status"] == "QUEUED"
        validate_error(
            api.confirm_dealer_order(order["id"], dealer_headers(ref)),
            "ERR_ORDER_STATE_INVALID",
            409,
        )
        assert read_order(order["id"])["version"] == queued["version"]

        paid = pay_deposit(ref, order)
        assert paid["financial_status"] == "DEPOSIT_PAID"
        assert paid["deposit_paid_cents"] == 499933
        validate_error(
            api.post_order_payment(
                order["id"], {"amount_cents": 499933}, dealer_headers(ref)
            ),
            "ERR_DEPOSIT_ALREADY_PAID",
            409,
        )
        assert read_order(order["id"])["version"] == paid["version"]

        completed = complete_run(run, 6410.4, 152.3)
        assert completed["status"] == "COMPLETED"
        validate_error(
            api.complete_roll_forming_run(
                run["id"], {"consumed_kg": 100.0, "scrap_kg": 0.0}, PLANNER
            ),
            "ERR_RUN_STATE_INVALID",
            409,
        )
        replayed = read_run(run["id"])
        assert replayed["version"] == completed["version"]
        assert replayed["consumed_kg"] == pytest.approx(6410.4, abs=1e-9)

        voided = void_run(run)
        assert voided["status"] == "VOIDED"
        validate_error(
            api.void_roll_forming_run(run["id"], PLANNER), "ERR_RUN_STATE_INVALID", 409
        )
        assert read_run(run["id"])["version"] == voided["version"]

        analysing = start_failure_analysis(failure)
        assert analysing["status"] == "ANALYSIS_IN_PROGRESS"
        validate_error(
            api.start_field_failure_analysis(failure["id"], QUALITY),
            "ERR_FAILURE_STATE_INVALID",
            409,
        )
        assert read_failure(failure["id"])["version"] == analysing["version"]

        determined = determine_failure(failure)
        assert determined["status"] == "DETERMINED"
        # 40.0 is above the governing demand of 28.518, so branch 3c selects OVERLOAD_MISUSE,
        # which fires no cross-entity hop and leaves the design SEALED.
        assert determined["structural_verdict"] == "EXCEEDS_DESIGN"
        assert determined["determined_cause"] == "OVERLOAD_MISUSE"
        assert read_design(design["id"])["status"] == "SEALED"
        validate_error(
            api.determine_field_failure(failure["id"], QUALITY),
            "ERR_FAILURE_STATE_INVALID",
            409,
        )
        assert read_failure(failure["id"])["version"] == determined["version"]

        cancelled = cancel_order(ref, order)
        assert cancelled["production_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "VOIDED"
        validate_error(
            api.cancel_dealer_order(order["id"], dealer_headers(ref)),
            "ERR_ORDER_STATE_INVALID",
            409,
        )
        assert read_order(order["id"])["version"] == cancelled["version"]


class TestRecalledDesignIsTerminal:
    def test_recalled_admits_no_transition_and_refuses_new_orders_with_its_own_error(
        self, api
    ):
        """PRD §3.3: "`RECALLED` is the terminal state of a design and is reachable only as a
        system consequence of a field failure investigation, from either `SEALED` or
        `UNDER_REVIEW`; §3.9 describes what that recall drags with it."
        PRD §3.9: "`STRUCTURAL_UNDERDESIGN` recalls the design: a design in `SEALED` or in
        `UNDER_REVIEW` moves to `RECALLED`, which is the first hop. The second hop, caused by the
        design entering `RECALLED`, moves every order against that design whose
        `production_status` is `QUEUED` or `KITTED` into `HOLD_ENGINEERING`."
        PRD §3.4: "An order may be placed against a design in any state except `RECALLED`; a
        recalled design is refused with `ERR_DESIGN_RECALLED`."

        Design: Corner/state_machines/recalled_bin_design_is_terminal_and_also_refuses_to_take_new_orders
        """
        ref = setup_reference_data()
        design = create_design(ref)
        add_analysis(ref, design)
        submit_for_review(ref, design)
        seal_design(ref, design)
        order = place_order(ref, design)
        confirm_order(ref, order)

        determined = drive_failure_to_determination(
            order,
            failure_mode="SIDEWALL_BUCKLE",
            observed_load_kpa=20.0,
            measured_coating_loss_pct=5.0,
            service_years=3.0,
        )
        assert determined["structural_verdict"] == "WITHIN_DESIGN"
        assert determined["determined_cause"] == "STRUCTURAL_UNDERDESIGN"

        recalled = read_design(design["id"])
        assert recalled["status"] == "RECALLED"
        recalled_version = recalled["version"]

        validate_error(
            api.submit_design_for_review(design["id"], engineer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.request_design_revision(
                design["id"], {"revision_note": "reopen please"}, sealer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.revise_bin_design(
                design["id"], {"eave_height_m": 8.8}, engineer_headers(ref)
            ),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.seal_bin_design(design["id"], sealer_headers(ref)),
            "ERR_DESIGN_STATE_INVALID",
            409,
        )
        validate_error(
            api.create_dealer_order(
                {
                    "dealer_id": ref["alpha"]["id"],
                    "bin_design_id": design["id"],
                    "order_season": "OFFSEASON",
                    "aeration_package": "NONE",
                    "unload_system": "GRAVITY",
                },
                dealer_headers(ref),
            ),
            "ERR_DESIGN_RECALLED",
            409,
        )

        held = read_order(order["id"])
        assert held["production_status"] == "HOLD_ENGINEERING"
        assert held["financial_status"] == "AWAITING_DEPOSIT"
        assert held["installation_readiness"] == "UNASSIGNED"
        assert read_design(design["id"])["version"] == recalled_version


class TestLapsedEngineer:
    def test_a_lapsed_licence_bars_future_work_but_leaves_prior_designs_intact(self, api):
        """PRD §2.10: "Three operations require the acting engineer to be licensed for the work:
        creating a design, revising a design, and sealing a design. In all three, the acting
        engineer's `status` must be `ACTIVE` — otherwise `ERR_ENGINEER_LICENSE_LAPSED` with HTTP
        422 — and the `code` of the design's `Jurisdiction` must appear in that engineer's
        `licensed_jurisdiction_codes` — otherwise `ERR_ENGINEER_NOT_LICENSED_IN_JURISDICTION`,
        also HTTP 422."
        PRD §2.10: "A lapsed licence never invalidates a design that has already been drawn or
        sealed; it only bars future authorship, revision and sealing."
        PRD §3.3: "Sealing writes the acting engineer's identifier into `sealed_by_engineer_id`,
        sets `sealed_at` to the current logical clock value, and sets `permit_ready_at` to
        `sealed_at` advanced by the jurisdiction's `permit_review_days` whole days."

        Design: Corner/state_machines/a_lapsed_engineer_can_no_longer_author_revise_or_seal_but_prior_designs_survive
        """
        ref = setup_reference_data()
        first = create_design(ref)
        add_analysis(ref, first)
        submit_for_review(ref, first)

        second = create_design(ref)
        add_analysis(ref, second)
        submit_for_review(ref, second)
        request_revision(ref, second)
        assert read_design(second["id"])["status"] == "REVISION_REQUIRED"

        lapsed_author = lapse_engineer(ref["author"])
        assert lapsed_author["status"] == "LAPSED"
        assert lapsed_author["version"] == 2

        validate_error(
            api.create_bin_design(
                build_design_payload(ref), engineer_headers(ref, "PE-1001")
            ),
            "ERR_ENGINEER_LICENSE_LAPSED",
            422,
        )
        validate_error(
            api.revise_bin_design(
                second["id"], {"eave_height_m": 12.0}, engineer_headers(ref, "PE-1001")
            ),
            "ERR_ENGINEER_LICENSE_LAPSED",
            422,
        )

        lapsed_sealer = lapse_engineer(ref["sealer"])
        assert lapsed_sealer["status"] == "LAPSED"
        validate_error(
            api.seal_bin_design(first["id"], sealer_headers(ref, "PE-1002")),
            "ERR_ENGINEER_LICENSE_LAPSED",
            422,
        )

        standby = ref["engineers"]["PE-1003"]
        sealed = validate_success(
            api.seal_bin_design(
                first["id"], make_sealing_engineer_headers(standby["id"])
            )
        )
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == standby["id"]

        revised = validate_success(
            api.revise_bin_design(
                second["id"],
                {"eave_height_m": 12.0},
                make_design_engineer_headers(standby["id"]),
            )
        )
        assert revised["status"] == "DRAFT"
        assert revised["revision_round"] == 1
        assert revised["author_engineer_id"] == standby["id"]


class TestDesignSafetyGateOrder:
    def test_moisture_outranks_wind_which_outranks_licensure_and_both_limits_are_inclusive(
        self, api
    ):
        """PRD §3.2: "The design's `moisture_pct` must be no greater than the referenced coating's
        `max_ambient_moisture_pct`; a wetter design than the coating tolerates is rejected with
        `ERR_MOISTURE_EXCEEDS_COATING_LIMIT`. The design's `design_wind_speed_mph` must be at
        least the referenced jurisdiction's `min_design_wind_speed_mph`; anything below the local
        minimum is rejected with `ERR_WIND_BELOW_JURISDICTION_MINIMUM`."
        PRD §2.11: "9. Design moisture against the coating's ambient limit, on design creation and
        revision — `ERR_MOISTURE_EXCEEDS_COATING_LIMIT`, 422."
        PRD §2.11: "10. Design wind speed against the jurisdiction minimum, on design creation and
        revision — `ERR_WIND_BELOW_JURISDICTION_MINIMUM`, 422."
        PRD §2.11: "15. Engineer licence standing and jurisdiction licensure, on design creation,
        revision and sealing — `ERR_ENGINEER_LICENSE_LAPSED` or
        `ERR_ENGINEER_NOT_LICENSED_IN_JURISDICTION`, 422."
        PRD §3.2: "its own `seal_required` flag is copied from the referenced jurisdiction's
        `seal_required` at the moment of creation and thereafter never re-read from the
        jurisdiction"

        Design: Corner/validations/moisture_gate_outranks_the_wind_gate_which_outranks_the_engineer_licence_gate
        """
        ref = setup_reference_data()
        outstate = engineer_headers(ref, "PE-9001")

        def payload(**geometry):
            return build_design_payload(
                ref, jurisdiction="IA-CENTRAL", coating="G90", **geometry
            )

        # G90 tolerates 14.0 pct, IA-CENTRAL demands 105 mph, PE-9001 is licensed only in
        # NE-WEST: all three gates are live and the moisture gate speaks first.
        validate_error(
            api.create_bin_design(
                payload(design_wind_speed_mph=90, moisture_pct=15.0), outstate
            ),
            "ERR_MOISTURE_EXCEEDS_COATING_LIMIT",
            422,
        )
        validate_error(
            api.create_bin_design(
                payload(design_wind_speed_mph=90, moisture_pct=13.0), outstate
            ),
            "ERR_WIND_BELOW_JURISDICTION_MINIMUM",
            422,
        )
        validate_error(
            api.create_bin_design(
                payload(design_wind_speed_mph=105, moisture_pct=13.0), outstate
            ),
            "ERR_ENGINEER_NOT_LICENSED_IN_JURISDICTION",
            422,
        )

        # Both limits are inclusive: moisture exactly 14.0 and wind exactly 105 pass.
        created = validate_success(
            api.create_bin_design(
                payload(design_wind_speed_mph=105, moisture_pct=14.0),
                engineer_headers(ref, "PE-1001"),
            ),
            201,
        )
        assert created["seal_required"] is True
        assert created["status"] == "DRAFT"


class TestSegregationOfEngineeringDuties:
    def test_the_author_may_neither_seal_nor_return_their_own_design(self, api):
        """PRD §2.10: "Whenever a `SealingEngineer` acts on a design — whether to return it for
        revision or to apply the seal — the acting `X-User-ID` must differ from that design's
        `author_engineer_id`. An engineer attempting either action on their own work is rejected
        with `ERR_SEAL_SEGREGATION_VIOLATION` and HTTP 403. Note that this rule guards **both**
        sealing-engineer actions, not only the seal itself."
        PRD §3.3: "A `SealingEngineer` picks the design up from there and has two choices, both of
        which require that the acting engineer identifier differ from the design's
        `author_engineer_id`."
        PRD §3.3: "Applying the seal moves the design from `UNDER_REVIEW` to `SEALED` and
        additionally requires the acting engineer's `status` to be `ACTIVE` and the design's
        jurisdiction `code` to appear in that engineer's `licensed_jurisdiction_codes`."

        Design: Corner/validations/segregation_of_duties_blocks_the_author_from_reviewing_or_sealing_their_own_design
        """
        ref = setup_reference_data()
        design = create_design(ref, jurisdiction="IA-CENTRAL")
        assert design["author_engineer_id"] == ref["author"]["id"]
        add_analysis(ref, design)
        assert submit_for_review(ref, design)["status"] == "UNDER_REVIEW"

        author_as_sealer = make_sealing_engineer_headers(ref["author"]["id"])
        validate_error(
            api.seal_bin_design(design["id"], author_as_sealer),
            "ERR_SEAL_SEGREGATION_VIOLATION",
            403,
        )
        validate_error(
            api.request_design_revision(
                design["id"], {"revision_note": "self review attempt"}, author_as_sealer
            ),
            "ERR_SEAL_SEGREGATION_VIOLATION",
            403,
        )
        untouched = read_design(design["id"])
        assert untouched["status"] == "UNDER_REVIEW"
        assert untouched["sealed_by_engineer_id"] is None
        assert untouched["sealed_at"] is None
        assert untouched["revision_round"] == 0

        # A different engineer, but unlicensed in IA-CENTRAL: a different rule entirely.
        validate_error(
            api.seal_bin_design(
                design["id"], make_sealing_engineer_headers(ref["outstate"]["id"])
            ),
            "ERR_ENGINEER_NOT_LICENSED_IN_JURISDICTION",
            422,
        )

        sealed = validate_success(
            api.seal_bin_design(design["id"], sealer_headers(ref, "PE-1002"))
        )
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_engineer_id"] == ref["sealer"]["id"]
