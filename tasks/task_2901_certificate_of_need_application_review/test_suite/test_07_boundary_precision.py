"""Boundaries: the occupancy tier at exactly the threshold, and an empty candidate set."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_four_decimal_value,
    validate_error,
)
from test_helpers.constants import SOUTH_HSA
from test_helpers.fixtures import (
    OFFICER,
    advance_cycle,
    refresh_cycle,
    seed_batching_cycle,
    seed_health_service_area,
    seed_state_plan_formula,
)


class TestOccupancyTierThresholdBoundary:
    def test_exactly_one_hundred_provisional_beds_selects_the_high_volume_rate(self):
        """100.0000 satisfies the greater-than-or-equal test at the threshold.

        PRD §3.2: "Third — and this is the step that makes the calculation look
        circular without being so — the occupancy tier is selected from the
        **stored** four-decimal value of `provisional_required_beds`:
        `selected_target_occupancy_rate` becomes
        `high_volume_target_occupancy_rate` when `provisional_required_beds` is
        greater than or equal to `high_volume_bed_threshold`, and stays at
        `base_target_occupancy_rate` otherwise."

        Design: Difficulty/boundary_precision_check/occupancy_tier_boundary_at_exactly_high_volume_threshold
        """
        formula = seed_state_plan_formula()
        north = seed_batching_cycle(formula=formula)["cycle"]

        assert_four_decimal_value(north["projected_patient_days"], 27375.0000)
        assert_four_decimal_value(north["provisional_required_beds"], 100.0000)
        assert north["selected_target_occupancy_rate"] == 0.85
        assert north["required_beds_final"] == 89
        assert north["unmet_bed_need_at_open"] == 19

    def test_two_people_fewer_falls_below_the_threshold_and_keeps_the_base_rate(self):
        """99.9963 misses the same threshold and moves the pool by 11 beds.

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

        Design: Difficulty/boundary_precision_check/occupancy_tier_boundary_at_exactly_high_volume_threshold
        """
        formula = seed_state_plan_formula()
        south_hsa = seed_health_service_area(**SOUTH_HSA)

        south = seed_batching_cycle(hsa=south_hsa, formula=formula)["cycle"]

        assert_four_decimal_value(south["projected_patient_days"], 27374.0000)
        assert_four_decimal_value(south["provisional_required_beds"], 99.9963)
        assert south["selected_target_occupancy_rate"] == 0.75
        assert south["required_beds_final"] == 100
        assert south["unmet_bed_need_at_open"] == 30

    def test_the_two_areas_diverge_by_eleven_beds_on_the_same_formula(self):
        """One shared formula, a two-person gap, and a different tier each side.

        PRD §3.2: "Fourth, `required_beds_final` is `projected_patient_days`
        divided by the product of 365 and `selected_target_occupancy_rate`, taken
        as the ceiling to a whole bed."
        PRD §3.2: "The tier is chosen exactly once, from the base-occupancy pass,
        and is never re-selected from the result of the next step, even when that
        result falls on the other side of the threshold."

        Design: Difficulty/boundary_precision_check/occupancy_tier_boundary_at_exactly_high_volume_threshold
        """
        formula = seed_state_plan_formula()
        north = seed_batching_cycle(formula=formula)["cycle"]
        south_hsa = seed_health_service_area(**SOUTH_HSA)
        south = seed_batching_cycle(hsa=south_hsa, formula=formula)["cycle"]

        assert north["pinned_formula_version"] == south["pinned_formula_version"]
        assert (
            south["unmet_bed_need_at_open"] - north["unmet_bed_need_at_open"] == 11
        )
        assert north["selected_target_occupancy_rate"] != south[
            "selected_target_occupancy_rate"
        ]


class TestEmptyCandidateSetBoundary:
    def test_a_cycle_with_no_applications_cannot_be_decided(self):
        """The zero-cardinality candidate set is refused, not decorated.

        PRD §3.7: "The candidate set must be non-empty, or
        `ERR_NO_ELIGIBLE_APPLICATIONS`."
        PRD §3.7: "The candidate set is precisely the applications of this cycle
        whose `status` is `COMPARATIVE_REVIEW` or `REMANDED`."

        Design: Difficulty/boundary_precision_check/comparative_decision_on_empty_candidate_set_yields_no_eligible_applications
        """
        world = seed_batching_cycle()
        cycle_id = world["cycle"]["id"]
        advance_cycle(cycle_id, "OPEN_FOR_APPLICATIONS")
        advance_cycle(cycle_id, "COMPLETENESS_WINDOW")
        advance_cycle(cycle_id, "COMPARATIVE_REVIEW")

        response = api_client.run_comparative_decision(
            cycle_id, {"decision_note": "Nothing to decide"}, OFFICER
        )

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_APPLICATIONS, 422)

    def test_the_refused_decision_leaves_the_cycle_in_comparative_review(self):
        """No DECIDED status and no drained pool follow a refused decision.

        PRD §3.7: "The pool being distributed is `unmet_bed_need_at_open`, the
        figure fixed when the cycle was opened or last recomputed — not the live
        area inventory, and not the current `unallocated_bed_need`."
        PRD §3.2: "The permitted sequence is `OPEN_FOR_LOI` →
        `OPEN_FOR_APPLICATIONS` → `COMPLETENESS_WINDOW` → `COMPARATIVE_REVIEW`,
        then `DECIDED` (reached not by an advance but by the comparative decision
        of §3.7), then `CLOSED`; `CLOSED` is terminal."

        Design: Difficulty/boundary_precision_check/comparative_decision_on_empty_candidate_set_yields_no_eligible_applications
        """
        world = seed_batching_cycle()
        cycle_id = world["cycle"]["id"]
        advance_cycle(cycle_id, "OPEN_FOR_APPLICATIONS")
        advance_cycle(cycle_id, "COMPLETENESS_WINDOW")
        advance_cycle(cycle_id, "COMPARATIVE_REVIEW")

        api_client.run_comparative_decision(
            cycle_id, {"decision_note": "Nothing to decide"}, OFFICER
        )

        cycle = refresh_cycle(cycle_id)
        assert cycle["status"] == "COMPARATIVE_REVIEW"
        assert cycle["unallocated_bed_need"] == 19
        assert cycle["unmet_bed_need_at_open"] == 19
