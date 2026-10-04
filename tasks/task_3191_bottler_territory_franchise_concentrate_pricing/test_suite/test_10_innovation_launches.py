"""Innovation launches: commitment review fork, penalty tiers, time gating."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    get_success_data,
    seed_active_agreement,
    create_launch,
    launch_to_in_production,
    record_sales,
    set_clock,
    ops_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def _launch_in_production(env, committed_cases=50000, launch_end="2026-10-31"):
    launch = create_launch(env, committed_cases=committed_cases, launch_end=launch_end)
    launch_to_in_production(env, launch["id"])
    return launch


def test_launch_fork_penalized_applies_penalty_and_margin_debit(api):
    """PRD §3.7: "Otherwise the launch lands in the terminal `PENALIZED` state,
    and a shortfall penalty is computed: the shortfall is `committed_cases`
    minus `cases_sold`, and the shortfall percentage is that shortfall divided
    by `committed_cases`, compared in exact rational arithmetic."
    PRD §3.7: "when it is greater than ten percent but at most twenty-five
    percent, the rate is 12 cents per case on the whole shortfall; beyond
    twenty-five percent the rate is 25 cents per case on the whole shortfall."
    PRD §3.7: "`penalty_cents` is the shortfall multiplied by the selected
    rate, and the same amount is subtracted from the agreement's
    `margin_ledger_cents` — the second source feeding that ledger after the NCA
    cascade of §3.3."

    Design: Corner/state_machines/launch_fork_penalized_applies_penalty_and_margin_debit
    """
    env = seed_active_agreement()
    launch = _launch_in_production(env)
    record_sales(env, launch["id"], 44999)
    set_clock("2026-11-01T00:00:00Z")
    r = api_client.review_commitment(launch["id"], BOA)
    assert r.status_code == 200
    data = get_success_data(r)
    # shortfall 5001 of 50000 -> 10.002% -> 12-cent tier -> 5001 * 12 = 60012
    assert data["status"] == "PENALIZED"
    assert data["penalty_cents"] == 60012
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["margin_ledger_cents"] == -60012


def test_launch_penalty_exactly_ten_percent_shortfall_uses_lowest_tier(api):
    """PRD §3.7: "When the shortfall percentage is at most ten percent, the
    rate is 5 cents per case; when it is greater than ten percent but at most
    twenty-five percent, the rate is 12 cents per case on the whole shortfall;
    beyond twenty-five percent the rate is 25 cents per case on the whole
    shortfall. A shortfall of exactly ten percent sits in the 5-cent tier,
    because the tier boundary is inclusive."

    Design: Corner/calculations/launch_penalty_exactly_ten_percent_shortfall_uses_lowest_tier
    """
    env = seed_active_agreement()
    launch = _launch_in_production(env)
    record_sales(env, launch["id"], 45000)
    set_clock("2026-11-01T00:00:00Z")
    r = api_client.review_commitment(launch["id"], BOA)
    assert r.status_code == 200
    data = get_success_data(r)
    # shortfall 5000 of 50000 -> exactly 10% -> 5-cent tier -> 25000
    assert data["status"] == "PENALIZED"
    assert data["penalty_cents"] == 25000
    agreement = get_success_data(api_client.get_agreement(env["agreement"]["id"], PA))
    assert agreement["margin_ledger_cents"] == -25000


def test_launch_review_before_window_end_rejected(api):
    """PRD §3.7: "**Commitment review** is performed by the brand owner's staff
    once the logical clock's current date is strictly after `launch_end`;
    reviewing earlier is rejected with `ERR_COMMITMENT_WINDOW_OPEN`
    (HTTP 409)."

    Design: Corner/state_machines/launch_review_before_window_end_rejected
    """
    env = seed_active_agreement()
    launch = _launch_in_production(env)
    set_clock("2026-10-15T00:00:00Z")
    r = api_client.review_commitment(launch["id"], BOA)
    validate_error(r, ApiErrorId.ERR_COMMITMENT_WINDOW_OPEN.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_innovation_launch(launch["id"], PA))
    assert after["status"] == "IN_PRODUCTION"


def test_launch_changeover_with_retired_product_line_rejected(api):
    """PRD §3.7: "Scheduling requires the product line to still be `ACTIVE` — a
    retired line yields `ERR_LAUNCH_PRODUCT_INACTIVE` (HTTP 409) — and the
    agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`, HTTP 409)."

    Design: Corner/errors/launch_changeover_with_retired_product_line_rejected
    """
    env = seed_active_agreement()
    launch = create_launch(env)
    r = api_client.retire_product_line(env["line"]["id"], BOA)
    assert r.status_code == 200
    r = api_client.schedule_changeover(launch["id"], ops_headers(env))
    validate_error(r, ApiErrorId.ERR_LAUNCH_PRODUCT_INACTIVE.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_innovation_launch(launch["id"], PA))
    assert after["status"] == "PLANNED"
