"""Breadth claims about the threshold and weighted-scoring rules."""

import pytest

from test_helpers import (
    assert_same_instant,
    fixtures,
    get_acceptance_data,
    get_engagement_data,
    get_summary_data,
    get_threat_data,
)


class TestDecayTierFlip:
    """The decay tier is a function of the clock, not of the row alone."""

    def test_twelve_month_old_row_does_not_decay(self, api):
        """PRD §3.2: "an age of 12 months or less decays not at all, an age
        above 12 months and up to 24 months halves the impact, and an age
        beyond 24 months quarters it."

        Design: Corner/calculations/integrity_score_decay_tier_flips_at_thirteen_months
        """
        world = fixtures.scenario_decay_tier(api)
        acceptance = get_acceptance_data(api, world["acceptance"]["id"])

        # Exactly twelve whole months old, so the impact is undecayed.
        assert acceptance["integrity_score"] == pytest.approx(80.0)
        assert acceptance["risk_score"] == pytest.approx(40.0)

    def test_thirteen_month_old_row_halves_its_impact(self, api):
        """PRD §2.5: "the integrity decay tiers of §3.2 count whole months from
        each assessment's `assessed_on` to the clock's current date."

        Design: Corner/calculations/integrity_score_decay_tier_flips_at_thirteen_months
        """
        world = fixtures.scenario_decay_tier(api)
        acceptance_id = world["acceptance"]["id"]

        fixtures.set_clock(api, "2026-11-01T00:00:00Z")

        acceptance = get_acceptance_data(api, acceptance_id)
        assert acceptance["integrity_score"] == pytest.approx(90.0)
        assert acceptance["risk_score"] == pytest.approx(30.0)


class TestFinancialInterestMateriality:
    """The threshold is inclusive and doubled for an indirect holding."""

    def test_indirect_holding_below_the_doubled_threshold_is_immaterial(self, api):
        """PRD §3.4: "the interest is material when `value_cents` is greater
        than or equal to the professional's grade threshold in cents,
        multiplied by two when the holding is indirect."

        Design: Corner/calculations/materiality_is_inclusive_and_two_tiered_by_instrument
        """
        world = fixtures.scenario_materiality_tiers(api)
        threat = fixtures.declare_financial_interest(
            api, world["professional"]["id"], world["client"]["id"],
            instrument_type="MUTUAL_FUND", value_cents=199999,
            effective_on="2026-09-01T00:00:00Z",
        )
        stored = get_threat_data(api, threat["id"])
        assert stored["is_material"] is False

        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["independence_status"] == "CLEAR"

    def test_indirect_holding_at_the_doubled_threshold_is_material(self, api):
        """PRD §3.4: "The boundary is inclusive at the cent, so a manager's
        25,000-cent direct holding in a non-public-interest client is material
        while a 24,999-cent holding is not."

        Design: Corner/calculations/materiality_is_inclusive_and_two_tiered_by_instrument
        """
        world = fixtures.scenario_materiality_tiers(api)
        threat = fixtures.declare_financial_interest(
            api, world["professional"]["id"], world["client"]["id"],
            instrument_type="MUTUAL_FUND", value_cents=200000,
            effective_on="2026-09-01T00:00:00Z",
        )
        stored = get_threat_data(api, threat["id"])
        assert stored["is_material"] is True

        engagement = get_engagement_data(api, world["engagement"]["id"])
        assert engagement["independence_status"] == "FROZEN"

    def test_direct_holding_uses_the_single_threshold(self, api):
        """PRD §3.4: "Equity, debt, derivatives and trust interests are direct;
        a mutual fund holding is indirect."

        Design: Corner/calculations/materiality_is_inclusive_and_two_tiered_by_instrument
        """
        world = fixtures.scenario_materiality_tiers(api)
        threat = fixtures.declare_financial_interest(
            api, world["professional"]["id"], world["client"]["id"],
            instrument_type="EQUITY", value_cents=199999,
            effective_on="2026-09-01T00:00:00Z",
        )
        stored = get_threat_data(api, threat["id"])
        assert stored["is_material"] is True


