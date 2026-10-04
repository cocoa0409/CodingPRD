"""Close and cancel cascades: one write moves four or five linked rows."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures


def test_closing_consumes_the_lock_and_draws_the_last_unit_from_the_pool(api):
    """A single-unit commitment is exhausted by one close, four hops downstream.

    PRD §3.6: "Every rate lock belonging to the contract's applications is then
    consumed, moving from `ACTIVE` to `CONSUMED`."
    PRD §3.6: "Each consumed lock increments its commitment's `units_drawn` by
    exactly one, and the commitment recomputes `units_available` as committed count
    minus drawn plus released; if that recomputation leaves zero units available the
    commitment moves from `OPEN` to `EXHAUSTED`".
    Design: Difficulty/transitive_cascade/close_cascade_contract_to_commitment_to_community_depth4
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="FINISH", committed_units=1, lock_days=180,
        target_state="CLOSED",
    )
    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "CLOSED", contract["contract_status"]

    site = fixtures.read_home_site(api, world["hs1"])
    assert site["home_site_status"] == "SOLD", (
        f"the close is what flips the home to its terminal posture, got {site['home_site_status']}"
    )

    lock = fixtures.read_rate_lock(api, world["lk1"])
    assert lock["lock_status"] == "CONSUMED", (
        f"the close consumes the lock it drew on, got {lock['lock_status']}"
    )

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_drawn"] == 1, (
        f"one consumed lock draws exactly one unit, got {commitment['units_drawn']}"
    )
    assert commitment["units_available"] == 0, commitment["units_available"]
    assert commitment["commitment_status"] == "EXHAUSTED", (
        f"the emptied pool stops funding new locks, got {commitment['commitment_status']}"
    )


def test_closing_a_captured_deal_reconciles_the_community_ratio_metrics(api):
    """The affiliated close moves funded, affiliated and capture rate together.

    PRD §2.6: "The `funded_units` counter is the count of sale contracts whose home
    site belongs to the community and whose `contract_status` is `CLOSED`."
    PRD §2.6: "The `capture_rate_bps` value is the affiliated count multiplied by ten
    thousand, divided by the funded count, using floor division — integer basis
    points with no rounding."
    Design: Difficulty/transitive_cascade/close_cascade_contract_to_commitment_to_community_depth4
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="FINISH", committed_units=1, lock_days=180,
        target_state="CLOSED",
    )
    assert world["contract"]["contract_status"] == "CLOSED"

    community = fixtures.read_community(api, world["cm1"])
    assert community["funded_units"] == 1, community["funded_units"]
    assert community["affiliated_units"] == 1, community["affiliated_units"]
    assert community["capture_rate_bps"] == 10000, (
        f"one affiliated close out of one funded unit is a perfect capture, "
        f"got {community['capture_rate_bps']}"
    )


def locked_deal_with_reserved_buydown(api):
    """A booked rate-buydown contract and its record, ready for the cancel inverse."""
    return fixtures.setup_contract_with_rate_buydown(
        api, construction_stage="DRYWALL", committed_units=1,
        buydown_cents=6_000_000, gross_buydown_cents=400_000,
        target_state="APPROVED", with_buydown_record=True,
    )


def test_cancelling_a_locked_deal_voids_its_lock_and_returns_the_unit(api):
    """The cancel voids the lock and releases a whole unit back to the pool.

    PRD §3.4: "The contract moves to `CANCELLED` with that reason recorded, its home
    site returns from `UNDER_CONTRACT` to `AVAILABLE`, and every `ACTIVE` rate lock
    for the contract's applications is voided."
    PRD §3.5: "the lock moves to `VOIDED`, its commitment's `units_released`
    increments by one and `units_available` is recomputed".
    Design: Difficulty/transitive_cascade/cancel_cascade_contract_to_lock_to_commitment_depth5
    """
    world = locked_deal_with_reserved_buydown(api)

    fixtures.drive_cancel(api, world, "RATE_SHOCK")

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "CANCELLED", contract["contract_status"]
    assert contract["cancellation_reason"] == "RATE_SHOCK", contract["cancellation_reason"]

    site = fixtures.read_home_site(api, world["hs1"])
    assert site["home_site_status"] == "AVAILABLE", (
        f"the cancellation frees the inventory home again, got {site['home_site_status']}"
    )

    lock = fixtures.read_rate_lock(api, world["lk1"])
    assert lock["lock_status"] == "VOIDED", lock["lock_status"]

    commitment = fixtures.read_commitment(api, world["fc1"])
    assert commitment["units_released"] == 1, (
        f"the voided lock returns exactly one unit, got {commitment['units_released']}"
    )


def test_cancelling_a_locked_deal_reverses_the_allocation_and_its_buydown_record(api):
    """The incentive side reverses completely and a settlement is proposed.

    PRD §3.4: "The incentive side reverses completely: every allocation in `APPLIED`
    status moves to `REVERSED`, every allocation in `RESERVED` status moves to
    `REVERSED`, and each reversed allocation recomputes its linked buydown record's
    `allowed_buydown_cost_cents` through the recognition rule while moving a booked
    record to `REVERSED`."
    PRD §3.4: "a deposit settlement is created in `PROPOSED` status with its
    `statute_class` chosen by the statute selector described in §3.8".
    PRD §3.8: "When the cancellation reason is `CONSTRUCTION_DELAY`, `RATE_SHOCK` or
    `FINANCING_DENIED` the statute is `RESTITUTION_REQUIRED`".
    Design: Difficulty/transitive_cascade/cancel_cascade_contract_to_lock_to_commitment_depth5
    """
    world = locked_deal_with_reserved_buydown(api)

    fixtures.drive_cancel(api, world, "RATE_SHOCK")

    allocation = fixtures.read_allocation(api, world["al1"])
    assert allocation["allocation_status"] == "REVERSED", (
        f"a RESERVED allocation reverses on cancel, got {allocation['allocation_status']}"
    )

    record = fixtures.read_buydown_record(api, world["bd1"])
    assert record["record_status"] == "REVERSED", (
        f"the linked record reverses with its allocation, got {record['record_status']}"
    )
    assert record["allowed_buydown_cost_cents"] == 0, (
        f"a reversed record recognises nothing, got {record['allowed_buydown_cost_cents']}"
    )

    settlements, _ = fixtures.rows(
        api.list_contract_deposit_forfeitures(world["ct1"], world["closing_headers"])
    )
    assert len(settlements) == 1, (
        f"the cancellation proposes exactly one settlement, got {len(settlements)}"
    )
    assert settlements[0]["forfeiture_status"] == "PROPOSED", settlements[0]["forfeiture_status"]
    assert settlements[0]["statute_class"] == "RESTITUTION_REQUIRED", (
        f"a rate-shock cancellation restores the deposit, got {settlements[0]['statute_class']}"
    )