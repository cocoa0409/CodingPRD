"""Cross-entity gates: one resource's posture deciding another's write."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import BANKER_HEADERS, COMPLIANCE_HEADERS, SALES_HEADERS


def test_a_second_contract_on_an_already_reserved_home_is_refused(api):
    """Once the first contract flips the home to UNDER_CONTRACT the second is rejected.

    PRD §2.10: "Creating a sale contract requires that its home site be in
    `AVAILABLE` status, and filing a loan application requires that its contract be
    in `PENDING` or `LOCKED` status; failure of either branch yields the single
    shared identifier `ERR_HOME_SITE_NOT_AVAILABLE` at HTTP 409".
    PRD §3.2: "When a sales counselor reserves an available inventory home, it moves
    to `UNDER_CONTRACT` and the owning community's `forward_units_committed` is
    recomputed."
    Design: Difficulty/cross_entity_state_dependency/contract_creation_gated_on_home_site_available
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})

    first = fixtures.create_contract(api, world["hs1"], world["b1"])
    assert first["contract_status"] == "PENDING", first["contract_status"]

    refused = api.create_contract(
        world["hs1"],
        f.contract_payload(world["b1"], purchase_price_cents=45_000_000,
                           earnest_money_cents=1_000_000),
        SALES_HEADERS,
    )
    validate_error(refused, "ERR_HOME_SITE_NOT_AVAILABLE", 409)

    site_after = fixtures.read_home_site(api, world["hs1"])
    assert site_after["home_site_status"] == "UNDER_CONTRACT", (
        f"the first contract's creation is what reserves the home, "
        f"got {site_after['home_site_status']}"
    )


def test_the_reserved_home_keeps_exactly_one_contract(api):
    """The rejected second contract leaves a single contract against the home.

    PRD §3.4: "Creation is refused with `ERR_HOME_SITE_NOT_AVAILABLE` at HTTP 409 if
    the home site is not available, and with `ERR_COMMUNITY_SUSPENDED` at HTTP 403 if
    the community is suspended."
    PRD §3.2: "The reverse move, back to `AVAILABLE`, happens automatically when the
    contract written against that home is cancelled".
    Design: Difficulty/cross_entity_state_dependency/contract_creation_gated_on_home_site_available
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    world.update({"hs1": site["id"]})
    fixtures.create_contract(api, world["hs1"], world["b1"])

    api.create_contract(
        world["hs1"],
        f.contract_payload(world["b1"], purchase_price_cents=45_000_000,
                           earnest_money_cents=1_000_000),
        SALES_HEADERS,
    )

    contracts, _ = fixtures.rows(
        api.list_home_site_contracts(world["hs1"], world["sales_headers"])
    )
    assert len(contracts) == 1, (
        f"exactly one contract survives the refused second write, got {len(contracts)}"
    )
    assert contracts[0]["contract_status"] == "PENDING", contracts[0]["contract_status"]


def suspended_community_world(api):
    """A community suspended by the lapse of an unacknowledged disclosure.

    The contract reaches LOCKED first, then a disclosure is delivered and left
    unacknowledged until the clock runs past its cure deadline.
    """
    world = fixtures.setup_contract_with_aba(
        api, construction_stage="DRYWALL", target_state="LOCKED", acknowledge_aba=False
    )
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    return world


def test_a_lapsed_disclosure_suspends_the_community(api):
    """The undisposed disclosure lapses into CURING and takes its community with it.

    PRD §2.8: "A `CURING` disclosure is a compliance failure: it forces the buyer's
    `steering_protection_flag` to false, and it drives the owning community into
    `SUSPENDED` posture".
    PRD §3.9: "If the clock passes `cure_deadline_iso` while a form is still `ISSUED`,
    the form lapses to `CURING` automatically."
    Design: Difficulty/cross_entity_state_dependency/incentive_allocation_gated_on_community_program_status
    """
    world = suspended_community_world(api)

    disclosure = fixtures.read_disclosure(api, world["d1"])
    assert disclosure["disclosure_status"] == "CURING", (
        f"the clock is past the cure deadline, got {disclosure['disclosure_status']}"
    )

    community = fixtures.read_community(api, world["cm1"])
    assert community["program_status"] == "SUSPENDED", (
        f"a lapse suspends the community, got {community['program_status']}"
    )

    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "LOCKED", (
        "the contract's own posture was never the blocker"
    )


def test_an_incentive_write_against_a_suspended_community_is_refused(api):
    """The parent posture blocks an allocation the contract's own state would allow.

    PRD §2.10: "Priority 10 requires that the contract's community not be in
    `SUSPENDED` posture; failure yields `ERR_COMMUNITY_SUSPENDED` at HTTP 403".
    PRD §3.7: "Allocation is refused with `ERR_COMMUNITY_SUSPENDED` at HTTP 403 when
    the community is suspended".
    Design: Difficulty/cross_entity_state_dependency/incentive_allocation_gated_on_community_program_status
    """
    world = suspended_community_world(api)
    contract = fixtures.read_contract(api, world["ct1"])
    assert contract["contract_status"] == "LOCKED", contract["contract_status"]

    refused = api.create_incentive_allocation(
        world["ct1"],
        f.incentive_allocation_payload("PRICE_REDUCTION", 1_000_000, contract["version"]),
        SALES_HEADERS,
    )
    validate_error(refused, "ERR_COMMUNITY_SUSPENDED", 403)

    rows, _ = fixtures.rows(
        api.list_contract_incentive_allocations(world["ct1"], world["sales_headers"])
    )
    assert rows == [], f"the refused write created no allocation, got {rows}"