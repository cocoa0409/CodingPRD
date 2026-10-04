"""Breadth: action endpoints that compute a value as a side effect.

The portfolio-summary corner instance is not translated: the PRD names the
summary's fields but never declares the surface they are returned on, so two
faithful readers could place them on different endpoints and field names.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    find_capital_call,
    issue_call,
    schedule_capital_call,
    set_logical_clock,
    setup_committed_project,
)


def _scheduled_call_scenario():
    scenario = setup_committed_project()
    call = schedule_capital_call(
        scenario.project["id"],
        "CONSTRUCTION_START",
        scheduled_date="2026-10-01T00:00:00Z",
        due_date="2026-10-31T00:00:00Z",
        milestone_share=0.20,
    )
    scenario.call = call
    return scenario


def test_a_scheduled_call_carries_no_called_amount_and_a_zero_adjuster():
    """PRD §3.5: "A newly scheduled call begins at `SCHEDULED`, with
    `credit_delivery_adjuster_pct` at 0.0, `settled_amount_cents` at 0, and
    `shortfall_cents` at 0, and it increments the project's `version`."

    Design: Corner/endpoints/capital_call_issue_side_effect_computes_and_stores_the_adjusted_amount
    """
    scenario = _scheduled_call_scenario()
    call = scenario.call

    assert call["status"] == "SCHEDULED"
    assert call["called_amount_cents"] == 0
    assert call["credit_delivery_adjuster_pct"] == pytest.approx(0.0, abs=1e-9)
    assert call["settled_amount_cents"] == 0
    assert call["shortfall_cents"] == 0
    assert call["base_call_cents"] == 0


def test_issuing_a_call_computes_and_stores_the_adjusted_amount():
    """PRD §3.5: "Issuing a call computes its `called_amount_cents`."
    PRD §3.5: "A ratio below 0.90 selects 0.20."

    Nothing has been delivered against the committed allocation, so the delivery
    ratio is 0 and the band is 0.20; the base is round(529436038 * 0.20) =
    105887208 and the called amount is round(105887208 * 1.20) = 127064650.

    PRD §3.5: "The logical clock must be at or after the call's `scheduled_date`,
    else the request is rejected with `ERR_CALL_NOT_DUE`."

    Design: Corner/endpoints/capital_call_issue_side_effect_computes_and_stores_the_adjusted_amount
    """
    scenario = _scheduled_call_scenario()
    # The call is scheduled for 2026-10-01 and the scenario leaves the clock at
    # 2026-09-02, so advance it past the scheduled date before issuing.
    set_logical_clock("2026-10-05T00:00:00Z")

    issued = issue_call(scenario.call["id"])

    assert issued["status"] == "ISSUED"
    assert issued["base_call_cents"] == 105887208
    assert issued["credit_delivery_adjuster_pct"] == pytest.approx(0.20, abs=1e-9)
    assert issued["called_amount_cents"] == 127064650
    assert issued["shortfall_cents"] == 0

    stored = find_capital_call(scenario.project["id"], scenario.call["id"])
    assert stored["called_amount_cents"] == 127064650
