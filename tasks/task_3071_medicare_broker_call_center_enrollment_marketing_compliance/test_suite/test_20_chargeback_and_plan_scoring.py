"""The day-band schedule for a rapid-disenrollment clawback, and the plan scoring
formula whose pharmacy term is a hard zero.
"""
import pytest

from test_helpers import (
    validate_paginated, api_client, get_success_data, validate_success,
    setup_agency_with_active_agent, setup_scope_and_completed_call,
    get_call, submit_enrollment, set_clock, acknowledge_enrollment,
    effectuate_enrollment, raise_tier_with_repeated_withdrawals,
    setup_three_plan_comparison_scenario, create_plan_comparison_payload,
    TEST_USERS, make_licensed_agent_headers,
)

DIRECTOR = TEST_USERS["director_of_sales_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def _effectuate_enrollment_at_tier(scn, tier: int):
    """Raise the agent's chargeback tier, then leave one EFFECTUATED enrollment."""
    raise_tier_with_repeated_withdrawals(scn, tier)
    call = get_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])
    return enrollment


class TestChargebackBandBeforeTierEscalation:
    """The band is selected first; only then does the tier escalation rewrite it."""

    def test_day_45_disenrollment_at_tier_4_escalates_the_selected_band(self):
        """PRD §3.7: "The third step is a softer escalation, evaluated only when the hard
        escalation did not apply: if the agent's `chargeback_tier` has reached 4 or more,
        the base percentage becomes the base percentage of the band one step higher in the
        list."
        PRD §3.7: "The clawback amount is that absolute initial figure multiplied by the
        final base percentage, rounded half-up to 2 decimal places, and then negated."

        Design: Difficulty/combinatorial_formula/combinatorial_chargeback_band_selected_before_tier_escalation
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        enrollment = _effectuate_enrollment_at_tier(scn, 4)

        set_clock("2026-12-16T00:00:00Z")
        result = validate_success(api_client.disenroll_enrollment(
            enrollment["id"],
            {"disenrollment_date": "2026-12-16T00:00:00Z",
             "disenrollment_reason": "BENEFICIARY_REQUEST"},
            CARRIER_INT), 200)

        assert result["disenrolled_day_number"] == 45
        assert result["is_rapid_disenrollment"] is True

        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": enrollment["id"]}))
        chargebacks = [r for r in rows if r["entry_type"] == "CHARGEBACK"
                       and r["status"] == "FINALIZED"]
        assert len(chargebacks) == 1
        # absolute initial 1500 x 12 x 0.20 = 3600; the day-45 band is DAY_31_60
        # (0.75) and the tier-4 escalation replaces it with the band above (0.50).
        assert chargebacks[0]["amount_cents"] == pytest.approx(-1800.00, abs=0.01)
        assert chargebacks[0]["clawback_pct_applied"] == pytest.approx(0.50, abs=0.001)

    def test_clawback_percentage_is_neither_the_band_nor_the_hard_escalation(self):
        """PRD §3.7: "The same absolute initial figure of 3600 therefore yields -3600 for
        a day-30 disenrollment by an agent at `chargeback_tier` 0, because the 0-to-30 band
        applies at 1.00; -2700 for a day-31 disenrollment by that same tier-0 agent, because
        the 31-to-60 band applies at 0.75; and -3600 again for a day-45 disenrollment by an
        agent whose `chargeback_tier` has reached 4, because the 31-to-60 band is escalated
        one step up to the 1.00 band."

        Design: Difficulty/combinatorial_formula/combinatorial_chargeback_band_selected_before_tier_escalation
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        enrollment = _effectuate_enrollment_at_tier(scn, 4)

        set_clock("2026-12-16T00:00:00Z")
        api_client.disenroll_enrollment(
            enrollment["id"],
            {"disenrollment_date": "2026-12-16T00:00:00Z",
             "disenrollment_reason": "BENEFICIARY_REQUEST"},
            CARRIER_INT)

        rows, _meta = validate_paginated(api_client.list_ledger_entries(
            DIRECTOR, params={"enrollment_id": enrollment["id"]}))
        cb = [r for r in rows if r["entry_type"] == "CHARGEBACK"][0]
        # The tier-4 escalation lands one band higher than the selected DAY_31_60 band,
        # so the applied percentage is neither the un-escalated 0.75 nor the hard-path 1.00.
        assert cb["clawback_pct_applied"] != pytest.approx(0.75, abs=0.001)
        assert cb["clawback_pct_applied"] != pytest.approx(1.00, abs=0.001)

    def test_chargeback_tier_rises_by_one_on_each_withdrawal(self):
        """PRD §3.6: "All three paths move the submission to `WITHDRAWN`, void the scope
        when it had been consumed while leaving a still-`CAPTURED` scope alone, and
        increment the agent's `chargeback_tier` by one."

        Design: Difficulty/combinatorial_formula/combinatorial_chargeback_band_selected_before_tier_escalation
        """
        scn = setup_agency_with_active_agent()
        setup_scope_and_completed_call(scn, member_index=0)
        raise_tier_with_repeated_withdrawals(scn, 4)
        agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
        assert agent["chargeback_tier"] == 4


