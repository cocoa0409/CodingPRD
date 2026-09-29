"""Derived arithmetic: review thresholds, need methodology, waterfall, extensions."""

from test_helpers import (
    api_client,
    assert_cycle_pool_invariant,
    assert_four_decimal_value,
    assert_instant_equals,
    get_success_data,
)
from test_helpers.constants import (
    DECISION_CLOCK,
    DEFAULT_CLOCK,
    ISSUANCE_CLOCK,
    SHEET_B_REV_1,
    SHEET_B_REV_2,
    SHEET_REV_1,
    SHEET_REV_2,
)
from test_helpers.factories import batching_cycle_payload
from test_helpers.fixtures import (
    ADMIN,
    INTAKE,
    OFFICER,
    advance_cycle,
    create_application,
    file_letter_of_intent,
    file_score_sheet,
    issue_certificate,
    refresh_application,
    refresh_certificate,
    run_comparative_decision,
    seed_applicant,
    seed_batching_cycle,
    seed_reference_data,
    seed_second_applicant,
    seed_state_plan_formula,
    set_clock,
    submit_application,
)
from test_helpers.test_users import (
    REVIEWER_USER_ID_1,
    REVIEWER_USER_ID_2,
    make_applicant_headers,
)

MRI_CALENDAR = {
    "loi_deadline_at": "2026-08-10T00:00:00Z",
    "application_deadline_at": "2026-08-20T00:00:00Z",
    "comment_period_closes_at": "2026-08-25T00:00:00Z",
    "intervention_deadline_at": "2026-08-28T00:00:00Z",
    "completeness_deadline_at": "2026-09-05T00:00:00Z",
    "decision_deadline_at": "2026-09-30T00:00:00Z",
}


def _two_candidates_scored_two_sheets_each():
    """A 19-bed pool with A at 79.40 wanting 12 and B at 75.10 wanting 10."""
    set_clock(DEFAULT_CLOCK)
    world = seed_batching_cycle()
    applicant_a = seed_applicant()
    applicant_b = seed_second_applicant()
    world["applicant"] = applicant_a
    world["loi_a"] = file_letter_of_intent(world, applicant_a)
    world["loi_b"] = file_letter_of_intent(
        world,
        applicant_b,
        project_description="10-bed acute care expansion",
        capital_cost_cents=600000000,
        bed_delta=10,
    )
    world["application_a"] = create_application(world, applicant_a, world["loi_a"])
    world["application_b"] = create_application(
        world,
        applicant_b,
        world["loi_b"],
        requested_bed_count=10,
        projected_capital_cost_cents=600000000,
        narrative="Lakeview 10-bed acute care application",
        partial_award_acceptable=True,
    )
    world["cycle"] = advance_cycle(world["cycle"]["id"], "OPEN_FOR_APPLICATIONS")
    world["application_a"] = submit_application(world["application_a"], applicant_a)
    world["application_b"] = submit_application(world["application_b"], applicant_b)
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPLETENESS_WINDOW")
    for key in ("application_a", "application_b"):
        world[key] = get_success_data(
            api_client.deem_application_complete(world[key]["id"], INTAKE)
        )
    world["cycle"] = advance_cycle(world["cycle"]["id"], "COMPARATIVE_REVIEW")

    for key, sheets in (
        ("application_a", (SHEET_REV_1, SHEET_REV_2)),
        ("application_b", (SHEET_B_REV_1, SHEET_B_REV_2)),
    ):
        for scores, reviewer in zip(
            sheets, (REVIEWER_USER_ID_1, REVIEWER_USER_ID_2)
        ):
            world[key] = refresh_application(world[key]["id"])
            file_score_sheet(world[key], scores, reviewer)
        world[key] = refresh_application(world[key]["id"])
    return world


