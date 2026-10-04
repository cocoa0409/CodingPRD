"""Difficulty claims about the two rules that carry two variants at once.

Each test drives the system to one exact state and asserts the numbers the
contract's own arithmetic produces there.
"""

import pytest

from test_helpers import (
    fixtures,
    get_acceptance_data,
    get_assignment_data,
    submit_acceptance,
)


class TestAcceptanceRiskVariants:
    """One set of integrity rows, two admissible readings of it."""

    def test_provisional_risk_score_counts_only_resolved_rows(self, api):
        """PRD §3.2: "While the evaluation is still in `DRAFT`, the provisional
        variant counts only rows whose `resolved` flag is true, so unresolved
        matters are excluded from the input set entirely and the provisional
        score is lower than the final score for the same evidence."
        PRD §3.2: "The integrity score starts from a perfect 100 and subtracts
        decayed penalties."

        Design: Difficulty/dual_variant_calc/acceptance_risk_provisional_vs_final_divergence
        """
        world = fixtures.scenario_provisional_vs_final(api)
        acceptance = get_acceptance_data(api, world["acceptance"]["id"])

        assert acceptance["status"] == "DRAFT"
        # Base layer: TECH 20 + US 0, with no public-interest surcharge.
        # Provisional penalty: the resolved 20-point row at full weight.
        assert acceptance["risk_score"] == pytest.approx(40.0)
        assert acceptance["combined_risk_score"] == pytest.approx(40.0)
        # Both rows are inside the twelve-month tier, so nothing decays.
        assert acceptance["integrity_score"] == pytest.approx(70.0)

    def test_submitting_switches_to_the_final_variant(self, api):
        """PRD §3.2: "Submitting the evaluation switches to the final variant,
        in which every assessment row contributes its full decayed impact
        whether or not it has been resolved."

        Design: Difficulty/dual_variant_calc/acceptance_risk_provisional_vs_final_divergence
        """
        world = fixtures.scenario_provisional_vs_final(api)
        acceptance_id = world["acceptance"]["id"]

        before = get_acceptance_data(api, acceptance_id)
        submit_acceptance(api, acceptance_id)
        after = get_acceptance_data(api, acceptance_id)

        assert after["status"] == "SUBMITTED"
        assert before["risk_score"] == pytest.approx(40.0)
        assert after["risk_score"] == pytest.approx(50.0)
        assert after["combined_risk_score"] == pytest.approx(50.0)
        assert before["risk_score"] != after["risk_score"]
        # The integrity score counts every row under both variants.
        assert after["integrity_score"] == pytest.approx(70.0)


class TestRotationRegimeVariants:
    """The same sixty-month run under the standard and accelerated regimes."""

    def test_pie_accelerated_lead_partner_at_sixty_months_is_rotation_due(self, api):
        """PRD §3.3: "For a public interest entity, the accelerated regime
        applies to the two partner roles: both the lead partner and the
        concurring partner see their time-on limit cut to 60 months and their
        required time off extended to 60 months".
        PRD §3.3: "the boundary is inclusive, so a partner at exactly 60 months
        under the accelerated regime is already due for rotation".

        Design: Difficulty/dual_variant_calc/rotation_tenure_standard_vs_pie_accelerated_divergence
        """
        world = fixtures.scenario_rotation_variants(api)
        assignment = get_assignment_data(api, world["pie_assignment_id"])

        assert assignment["status"] == "ACTIVE"
        assert assignment["consecutive_service_months"] == 60
        assert assignment["rotation_status"] == "ROTATION_DUE"

    def test_standard_lead_partner_at_sixty_months_remains_on_service(self, api):
        """PRD §3.3: "For a client that is not a public interest entity, the
        standard regime applies: lead and concurring partners each have a
        time-on limit of 84 months and owe 24 months of time off once the
        assignment ends".

        Design: Difficulty/dual_variant_calc/rotation_tenure_standard_vs_pie_accelerated_divergence
        """
        world = fixtures.scenario_rotation_variants(api)
        assignment = get_assignment_data(api, world["std_assignment_id"])

        assert assignment["status"] == "ACTIVE"
        assert assignment["consecutive_service_months"] == 60
        assert assignment["rotation_status"] == "ON_SERVICE"
