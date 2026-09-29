"""Corner cases of the group concentration ratio and of the monthly growth cap."""
from test_helpers import (
    ApiErrorId,
    close_cycle,
    open_cycle,
    open_second_cycle,
    oversight_summary,
    post_ledger_entry,
    read_custody_account,
    read_partner,
    set_clock,
    setup_ballast_partner,
    setup_live_partner,
    validate_error,
    validate_success,
)


def _live_with_empty_custody(cap_pct, cycle_label="2026-08"):
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Harborline Wallet Inc",
            "business_model": "DEPOSIT_WALLET",
            "end_user_account_count": 7_000,
        },
        agreement_overrides={
            "reserve_requirement_bps": 500,
            "concentration_cap_pct": cap_pct,
        },
        fbo_balance_cents=0,
        reserve_balance_cents=312_500,
        open_the_cycle=False,
        cycle_label=cycle_label,
    )


class TestConcentrationRatio:
    def test_an_empty_denominator_reads_zero_and_the_cap_breaches_on_equality(self):
        """If the denominator is zero, `concentration_ratio_pct` is defined to be `0.00`; that is a
        value, not an error. And after an `END_USER_CREDIT`, the recomputed group concentration ratio
        must be **strictly below** the agreement's `concentration_cap_pct`; a recomputed ratio
        exactly equal to the cap counts as a breach and the credit is refused with
        `ERR_CONCENTRATION_CAP_BREACH`.

        Design: Corner/calculations/concentration_ratio_is_zero_on_an_empty_denominator_and_breaches_inclusively_at_the_cap
        """
        open_cycle()
        ctx = _live_with_empty_custody(80.00)
        partner_id = ctx["partner"]["id"]

        empty = oversight_summary(partner_id)
        assert empty["group_balance_cents"] == 0
        assert empty["bank_total_fbo_balance_cents"] == 0
        assert empty["concentration_ratio_pct"] == 0.00, (
            "an empty denominator is a defined value, not an error"
        )
        assert empty["group_root_partner_id"] == partner_id, (
            "a null parent_partner_id makes the partner its own group root"
        )

        ballast = setup_ballast_partner(2_000_000, legal_name="Stonebridge Ballast Inc")
        assert ballast["partner"]["parent_partner_id"] is None

        validate_success(
            post_ledger_entry(
                partner_id, ctx["fbo"], "END_USER_CREDIT", 7_000_000,
                effective_at="2026-08-10T00:00:00Z",
            ),
            201,
        )
        loaded = oversight_summary(partner_id)
        assert loaded["group_balance_cents"] == 7_000_000
        assert loaded["bank_total_fbo_balance_cents"] == 9_000_000
        assert loaded["concentration_ratio_pct"] == 77.78, (
            f"700000000/9000000 is 77.7777... and rounds half up to 77.78, got "
            f"{loaded['concentration_ratio_pct']}"
        )
        credited = read_partner(partner_id)
        assert credited["reserve_shortfall_cents"] == 37_500, (
            "the balance arm now demands 350000 against a 312500 reserve"
        )
        assert credited["oversight_posture"] == "HEIGHTENED"

        refused = post_ledger_entry(
            partner_id, ctx["fbo"], "END_USER_CREDIT", 1_000_000,
            effective_at="2026-08-11T00:00:00Z",
        )
        validate_error(refused, ApiErrorId.ERR_CONCENTRATION_CAP_BREACH, 409)
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 7_000_000, (
            "the refused credit booked no ledger entry"
        )
        assert oversight_summary(partner_id)["concentration_ratio_pct"] == 77.78


class TestMonthlyGrowthRounding:
    def test_the_growth_percentage_rounds_to_two_places_before_the_strict_comparison(self):
        """When the prior figure is non-zero, `monthly_growth_pct` is the current figure minus the
        prior figure, multiplied by 100, divided by the prior figure, rounded half up to two decimal
        places; the partner is in breach when that percentage is strictly greater than the
        `monthly_growth_cap_pct` of the partner's agreement. Both comparisons are strict: growth of
        exactly the contracted cap is compliant, and a current figure exactly equal to 5,000,000
        cents is compliant.

        Design: Corner/calculations/monthly_growth_rounds_to_two_dp_before_the_strictly_greater_cap_comparison
        """
        first_cycle = open_cycle()
        assert first_cycle["cycle_index"] == 1
        setup_ballast_partner(60_000_000, legal_name="Ironvale Ballast Inc")
        ctx = _live_with_empty_custody(90.00)
        partner_id = ctx["partner"]["id"]

        validate_success(
            post_ledger_entry(
                partner_id, ctx["fbo"], "END_USER_CREDIT", 5_000_000,
                effective_at="2026-08-15T00:00:00Z",
            ),
            201,
        )
        second_cycle = open_second_cycle()
        assert second_cycle["cycle_index"] == 2

        set_clock("2026-09-01T00:00:00Z")
        august = close_cycle(first_cycle["id"])
        assert august["growth_breach_partner_count"] == 0, (
            "with no prior closed cycle the absolute seed cap applies and 5000000 is not "
            "strictly greater than 5000000"
        )
        after_august = read_partner(partner_id)
        assert after_august["growth_breach_count"] == 0
        assert after_august["required_reserve_cents"] == 250_000
        assert after_august["reserve_shortfall_cents"] == 0
        assert after_august["consecutive_shortfall_cycles"] == 0
        assert after_august["oversight_posture"] == "OPEN"

        set_clock("2026-09-15T00:00:00Z")
        validate_success(
            post_ledger_entry(
                partner_id, ctx["fbo"], "END_USER_CREDIT", 7_500_001,
                effective_at="2026-09-15T00:00:00Z",
            ),
            201,
        )
        set_clock("2026-10-01T00:00:00Z")
        september = close_cycle(second_cycle["id"])
        assert september["growth_breach_partner_count"] == 0, (
            "(7500001 - 5000000) * 100 / 5000000 is 50.00002, which rounds half up to exactly "
            "50.00, and 50.00 is not strictly greater than the 50.00 cap"
        )
        after_september = read_partner(partner_id)
        assert after_september["growth_breach_count"] == 0, (
            "comparing the unrounded ratio instead would have recorded a breach here"
        )
        assert after_september["required_reserve_cents"] == 781_250, (
            "500 bps of the 12500001 balance is 625000, scaled by the HEIGHTENED multiplier, got "
            f"{after_september['required_reserve_cents']}"
        )
        assert after_september["reserve_shortfall_cents"] == 468_750
        assert after_september["consecutive_shortfall_cycles"] == 1
        assert after_september["oversight_posture"] == "HEIGHTENED", (
            "driven by the reserve shortfall rung, not by a growth breach"
        )
