"""Corner coverage - the stale-version guard and derived-field reconciliation."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import CLOSING_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def test_the_first_allocation_succeeds_and_advances_the_contract_version(api):
    """The version moves with the write, which is what makes the second guard stale.

    PRD §2.11: "Incentive allocation, buydown-record creation, and deposit-settlement
    proposal are all contract-scoped writes and each requires `expected_contract_version`
    carrying the target `HomeSaleContract`'s last observed `version`."
    PRD §2.4: "The `version` field is an integer that begins at its initial value when the
    row is created and increments by one on every mutation".
    Design: Corner/cross_cutting_layers/stale_contract_version_rejects_a_second_allocation_write
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    first = get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 1_000_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    assert first["allocation_status"] == "RESERVED", first["allocation_status"]

    refreshed = fixtures.read_contract(api, world["ct1"])
    assert refreshed["version"] == world["ct1_v"] + 1, (
        f"the allocation write bumps the parent, got {refreshed['version']} "
        f"from {world['ct1_v']}"
    )


def test_a_second_allocation_carrying_the_original_version_is_rejected(api):
    """A writer holding the pre-bump view is deterministically refused.

    PRD §2.11: "The guard exists because each of these writes may legitimately supersede
    a prior draft — a new allocation can re-split the bucket budget ... so the client's
    stale view of the contract is the only deterministic signal that the write would
    overwrite a split the client has not observed."
    PRD §2.11: "A mismatched value on any of the three is rejected with
    `ERR_STALE_CONTRACT_VERSION` at HTTP 412."
    Design: Corner/cross_cutting_layers/stale_contract_version_rejects_a_second_allocation_write
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])
    world.update({"hs1": site["id"], "ct1": contract["id"], "ct1_v": contract["version"]})

    get_success_data(
        api.create_incentive_allocation(
            world["ct1"],
            f.incentive_allocation_payload("PRICE_REDUCTION", 1_000_000, world["ct1_v"]),
            SALES_HEADERS,
        )
    )
    refused = api.create_incentive_allocation(
        world["ct1"],
        f.incentive_allocation_payload("CLOSING_COSTS", 1_000_000, world["ct1_v"]),
        SALES_HEADERS,
    )
    validate_error(refused, "ERR_STALE_CONTRACT_VERSION", 412)

    rows, _ = fixtures.rows(
        api.list_contract_incentive_allocations(world["ct1"], world["sales_headers"])
    )
    assert len(rows) == 1, f"the stale write added nothing, got {len(rows)}"


def test_the_derived_counters_rise_together_on_a_captured_close(api):
    """One close lifts funded, affiliated and capture rate, all recomputed from source rows.

    PRD §2.6: "The community's ratio metrics are produced by a single reconciliation rule,
    *capture_rate_realization*, which runs whenever a sale contract reaches `CLOSED`".
    PRD §2.6: "Only `CLOSED` contracts enter either counter: contracts in `LOCKED`,
    `APPROVED`, `PENDING` or `CANCELLED` status are excluded from both numerator and
    denominator."
    Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_close_and_reopen
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="FINISH", committed_units=5, target_state="CLOSED"
    )
    assert world["contract"]["contract_status"] == "CLOSED"

    community = fixtures.read_community(api, world["cm1"])
    assert community["funded_units"] == 1, community["funded_units"]
    assert community["affiliated_units"] == 1, community["affiliated_units"]
    assert community["capture_rate_bps"] == 10000, community["capture_rate_bps"]


def test_the_derived_counters_are_recomputed_rather_than_incremented_blindly(api):
    """No buydown record exists, so the recognised spend is recomputed to zero.

    PRD §2.6: "The `incentive_spend_cents` value is the sum of `allowed_buydown_cost_cents`
    across buydown cost records that are in `BOOKED` status".
    PRD §2.6: "Only `BOOKED` records contribute: records in `DRAFT` status and records in
    `REVERSED` status are both excluded".
    Design: Corner/cross_cutting_layers/derived_field_reconciliation_after_close_and_reopen
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="FINISH", committed_units=5, target_state="CLOSED"
    )

    community = fixtures.read_community(api, world["cm1"])
    assert community["incentive_spend_cents"] == 0, (
        f"the close carried no buydown bookings, so the recomputation leaves zero, "
        f"got {community['incentive_spend_cents']}"
    )

    records, _ = fixtures.rows(
        api.list_contract_buydown_records(world["ct1"], world["closing_headers"])
    )
    assert records == [], f"this deal booked no buydown records, got {records}"