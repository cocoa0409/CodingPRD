"""Compensating invariants: a forward move and its inverse leave the books even."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, CLOSING_HEADERS


def reversible_deal(api):
    """A LOCKED contract carrying a price-reduction and a rate-buydown allocation.

    The rate-buydown deal is built through the shared helper, which delivers and
    acknowledges the affiliated-business disclosure before the RATE_BUYDOWN
    allocation is written (PRD section 3.7 makes that acknowledgement a
    precondition of the allocation), then the price-reduction allocation is added
    and approval applies both.
    """
    world = fixtures.setup_contract_with_rate_buydown(
        api, lock_days=360, buydown_cents=3_000_000, target_state="LOCKED"
    )
    price = fixtures.allocate(api, world["ct1"], "PRICE_REDUCTION", 3_000_000)
    world["allocation_price"] = price
    world["allocation_buydown"] = world["allocation"]
    world["al1"] = price["id"]
    world["al2"] = world["allocation"]["id"]

    fixtures.drive_approve(api, world)
    return world


def test_cancel_then_reinstate_returns_the_contract_and_its_allocations_forward_again(api):
    """The inverse pair restores the contract's posture and its allocations' posture.

    PRD §3.4: "Reinstatement sets the contract back to `PENDING`, voids every proposed
    settlement, returns the home site to `UNDER_CONTRACT`, bubbles the buyer from
    `WITHDRAWN` to `CONTRACTED`, and returns every `REVERSED` allocation attached to
    the contract to `PENDING`".
    PRD §3.4: "The contract moves to `CANCELLED` with that reason recorded, its home
    site returns from `UNDER_CONTRACT` to `AVAILABLE`".
    Design: Difficulty/compensating_invariant/cancel_then_reinstate_conserves_allocated_incentive_cents
    """
    world = reversible_deal(api)
    approved = fixtures.read_contract(api, world["ct1"])
    assert approved["contract_status"] == "APPROVED", approved["contract_status"]

    fixtures.drive_cancel(api, world, "RATE_SHOCK")
    cancelled = fixtures.read_contract(api, world["ct1"])
    assert cancelled["contract_status"] == "CANCELLED", cancelled["contract_status"]
    reversed_allocation = fixtures.read_allocation(api, world["al1"])
    assert reversed_allocation["allocation_status"] == "REVERSED", (
        f"an applied allocation reverses on cancel, got {reversed_allocation['allocation_status']}"
    )

    fixtures.drive_reinstate(api, world)
    reinstated = fixtures.read_contract(api, world["ct1"])
    assert reinstated["contract_status"] == "PENDING", reinstated["contract_status"]

    site = fixtures.read_home_site(api, world["hs1"])
    assert site["home_site_status"] == "UNDER_CONTRACT", (
        f"the reinstatement re-reserves the home, got {site['home_site_status']}"
    )

    for allocation_id in (world["al1"], world["al2"]):
        row = fixtures.read_allocation(api, allocation_id)
        assert row["allocation_status"] == "PENDING", (
            f"a reversed allocation returns to PENDING, got {row['allocation_status']}"
        )


def test_reinstate_preserves_each_granted_total_without_rerunning_the_waterfall(api):
    """Both allocation rows keep the amount the waterfall granted them before the cancel.

    PRD §3.4: "returns every `REVERSED` allocation attached to the contract to
    `PENDING` — retaining its `allocation_total_cents` so the waterfall need not be
    re-run."
    PRD §3.7: "a reinstated contract returns its `REVERSED` allocations to `PENDING`
    with their granted amounts retained."
    Design: Difficulty/compensating_invariant/cancel_then_reinstate_conserves_allocated_incentive_cents
    """
    world = reversible_deal(api)
    before = {
        allocation_id: fixtures.read_allocation(api, allocation_id)["allocation_total_cents"]
        for allocation_id in (world["al1"], world["al2"])
    }
    assert before[world["al1"]] == 3_000_000, before
    assert before[world["al2"]] == 3_000_000, before

    fixtures.drive_cancel(api, world, "RATE_SHOCK")
    fixtures.drive_reinstate(api, world)

    after = {
        allocation_id: fixtures.read_allocation(api, allocation_id)["allocation_total_cents"]
        for allocation_id in (world["al1"], world["al2"])
    }
    assert after == before, (
        f"the granted amounts must survive the cancel and reinstate unchanged, "
        f"before {before} after {after}"
    )
    assert sum(after.values()) == 6_000_000, (
        f"the granted budget is conserved at the original total, got {sum(after.values())}"
    )


def two_unit_pool_world(api):
    """A two-unit commitment funding two contracts, each holding one active lock."""
    world = fixtures.seed_reference_data(api, committed_units=2)
    site1 = fixtures.create_home_site(api, world["cm1"], lot_number="L1", address="1 Elm")
    site2 = fixtures.create_home_site(api, world["cm1"], lot_number="L2", address="2 Elm")
    site3 = fixtures.create_home_site(api, world["cm1"], lot_number="L3", address="3 Elm")
    world.update({"hs1": site1["id"], "hs2": site2["id"], "hs3": site3["id"]})

    contract1 = fixtures.create_contract(api, world["hs1"], world["b1"])
    contract2 = fixtures.create_contract(api, world["hs2"], world["b1"])
    world.update({"ct1": contract1["id"], "ct2": contract2["id"]})

    app1 = fixtures.create_application(api, world["ct1"], application_number="APP-1")
    app2 = fixtures.create_application(api, world["ct2"], application_number="APP-2")
    app1 = get_success_data(api.qualify_loan_application(app1["id"], BANKER_HEADERS))
    app2 = get_success_data(api.qualify_loan_application(app2["id"], BANKER_HEADERS))
    world.update({"la1": app1["id"], "la2": app2["id"]})

    lock1 = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=180,
                                expected_application_version=app1["version"]),
            BANKER_HEADERS,
        )
    )
    lock2 = get_success_data(
        api.create_rate_lock(
            world["la2"],
            f.rate_lock_payload(world["fc1"], lock_days=180,
                                expected_application_version=app2["version"]),
            BANKER_HEADERS,
        )
    )
    world.update({"lk1": lock1["id"], "lk2": lock2["id"]})
    return world


def test_consuming_a_unit_debits_the_pool_and_preserves_the_available_identity(api):
    """One close draws one unit, and units_available still reconstructs from the ledger.

    PRD §2.7: "The `units_available` field is the committed count minus the drawn
    count plus the released count, and it is never permitted to fall below zero."
    PRD §3.6: "Each consumed lock increments its commitment's `units_drawn` by exactly
    one, and the commitment recomputes `units_available` as committed count minus
    drawn plus released".
    Design: Difficulty/compensating_invariant/void_then_relock_conserves_commitment_unit_pool
    """
    world = two_unit_pool_world(api)
    fixtures.drive_lock(api, world)
    fixtures.drive_approve(api, world)
    fixtures.drive_close(api, world)

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_drawn"] == 1, (
        f"one consumed lock draws exactly one unit, got {commitment['units_drawn']}"
    )
    assert commitment["units_available"] == 1, commitment["units_available"]
    assert commitment["units_available"] == (
        commitment["committed_units"] - commitment["units_drawn"] + commitment["units_released"]
    ), "the available count must reconstruct from the ledger"


def test_voiding_an_active_lock_returns_the_pool_to_its_original_size(api):
    """The voided lock's unit comes back, so available equals committed_units again.

    PRD §2.7: "The `units_released` counter accumulates one whole unit for every rate
    lock that has been voided against the commitment."
    PRD §2.7: "Because a voided lock returns its unit to the pool, the debit-then-release
    accounting means an exhausted commitment can be reopened by a void".
    Design: Difficulty/compensating_invariant/void_then_relock_conserves_commitment_unit_pool
    """
    world = two_unit_pool_world(api)
    fixtures.drive_lock(api, world)
    fixtures.drive_approve(api, world)
    fixtures.drive_close(api, world)

    # The second contract holds its own ACTIVE lock (created by the world helper) but is
    # still PENDING: PRD section 3.4 only moves a contract to LOCKED through the explicit
    # PENDING->LOCKED lock step, and no step was taken for ct2. Locking it now puts its
    # ACTIVE lock in the consuming posture the void under test expects to unwind.
    fixtures.drive_lock(api, {"ct1": world["ct2"]})

    second_contract = fixtures.read_contract(api, world["ct2"])
    assert second_contract["contract_status"] == "LOCKED", second_contract["contract_status"]

    voided = get_success_data(api.void_rate_lock(world["lk2"], BANKER_HEADERS))
    assert voided["lock_status"] == "VOIDED", voided["lock_status"]

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_released"] == 1, (
        f"the void returns exactly one unit, got {commitment['units_released']}"
    )
    assert commitment["units_available"] == commitment["committed_units"], (
        f"the pool is back to its original size, got {commitment['units_available']} "
        f"against {commitment['committed_units']}"
    )
    assert commitment["units_drawn"] - commitment["units_released"] == 0, (
        "the conserved quantity committed_units - units_drawn + units_released equals committed_units"
    )