"""Transitive cascades: charge-post recompute chain and advisor termination."""
from test_helpers import (
    TEST_USERS, validate_success, validate_paginated, get_success_data,
    api_client, setup_open_branch_with_period,
    setup_practicing_advisor_with_solicitation,
    post_production, post_charge, get_period,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_charge_post_recomputes_period_aggregates():
    """PRD §3.5: "Every charge post or reversal recomputes the period's
    aggregates while the period is `OPEN` or `CLOSED`: `gross_revenue_cents`
    is the sum of `POSTED` revenue lines for the branch inside the period
    window; `total_charges_cents` is the sum of `POSTED`, non-reversed charge
    amounts for the period; `net_profit_cents` is gross revenue minus total
    charges and may go negative; and `advisor_share_cents` is recomputed in
    its provisional variant (§3.6)."

    Design: Difficulty/transitive_cascade/charge_post_cascade_to_share_and_tier
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 900000, "2026-09-10T00:00:00Z")

    post_charge(period["id"], branch["id"], 480000, "BOA_PAYROLL")
    snapshot = get_period(period["id"])
    assert snapshot["total_charges_cents"] == 480000
    assert snapshot["net_profit_cents"] == 420000
    # provisional share: 420000 * 0.38 = 159600
    assert snapshot["advisor_share_cents"] == 159600
    assert snapshot["deficit_carryforward_cents"] == 0


def test_second_charge_recomputes_again_from_new_base():
    """PRD §3.5: "Every charge post or reversal recomputes the period's
    aggregates while the period is `OPEN` or `CLOSED`: `gross_revenue_cents`
    is the sum of `POSTED` revenue lines for the branch inside the period
    window; `total_charges_cents` is the sum of `POSTED`, non-reversed charge
    amounts for the period; `net_profit_cents` is gross revenue minus total
    charges and may go negative; and `advisor_share_cents` is recomputed in
    its provisional variant (§3.6)."

    Design: Difficulty/transitive_cascade/charge_post_cascade_to_share_and_tier
    """
    branch, territory, advisor, boa, period = setup_open_branch_with_period()
    post_production(advisor["id"], 900000, "2026-09-10T00:00:00Z")

    post_charge(period["id"], branch["id"], 480000, "BOA_PAYROLL")
    first = get_period(period["id"])
    assert first["net_profit_cents"] == 420000
    assert first["advisor_share_cents"] == 159600

    post_charge(period["id"], branch["id"], 20000, "EQUIPMENT")
    second = get_period(period["id"])
    assert second["total_charges_cents"] == 500000
    assert second["net_profit_cents"] == 400000
    assert second["advisor_share_cents"] == 152000


def test_advisor_termination_cascades_branch_territory_solicitations():
    """PRD §3.7: "The termination cascade then: clears the advisor's
    `branch_id`; drops the branch's staffing to `UNSTAFFED` — the
    administrator stays employed, but the branch loses `FULLY_STAFFED`;
    suspends the branch's operations (`OPEN → SUSPENDED`-equivalent
    `operating_status`), since no advisor remains to run the practice;
    releases the territory assignment — `assigned_advisor_id` cleared,
    `assignment_end` stamped, territory back to `OPEN`; and withdraws every
    `SUBMITTED` solicitation request the advisor had outstanding, moving each
    to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/advisor_termination_cascade_branch_and_territory
    """
    branch, advisor, entry, request = setup_practicing_advisor_with_solicitation()

    validate_success(api_client.terminate_advisor(advisor["id"], ADMIN))

    advisor_after = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert advisor_after["status"] == "TERMINATED"
    assert advisor_after["branch_id"] is None

    branch_after = get_success_data(api_client.get_branch(branch["id"], ADMIN))
    assert branch_after["operating_status"] == "SUSPENDED"
    assert branch_after["staffing_status"] == "UNSTAFFED"

    territory_after = get_success_data(
        api_client.get_territory(branch["territory_id"], ADMIN)
    )
    assert territory_after["status"] == "OPEN"
    assert territory_after["assigned_advisor_id"] is None
    assert territory_after["assignment_end"] is not None

    requests, meta = validate_paginated(
        api_client.list_solicitation_requests(ADMIN, params={"advisor_id": advisor["id"]})
    )
    assert len(requests) == 1
    assert requests[0]["status"] == "WITHDRAWN"


def test_advisor_termination_keeps_administrator_employed():
    """PRD §3.7: "The termination cascade then: clears the advisor's
    `branch_id`; drops the branch's staffing to `UNSTAFFED` — the
    administrator stays employed, but the branch loses `FULLY_STAFFED`;
    suspends the branch's operations (`OPEN → SUSPENDED`-equivalent
    `operating_status`), since no advisor remains to run the practice;
    releases the territory assignment — `assigned_advisor_id` cleared,
    `assignment_end` stamped, territory back to `OPEN`; and withdraws every
    `SUBMITTED` solicitation request the advisor had outstanding, moving each
    to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/advisor_termination_cascade_branch_and_territory
    """
    branch, territory, advisor, boa, _period = setup_open_branch_with_period()
    assert branch["staffing_status"] == "FULLY_STAFFED"

    validate_success(api_client.terminate_advisor(advisor["id"], ADMIN))

    boa_after = get_success_data(api_client.get_administrator(boa["id"], ADMIN))
    assert boa_after["status"] == "ACTIVE"
    assert boa_after["branch_id"] == branch["id"]

    branch_after = get_success_data(api_client.get_branch(branch["id"], ADMIN))
    assert branch_after["staffing_status"] == "UNSTAFFED"
    assert branch_after["operating_status"] == "SUSPENDED"
