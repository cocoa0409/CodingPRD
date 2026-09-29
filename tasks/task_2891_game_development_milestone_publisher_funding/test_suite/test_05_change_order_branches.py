"""Change-order decisions: the feature-cut branch writes funding, relief and the ship
date, while the decline branch writes nothing but its own state."""

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal, assert_ledger, assert_pct_equals
from test_helpers.fixtures import read_agreement, read_milestone, setup_aurora_drift
from prd_bench_local_runner.testing import validate_success

CUT_RATIONALE = "Cut the tutorial cinematic and pull the ship date in"
UPLIFT_RATIONALE = "Extra co-op QA pass"


def _approved_cut(scenario):
    """A 300000 FEATURE_CUT on M1 carrying 10.00 points of relief and -20 days."""
    reg = scenario.reg
    order = validate_success(
        reg.api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m1["id"], "FEATURE_CUT",
                scenario.version(), CUT_RATIONALE,
                requested_amount_cents=300000, ship_date_delta_days=-20,
                content_threshold_relief_pct=10.00,
            ),
            reg.dev,
        ),
        201,
    )
    assert order["state"] == "PROPOSED"
    decided = validate_success(
        reg.api.decide_change_order(order["id"], f.approve_payload("Cut approved"), reg.finance)
    )
    return order, decided


def _declined_uplift(scenario):
    """A 200000 FUNDING_UPLIFT on M2 asking for +15 days, then refused."""
    reg = scenario.reg
    order = validate_success(
        reg.api.create_change_order(
            f.change_order_payload(
                scenario.agreement_id, scenario.m2["id"], "FUNDING_UPLIFT",
                scenario.version(), UPLIFT_RATIONALE,
                requested_amount_cents=200000, ship_date_delta_days=15,
            ),
            reg.dev,
        ),
        201,
    )
    decided = validate_success(
        reg.api.decide_change_order(
            order["id"],
            f.decline_payload("No additional funding this quarter"),
            reg.finance,
        )
    )
    return order, decided


def test_the_approved_cut_credits_the_milestone_funding_back_to_the_pool(api):
    """PRD §3.7 branch B: "the target milestone's `uplift_cents` is *reduced* by
    `requested_amount_cents`, crediting that money back to the pool; and the
    milestone's `content_threshold_relief_pct` grows by the order's own
    `content_threshold_relief_pct`" while "`uplift_funded_cents` is deliberately
    **not** touched".

    Design: Difficulty/non_linear_state_machine/change_order_branch_cut_moves_funding_and_schedule_while_decline_branch_moves_nothing
    """
    scenario = setup_aurora_drift(api)
    _order, decided = _approved_cut(scenario)

    assert decided["state"] == "APPROVED_CUT"
    assert decided["decided_at"] is not None

    milestone = read_milestone(scenario.reg, scenario.m1["id"])
    assert milestone["uplift_cents"] == -300000
    assert_pct_equals(milestone["content_threshold_relief_pct"], 10.00, "relief")

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert_ledger(
        agreement,
        committed_cents=11700000,
        available_funding_cents=300000,
        funding_pool_cents=12000000,
        uplift_funded_cents=0,
    )


def test_the_approved_cut_pulls_the_current_ship_date_forward(api):
    """PRD §3.7: "set `ship_date_current` to `ship_date_original` advanced by the sum
    of their `ship_date_delta_days` in whole calendar days. `schedule_slip_days` is
    then the difference in whole days between `ship_date_current` and
    `ship_date_original`, and it is negative when accumulated cuts have pulled the
    date earlier than the contract's original."

    Design: Difficulty/non_linear_state_machine/change_order_branch_cut_moves_funding_and_schedule_while_decline_branch_moves_nothing
    """
    scenario = setup_aurora_drift(api)
    _approved_cut(scenario)

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert_fields_equal(
        agreement,
        {"ship_date_current": "2027-03-11", "ship_date_original": "2027-03-31",
         "schedule_slip_days": -20},
        "agreement",
    )


def test_the_declined_order_writes_only_its_own_state(api):
    """PRD §3.7 branch C: "A decline writes the order's `state` as `DECLINED` and its
    `decided_at`, and nothing else at all: no funding field, no content threshold and
    no ship date moves."

    Design: Difficulty/non_linear_state_machine/change_order_branch_cut_moves_funding_and_schedule_while_decline_branch_moves_nothing
    """
    scenario = setup_aurora_drift(api)
    _approved_cut(scenario)
    _order, declined = _declined_uplift(scenario)

    assert declined["state"] == "DECLINED"
    assert declined["decided_at"] is not None

    milestone = read_milestone(scenario.reg, scenario.m2["id"])
    assert milestone["uplift_cents"] == 0
    assert_pct_equals(milestone["content_threshold_relief_pct"], 0.00, "relief")

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert_ledger(
        agreement,
        committed_cents=11700000,
        available_funding_cents=300000,
        uplift_funded_cents=0,
        funding_pool_cents=12000000,
    )
    assert_fields_equal(
        agreement,
        {"ship_date_current": "2027-03-11", "schedule_slip_days": -20},
        "agreement",
    )
