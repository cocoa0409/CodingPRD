"""Combinatorial formulas: the pinned need methodology and the score rounding order.

Both computations look circular or order-free until the pinned evaluation order
is honoured, and both are asserted against pre-computed literals.
"""

from test_helpers import (
    api_client,
    assert_batching_cycle,
    assert_four_decimal_value,
    assert_score,
    validate_paginated,
)
from test_helpers.constants import (
    SCORE_ONE_SHEET,
    SCORE_THREE_SHEETS,
    SCORE_TWO_SHEETS,
    SHEET_REV_1,
    SHEET_REV_2,
    SHEET_REV_3,
)
from test_helpers.fixtures import (
    ADMIN,
    file_score_sheet,
    refresh_application,
    seed_batching_cycle,
    seed_comparative_review,
    seed_health_service_area,
    seed_state_plan_formula,
)
from test_helpers.test_users import (
    REVIEWER_USER_ID_1,
    REVIEWER_USER_ID_2,
    REVIEWER_USER_ID_3,
)


class TestNeedMethodologyEvaluationOrder:
    def test_cycle_creation_pins_the_high_volume_tier_from_the_base_pass(self):
        """54750 people and a 100-bed tier threshold give 0.85 and 89 beds.

        PRD §3.2: "First, demand is converted into patient days:
        `projected_patient_days` is the area's `population_projection` divided
        by 1000, multiplied by the formula's `use_rate_per_1000`, multiplied by
        its `average_length_of_stay_days`, with the result rounded half up to 4
        decimal places."
        PRD §3.2: "Second, a provisional bed requirement is taken at the base
        occupancy: `provisional_required_beds` is `projected_patient_days`
        divided by the product of 365 days per year and
        `base_target_occupancy_rate`, rounded half up to 4 decimal places."
        PRD §3.2: "The tier is chosen exactly once, from the base-occupancy
        pass, and is never re-selected from the result of the next step, even
        when that result falls on the other side of the threshold."
        PRD §3.2: "Fourth, `required_beds_final` is `projected_patient_days`
        divided by the product of 365 and `selected_target_occupancy_rate`,
        taken as the ceiling to a whole bed."

        Design: Difficulty/combinatorial_formula/need_methodology_occupancy_tier_pinned_evaluation_order
        """
        world = seed_batching_cycle()
        cycle = world["cycle"]

        assert_batching_cycle(cycle)
        assert_four_decimal_value(cycle["projected_patient_days"], 27375.0000)
        assert_four_decimal_value(cycle["provisional_required_beds"], 100.0000)
        assert cycle["selected_target_occupancy_rate"] == 0.85
        assert cycle["required_beds_final"] == 89
        assert cycle["inventory_beds_at_open"] == 70
        assert cycle["unmet_bed_need_at_open"] == 19
        assert cycle["unallocated_bed_need"] == 19
        assert cycle["pinned_formula_version"] == 1

    def test_final_bed_count_does_not_re_select_the_base_tier(self):
        """89 final beds fall below the 100-bed threshold yet 0.85 still governs.

        PRD §3.2: "Third — and this is the step that makes the calculation look
        circular without being so — the occupancy tier is selected from the
        **stored** four-decimal value of `provisional_required_beds`:
        `selected_target_occupancy_rate` becomes
        `high_volume_target_occupancy_rate` when `provisional_required_beds` is
        greater than or equal to `high_volume_bed_threshold`, and stays at
        `base_target_occupancy_rate` otherwise."
        PRD §3.2: "There is one base pass and one final pass; there is no
        iteration to a fixed point."

        Design: Difficulty/combinatorial_formula/need_methodology_occupancy_tier_pinned_evaluation_order
        """
        world = seed_batching_cycle()
        cycle = world["cycle"]

        assert cycle["required_beds_final"] < 100
        assert cycle["selected_target_occupancy_rate"] == 0.85
        assert cycle["selected_target_occupancy_rate"] != 0.75

    def test_provisional_below_the_tier_threshold_keeps_the_base_rate(self):
        """Raising the threshold to 101 leaves the base 0.75 rate in force.

        PRD §3.2: "Third — and this is the step that makes the calculation look
        circular without being so — the occupancy tier is selected from the
        **stored** four-decimal value of `provisional_required_beds`:
        `selected_target_occupancy_rate` becomes
        `high_volume_target_occupancy_rate` when `provisional_required_beds` is
        greater than or equal to `high_volume_bed_threshold`, and stays at
        `base_target_occupancy_rate` otherwise."
        PRD §3.2: "Fifth, inventory and need are captured:
        `inventory_beds_at_open` is the area's `existing_licensed_beds` plus its
        `approved_unimplemented_beds` as they stand at that instant, and
        `unmet_bed_need_at_open` is the greater of 0 and `required_beds_final`
        minus `inventory_beds_at_open`."

        Design: Difficulty/combinatorial_formula/need_methodology_occupancy_tier_pinned_evaluation_order
        """
        hsa = seed_health_service_area()
        formula = seed_state_plan_formula(high_volume_bed_threshold=101)

        world = seed_batching_cycle(hsa=hsa, formula=formula)
        cycle = world["cycle"]

        assert_four_decimal_value(cycle["provisional_required_beds"], 100.0000)
        assert cycle["selected_target_occupancy_rate"] == 0.75
        assert cycle["required_beds_final"] == 100
        assert cycle["unmet_bed_need_at_open"] == 30


