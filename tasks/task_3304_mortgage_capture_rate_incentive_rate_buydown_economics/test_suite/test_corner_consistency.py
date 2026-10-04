"""Corner coverage - derived totals are correct on the very next read."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def approved_price_reduction_deal(api):
    """A LOCKED contract holding one reserved price-reduction allocation."""
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    application = fixtures.create_application(api, world["ct1"])
    application = get_success_data(api.qualify_loan_application(application["id"], BANKER_HEADERS))
    world.update({"la1": application["id"]})

    lock = get_success_data(
        api.create_rate_lock(
            world["la1"],
            f.rate_lock_payload(world["fc1"], lock_days=180,
                                expected_application_version=application["version"]),
            BANKER_HEADERS,
        )
    )
    world.update({"lk1": lock["id"]})
    fixtures.drive_lock(api, world)

    allocation = fixtures.allocate(api, world["ct1"], "PRICE_REDUCTION", 6_000_000)
    world.update({"allocation": allocation, "al1": allocation["id"]})
    return world


def test_the_buyers_derived_incentive_total_is_correct_on_the_first_read_after_approval(api):
    """No reconciliation window: the very next read already carries the applied total.

    PRD §3.7: "The buyer's `total_incentive_received_cents` aggregates the granted totals
    of applied allocations together with the recognized costs of booked records."
    PRD §3.4: "the buyer's `total_incentive_received_cents` and the community's
    `incentive_spend_cents` are both recomputed."
    Design: Corner/consistency_model/immediate_visibility_of_derived_buyer_totals_within_the_write_response
    """
    world = approved_price_reduction_deal(api)
    get_success_data(api.approve_contract(world["ct1"], COMPLIANCE_HEADERS))

    buyer = fixtures.read_buyer(api, world["b1"])
    assert buyer["total_incentive_received_cents"] == 6_000_000, (
        f"the applied allocation is visible immediately, "
        f"got {buyer['total_incentive_received_cents']}"
    )


def test_approval_applies_the_reserved_allocation_and_the_contract_total_follows(api):
    """The allocation moves to APPLIED and the contract's rollup reflects it at once.

    PRD §3.4: "Approval applies every allocation that is still `RESERVED` by moving it to
    `APPLIED`".
    PRD §3.7: "The allocation becomes `APPLIED` when the contract is approved".
    Design: Corner/consistency_model/immediate_visibility_of_derived_buyer_totals_within_the_write_response
    """
    world = approved_price_reduction_deal(api)
    reserved = fixtures.read_allocation(api, world["al1"])
    assert reserved["allocation_status"] == "RESERVED", reserved["allocation_status"]

    approved = get_success_data(api.approve_contract(world["ct1"], COMPLIANCE_HEADERS))
    assert approved["contract_status"] == "APPROVED", approved["contract_status"]

    applied = fixtures.read_allocation(api, world["al1"])
    assert applied["allocation_status"] == "APPLIED", (
        f"approval promotes the reservation, got {applied['allocation_status']}"
    )

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["incentive_allocated_cents"] == 6_000_000, (
        f"the contract rollup follows the granted total, "
        f"got {contract['incentive_allocated_cents']}"
    )