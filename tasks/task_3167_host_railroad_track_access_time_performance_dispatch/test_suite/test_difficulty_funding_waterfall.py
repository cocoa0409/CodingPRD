"""Funding allocation waterfall: the pinned per-line rounding order."""

from test_helpers import fixtures


def test_per_line_rounded_state_shares_sum_above_period_cost(api):
    """Each state line is rounded independently; the corridor total is the sum of lines.

    Annual cost 10,000,000 cents prorated over 30 days rounds to 821,918;
    the IL line rounds 205,479.5 to 205,480 and the MO line rounds 616,438.5
    to 616,439, so the committed lines sum to 821,919 - one cent above the
    rounded period cost.

    PRD: "First, the period's allocatable cost is the corridor's `annual_cost_cents` prorated by the inclusive day count of the period over 365, rounded half-up to whole cents — this is rounding step one."
    PRD: "Second, the corridor's total mileage is the sum over its segments (of any status) of `milepost_end` minus `milepost_start`, and each state's line is the rounded period cost multiplied by the sum of segment miles lying in that state and divided by the corridor's total miles, rounded half-up to whole cents per line — this is rounding step two, applied to each state line independently."
    PRD: "The authoritative corridor total is the **sum of the rounded per-state lines**; the rounding remainder is deliberately not redistributed, so the total of all states' lines may differ from the rounded period cost."
    Design: Difficulty/combinatorial_formula/funding_allocation_per_line_rounding
    """
    net = fixtures.setup_network(api)
    fa_il = fixtures.create_funding(api, net, "IL", period_start="2026-09-01", period_end="2026-09-30")
    fa_mo = fixtures.create_funding(api, net, "MO", period_start="2026-09-01", period_end="2026-09-30")

    committed_il = fixtures.commit_funding(api, fa_il["id"])
    committed_mo = fixtures.commit_funding(api, fa_mo["id"])

    assert committed_il["status"] == "COMMITTED"
    assert committed_mo["status"] == "COMMITTED"
    assert committed_il["allocated_cost_cents"] == 205480
    assert committed_mo["allocated_cost_cents"] == 616439
    assert committed_il["allocated_cost_cents"] + committed_mo["allocated_cost_cents"] == 821919


def test_committed_agreement_carries_its_own_states_rounded_line(api):
    """The committed agreement's allocated_cost_cents is its own state's rounded line.

    PRD: "The committed agreement's `allocated_cost_cents` is its own state's rounded line."
    Design: Difficulty/combinatorial_formula/funding_allocation_per_line_rounding
    """
    net = fixtures.setup_network(api)
    fa_il = fixtures.create_funding(api, net, "IL", period_start="2026-09-01", period_end="2026-09-30")
    fa_mo = fixtures.create_funding(api, net, "MO", period_start="2026-09-01", period_end="2026-09-30")

    committed_il = fixtures.commit_funding(api, fa_il["id"])
    committed_mo = fixtures.commit_funding(api, fa_mo["id"])

    # IL spans 10.0 of the corridor's 40.0 miles; MO spans 30.0.
    assert committed_il["allocated_cost_cents"] == 205480
    assert committed_mo["allocated_cost_cents"] == 616439
    # The remainder is not redistributed: the sum is one cent above 821918.
    assert committed_il["allocated_cost_cents"] + committed_mo["allocated_cost_cents"] != 821918
