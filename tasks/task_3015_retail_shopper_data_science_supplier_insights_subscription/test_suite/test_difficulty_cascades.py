"""Transitive cascades: contract suspension fans out through reports,
deliverables, and cycle counters; cycle lock fans out through deliverables
into the funding contract's compliance score."""

from test_helpers import (
    account_with_contract,
    create_cycle,
    create_deliverable,
    create_report,
    get_success_data,
    list_cycle_deliverables,
    read_contract,
    read_cycle,
    set_clock,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
MANAGER = TEST_USERS["category_manager_headers"]


def _suspended_cascade_world(api):
    """ACTIVE contract with a REQUESTED report whose PLANNED deliverable sits in a cycle."""
    world = account_with_contract(
        api, name="Epsilon Eggs", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    cycle = create_cycle(api)
    deliverable = create_deliverable(api, cycle["id"], world["contract"]["id"], report["id"])
    return world, report, cycle, deliverable


def test_suspend_cascades_report_cancel_to_deliverable_block(api):
    """Suspending cancels the open report, and the deliverable it backs is blocked.

    PRD: "every insight report of the contract still in `REQUESTED` or `GENERATING` is moved to `CANCELLED` and its reserved credits are refunded to the contract (the reserved counter decreases by the cancelled report's `credit_cost`); every review deliverable backed by one of those cancelled reports and still in `PLANNED` moves to `BLOCKED`"
    Design: Difficulty/transitive_cascade/contract_suspend_three_level_cascade
    """
    world, report, cycle, deliverable = _suspended_cascade_world(api)
    suspended = get_success_data(api.suspend_contract(world["contract"]["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    report_after = get_success_data(api.get_insight_report(report["id"], ADMIN))
    assert report_after["status"] == "CANCELLED"
    deliverables = list_cycle_deliverables(api, cycle["id"])
    assert deliverables[0]["status"] == "BLOCKED"


def test_suspend_cascade_refunds_reservation_and_decrements_cycle_count(api):
    """The three-level cascade also releases the reserved credit and drops planned_open_count to zero.

    PRD: "and for each deliverable so blocked, its line review cycle's `planned_open_count` decreases by one, because that counter tracks only deliverables in `PLANNED` or `SUBMITTED`."
    PRD: "every insight report of the contract still in `REQUESTED` or `GENERATING` is moved to `CANCELLED` and its reserved credits are refunded to the contract (the reserved counter decreases by the cancelled report's `credit_cost`)"
    Design: Difficulty/transitive_cascade/contract_suspend_three_level_cascade
    """
    world, report, cycle, deliverable = _suspended_cascade_world(api)
    get_success_data(api.suspend_contract(world["contract"]["id"], ADMIN))
    contract = read_contract(api, world["contract"]["id"])
    assert contract["report_credits_reserved"] == 0
    cycle_after = read_cycle(api, cycle["id"])
    assert cycle_after["planned_open_count"] == 0


def _lock_cascade_world(api):
    """Contract + REQUESTED report + PLANNED deliverable; clock advanced so the cycle is OPEN."""
    world = account_with_contract(api, name="Zeta Zucchini", scope_category="SNACKS", scope_brands=["ACME"])
    report = create_report(api, world["contract"]["id"], world["analyst_headers"])
    cycle = create_cycle(api)
    deliverable = create_deliverable(api, cycle["id"], world["contract"]["id"], report["id"])
    set_clock(api, "2026-09-07T00:00:00Z")
    assert read_cycle(api, cycle["id"])["status"] == "OPEN", "Setup failed: cycle did not auto-open"
    return world, report, cycle, deliverable


def test_lock_marks_planned_deliverable_missed(api):
    """Locking an OPEN cycle moves its still-PLANNED deliverable to terminal MISSED.

    PRD: "The lock cascades: every deliverable of the cycle still in `PLANNED` moves to its terminal `MISSED` state"
    Design: Difficulty/transitive_cascade/cycle_lock_two_level_compliance_cascade
    """
    world, report, cycle, deliverable = _lock_cascade_world(api)
    locked = get_success_data(api.lock_cycle(cycle["id"], MANAGER))
    assert locked["status"] == "LOCKED"
    deliverables = list_cycle_deliverables(api, cycle["id"])
    assert deliverables[0]["status"] == "MISSED"


def test_lock_cascade_applies_missed_penalty_to_funding_contract(api):
    """The missed deliverable debits the funding contract's compliance score from 1000 to 975.

    PRD: "for each missed deliverable the funding contract's `compliance_score` decreases by twenty-five points — the missed-deliverable penalty — floored at zero"
    PRD: "the contract carries a `compliance_score` that starts at 1000 and only ever decreases (see §3.7), with a floor of zero."
    Design: Difficulty/transitive_cascade/cycle_lock_two_level_compliance_cascade
    """
    world, report, cycle, deliverable = _lock_cascade_world(api)
    get_success_data(api.lock_cycle(cycle["id"], MANAGER))
    contract = read_contract(api, world["contract"]["id"])
    assert contract["compliance_score"] == 975
    cycle_after = read_cycle(api, cycle["id"])
    assert cycle_after["planned_open_count"] == 0