class TestReviewThresholdDetermination:
    def test_a_small_first_filing_is_not_subject_to_review(self):
        """No priors, so the project basis governs and both tests miss.

        PRD §3.3: "`project_basis_reviewable` is true when at least one of three
        tests passes: the letter's own `capital_cost_cents` is at least 500000000
        cents (five million dollars); or its own `bed_delta` is at least 10 beds; or
        its `service_type` is one of the three categories the state always reviews
        regardless of size — `OPEN_HEART_SURGERY`, `MRI_UNIT` or
        `NURSING_HOME_BEDS`."
        PRD §3.3: "`aggregate_capital_cost_cents` is this letter's own
        `capital_cost_cents` plus the sum of the qualifying priors'
        `capital_cost_cents`, and `aggregate_bed_delta` is this letter's own
        `bed_delta` plus the sum of the priors' `bed_delta`."
        PRD §3.3: "`governing_review_basis` is `AGGREGATED_24_MONTH` when
        `prior_window_loi_count` is 1 or more, and `PROJECT_BASED` when it is 0."
        PRD §3.3: "`review_determination` is then `REVIEWABLE` when the governing
        variant's flag is true, and `NON_REVIEWABLE` when it is false."

        Design: Corner/calculations/first_letter_of_intent_below_both_thresholds_is_non_reviewable
        """
        set_clock(DEFAULT_CLOCK)
        world = seed_batching_cycle()
        applicant = seed_applicant()
        world["applicant"] = applicant

        loi = file_letter_of_intent(
            world,
            applicant,
            project_description="Three-bed observation annex",
            capital_cost_cents=250000000,
            bed_delta=3,
        )

        assert loi["review_determination"] == "NON_REVIEWABLE"
        assert loi["governing_review_basis"] == "PROJECT_BASED"
        assert loi["prior_window_loi_count"] == 0
        assert loi["project_basis_reviewable"] is False
        assert loi["aggregated_basis_reviewable"] is False
        assert loi["aggregate_capital_cost_cents"] == 250000000
        assert loi["aggregate_bed_delta"] == 3
        assert_instant_equals(loi["filed_at"], DEFAULT_CLOCK)

    def test_an_always_reviewable_category_overrides_both_size_thresholds(self):
        """A one-million-dollar two-unit MRI project is reviewable on category alone.

        PRD §3.3: "`project_basis_reviewable` is true when at least one of three
        tests passes: the letter's own `capital_cost_cents` is at least 500000000
        cents (five million dollars); or its own `bed_delta` is at least 10 beds; or
        its `service_type` is one of the three categories the state always reviews
        regardless of size — `OPEN_HEART_SURGERY`, `MRI_UNIT` or
        `NURSING_HOME_BEDS`."
        PRD §3.3: "Then `aggregated_basis_reviewable` is true when at least one of
        the same three tests passes against the aggregates:
        `aggregate_capital_cost_cents` is at least 500000000 cents, or
        `aggregate_bed_delta` is at least 10 beds, or the `service_type` is one of
        the three always-reviewable categories."
        PRD §3.3: "`governing_review_basis` is `AGGREGATED_24_MONTH` when
        `prior_window_loi_count` is 1 or more, and `PROJECT_BASED` when it is 0."

        Design: Corner/calculations/always_reviewable_service_type_forces_a_tiny_mri_project_to_be_reviewable
        """
        set_clock(DEFAULT_CLOCK)
        reference = seed_reference_data()
        mri_formula = seed_state_plan_formula(service_type="MRI_UNIT")
        mri_cycle = get_success_data(
            api_client.create_batching_cycle(
                batching_cycle_payload(
                    reference["hsa"]["id"],
                    mri_formula["id"],
                    service_type="MRI_UNIT",
                    **MRI_CALENDAR,
                ),
                ADMIN,
            ),
            201,
        )
        applicant = seed_applicant()

        loi = get_success_data(
            api_client.create_letter_of_intent(
                {
                    "applicant_id": applicant["id"],
                    "hsa_id": reference["hsa"]["id"],
                    "batching_cycle_id": mri_cycle["id"],
                    "service_type": "MRI_UNIT",
                    "project_description": "Single replacement MRI unit",
                    "capital_cost_cents": 100000000,
                    "bed_delta": 2,
                },
                make_applicant_headers(applicant["id"]),
            ),
            201,
        )

        assert loi["review_determination"] == "REVIEWABLE"
        assert loi["project_basis_reviewable"] is True
        assert loi["aggregated_basis_reviewable"] is True
        assert loi["governing_review_basis"] == "PROJECT_BASED"
        assert loi["prior_window_loi_count"] == 0
        assert loi["aggregate_capital_cost_cents"] == 100000000
        assert loi["aggregate_bed_delta"] == 2