class TestPlanComparisonPharmacyTerm:
    """A single missing pharmacy row costs exactly the 8.00 pharmacy weight."""

    def _comparison(self, scn):
        headers = make_licensed_agent_headers(scn["agent"]["id"])
        return validate_success(api_client.create_plan_comparison(
            create_plan_comparison_payload(scn["member"]["id"], scn["agent"]["id"],
                                           scn["scope"]["id"]), headers), 201)

    def test_three_candidate_plans_are_scored_and_ranked(self):
        """PRD §3.4: "The candidate set is every plan whose status is `ACTIVE` and whose
        `state_code` and `county_code` both equal the member's; plans in status
        `TERMINATED` never enter the comparison."
        PRD §3.4: "Plans are ranked by descending composite score, with ties broken first
        by ascending `monthly_premium_cents` and then by ascending creation order, and the
        top-ranked plan becomes the recommendation."

        Design: Difficulty/combinatorial_formula/combinatorial_plan_comparison_pharmacy_term_is_a_hard_zero
        """
        scn = setup_three_plan_comparison_scenario()
        result = self._comparison(scn)

        assert result["candidate_plan_count"] == 3
        assert len(result["ranked_plans"]) == 3
        assert result["recommended_plan_id"] == scn["alpha"]["id"]

    def test_pharmacy_component_is_a_hard_zero_without_a_network_row(self):
        """PRD §3.4: "The second is a pharmacy component: worth 1 when the plan has at
        least one pharmacy network entry whose `network_tier` is `PREFERRED` or `STANDARD`,
        and 0 otherwise."

        Design: Difficulty/combinatorial_formula/combinatorial_plan_comparison_pharmacy_term_is_a_hard_zero
        """
        scn = setup_three_plan_comparison_scenario()
        result = self._comparison(scn)

        by_id = {p.get("plan_id", p.get("id")): p for p in result["ranked_plans"]}
        alpha = by_id[scn["alpha"]["id"]]
        gamma = by_id[scn["gamma"]["id"]]
        beta = by_id[scn["beta"]["id"]]

        # ALPHA has the pharmacy row, GAMMA does not; the 8.00 weight is the gap.
        assert alpha["composite_score"] == pytest.approx(gamma["composite_score"] + 8.00,
                                                         abs=0.01)
        assert gamma["composite_score"] < beta["composite_score"], (
            "GAMMA loses to BETA by the pharmacy term"
        )

    def test_drug_cost_changes_the_out_of_pocket_figure(self):
        """PRD §3.4: "The plan's annual out-of-pocket figure is then assembled from three
        parts: twelve times the plan's `monthly_premium_cents`, plus its
        `annual_drug_deductible_cents`, plus the sum of the per-drug costs already rounded."

        Design: Difficulty/combinatorial_formula/combinatorial_plan_comparison_pharmacy_term_is_a_hard_zero
        """
        scn = setup_three_plan_comparison_scenario()
        result = self._comparison(scn)
        by_id = {p.get("plan_id", p.get("id")): p for p in result["ranked_plans"]}
        alpha = by_id[scn["alpha"]["id"]]
        beta = by_id[scn["beta"]["id"]]

        # ALPHA: 1500x12 + 20000 = 38000 before drugs; BETA: 3200x12 + 0 = 38400.
        # The premium/deductible halves differ by 400, and the drug halves differ by
        # 1575.00 - 1470.00 = 105.00, so the totals differ by 505 in one direction.
        assert (beta["plan_out_of_pocket_cents"] - alpha["plan_out_of_pocket_cents"]) == \
            pytest.approx(505.00, abs=1.00)

    def test_prior_authorization_does_not_change_a_drug_cost(self):
        """PRD §3.4: "Whether a drug requires prior authorization does not change its cost."

        Design: Difficulty/combinatorial_formula/combinatorial_plan_comparison_pharmacy_term_is_a_hard_zero
        """
        scn = setup_three_plan_comparison_scenario()
        result = self._comparison(scn)
        by_id = {p.get("plan_id", p.get("id")): p for p in result["ranked_plans"]}
        beta = by_id[scn["beta"]["id"]]
        # The Metformin row BETA carries is not covered, so BETA's drug subtotal comes
        # only from the covered Lisinopril row: 1 fill x 1500 copay x 1.05 = 1575.00.
        # BETA's Lisinopril row is the only one flagged prior_authorization_required,
        # and that flag does not change the 1575.00 figure.
        assert beta["plan_out_of_pocket_cents"] == pytest.approx(
            3200 * 12 + 0 + 1575.00, abs=1.00)