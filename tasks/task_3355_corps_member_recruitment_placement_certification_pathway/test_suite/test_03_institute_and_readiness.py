"""Institute stipend proration and the readiness-score credit lookup."""
import pytest

from test_helpers import assert_readiness_matches_formula, validate_success

from test_helpers.fixtures import (
    INSTITUTE_DIRECTOR,
    complete_and_verify_milestone,
    get_member,
    milestones_by_type,
    record_practice_hours,
    setup_member_scenario,
    setup_member_with_fully_verified_schedule,
)


class TestInstituteStipend:
    """The stipend rounds each week's amount before summing."""

    def test_six_full_weeks_of_practice_pay_75114_cents(self, api):
        """PRD §3.4: "The annual stipend of 6510.00 dollars is divided by the 52 weeks of the year, and that quotient is rounded half up to 2 decimal places, which fixes the weekly amount at 125.19 dollars."
        PRD §3.4: "Rounding each week's amount and the partial amount to 2 decimals before summing — rather than summing in full precision and rounding once at the end — is a deliberate requirement, because the two orders produce different cents for some hour totals."

        240 hours is six whole weeks with no remainder: 6 * 12519 = 75114
        cents under the pinned order, while summing first would give 75115.

        Design: Difficulty/combinatorial_formula/institute_stipend_round_per_week_mode_b
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]

        data = validate_success(
            api.record_practice_hours(member_id, 240, INSTITUTE_DIRECTOR)
        )
        assert data["practice_teaching_hours"] == 240
        assert data["institute_status"] == "IN_TRAINING"
        assert data["institute_stipend_cents"] == 75114, (
            "6 whole weeks * 12519 cents; the rejected sum-then-round order gives 75115"
        )

    def test_partial_week_pays_only_the_prorated_partial(self, api):
        """PRD §3.4: "a member who has not yet accumulated a full week therefore has a whole-week count of zero and is paid only the prorated partial."
        PRD §3.4: "The partial week is paid pro rata — the weekly amount multiplied by the remainder and divided by 40, rounded half up to 2 decimal places."

        39 hours: 125.19 * 39 / 40 = 122.06025 -> 122.06 dollars -> 12206 cents.

        Design: Difficulty/combinatorial_formula/institute_stipend_round_per_week_mode_b
        """
        scenario = setup_member_scenario()
        data = validate_success(
            api.record_practice_hours(scenario["member_id"], 39, INSTITUTE_DIRECTOR)
        )
        assert data["practice_teaching_hours"] == 39
        assert data["institute_stipend_cents"] == 12206

    def test_exactly_one_week_pays_the_rounded_weekly_amount(self, api):
        """PRD §3.4: "The stipend in dollars is the whole-week count multiplied by the weekly amount, plus the prorated partial amount"

        Design: Difficulty/combinatorial_formula/institute_stipend_round_per_week_mode_b
        """
        scenario = setup_member_scenario()
        data = validate_success(
            api.record_practice_hours(scenario["member_id"], 40, INSTITUTE_DIRECTOR)
        )
        assert data["practice_teaching_hours"] == 40
        assert data["institute_stipend_cents"] == 12519, (
            "one whole week at the pinned weekly amount of 125.19 dollars"
        )


class TestReadinessScore:
    """The support credit is keyed on the pre-credit subtotal."""

    def test_credit_is_keyed_on_the_subtotal_before_it_is_added(self, api):
        """PRD §3.5: "The three ratios are weighted 0.5, 0.3 and 0.2 respectively, scaled to 100, and rounded half up to 2 decimal places to give a subtotal."
        PRD §3.5: "The credit is keyed on the subtotal as it stood before the credit was added; the tier is never re-derived from the final score."

        certified 180/240 = 0.75, practice 84/120 = 0.7 and coursework 60/60
        = 1.0 give a subtotal of 78.50, which lands in QUALIFIED and earns
        the 1.5 credit: 80.00, not the 81.50 a post-credit re-key would give.

        Design: Difficulty/combinatorial_formula/readiness_score_credit_keyed_on_subtotal_mode_c
        """
        scenario = setup_member_scenario()
        member_id = scenario["member_id"]
        record_practice_hours(member_id, 84)

        milestones = milestones_by_type(member_id)
        complete_and_verify_milestone(milestones["COURSEWORK"]["id"])
        complete_and_verify_milestone(milestones["PRACTICUM"]["id"])

        member = get_member(member_id)
        assert member["certification_hours_verified"] == 180
        assert member["coursework_hours_completed"] == 60
        assert member["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "subtotal 78.50 + QUALIFIED credit 1.5"
        )
        assert_readiness_matches_formula(
            member, list(milestones_by_type(member_id).values()), scenario["pathway"]
        )

    def test_full_schedule_saturates_the_ceiling(self, api):
        """PRD §3.5: "The final `readiness_score` is the subtotal plus the credit, rounded half up to 2 decimal places and capped at 100.0."

        With every hour-bearing milestone verified the subtotal is 100.00;
        adding the STRONG credit of 3.0 would give 103.00 without the cap.

        Design: Difficulty/combinatorial_formula/readiness_score_credit_keyed_on_subtotal_mode_c
        """
        scenario = setup_member_with_fully_verified_schedule()
        member = get_member(scenario["member_id"])
        assert member["certification_hours_verified"] == 240
        assert member["readiness_score"] == pytest.approx(100.00, abs=0.01)
