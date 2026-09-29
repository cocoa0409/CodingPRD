"""The group concentration ratio is rounded half up before it meets the cap, and
the cap breaches on equality."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_two_decimal_percentage,
    get_success_data,
    post_ledger_entry,
    read_custody_account,
    read_partner,
    setup_ballast_partner,
    setup_live_partner,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PO

BALLAST_CENTS = 1_500_100_000
FIRST_CREDIT_CENTS = 499_700_000


def _subject_just_under_the_cap():
    ballast = setup_ballast_partner(
        BALLAST_CENTS, cycle_open=True, legal_name="Continental Ballast Inc"
    )
    ctx = setup_live_partner(
        partner_overrides={
            "legal_name": "Apex Reserve Wallet Inc",
            "business_model": "DEPOSIT_WALLET",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 36,
            "disclosed_complaints_per_10k": 1.00,
            "end_user_account_count": 20000,
        },
        agreement_overrides={
            "concentration_cap_pct": 25.00,
            "max_end_user_balance_cents": 600_000_000,
            "reserve_requirement_bps": 10,
            "monthly_growth_cap_pct": 99.00,
        },
        fbo_balance_cents=0,
        reserve_balance_cents=312_500,
        open_the_cycle=False,
    )
    ctx["ballast"] = ballast
    return ctx


class TestConcentrationCapBoundary:
    def test_a_ratio_that_rounds_just_below_the_cap_is_accepted(self):
        """Otherwise the ratio is the numerator multiplied by 100, divided by the denominator, and
        rounded half up to two decimal places. Every partner in the group is written with the
        **same** `concentration_ratio_pct`, because the ratio is a property of the group.

        Design: Difficulty/boundary_precision_check/concentration_ratio_rounds_up_into_the_inclusive_cap_breach
        """
        ctx = _subject_just_under_the_cap()
        partner_id = ctx["partner"]["id"]
        accepted = post_ledger_entry(
            partner_id,
            ctx["fbo"],
            "END_USER_CREDIT",
            FIRST_CREDIT_CENTS,
            effective_at="2026-08-05T00:00:00Z",
            memo="eu-conc-1",
        )
        validate_success(accepted, 201)

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == FIRST_CREDIT_CENTS
        partner = read_partner(partner_id)
        assert_two_decimal_percentage(partner["concentration_ratio_pct"], "concentration_ratio_pct")
        assert partner["concentration_ratio_pct"] == 24.99, (
            "499700000 of a 1999800000 book is 24.98749 percent, which rounds to 24.99, got "
            f"{partner['concentration_ratio_pct']}"
        )
        assert partner["required_reserve_cents"] == 499_700, partner["required_reserve_cents"]
        assert partner["reserve_shortfall_cents"] == 187_200

        ballast = read_partner(ctx["ballast"]["partner"]["id"])
        assert ballast["concentration_ratio_pct"] == 100.00, (
            "the insert recomputes the ratio for every partner in the subject's group only, so "
            "the unrelated ballast group keeps the value its own last write left behind, got "
            f"{ballast['concentration_ratio_pct']}"
        )

    def test_a_ratio_that_rounds_up_onto_the_cap_is_a_breach(self):
        """And after an `END_USER_CREDIT`, the recomputed group concentration ratio must be
        **strictly below** the agreement's `concentration_cap_pct`; a recomputed ratio exactly equal
        to the cap counts as a breach and the credit is refused with `ERR_CONCENTRATION_CAP_BREACH`.
        The cap comparison uses the rounded value, so a true ratio of 24.995 percent rounds to 25.00
        and breaches a cap of 25.00.

        Design: Difficulty/boundary_precision_check/concentration_ratio_rounds_up_into_the_inclusive_cap_breach
        """
        ctx = _subject_just_under_the_cap()
        partner_id = ctx["partner"]["id"]
        validate_success(
            post_ledger_entry(
                partner_id,
                ctx["fbo"],
                "END_USER_CREDIT",
                FIRST_CREDIT_CENTS,
                effective_at="2026-08-05T00:00:00Z",
                memo="eu-conc-1",
            ),
            201,
        )
        pinned = read_custody_account(ctx["fbo"]["id"])

        refused = post_ledger_entry(
            partner_id,
            ctx["fbo"],
            "END_USER_CREDIT",
            200_000,
            effective_at="2026-08-06T00:00:00Z",
            memo="eu-conc-2",
        )
        validate_error(refused, ApiErrorId.ERR_CONCENTRATION_CAP_BREACH, 409)

        after = read_custody_account(ctx["fbo"]["id"])
        assert after["balance_cents"] == FIRST_CREDIT_CENTS, (
            "499900000 of a 2000000000 book is 24.995 percent, which rounds onto the cap"
        )
        assert after["version"] == pinned["version"]
        entries = get_success_data(
            api_client.list_ledger_entries(PO, {"partner_id": partner_id, "limit": 100})
        )
        assert [e for e in entries if e.get("memo") == "eu-conc-2"] == []
        assert read_partner(partner_id)["concentration_ratio_pct"] == 24.99
