"""Two machines that are not simple forward chains.

PRD 3.5 runs an exchange transaction on two independent axes: "settlement_status
and compliance_status advance independently of one another", so a FLAG never blocks
a settle.  PRD 3.3 gives the stocking plan the one backward edge in the domain: a
REJECT decision "sends the plan SUBMITTED to DRAFT and increases revision_count by
one; the plan may then be revised and resubmitted any number of times".
"""

from test_helpers import (
    OPERATORS,
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_success,
)

MIX = [f.denom(2000, 10), f.denom(5000, 10), f.denom(10000, 20)]
DEAL = [f.denom(10000, 1), f.denom(5000, 1), f.denom(2000, 2)]


def test_a_flagged_transaction_still_settles_on_the_settlement_axis(
    api, teller_headers, compliance_headers
):
    """An AUTHORIZED deal flagged by compliance settles to SETTLED with a
    21626-cent settled gross and draws 19000 minor units out of the 270000-unit
    position, while compliance_status stays FLAGGED - the settle never touches the
    other axis.

    Design: Difficulty/non_linear_state_machine/exchange_transaction_parallel_axes_settle_while_compliance_flagged
    """
    world = fx.trading_world(api, vault_limit_usd_cents=20_000_000, position_mix=MIX)
    txn = fx.authorized_deal(api, world, denominations=DEAL, headers=teller_headers)
    assert txn["settlement_status"] == "AUTHORIZED"

    flagged = fx.decide_compliance(
        api, txn["id"], "FLAG", "unusual denomination request", compliance_headers
    )
    assert flagged["compliance_status"] == "FLAGGED"

    settled = validate_success(api.settle_transaction(txn["id"], teller_headers))

    assert settled["settlement_status"] == "SETTLED"
    assert settled["compliance_status"] == "FLAGGED"
    assert settled["settled_usd_gross_cents"] == 21626
    a.assert_timestamp_equals(settled["settled_at"], "2026-08-01T00:00:00Z")

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    assert position["total_minor_units"] == 251000


def test_clearing_after_settlement_moves_only_the_compliance_axis(
    api, teller_headers, compliance_headers
):
    """A CLEAR decision on an already-SETTLED, FLAGGED transaction advances
    compliance_status to CLEARED and leaves settlement_status at SETTLED with the
    same 21626-cent settled gross, proving the combined state is stable rather than
    a transient the machine collapses.

    Design: Difficulty/non_linear_state_machine/exchange_transaction_parallel_axes_settle_while_compliance_flagged
    """
    world = fx.trading_world(api, vault_limit_usd_cents=20_000_000, position_mix=MIX)
    txn = fx.authorized_deal(api, world, denominations=DEAL, headers=teller_headers)
    fx.decide_compliance(api, txn["id"], "FLAG", headers=compliance_headers)
    fx.settle_deal(api, txn["id"], teller_headers)

    cleared = fx.decide_compliance(
        api, txn["id"], "CLEAR", "reviewed and released", compliance_headers
    )

    a.assert_exchange_transaction(cleared)
    assert cleared["compliance_status"] == "CLEARED"
    assert cleared["settlement_status"] == "SETTLED"
    assert cleared["settled_usd_gross_cents"] == 21626
    assert cleared["settled_by_user_id"] == OPERATORS["TELLER_1"]


def _submitted_plan(api):
    """A 92-day EUR plan submitted once by the branch manager."""
    branch = fx.register_branch(api, vault_limit_usd_cents=5_000_000)
    fx.register_currency(api)
    fx.record_wholesale_rate(api)
    corridor = fx.register_corridor(
        api,
        code="LHR-CMN-SUMMER",
        destination_country_code="MA",
        destination_currency_code="EUR",
        season="SUMMER",
        season_start_date="2026-06-01T00:00:00Z",
        season_end_date="2026-09-01T00:00:00Z",
        demand_index_bps=13500,
    )
    plan = fx.draft_plan(
        api,
        branch["id"],
        corridor["id"],
        season_days=92,
        target_lines=[f.target_line("EUR", 2000)],
    )
    assert plan["revision_count"] == 0
    return fx.submit_plan(api, plan["id"])


def test_reject_walks_the_backward_edge_and_counts_the_revision(api, treasury_headers):
    """A REJECT decision returns the plan SUBMITTED to DRAFT and lifts
    revision_count from 0 to 1, recording the reviewing operator and the note.

    Design: Difficulty/non_linear_state_machine/inventory_plan_reject_resubmit_cycle_increments_revision_count
    """
    plan = _submitted_plan(api)
    assert plan["status"] == "SUBMITTED"
    assert plan["submitted_by_user_id"] == OPERATORS["MANAGER"]

    rejected = fx.review_plan(api, plan["id"], "REJECT", "trim the EUR line", treasury_headers)

    a.assert_inventory_plan(rejected)
    assert rejected["status"] == "DRAFT"
    assert rejected["revision_count"] == 1
    assert rejected["reviewed_by_user_id"] == OPERATORS["TREASURY"]
    assert rejected["review_note"] == "trim the EUR line"


def test_resubmission_after_rejection_does_not_bump_the_revision_count_again(
    api, treasury_headers
):
    """The cycle DRAFT to SUBMITTED to DRAFT to SUBMITTED to APPROVED leaves
    revision_count at 1 - only the backward edge counts - and the approved plan
    still carries the 250000-unit EUR target.

    Design: Difficulty/non_linear_state_machine/inventory_plan_reject_resubmit_cycle_increments_revision_count
    """
    plan = _submitted_plan(api)
    fx.review_plan(api, plan["id"], "REJECT", "trim the EUR line", treasury_headers)

    resubmitted = fx.submit_plan(api, plan["id"], [f.target_line("EUR", 2000)])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1

    approved = fx.review_plan(api, plan["id"], "APPROVE", headers=treasury_headers)
    assert approved["status"] == "APPROVED"
    assert approved["revision_count"] == 1
    assert approved["submitted_by_user_id"] == OPERATORS["MANAGER"]
    assert approved["reviewed_by_user_id"] == OPERATORS["TREASURY"]
    assert approved["computed_targets"] == [
        {"currency_code": "EUR", "target_minor_units": 250000}
    ]