class TestNeedMethodologyReadAndRecompute:
    def test_the_need_analysis_read_exposes_the_four_decimal_intermediates(self):
        """Every step of the derivation is readable, and the pin is fresh.

        PRD §3.2: "A separate read-only need analysis exposes the whole derivation
        for inspection, returning `projected_patient_days`,
        `provisional_required_beds`, `selected_target_occupancy_rate`,
        `required_beds_final`, `inventory_beds`, `unmet_bed_need`,
        `unallocated_bed_need`, `pinned_formula_version`, `formula_current_version`
        and a boolean `formula_pin_stale` that says whether the pinned and current
        formula versions have diverged."
        PRD §3.2: "First, demand is converted into patient days:
        `projected_patient_days` is the area's `population_projection` divided by
        1000, multiplied by the formula's `use_rate_per_1000`, multiplied by its
        `average_length_of_stay_days`, with the result rounded half up to 4 decimal
        places."
        PRD §3.2: "Second, a provisional bed requirement is taken at the base
        occupancy: `provisional_required_beds` is `projected_patient_days` divided
        by the product of 365 days per year and `base_target_occupancy_rate`,
        rounded half up to 4 decimal places."
        PRD §3.2: "Fourth, `required_beds_final` is `projected_patient_days`
        divided by the product of 365 and `selected_target_occupancy_rate`, taken
        as the ceiling to a whole bed."

        Design: Corner/calculations/need_analysis_read_reports_four_decimal_intermediates_with_a_fresh_pin
        """
        world = seed_batching_cycle()

        analysis = get_success_data(
            api_client.get_need_analysis(world["cycle"]["id"], INTAKE)
        )

        assert_four_decimal_value(analysis["projected_patient_days"], 27375.0000)
        assert_four_decimal_value(analysis["provisional_required_beds"], 100.0000)
        assert analysis["selected_target_occupancy_rate"] == 0.85
        assert analysis["required_beds_final"] == 89
        assert analysis["inventory_beds"] == 70
        assert analysis["unmet_bed_need"] == 19
        assert analysis["unallocated_bed_need"] == 19
        assert analysis["pinned_formula_version"] == 1
        assert analysis["formula_current_version"] == 1
        assert analysis["formula_pin_stale"] is False

    def test_an_amendment_stales_the_pin_and_only_a_recompute_moves_the_pool(self):
        """The amendment alone changes nothing stored; the recompute rewrites it.

        PRD §3.1: "Every amendment increases the formula's `version` by exactly 1,
        and that single fact is what makes a cycle's pin stale: any cycle whose
        `pinned_formula_version` no longer equals the formula's current `version` is
        blocked from its comparative decision with `ERR_FORMULA_VERSION_STALE` until
        its need is recomputed."
        PRD §3.2: "Recomputing a cycle's need refreshes `pinned_formula_version` to
        the formula's current `version`, re-executes all five steps against current
        area inventory, and overwrites `unmet_bed_need_at_open` and
        `unallocated_bed_need` with the fresh results."
        PRD §3.2: "Fifth, inventory and need are captured: `inventory_beds_at_open`
        is the area's `existing_licensed_beds` plus its `approved_unimplemented_beds`
        as they stand at that instant, and `unmet_bed_need_at_open` is the greater of
        0 and `required_beds_final` minus `inventory_beds_at_open`."

        Design: Corner/calculations/formula_amendment_marks_the_pin_stale_and_recompute_need_moves_the_pool
        """
        world = seed_batching_cycle()
        assert world["cycle"]["unmet_bed_need_at_open"] == 19

        amended = get_success_data(
            api_client.amend_state_plan_formula(
                world["formula"]["id"], {"use_rate_per_1000": 110.0}, ADMIN
            )
        )
        assert amended["version"] == 2
        stale_read = get_success_data(
            api_client.get_need_analysis(world["cycle"]["id"], INTAKE)
        )
        assert stale_read["formula_pin_stale"] is True
        assert stale_read["unmet_bed_need"] == 19

        recomputed = get_success_data(
            api_client.recompute_need(world["cycle"]["id"], ADMIN)
        )

        assert recomputed["pinned_formula_version"] == 2
        assert_four_decimal_value(recomputed["projected_patient_days"], 30112.5000)
        assert_four_decimal_value(recomputed["provisional_required_beds"], 110.0000)
        assert recomputed["selected_target_occupancy_rate"] == 0.85
        assert recomputed["required_beds_final"] == 98
        assert recomputed["unmet_bed_need_at_open"] == 28
        assert recomputed["unallocated_bed_need"] == 28

        fresh_read = get_success_data(
            api_client.get_need_analysis(world["cycle"]["id"], INTAKE)
        )
        assert fresh_read["formula_pin_stale"] is False