class TestNetworkRiskWeighting:
    """Cumulative breaches are weighted by tier and clamped at fifty."""

    def test_weighted_sum_is_clamped_at_the_ceiling(self, api):
        """PRD §2.7: "The raw score is then clamped into the range 0 to 50
        inclusive — never below zero, never above 50."

        Design: Corner/calculations/network_risk_points_clamp_at_the_ceiling
        """
        world = fixtures.scenario_network_risk(api)
        summary = get_summary_data(api, world["first"]["id"])

        # Twenty cumulative breaches on a member firm would weigh sixty.
        assert summary["network_risk_points"] == 50
        assert summary["breached_attestation_count"] == 1
        assert summary["high_open_count"] == 1

    def test_weighted_sum_below_the_ceiling_is_unclamped(self, api):
        """PRD §2.7: "Member firms weigh 3, correspondents weigh 2, and
        alliance firms weigh 1."

        Design: Corner/calculations/network_risk_points_clamp_at_the_ceiling
        """
        world = fixtures.scenario_network_risk(api)
        summary = get_summary_data(api, world["second"]["id"])

        # Sixteen cumulative breaches on a member firm weigh forty-eight.
        assert summary["network_risk_points"] == 48
        assert summary["breached_attestation_count"] == 1

    def test_domestic_engagement_accrues_no_network_risk(self, api):
        """PRD §2.7: "An engagement that is not multinational accrues no
        network risk at all: its network risk points are zero regardless of what
        any affiliate reports."

        Design: Corner/calculations/network_risk_points_clamp_at_the_ceiling
        """
        world = fixtures.scenario_network_risk(api)
        summary = get_summary_data(api, world["domestic"]["id"])
        assert summary["network_risk_points"] == 0


class TestZeroMonthCoolingOff:
    """A zero-month relationship type never enters the cooling-off state."""

    def test_board_membership_opens_cleared_with_an_empty_window(self, api):
        """PRD §3.4: "an immediate family member employed by the client or a
        client board membership triggers no window at all."
        PRD §3.4: "`cooling_off_end_on` equals `effective_on` for the zero-month
        relationship types".

        Design: Corner/calculations/zero_month_cooling_off_types_clear_on_creation
        """
        world = fixtures.scenario_zero_month_cooling_off(api)
        threat = fixtures.declare_employment_relationship(
            api, world["first_professional"]["id"], world["client"]["id"],
            relationship_type="CLIENT_BOARD_MEMBERSHIP",
            effective_on="2026-09-01T00:00:00Z",
        )
        stored = get_threat_data(api, threat["id"])
        assert_same_instant(stored["cooling_off_end_on"], "2026-09-01T00:00:00Z")
        assert stored["status"] == "CLEARED"

        # The empty window is not a staffing bar.
        assignment = fixtures.staff_ok(
            api, world["engagement"]["id"], world["first_professional"]["id"],
            "ENGAGEMENT_MANAGER", "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            ep_headers=world["ep_headers"],
        )
        assert assignment["status"] == "ACTIVE"

    def test_prior_client_employment_opens_a_twenty_four_month_window(self, api):
        """PRD §3.4: "a professional who was previously employed by the client
        triggers 24 months".
        PRD §3.4: "A relationship with a positive cooling-off window opens in
        `IN_COOLING_OFF`."

        Design: Corner/calculations/zero_month_cooling_off_types_clear_on_creation
        """
        world = fixtures.scenario_zero_month_cooling_off(api)
        threat = fixtures.declare_employment_relationship(
            api, world["second_professional"]["id"], world["client"]["id"],
            relationship_type="PROFESSIONAL_PRIOR_CLIENT_EMPLOYEE",
            effective_on="2026-09-01T00:00:00Z",
        )
        stored = get_threat_data(api, threat["id"])
        assert_same_instant(stored["cooling_off_end_on"], "2028-09-01T00:00:00Z")
        assert stored["status"] == "IN_COOLING_OFF"
