"""Cyclic lock lifecycles and the two independent application dimensions."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, SALES_HEADERS


def locked_deal(api, *, lock_days=30):
    """A contract driven to LOCKED off a 30-day lock on a qualified application."""
    world = fixtures.build_deal(api)
    fixtures.give_lock(api, world, lock_days=lock_days)
    fixtures.drive_lock(api, world)
    return world


def test_a_lapsed_lock_leaves_the_contract_pending_and_can_be_revived(api):
    """The lock leaves ACTIVE by expiry and re-enters ACTIVE by relock.

    PRD §2.13: "a rate lock whose `lock_expires_iso` has passed moves from `ACTIVE`
    to `EXPIRED`".
    PRD §3.5: "Reviving the lock then cascades the owning contract from `PENDING`
    back to `LOCKED`, its disclosures from `ISSUED` to `ACKNOWLEDGED`, the buyer
    from `CONTRACTED` to `QUALIFIED`, and recomputes the buyer's
    `total_incentive_received_cents`."
    Design: Difficulty/non_linear_state_machine/rate_lock_relock_cycle_returns_to_active
    """
    world = locked_deal(api, lock_days=30)

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    lapsed = fixtures.read_rate_lock(api, world["lk1"])
    assert lapsed["lock_status"] == "EXPIRED", (
        f"the expiry instant is past the clock, got {lapsed['lock_status']}"
    )
    pending = fixtures.read_contract(api, world["ct1"])
    assert pending["contract_status"] == "PENDING", (
        f"the expiry pushes the contract back to PENDING, got {pending['contract_status']}"
    )

    revived = get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    assert revived["lock_status"] == "ACTIVE", (
        f"the cycle closes back on its source state, got {revived['lock_status']}"
    )
    locked_again = fixtures.read_contract(api, world["ct1"])
    assert locked_again["contract_status"] == "LOCKED", (
        f"the revival re-locks the contract, got {locked_again['contract_status']}"
    )


def test_the_relock_cycle_writes_its_witness_onto_relock_count_and_expiry(api):
    """relock_count rises to one and the expiry is recomputed from the current clock.

    PRD §3.5: "A revival returns the lock to `ACTIVE`, increments `relock_count` by
    one, recomputes `lock_expires_iso` from the current clock plus `lock_days`, and
    charges the relock variant of the lock economics".
    PRD §2.13: "Setting the clock forward applies every clock-driven transition in
    one pass: a rate lock whose `lock_expires_iso` has passed moves from `ACTIVE`
    to `EXPIRED`".
    Design: Difficulty/non_linear_state_machine/rate_lock_relock_cycle_returns_to_active
    """
    world = locked_deal(api, lock_days=30)
    assert fixtures.read_rate_lock(api, world["lk1"])["relock_count"] == 0

    fixtures.set_clock(api, "2026-10-05T00:00:00Z")
    expired = fixtures.read_rate_lock(api, world["lk1"])
    assert expired["lock_status"] == "EXPIRED", expired["lock_status"]

    revived = get_success_data(api.relock_rate_lock(world["lk1"], BANKER_HEADERS))
    assert revived["relock_count"] == 1, (
        f"the row has now visited ACTIVE twice, got {revived['relock_count']}"
    )
    assert revived["lock_expires_iso"] > "2026-10-05T00:00:00Z", (
        f"expiry was recomputed from the current clock, got {revived['lock_expires_iso']}"
    )


def test_requesting_a_rate_lock_waiver_leaves_the_underwriting_status_qualifying(api):
    """The waiver track advances to REQUESTED while the application stays QUALIFIED.

    PRD §3.3: "The waiver track is advanced separately by a `SalesCounselor` or
    `MortgageBanker` supplying a `target_waiver_status`, and it never touches
    `application_status`."
    PRD §3.3: "A waiver may be requested from `NOT_REQUESTED` while the application
    is in any of `SUBMITTED`, `QUALIFIED` or `EXPIRED`."
    Design: Difficulty/non_linear_state_machine/loan_application_parallel_underwriting_and_waiver_dimensions
    """
    world = fixtures.build_deal(api)
    application = fixtures.read_application(api, world["la1"])
    assert application["application_status"] == "QUALIFIED", application["application_status"]
    assert application["lock_waiver_status"] == "NOT_REQUESTED", application["lock_waiver_status"]

    requested = get_success_data(
        api.set_lock_waiver(world["la1"], "REQUESTED", SALES_HEADERS)
    )
    assert requested["lock_waiver_status"] == "REQUESTED", requested["lock_waiver_status"]
    assert requested["application_status"] == "QUALIFIED", (
        f"the two dimensions evolve independently, got {requested['application_status']}"
    )


def test_granting_the_waiver_while_qualified_composes_the_precedence_string(api):
    """A granted waiver on a qualified application reads QUALIFIED_GRANTED.

    PRD §3.3: "From `REQUESTED` the banker may grant the waiver only while the
    application is `QUALIFIED`, which leaves the application status untouched at
    `QUALIFIED`".
    PRD §3.3: "The `uw_precedence` field is the canonical concatenation of the two,
    an underscore-joined `{application_status}_{lock_waiver_status}` string".
    Design: Difficulty/non_linear_state_machine/loan_application_parallel_underwriting_and_waiver_dimensions
    """
    world = fixtures.build_deal(api)
    get_success_data(api.set_lock_waiver(world["la1"], "REQUESTED", SALES_HEADERS))

    granted = get_success_data(
        api.set_lock_waiver(world["la1"], "GRANTED", BANKER_HEADERS)
    )
    assert granted["lock_waiver_status"] == "GRANTED", granted["lock_waiver_status"]
    assert granted["application_status"] == "QUALIFIED", granted["application_status"]
    assert granted["uw_precedence"] == "QUALIFIED_GRANTED", (
        f"the composite should join both dimensions, got {granted['uw_precedence']}"
    )

    persisted = fixtures.read_application(api, world["la1"])
    assert persisted["uw_precedence"] == "QUALIFIED_GRANTED", (
        f"the join is persisted, got {persisted['uw_precedence']}"
    )