class TestAllocationWaterfall:
    def test_the_top_rank_is_filled_before_the_runner_up_takes_the_remainder(self):
        """12 of 19 to the winner, the surviving 7 to a partial-award candidate.

        PRD §3.7: "Allocation runs as a **waterfall** down a fully pinned ranking:
        highest `comparative_score` first; where two candidates tie on score, the
        smaller `requested_bed_count` first; where they still tie, the earlier
        `created_at` first."
        PRD §3.7: "**Full award.** When the remaining need is greater than or equal
        to the candidate's `requested_bed_count`, the candidate's
        `allocated_bed_count` is set to its full `requested_bed_count`, its `status`
        becomes `APPROVED`, and the remaining need is reduced by that same count."
        PRD §3.7: "**Partial award.** Otherwise, when the remaining need is greater
        than 0 and the candidate's `partial_award_acceptable` is true, the
        candidate's `allocated_bed_count` is set to whatever remaining need is left
        at its rank position, its `status` becomes `APPROVED_WITH_CONDITIONS`, and
        the remaining need drops to 0 — which means every candidate ranked below it
        takes the denial branch."
        PRD §3.7: "After the loop the cycle's `unallocated_bed_need` is set to
        whatever remaining need survived, and the invariant of §2.10 must hold:
        `unallocated_bed_need` plus the sum of `allocated_bed_count` over the
        cycle's `APPROVED` and `APPROVED_WITH_CONDITIONS` applications equals
        `unmet_bed_need_at_open`."

        Design: Corner/calculations/waterfall_awards_the_top_rank_in_full_then_a_partial_award_to_the_runner_up
        """
        world = _two_candidates_scored_two_sheets_each()
        assert world["cycle"]["unmet_bed_need_at_open"] == 19
        assert world["application_a"]["comparative_score"] == 79.40
        assert world["application_b"]["comparative_score"] == 75.10
        set_clock(DECISION_CLOCK)

        cycle = run_comparative_decision(
            world["cycle"]["id"], "Comparative review of the ACUTE_CARE_BEDS batch"
        )

        assert cycle["status"] == "DECIDED"
        application_a = refresh_application(world["application_a"]["id"])
        application_b = refresh_application(world["application_b"]["id"])
        assert application_a["status"] == "APPROVED"
        assert application_a["allocated_bed_count"] == 12
        assert application_b["status"] == "APPROVED_WITH_CONDITIONS"
        assert application_b["allocated_bed_count"] == 7
        assert application_b["denial_reason"] is None
        assert cycle["unallocated_bed_need"] == 0
        assert_cycle_pool_invariant(cycle, [application_a, application_b])


class TestExtensionArithmetic:
    def test_the_grant_is_the_smallest_of_request_ceiling_and_lineage_allowance(self):
        """Three grants bind on three different arms of the same minimum.

        PRD §3.8: "Otherwise the granted days are the smallest of three quantities:
        the `requested_days` asked for, the per-grant ceiling of 365 days, and the
        remaining lineage allowance."
        PRD §3.8: "The granted days are added to `extension_days_granted_total`, and
        `implementation_milestone_date` is pushed forward by exactly that many
        calendar days in UTC."
        PRD §3.8: "`required_completion_pct_at_milestone` is deliberately not
        changed by an extension — the project gets more time, not a lower bar."
        PRD §3.8: "The three-way minimum is not academic: a certificate that has
        already been granted 400 days and asks for 200 more receives 140, because
        the lineage allowance is what binds."

        Design: Corner/calculations/extension_grant_takes_the_nested_minimum_of_request_ceiling_and_lineage_cap
        """
        world = _two_candidates_scored_two_sheets_each()
        set_clock(DECISION_CLOCK)
        run_comparative_decision(world["cycle"]["id"])
        set_clock(ISSUANCE_CLOCK)
        certificate = issue_certificate(
            refresh_application(world["application_a"]["id"])
        )
        assert certificate["implementation_milestone_date"] == "2027-06-30"

        first = get_success_data(
            api_client.extend_certificate(
                certificate["id"],
                {"requested_days": 400, "justification": "Site preparation delays"},
                OFFICER,
            )
        )
        assert first["extension_days_granted_total"] == 365
        assert first["implementation_milestone_date"] == "2028-06-29"

        second = get_success_data(
            api_client.extend_certificate(
                certificate["id"],
                {"requested_days": 35, "justification": "Equipment lead times"},
                OFFICER,
            )
        )
        assert second["extension_days_granted_total"] == 400
        assert second["implementation_milestone_date"] == "2028-08-03"

        third = get_success_data(
            api_client.extend_certificate(
                certificate["id"],
                {"requested_days": 200, "justification": "Final commissioning slip"},
                OFFICER,
            )
        )

        assert third["extension_days_granted_total"] == 540
        assert third["implementation_milestone_date"] == "2028-12-21"
        stored = refresh_certificate(certificate["id"])
        assert stored["required_completion_pct_at_milestone"] == 25
        assert stored["lifecycle_status"] == "ISSUED"