class TestComparativeScoreRoundingOrder:
    def test_three_sheets_round_each_criterion_before_weighting(self):
        """The pinned order gives 79.70 where weighting the raw means gives 79.45.

        PRD §3.7: "Otherwise, for each of the five criteria independently, the
        arithmetic mean of that criterion's scores across the contributing
        sheets is taken and immediately rounded half up to a whole number of
        points."
        PRD §3.7: "Rounding each criterion mean to whole points first gives 90,
        78, 68, 90 and 61, and weighting those gives a `comparative_score` of
        79.70."
        PRD §3.7: "Weighting the unrounded means instead and rounding only the
        total gives 79.45."

        Design: Difficulty/combinatorial_formula/comparative_score_per_criterion_rounding_before_weighting
        """
        world = seed_comparative_review()
        application = world["application"]
        file_score_sheet(application, SHEET_REV_1, REVIEWER_USER_ID_1)
        application = refresh_application(application["id"])
        file_score_sheet(application, SHEET_REV_2, REVIEWER_USER_ID_2)
        application = refresh_application(application["id"])

        sheet_3 = file_score_sheet(application, SHEET_REV_3, REVIEWER_USER_ID_3)

        application = refresh_application(application["id"])
        assert application["score_sheet_count"] == 3
        assert_score(application["comparative_score"], SCORE_THREE_SHEETS)
        assert application["comparative_score"] != 79.45
        assert sheet_3["status"] == "ACTIVE"
        assert sheet_3["reviewer_user_id"] == REVIEWER_USER_ID_3

    def test_score_is_recomputed_on_every_submission(self):
        """One sheet gives 78.65 and the second lifts a 89.5 mean to 90 points.

        PRD §3.7: "Every submission — first or revised — recomputes the parent
        application's `comparative_score` and `score_sheet_count` and increases
        the application's `version` by 1."
        PRD §3.7: "The five products are summed, and that sum is rounded half up
        to 2 decimal places to give `comparative_score`."

        Design: Difficulty/combinatorial_formula/comparative_score_per_criterion_rounding_before_weighting
        """
        world = seed_comparative_review()
        application = world["application"]
        version_before = application["version"]

        file_score_sheet(application, SHEET_REV_1, REVIEWER_USER_ID_1)
        application = refresh_application(application["id"])
        assert application["score_sheet_count"] == 1
        assert_score(application["comparative_score"], SCORE_ONE_SHEET)
        assert application["version"] == version_before + 1

        file_score_sheet(application, SHEET_REV_2, REVIEWER_USER_ID_2)
        application = refresh_application(application["id"])
        assert application["score_sheet_count"] == 2
        assert_score(application["comparative_score"], SCORE_TWO_SHEETS)
        assert application["version"] == version_before + 2

    def test_score_sheet_list_shows_every_active_sheet(self):
        """All three sheets stay ACTIVE because each reviewer filed once.

        PRD §3.7: "When a reviewer files a second sheet on the same
        application, the reviewer's own earlier `ACTIVE` sheet on that
        application is set to `SUPERSEDED`, so exactly one `ACTIVE` sheet per
        reviewer per application survives."
        PRD §3.7: "First, the set of contributing sheets is fixed: only sheets
        on this application whose `status` is `ACTIVE` participate, and
        `score_sheet_count` is how many there are."

        Design: Difficulty/combinatorial_formula/comparative_score_per_criterion_rounding_before_weighting
        """
        world = seed_comparative_review()
        application = world["application"]
        for scores, reviewer in (
            (SHEET_REV_1, REVIEWER_USER_ID_1),
            (SHEET_REV_2, REVIEWER_USER_ID_2),
            (SHEET_REV_3, REVIEWER_USER_ID_3),
        ):
            application = refresh_application(application["id"])
            file_score_sheet(application, scores, reviewer)

        sheets, meta = validate_paginated(
            api_client.list_score_sheets(application["id"], ADMIN)
        )

        assert meta["total_count"] == 3
        assert len(sheets) == 3
        assert all(sheet["status"] == "ACTIVE" for sheet in sheets)
        assert {sheet["reviewer_user_id"] for sheet in sheets} == {
            REVIEWER_USER_ID_1,
            REVIEWER_USER_ID_2,
            REVIEWER_USER_ID_3,
        }
