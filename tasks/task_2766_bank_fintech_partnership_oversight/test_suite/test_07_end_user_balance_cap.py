"""The end-user balance cap tolerates exact equality and refuses one cent more."""
from test_helpers import (
    ApiErrorId,
    api_client,
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

CAP_CENTS = 10_000_000


def _subject_at_one_cent_below_the_cap():
    """A ballast book keeps the group concentration near 1.10 percent, so the
    concentration cap can never pre-empt the balance cap."""
    ballast = setup_ballast_partner(900_000_000, cycle_open=True)
    ctx = setup_live_partner(
        partner_overrides={
            "legal_name": "Pinnacle Wallet Inc",
            "business_model": "DEPOSIT_WALLET",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 1.00,
            "end_user_account_count": 3000,
        },
        agreement_overrides={
            "max_end_user_balance_cents": CAP_CENTS,
            "concentration_cap_pct": 90.00,
            "reserve_requirement_bps": 500,
        },
        fbo_balance_cents=0,
        reserve_balance_cents=312_500,
        open_the_cycle=False,
    )
    ctx["ballast"] = ballast
    first = post_ledger_entry(
        ctx["partner"]["id"],
        ctx["fbo"],
        "END_USER_CREDIT",
        CAP_CENTS - 1,
        effective_at="2026-08-05T00:00:00Z",
        memo="eu-A",
    )
    validate_success(first, 201)
    return ctx


class TestEndUserBalanceCapBoundary:
    def test_a_credit_landing_exactly_on_the_cap_is_accepted(self):
        """After an `END_USER_CREDIT`, the `FBO_END_USER` account's resulting `balance_cents` must
        not exceed the partner's agreement `max_end_user_balance_cents`; a post-credit balance
        exactly equal to the cap is accepted, and only a balance above it is refused with
        `ERR_END_USER_BALANCE_CAP_EXCEEDED`.

        Design: Difficulty/boundary_precision_check/end_user_balance_cap_accepts_exact_equality_then_refuses_one_cent_more
        """
        ctx = _subject_at_one_cent_below_the_cap()
        partner_id = ctx["partner"]["id"]

        below = read_custody_account(ctx["fbo"]["id"])
        assert below["balance_cents"] == CAP_CENTS - 1
        one_below = read_partner(partner_id)
        assert one_below["required_reserve_cents"] == 499_999, (
            f"floor(9999999*500/10000) is 499999, not 500000, got "
            f"{one_below['required_reserve_cents']}"
        )
        assert one_below["reserve_shortfall_cents"] == 187_499

        at_the_cap = post_ledger_entry(
            partner_id,
            ctx["fbo"],
            "END_USER_CREDIT",
            1,
            effective_at="2026-08-06T00:00:00Z",
            memo="eu-B",
        )
        validate_success(at_the_cap, 201)

        exact = read_custody_account(ctx["fbo"]["id"])
        assert exact["balance_cents"] == CAP_CENTS, "equality with the cap is accepted"
        partner = read_partner(partner_id)
        assert partner["required_reserve_cents"] == 625_000, (
            f"a base of 500000 scaled by the HEIGHTENED multiplier 1.25, got "
            f"{partner['required_reserve_cents']}"
        )
        assert partner["reserve_shortfall_cents"] == 312_500
        assert partner["oversight_posture"] == "HEIGHTENED"

    def test_one_cent_above_the_cap_is_refused_and_leaves_the_balance_and_token_untouched(self):
        """After an `END_USER_CREDIT`, the `FBO_END_USER` account's resulting `balance_cents` must
        not exceed the partner's agreement `max_end_user_balance_cents`; a post-credit balance
        exactly equal to the cap is accepted, and only a balance above it is refused with
        `ERR_END_USER_BALANCE_CAP_EXCEEDED`.

        Design: Difficulty/boundary_precision_check/end_user_balance_cap_accepts_exact_equality_then_refuses_one_cent_more
        """
        ctx = _subject_at_one_cent_below_the_cap()
        partner_id = ctx["partner"]["id"]
        validate_success(
            post_ledger_entry(
                partner_id,
                ctx["fbo"],
                "END_USER_CREDIT",
                1,
                effective_at="2026-08-06T00:00:00Z",
                memo="eu-B",
            ),
            201,
        )
        pinned = read_custody_account(ctx["fbo"]["id"])
        assert pinned["balance_cents"] == CAP_CENTS

        refused = post_ledger_entry(
            partner_id,
            ctx["fbo"],
            "END_USER_CREDIT",
            1,
            effective_at="2026-08-07T00:00:00Z",
            memo="eu-C",
        )
        validate_error(refused, ApiErrorId.ERR_END_USER_BALANCE_CAP_EXCEEDED, 409)

        after = read_custody_account(ctx["fbo"]["id"])
        assert after["balance_cents"] == CAP_CENTS, "unchanged by the refusal"
        assert after["version"] == pinned["version"], (
            "a refused write must not bump the concurrency token"
        )
        entries = get_success_data(
            api_client.list_ledger_entries(PO, {"partner_id": partner_id, "limit": 100})
        )
        assert [e for e in entries if e.get("memo") == "eu-C"] == []

        partner = read_partner(partner_id)
        assert partner["required_reserve_cents"] == 625_000
        assert partner["reserve_shortfall_cents"] == 312_500
        assert partner["oversight_posture"] == "HEIGHTENED"
        assert (
            read_custody_account(ctx["ballast"]["fbo"]["id"])["balance_cents"] == 900_000_000
        ), "the ballast book is untouched"
