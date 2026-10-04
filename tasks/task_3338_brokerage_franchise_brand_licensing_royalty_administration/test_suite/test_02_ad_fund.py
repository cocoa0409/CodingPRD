"""Ad-fund accrual, ledger effects, and the computed fund balance."""
from test_helpers import (
    validate_paginated, validate_success, get_success_data,
    setup_active_agreement, setup_suspended_agreement, setup_submitted_proposal,
    submit_gci_report, assess_period, cast_votes,
    TEST_USERS, make_franchisee_admin_headers,
)

OPS = TEST_USERS["franchisor_ops_headers"]


def test_ad_fund_accrues_when_active_but_pauses_while_suspended(api):
    """PRD §3.5: "When the agreement is `SUSPENDED` at assessment time, the
    month's contribution is zero and no ledger entry is created at all —
    suspension pauses fund accrual without pausing royalty."
    PRD §3.5: "the month's GCI multiplied by `ad_fund_rate_bps` and divided by
    10000, floored to whole cents, exactly one rounding event at accrual."

    Design: Difficulty/dual_variant_calc/ad_fund_zero_when_suspended_vs_active
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=600,
        annual_royalty_cap_cents=900_000_000,
        volume_incentive_threshold_cents=1_000_000_000,
        volume_incentive_rate_bps=300,
        ad_fund_rate_bps=200,
    )
    ag_id = ctx["agreement"]["id"]
    brand_id = ctx["brand"]["id"]

    submit_gci_report(ag_id, "2027-03", 100_000_000)
    active_period = assess_period(ag_id, "2027-03")
    assert active_period["ad_fund_due_cents"] == 2_000_000

    # Suspend: open a default, then suspend the agreement.
    from test_helpers import open_default
    open_default(ag_id, "PAYMENT")
    get_success_data(api.suspend_agreement(ag_id, OPS))

    submit_gci_report(ag_id, "2027-04", 100_000_000)
    suspended_period = assess_period(ag_id, "2027-04")
    assert suspended_period["ad_fund_due_cents"] == 0
    # Royalty still runs while suspended.
    assert suspended_period["royalty_due_cents"] > 0

    ledger, _meta = validate_paginated(api.list_brand_ad_fund_ledger(brand_id, OPS))
    collects = [e for e in ledger if e["entry_type"] == "COLLECT"]
    assert len(collects) == 1, "suspended-month assessment must not append a ledger entry"
    assert collects[0]["amount_cents"] == 2_000_000
    assert collects[0]["period_id"] == active_period["id"]


def test_ad_fund_ledger_entry_carries_brand_agreement_and_period(api):
    """PRD §3.5: "When the computed contribution is greater than zero, the
    assessment appends a `COLLECT` entry to the brand's ad-fund ledger, recording
    the `brand_id` of the agreement's brand, the contributing `agreement_id`, and
    the new period's `period_id`, with `amount_cents` equal to the contribution."

    Design: Difficulty/dual_variant_calc/ad_fund_zero_when_suspended_vs_active
    """
    ctx = setup_active_agreement(
        base_royalty_rate_bps=600,
        annual_royalty_cap_cents=900_000_000,
        volume_incentive_threshold_cents=1_000_000_000,
        volume_incentive_rate_bps=300,
        ad_fund_rate_bps=200,
    )
    ag_id = ctx["agreement"]["id"]
    submit_gci_report(ag_id, "2027-03", 100_000_000)
    period = assess_period(ag_id, "2027-03")

    ledger, _meta = validate_paginated(
        api.list_period_ad_fund_ledger(period["id"], OPS)
    )
    assert len(ledger) == 1
    entry = ledger[0]
    assert entry["entry_type"] == "COLLECT"
    assert entry["brand_id"] == ctx["brand"]["id"]
    assert entry["agreement_id"] == ag_id
    assert entry["period_id"] == period["id"]
    assert entry["amount_cents"] == period["ad_fund_due_cents"]


def test_executing_full_balance_spend_drives_fund_balance_to_zero(api):
    """PRD §3.6: "The brand's fund balance is the sum of all `COLLECT` amounts
    minus the sum of all `SPEND` amounts across all periods with no time window,
    exposed as a computed read returning `balance_cents` and `brand_id`."
    PRD §3.6: "the system appends a `SPEND` ledger entry for the proposal's
    `amount_cents` with null `agreement_id` and `period_id`, and the proposal
    becomes `EXECUTED`."

    Design: Difficulty/compensating_invariant/ad_fund_collect_minus_spend_balance_conserved
    """
    ctx = setup_submitted_proposal(seat_count=3, amount_cents=2_000_000, ad_fund_rate_bps=200)
    brand_id = ctx["brand"]["id"]
    contributing_agreement = ctx["agreements"][0]
    submit_gci_report(contributing_agreement["id"], "2027-01", 100_000_000)
    assess_period(contributing_agreement["id"], "2027-01")  # COLLECT 2,000,000

    cast_votes(ctx["proposal"]["id"], [b["id"] for b in ctx["brokerages"][:2]], "APPROVE")
    executed = get_success_data(api.execute_ad_fund_proposal(ctx["proposal"]["id"], OPS))
    assert executed["status"] == "EXECUTED"

    balance = get_success_data(api.get_brand_ad_fund_balance(brand_id, OPS))
    assert balance["balance_cents"] == 0
    assert balance["brand_id"] == brand_id

    ledger, _meta = validate_paginated(api.list_brand_ad_fund_ledger(brand_id, OPS))
    spends = [e for e in ledger if e["entry_type"] == "SPEND"]
    collects = [e for e in ledger if e["entry_type"] == "COLLECT"]
    assert len(spends) == 1 and len(collects) == 1
    assert spends[0]["amount_cents"] == 2_000_000
    assert sum(e["amount_cents"] for e in collects) - sum(e["amount_cents"] for e in spends) == 0


def test_fund_balance_matches_collect_minus_spend_after_partial_spend(api):
    """PRD §3.6: "The brand's fund balance is the sum of all `COLLECT` amounts
    minus the sum of all `SPEND` amounts across all periods with no time window,
    exposed as a computed read returning `balance_cents` and `brand_id`."

    Design: Difficulty/compensating_invariant/ad_fund_collect_minus_spend_balance_conserved
    """
    ctx = setup_submitted_proposal(seat_count=3, amount_cents=1_000_000, ad_fund_rate_bps=200)
    brand_id = ctx["brand"]["id"]
    contributing_agreement = ctx["agreements"][0]
    submit_gci_report(contributing_agreement["id"], "2027-01", 100_000_000)
    assess_period(contributing_agreement["id"], "2027-01")  # COLLECT 2,000,000

    cast_votes(ctx["proposal"]["id"], [b["id"] for b in ctx["brokerages"][:2]], "APPROVE")
    executed = get_success_data(api.execute_ad_fund_proposal(ctx["proposal"]["id"], OPS))
    assert executed["status"] == "EXECUTED"

    balance = get_success_data(api.get_brand_ad_fund_balance(brand_id, OPS))
    assert balance["balance_cents"] == 1_000_000
