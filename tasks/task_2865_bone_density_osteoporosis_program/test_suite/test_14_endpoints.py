"""The update endpoint, the worklist, an action's side effects and the clock-gated actions.

Each case drives one endpoint and then reads the store back through a second
endpoint, so a write that only pretended to land is visible.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    BMD_LUMBAR_OSTEOPENIC,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    assert_ids_in_order,
    assert_instant_equals,
    assert_qc_scoring,
    assert_score_one_decimal,
    assert_three_decimals,
    assert_two_decimals,
    get_success_data,
    qc_run_payload,
    refill_payload,
    report_patch_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTheOnlyUpdateEndpointRederivesEverything:
    """Three writable fields, and one of them can change the clinical advice."""

    def test_attaching_a_frax_assessment_flips_the_recommended_action(
        self, world: ProgramWorld
    ):
        """Nothing about the density changes, and the report still changes its mind.

        "The same three fields — `frax_assessment_id`, `non_comparability_note` and
        `vfa_narrative` — are the **only** writable ones on an update, and every
        computed field is fully re-derived on each update, so attaching a FRAX
        assessment to an existing draft can flip its `recommended_action` outright."
        "The same patient assessed `WITHOUT_BMD` scores a `raw_score` of 2.30, a major
        probability of 16.8 and a hip probability of 4.1 — still treatment-eligible, but
        on the hip threshold alone."
        "an osteopenic patient whose FRAX crosses only the hip threshold still reads
        `INITIATE_TREATMENT`."

        Design: Corner/endpoints/patching_a_frax_assessment_onto_a_draft_report_flips_the_recommended_action
        """
        pipeline = world.build(
            stop_after="drafted",
            with_profile=True,
            profile_overrides={"height_cm": 165.0, "weight_kg": 58.0},
            sites=[("LUMBAR_SPINE", BMD_LUMBAR_OSTEOPENIC)],
        )

        drafted = pipeline.report
        assert drafted["diagnostic_category"] == "OSTEOPENIA"
        assert drafted["classification_basis"] == "T_SCORE_WHO"
        assert drafted["clinical_interval_months"] == 24
        assert drafted["payer_floor_months"] == 24
        assert drafted["recommended_interval_months"] == 24
        assert drafted["recommended_action"] == "ROUTINE_INTERVAL"

        frax = world.assess_frax(pipeline.patient_id, pipeline.profile_id)
        assert frax["variant"] == "WITHOUT_BMD"
        assert_two_decimals(frax["bmi_used"], 21.30, "bmi_used")
        assert_two_decimals(frax["age_points"], 1.70, "age_points")
        assert_two_decimals(frax["sex_points"], 0.60, "sex_points")
        assert_two_decimals(frax["bmi_points"], 0.00, "bmi_points")
        assert_two_decimals(frax["clinical_risk_points"], 0.00, "clinical_risk_points")
        assert_two_decimals(frax["bmd_points"], 0.00, "bmd_points")
        assert_two_decimals(frax["raw_score"], 2.30, "raw_score")
        assert_score_one_decimal(
            frax["major_osteoporotic_10yr_pct"], 16.8, "major_osteoporotic_10yr_pct"
        )
        assert_score_one_decimal(
            frax["hip_fracture_10yr_pct"], 4.1, "hip_fracture_10yr_pct"
        )
        assert frax["treatment_threshold_met"] is True
        assert frax["threshold_basis"] == "HIP"

        patched = validate_success(
            world.api.update_diagnostic_report(
                pipeline.report_id,
                report_patch_payload(frax_assessment_id=frax["id"]),
                PHYSICIAN_HEADERS,
            ),
            200,
        )
        assert patched["frax_assessment_id"] == frax["id"]
        assert patched["recommended_action"] == "INITIATE_TREATMENT"
        assert patched["recommended_interval_months"] == 24
        assert patched["diagnostic_category"] == "OSTEOPENIA"

        reread = world.read_report(pipeline.report_id)
        assert reread["recommended_action"] == "INITIATE_TREATMENT"
        assert reread["status"] == "DRAFT"

        _, meta = validate_paginated(
            world.api.list_frax_assessments(
                PHYSICIAN_HEADERS, {"risk_factor_profile_id": pipeline.profile_id}
            )
        )
        assert meta["total_count"] == 1


def _worklist_of_four_orders(world: ProgramWorld):
    """Three orders for one patient and one for another, created in a known order."""
    world.set_clock(CLOCK_SETUP)
    policy = world.create_policy()
    patient_a = world.create_patient(policy["id"], baseline_height_cm=165.0)
    patient_b = world.create_patient(
        policy["id"], birth_date="1962-01-20", baseline_height_cm=161.0
    )
    order_a1 = world.create_order(patient_a["id"], requested_scan_date="2026-03-10")
    order_a2 = world.create_order(
        patient_a["id"],
        indication="HIGH_RISK_CASE_FINDING",
        requested_sites=["TOTAL_HIP"],
        requested_scan_date="2026-03-11",
    )
    order_a3 = world.create_order(patient_a["id"], requested_scan_date="2026-03-12")
    world.create_order(patient_b["id"], requested_scan_date="2026-03-13")
    return patient_a, order_a1, order_a2, order_a3


class TestTheWorklistComposesFiltersWithPagination:
    """Filters narrow the count that pagination then slices."""

    def test_each_added_filter_narrows_the_total_and_the_pages_split_it(
        self, world: ProgramWorld
    ):
        """total_count reports the filtered population, not the page in hand.

        "Both values are echoed back in `meta` alongside `total_count`, the number of
        rows the filter matched before pagination was applied, and `has_more`, which is
        true exactly when rows remain beyond the current page."
        "Order worklist, ordered `created_at` ascending then `id` ascending. Filterable
        by `patient_id`, `required_densitometer_id`, `status` and `indication`."

        Design: Corner/endpoints/order_worklist_filters_compose_with_limit_and_offset
        """
        patient_a, order_a1, order_a2, order_a3 = _worklist_of_four_orders(world)

        rows, meta = validate_paginated(world.api.list_scan_orders(SCHEDULER_HEADERS))
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 4

        rows, meta = validate_paginated(
            world.api.list_scan_orders(SCHEDULER_HEADERS, {"patient_id": patient_a["id"]})
        )
        assert meta["total_count"] == 3
        assert [row["patient_id"] for row in rows] == [patient_a["id"]] * 3

        rows, meta = validate_paginated(
            world.api.list_scan_orders(
                SCHEDULER_HEADERS,
                {"patient_id": patient_a["id"], "indication": "BASELINE_SCREENING"},
            )
        )
        assert meta["total_count"] == 2
        assert_ids_in_order(rows, [order_a1["id"], order_a3["id"]])

        rows, meta = validate_paginated(
            world.api.list_scan_orders(
                SCHEDULER_HEADERS,
                {"patient_id": patient_a["id"], "limit": 2, "offset": 0},
            )
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert_ids_in_order(rows, [order_a1["id"], order_a2["id"]])

        rows, meta = validate_paginated(
            world.api.list_scan_orders(
                SCHEDULER_HEADERS,
                {"patient_id": patient_a["id"], "limit": 2, "offset": 2},
            )
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert_ids_in_order(rows, [order_a3["id"]])

        rows, meta = validate_paginated(
            world.api.list_scan_orders(SCHEDULER_HEADERS, {"status": "SCHEDULED"})
        )
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert rows == []


QC_DAY_TWO = "2026-03-03T08:00:00Z"


class TestAPassingQcRunWritesItsParentsControlFields:
    """The run itself is immutable; its whole effect is on the densitometer."""

    def test_two_clean_runs_leave_the_device_active_with_a_count_of_two(
        self, world: ProgramWorld
    ):
        """Exactly one standard deviation is still a pass, and still advances the count.

        "an absolute value of at most 1.000 is a `PASS`, an absolute value greater than
        1.000 but at most 1.500 is a `WARN`, and an absolute value greater than 1.500 is
        a `FAIL`. Both boundaries are inclusive on the gentler side, so exactly 1.000
        passes and exactly 1.500 warns rather than failing."
        "Otherwise, on a `PASS`, `consecutive_qc_pass_count` increments by one"
        "In every case the device's `last_qc_result` and `last_qc_run_at` are refreshed
        from the most recent daily run."
        "QC control chart, ordered `performed_at_utc` descending then `created_at`
        descending."

        Design: Corner/endpoints/passing_daily_qc_writes_the_device_control_fields_and_is_immediately_readable
        """
        world.set_clock(CLOCK_SETUP)
        device = world.create_device()

        first = validate_success(
            world.api.create_qc_run(
                device["id"],
                qc_run_payload(phantom_bmd_g_cm2=1.0050),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_qc_scoring(first, 0.0050, 0.500, "PASS")
        assert first["shift_detected"] is False
        assert first["calibration_event_id"] is None
        assert first["performed_by_user_id"] == "tech-001"
        assert_instant_equals(first["performed_at_utc"], CLOCK_SETUP, "performed_at_utc")

        world.set_clock(QC_DAY_TWO)
        second = validate_success(
            world.api.create_qc_run(
                device["id"],
                qc_run_payload(phantom_bmd_g_cm2=1.0100),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_qc_scoring(second, 0.0100, 1.000, "PASS")

        reread = world.read_device(device["id"])
        assert reread["status"] == "ACTIVE"
        assert reread["last_qc_result"] == "PASS"
        assert_instant_equals(reread["last_qc_run_at"], QC_DAY_TWO, "last_qc_run_at")
        assert reread["consecutive_qc_pass_count"] == 2
        assert reread["qc_hold_started_at"] is None
        assert reread["qc_hold_reason_code"] is None

        rows, meta = validate_paginated(
            world.api.list_qc_runs(
                ADMIN_HEADERS, {"densitometer_id": device["id"], "purpose": "DAILY_QC"}
            )
        )
        assert meta["total_count"] == 2
        assert rows[0]["id"] == second["id"]

        unchanged = get_success_data(world.api.get_qc_run(first["id"], ADMIN_HEADERS))
        assert_three_decimals(unchanged["deviation_sd_units"], 0.500, "deviation_sd_units")
        assert unchanged["result"] == "PASS"


PLAN_START = "2026-03-10"
REVIEW_TOO_EARLY = "2026-06-01T08:00:00Z"
REVIEW_JUST_IN_TIME = "2026-06-03T08:00:00Z"


class TestBothAdherenceActionsReadTheLogicalClock:
    """A refill has a window with two edges, and a review has an opening date."""

    def test_out_of_window_refills_and_an_early_review_are_refused(
        self, world: ProgramWorld
    ):
        """The same two calls are refused and then accepted on the clock alone.

        "The `dispensed_date` must fall on or after the plan's `start_date` and strictly
        before the logical clock date, otherwise the request is refused with
        `ERR_REFILL_DATE_OUT_OF_WINDOW`."
        "A review is accepted only when the logical clock date is at or after
        `next_followup_due_date` less seven days — a one-week early window — and is
        otherwise refused with `ERR_FOLLOWUP_NOT_DUE`."
        "`medication_possession_ratio` is `covered_days_supplied` divided by
        `adherence_window_days`, clamped to a maximum of 1.5, and then rounded half up to
        three decimal places"

        Design: Corner/endpoints/refill_and_review_windows_gate_the_adherence_action_endpoints
        """
        pipeline = world.build(
            stop_after="finalized",
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
        )
        plan = world.create_plan(
            pipeline.patient_id,
            pipeline.report_id,
            drug_class="BISPHOSPHONATE_ORAL",
            start_date=PLAN_START,
        )
        assert plan["followup_interval_months"] == 3
        assert plan["next_followup_due_date"] == "2026-06-10"
        assert plan["status"] == "INITIATED"
        assert plan["adherence_status"] == "NOT_ASSESSED"
        assert plan["adherence_source_policy"] == "CLAIMS_ONLY"

        before_start = world.api.create_adherence_refill(
            plan["id"],
            refill_payload(dispensed_date="2026-03-01", days_supplied=90),
            PHYSICIAN_HEADERS,
        )
        validate_error(before_start, ApiErrorId.REFILL_DATE_OUT_OF_WINDOW.value, 422)

        world.set_clock(REVIEW_TOO_EARLY)
        after_the_clock = world.api.create_adherence_refill(
            plan["id"],
            refill_payload(dispensed_date="2026-06-05", days_supplied=30),
            PHYSICIAN_HEADERS,
        )
        validate_error(after_the_clock, ApiErrorId.REFILL_DATE_OUT_OF_WINDOW.value, 422)

        accepted = validate_success(
            world.api.create_adherence_refill(
                plan["id"],
                refill_payload(dispensed_date=PLAN_START, days_supplied=90),
                PHYSICIAN_HEADERS,
            ),
            201,
        )
        assert accepted["source_weight"] == 1.0
        assert accepted["coverage_end_date"] == "2026-06-08"

        too_early = world.api.create_adherence_review(plan["id"], {}, PHYSICIAN_HEADERS)
        validate_error(too_early, ApiErrorId.FOLLOWUP_NOT_DUE.value, 409)
        assert world.read_plan(plan["id"])["adherence_review_count"] == 0

        world.set_clock(REVIEW_JUST_IN_TIME)
        reviewed = validate_success(
            world.api.create_adherence_review(plan["id"], {}, PHYSICIAN_HEADERS), 200
        )
        assert reviewed["adherence_window_days"] == 85
        assert reviewed["covered_days_supplied"] == 90.0
        assert_three_decimals(
            reviewed["medication_possession_ratio"], 1.059, "medication_possession_ratio"
        )
        assert reviewed["adherence_status"] == "ADHERENT"
        assert reviewed["status"] == "ON_THERAPY"
        assert reviewed["last_review_date"] == "2026-06-03"
        assert reviewed["next_followup_due_date"] == "2026-09-03"
        assert reviewed["adherence_review_count"] == 1
        assert reviewed["consecutive_nonadherent_reviews"] == 0
        assert reviewed["cumulative_therapy_months"] == 2
        assert reviewed["denosumab_gap_days"] is None
        assert reviewed["holiday_eligible"] is False

        _, meta = validate_paginated(
            world.api.list_adherence_refills(plan["id"], PHYSICIAN_HEADERS)
        )
        assert meta["total_count"] == 1
