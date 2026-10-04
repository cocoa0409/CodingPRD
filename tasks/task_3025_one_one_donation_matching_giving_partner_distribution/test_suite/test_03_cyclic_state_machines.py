"""Cyclic lifecycles: the vetting round and the liability/season freeze pair (PRD §3.1, §3.7)."""
from test_helpers import (
    TEST_USERS,
    add_line,
    add_product_line,
    api_client,
    create_active_product,
    create_order,
    create_season,
    get_liability_for,
    get_partner,
    get_season,
    onboard_partner,
    pay_order,
    record_round,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestVettingCycleArrestedAtTwoStrikes:
    """Difficulty/non_linear_state_machine — the cycle counts its own arrests."""

    def test_request_for_information_returns_the_partner_and_counts_a_rejection(self, api):
        """PRD §3.1: "That request-for-information is not free: it increments the partner's `total_rejections` and returns the partner to `CANDIDATE`, because a round sent back for information counts as a rejection under the two-strike rule."

        Design: Difficulty/non_linear_state_machine/vetting_cycle_reopens_with_a_new_round_then_finalizes_at_two_rejections
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        partner = onboard_partner(
            legal_name="Epsilon Bridge Shelter",
            operating_region="WEST",
            operating_state_code="OR",
            registry_id="OR-CHR-500005",
            ein="555666777",
        )
        vetting_id = partner["latest_vetting_round_id"]
        assert partner["total_rejections"] == 0

        record_round(vetting_id, registry_check_passed=True, tax_check_passed=False,
                     need_verification_points=0)
        sent_back = validate_success(
            api_client.update_vetting_round(
                vetting_id,
                {"outcome": "REQUESTED",
                 "outcome_message": "Tax determination letter unreadable; please resubmit"},
                COORD,
            ),
            200,
        )
        assert sent_back["outcome"] == "REQUESTED"

        refreshed = get_partner(partner["id"])
        assert refreshed["total_rejections"] == 1
        assert refreshed["status"] == "CANDIDATE"

    def test_second_rejection_is_final_and_the_cycle_cannot_advance(self, api):
        """PRD §3.1: "Rejecting a round increments the partner's `total_rejections` and moves the partner to `REJECTED`; the round's outcome becomes `REJECTED` as well."
        PRD §3.1: "A rejected partner can be reopened: reopening requires that `total_rejections` is still below 2 and that the current round's outcome is `REJECTED`; when either fails the attempt is refused with `ERR_PARTNER_REJECTION_FINAL` (HTTP 409) — a partner whose two rejections are spent cannot be brought back."
        PRD §3.1: "A successful reopen creates a fresh round numbered one above the partner's current `vetting_round` with outcome `DOCUMENTS_SUBMITTED`, increments `vetting_round`, and returns the partner to `VETTING`."

        Design: Difficulty/non_linear_state_machine/vetting_cycle_reopens_with_a_new_round_then_finalizes_at_two_rejections
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        partner = onboard_partner(
            legal_name="Epsilon Bridge Shelter",
            operating_region="WEST",
            operating_state_code="OR",
            registry_id="OR-CHR-550005",
            ein="555666777",
        )
        vetting_id = partner["latest_vetting_round_id"]

        # First strike: send round 1 back for information, which counts as a rejection.
        record_round(vetting_id, registry_check_passed=True, tax_check_passed=False,
                     need_verification_points=0)
        validate_success(
            api_client.update_vetting_round(
                vetting_id,
                {"outcome": "REQUESTED",
                 "outcome_message": "Tax determination letter unreadable; please resubmit"},
                COORD,
            ),
            200,
        )
        after_first = get_partner(partner["id"])
        assert after_first["total_rejections"] == 1
        assert after_first["status"] == "CANDIDATE"

        # Second strike on the same round: the two-strike allowance is spent.
        record_round(vetting_id, registry_check_passed=True, tax_check_passed=True,
                     need_verification_points=0)
        validate_success(api_client.reject_vetting_round(
            vetting_id, {"outcome_message": "Registry record still mismatched"}, COORD), 200)
        final = get_partner(partner["id"])
        assert final["total_rejections"] == 2
        assert final["status"] == "REJECTED_FINAL"
        assert final["vetting_round"] == 1

        refused = api_client.reopen_vetting_round(vetting_id, {}, COORD)
        validate_error(refused, "ERR_PARTNER_REJECTION_FINAL")

        rounds, _ = validate_paginated(
            api_client.list_vetting_rounds(COORD, {"partner_id": partner["id"]})
        )
        assert len(rounds) == 1
        assert rounds[0]["round_number"] == 1


class TestLiabilityFreezeCycle:
    """Difficulty/non_linear_state_machine — a freeze that can be taken back."""

    def _frozen_liability_scenario(self, freezes_at="2026-12-01T00:00:00Z"):
        # PRD §3.7: a season "opens automatically once the logical clock passes
        # `starts_at`" and "freezes once the clock passes `freezes_at`", so the
        # fixture's calendar must contain the clock instants it rolls through.
        set_clock("2026-08-15T00:00:00Z")
        season = create_season(starts_at="2026-08-15T00:00:00Z", freezes_at=freezes_at)
        product = create_active_product(
            product_name="Merino Trail Crew",
            product_kind="ATHLETIC_SOCK",
            design_channel="DUAL_CHANNEL",
            obligation_model="AT_SALE",
            retail_price_cents=2200,
            unit_cost_cents=1300,
            # PRD §3.4 gates activation at design_weight_score >= 60; this fixture
            # must clear the gate, so the sock is declared reusable (40 + 20 = 60).
            is_reusable=True,
        )
        line = add_product_line(product["id"], "00000000000101", "L", False)
        order = create_order(order_number="SO-NLSM-1", channel="RETAIL_POS")
        add_line(order["id"], line["id"], quantity=5, unit_price_cents=2200)
        pay_order(order["id"])
        return season, product

    def test_clock_roll_freezes_the_liability_at_its_provisional_units(self, api):
        """PRD §3.7: "It freezes once the clock passes `freezes_at`, provided every claim for the season is in one of `DRAFT`, `SUBSTANTIATED`, `OVERSTATED`, `UNSUBSTANTIATED` or `SEASON_RESTRICTED`; freezing moves every liability row to `FROZEN` with its frozen units taken from its provisional units, recomputes the season's frozen claim total, and re-evaluates the active season code of every active product pointing at the season."

        Design: Difficulty/non_linear_state_machine/donation_liability_cycles_accumulating_to_frozen_back_to_accumulating
        """
        season, product = self._frozen_liability_scenario()

        before = get_liability_for(product["id"], season["id"])
        assert before["status"] == "ACCUMULATING"

        set_clock("2026-12-02T00:00:00Z")

        after = get_liability_for(product["id"], season["id"])
        assert after["status"] == "FROZEN"
        assert after["frozen_units"] == 5

        rolled_season = get_season(season["id"])
        assert rolled_season["status"] == "FROZEN"
        assert rolled_season["claim_frozen_units_total"] == 5

    def test_unfreeze_returns_both_records_to_their_earlier_phases(self, api):
        """PRD §3.7: "An auditor can unfreeze a frozen liability, which requires that the season is `FROZEN` and that no audit for the season has been finalized; unfreezing recomputes the frozen units from the provisional units and returns the season to `OPEN`."

        Design: Difficulty/non_linear_state_machine/donation_liability_cycles_accumulating_to_frozen_back_to_accumulating
        """
        # PRD §3.7: "unfreezing ... requires that the season is `FROZEN`". The
        # season freezes because the clock passes `freezes_at`, so the fixture
        # sets that instant a few hours after the running clock.
        season, product = self._frozen_liability_scenario(
            freezes_at="2026-08-16T00:00:00Z"
        )
        created_version = season["version"]

        set_clock("2026-08-20T00:00:00Z")
        liability = get_liability_for(product["id"], season["id"])

        res = api_client.unfreeze_liability(liability["id"], {}, AUDITOR)
        validate_success(res, 200)

        unfrozen = get_liability_for(product["id"], season["id"])
        assert unfrozen["status"] == "ACCUMULATING"
        assert get_season(season["id"])["status"] == "OPEN"
        assert get_season(season["id"])["version"] > created_version