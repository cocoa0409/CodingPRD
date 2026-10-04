"""Depth: which of two failing rules the caller actually observes.

The PRD fixes a strict ten-tier rejection order, and a later tier is never
permitted to mask an earlier one. Both instances here construct a request that
fails two rules at once and assert the earlier tier's error id.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    SCENARIO,
    add_project,
    api_client,
    create_subscription_payload,
    form_fund,
    get_success_data,
    make_investor_headers,
    onboard_developer,
    onboard_investor,
    open_subscription,
    read_fund,
    read_investor,
    schedule_capital_call,
    set_logical_clock,
    setup_fund_with_subscription,
    validate_error,
)

_CLOCK_0902 = "2026-09-02T00:00:00Z"
_FUND_V = dict(SCENARIO["fund_v"])
_HARBOR_LIGHT = dict(SCENARIO["project_harbor_light"])


def _two_fund_setup():
    """Meridian subscribed in fund IV; Harbor Light financed by fund V."""
    scenario = setup_fund_with_subscription()
    fund_v = form_fund(**_FUND_V)
    harbor = add_project(scenario.developer["id"], fund_v["id"], **_HARBOR_LIGHT)
    return scenario, fund_v, harbor


def test_scope_violation_outranks_call_state_on_settle(asset_manager_headers):
    """PRD §2.9: "The order is strict, and the first failing rule wins; a later
    rule is never permitted to mask an earlier one."
    PRD §2.9: "Referential scope. An entity-backed actor must own the target, a
    nested child must carry the path parent's project identifier, and the
    settling capital call's project must be financed by the subscription's fund.
    Failure is `ERR_FORBIDDEN_SCOPE`, HTTP 403."

    The call is still SCHEDULED, so the target-state rule would also fail; the
    scope rule is a lower tier number and must win.

    Design: Difficulty/priority_pair_validation_conflict/referential_scope_outranks_call_state_on_settle
    """
    scenario, fund_v, harbor = _two_fund_setup()
    call = schedule_capital_call(harbor["id"], "CONSTRUCTION_START")
    assert call["status"] == "SCHEDULED"

    response = api_client.settle_capital_call(
        call["id"], 1000000, make_investor_headers(scenario.investor["id"])
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_SCOPE)


def test_the_outranked_state_rule_leaves_the_call_untouched(asset_manager_headers):
    """PRD §2.9: "a request which is stale and also violates a bucket rule reports
    the stale-version failure."
    PRD §3.5: "A settlement requested against a call that is not `ISSUED` is
    rejected with `ERR_CALL_NOT_ISSUED`"

    Design: Difficulty/priority_pair_validation_conflict/referential_scope_outranks_call_state_on_settle
    """
    scenario, fund_v, harbor = _two_fund_setup()
    call = schedule_capital_call(harbor["id"], "CONSTRUCTION_START")

    response = api_client.settle_capital_call(
        call["id"], 1000000, make_investor_headers(scenario.investor["id"])
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_SCOPE)

    from test_helpers import find_capital_call

    unchanged = find_capital_call(harbor["id"], call["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["settled_amount_cents"] == 0
    assert unchanged["shortfall_cents"] == 0


def test_fiscal_capacity_outranks_the_subscription_window():
    """PRD §2.9: "The ten priority tiers, from first to last, are as follows."
    PRD §2.9: "Equity buckets. A subscription may not exceed the fund's remaining
    raise nor the investor's remaining capacity against its tier cap
    (`ERR_SUBSCRIPTION_EXCEEDS_CAPACITY`)".
    PRD §2.9: "The three rejection codes here are HTTP 422."
    PRD §2.9: "Temporal windows. Subscription creation requires the logical clock
    to fall within the fund's subscription window
    (`ERR_SUBSCRIPTION_WINDOW_CLOSED`)."

    Meridian has 40000000 cents of headroom left against its 500000000-cent
    capacity, and the target fund's window has not opened yet, so both the
    bucket rule and the window rule fail; the bucket rule is the earlier tier.

    Design: Difficulty/priority_pair_validation_conflict/fiscal_capacity_outranks_subscription_window_on_late_subscription
    """
    set_logical_clock(_CLOCK_0902)
    developer = onboard_developer()
    investor = onboard_investor()
    fund_open = form_fund()
    open_subscription(fund_open, investor, committed_cents=460000000)

    late_fund = form_fund(
        fund_name="ECP Housing Fund IX",
        target_equity_cents=500000000,
        price_per_credit_dollar=0.9100,
        target_yield_pct=0.068,
        close_threshold_pct=0.85,
        subscription_open_date="2027-01-01T00:00:00Z",
        subscription_close_date="2027-12-31T00:00:00Z",
    )

    response = api_client.create_subscription(
        late_fund["id"],
        create_subscription_payload(
            investor_id=investor["id"],
            expected_fund_version=late_fund["version"],
            committed_cents=60000000,
            payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_EXCEEDS_CAPACITY)
    assert read_investor(investor["id"])["outstanding_commitment_cents"] == 460000000


def test_a_subscription_within_capacity_is_still_blocked_by_the_window():
    """PRD §3.2: "The subscription must also fall inside the fund's raise window:
    the logical clock must be at or after `subscription_open_date` and at or
    before `subscription_close_date`, and a request outside that window is
    rejected with `ERR_SUBSCRIPTION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/fiscal_capacity_outranks_subscription_window_on_late_subscription
    """
    set_logical_clock(_CLOCK_0902)
    developer = onboard_developer()
    investor = onboard_investor()
    fund_open = form_fund()
    open_subscription(fund_open, investor, committed_cents=460000000)

    late_fund = form_fund(
        fund_name="ECP Housing Fund IX",
        target_equity_cents=500000000,
        price_per_credit_dollar=0.9100,
        target_yield_pct=0.068,
        close_threshold_pct=0.85,
        subscription_open_date="2027-01-01T00:00:00Z",
        subscription_close_date="2027-12-31T00:00:00Z",
    )

    response = api_client.create_subscription(
        late_fund["id"],
        create_subscription_payload(
            investor_id=investor["id"],
            expected_fund_version=late_fund["version"],
            committed_cents=40000000,
            payin_schedule_entries=[{"milestone": "CONSTRUCTION_START", "share_pct": 1.0}],
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_WINDOW_CLOSED)
    assert read_fund(late_fund["id"])["subscribed_equity_cents"] == 0
