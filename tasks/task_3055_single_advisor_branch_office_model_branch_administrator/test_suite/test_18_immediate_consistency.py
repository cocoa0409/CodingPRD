"""Immediate consistency: derived totals visible in the next read."""
from test_helpers import (
    TEST_USERS, api_client,
    setup_open_branch_with_period, post_production, post_charge, get_period,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_immediate_consistency_derived_fields_same_request():
    """PRD §3.5: "Every charge post or reversal recomputes the period's
    aggregates while the period is `OPEN` or `CLOSED`: `gross_revenue_cents`
    is the sum of `POSTED` revenue lines for the branch inside the period
    window; `total_charges_cents` is the sum of `POSTED`, non-reversed charge
    amounts for the period; `net_profit_cents` is gross revenue minus total
    charges and may go negative; and `advisor_share_cents` is recomputed in
    its provisional variant (§3.6)."

    Design: Corner/consistency_model/immediate_consistency_derived_fields_same_request
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 500000, "2026-09-10T00:00:00Z")

    post_charge(period["id"], branch["id"], 100000, "LEASE_RENT")

    snapshot = get_period(period["id"])
    assert snapshot["total_charges_cents"] == 100000
    assert snapshot["net_profit_cents"] == 400000
    # 400000 * 0.38 = 152000
    assert snapshot["advisor_share_cents"] == 152000
