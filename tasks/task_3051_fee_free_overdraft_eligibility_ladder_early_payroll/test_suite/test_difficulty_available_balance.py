"""Depth tests for the two available-balance read models on an account."""

import test_helpers as th
from test_helpers import fixtures


def _setup_account_with_provisional(api):
    """Member enrolled 2026-01-01, two settled 10000 payroll deposits, BATCH
    evaluation, then a 20000 payroll deposit posted early."""
    w = fixtures.setup_eligible_member(
        api,
        external_ref="m1",
        enrolled_at="2026-01-01T00:00:00Z",
        num_deposits=2,
        settlement_dates=["2026-08-20T00:00:00Z", "2026-08-28T00:00:00Z"],
    )
    d3 = fixtures.register_deposit(
        api,
        w["account"]["id"],
        originator_id="EMP1-C",
        originator_type="PAYROLL",
        amount_cents=20000,
        settlement_date="2026-09-05T00:00:00Z",
        trace_id="t3",
    )
    fixtures.post_early(api, d3["id"])
    return w, d3


def test_available_balance_components(api):
    """PRD §3.6: "Then the optimistic figure, `available_optimistic_cents`, is the
    settled balance plus `provisional_early_cents`, minus `holds_cents`, plus the
    usable cushion — this is the member-facing spending power against which
    debits are checked."
    PRD §3.6: "The conservative figure, `available_conservative_cents`, is simply
    the settled balance minus holds — provisional money and cushion are excluded
    entirely, and this is the figure reclaim processing and sponsor-bank
    reporting rely on."

    Design: Difficulty/dual_variant_calc/available_balance_optimistic_vs_conservative
    """
    w, _d3 = _setup_account_with_provisional(api)
    account = fixtures.get_account(api, w["account"]["id"])
    th.assert_deposit_account(account)
    # Two settled 10000 payroll deposits credit the settled balance to 20000;
    # the 20000 early-posted deposit sits in provisional_early_cents, not the
    # settled balance (it materializes at settlement).
    assert account["posted_balance_cents"] == 20000
    assert account["provisional_early_cents"] == 20000
    assert account["holds_cents"] == 0
    assert account["usable_cushion_cents"] == 2000
    assert account["available_optimistic_cents"] == 42000
    assert account["available_conservative_cents"] == 20000


def test_available_balance_variants_differ_by_provisional_plus_cushion(api):
    """PRD §3.6: "Then the optimistic figure, `available_optimistic_cents`, is the
    settled balance plus `provisional_early_cents`, minus `holds_cents`, plus the
    usable cushion — this is the member-facing spending power against which
    debits are checked."
    PRD §3.6: "The conservative figure, `available_conservative_cents`, is simply
    the settled balance minus holds — provisional money and cushion are excluded
    entirely, and this is the figure reclaim processing and sponsor-bank
    reporting rely on."

    Design: Difficulty/dual_variant_calc/available_balance_optimistic_vs_conservative
    """
    w, _d3 = _setup_account_with_provisional(api)
    account = fixtures.get_account(api, w["account"]["id"])
    gap = account["available_optimistic_cents"] - account["available_conservative_cents"]
    assert gap == account["provisional_early_cents"] + account["usable_cushion_cents"]
    assert gap == 22000
