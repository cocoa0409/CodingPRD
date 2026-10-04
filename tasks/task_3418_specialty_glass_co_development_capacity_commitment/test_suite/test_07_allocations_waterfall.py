"""Allocation creation rules and the auto-allocation waterfall.

Covers the positivity, remaining-need, headroom, program-alignment, state, and
OCC gates on manual allocation (PRD sections 2.6, 2.8, and 3.6), the filtered
listing, and the deterministic waterfall ordering with its empty-pool
fallback.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    confirm_prepayment,
    countersign_commitment,
    create_allocation,
    create_campaign,
    create_commitment,
    create_commissioned_tank,
    create_program,
    create_program_with_nda,
    create_qualified_composition,
    create_secured_commitment,
    create_device_maker,
    execute_nda,
    factories,
    get_commitment_version,
    setup_supply_chain,
    setup_supply_chain_with_allocation,
    sign_commitment,
    validate_created,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
)

MANAGER = TEST_USERS["program_manager_headers"]
PLANNER = TEST_USERS["capacity_planner_headers"]


def _allocation_payload(commitment_id: str, campaign_id: str, units: int) -> dict:
    """Freshly observed commitment version, so only the rule under test can
    fail."""
    return factories.create_allocation_payload(
        commitment_id,
        campaign_id,
        expected_commitment_version=get_commitment_version(commitment_id),
        units=units,
    )


def test_allocation_zero_units_returns_nonpositive_units():
    """PRD section 3.6: "the `units` must be strictly positive
    (`ERR_NONPOSITIVE_UNITS`)" — zero is the rejected boundary.

    Design: Corner/errors/allocation_zero_units_returns_nonpositive_units
    """
    chain = setup_supply_chain()
    resp = api_client.create_allocation(
        _allocation_payload(chain.commitment["id"], chain.campaign["id"], 0),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_NONPOSITIVE_UNITS)


def test_allocation_beyond_remaining_need_returns_commitment_units_exceeded():
    """PRD section 3.6: "the `units` must not exceed the commitment's
    remaining need, meaning `committed_units` minus the units already reserved
    or fulfilled for it (`ERR_COMMITMENT_UNITS_EXCEEDED`)" — 6000 units against
    a 5000-unit commitment exceeds the need while fitting the 6200-unit
    campaign headroom.

    Design: Corner/errors/allocation_beyond_remaining_need_returns_commitment_units_exceeded
    """
    chain = setup_supply_chain()
    resp = api_client.create_allocation(
        _allocation_payload(chain.commitment["id"], chain.campaign["id"], 6000),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_UNITS_EXCEEDED)


def test_allocation_beyond_headroom_returns_insufficient_campaign_headroom():
    """PRD section 3.6: "must not exceed the campaign's `unallocated_units`,
    with an exactly-equal allocation allowed
    (`ERR_INSUFFICIENT_CAMPAIGN_HEADROOM`)" — 8000 units fit the 10000-unit
    commitment's need but exceed the 6200-unit campaign headroom.

    Design: Corner/errors/allocation_beyond_headroom_returns_insufficient_campaign_headroom
    """
    chain = setup_supply_chain(
        committed_units=10000, required_units=10000, prepayment_cents=5000000
    )
    resp = api_client.create_allocation(
        _allocation_payload(chain.commitment["id"], chain.campaign["id"], 8000),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CAMPAIGN_HEADROOM)


def test_cross_program_allocation_returns_program_mismatch():
    """PRD section 3.6: "the campaign's composition's program must equal the
    commitment's program, failing otherwise with `ERR_PROGRAM_MISMATCH`" — the
    commitment belongs to program Eagle while the campaign melts a composition
    of program Falcon.

    Design: Corner/errors/cross_program_allocation_returns_program_mismatch
    """
    maker = create_device_maker()
    program_one = execute_nda(
        create_program(maker, name="Eagle", primary_market="CONSUMER_ELECTRONICS")
    )
    commitment = create_secured_commitment(program_one, maker)
    tank = create_commissioned_tank(commitment, 1000)
    program_two = execute_nda(
        create_program(maker, name="Falcon", primary_market="AUTOMOTIVE")
    )
    qual_two = create_qualified_composition(program_two, maker, composition_code="GX-P2")
    campaign = create_campaign(tank, qual_two.composition)
    resp = api_client.create_allocation(
        _allocation_payload(commitment["id"], campaign["id"], 1000),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_MISMATCH)


def test_allocations_filtered_by_commitment_and_campaign():
    """PRD section 3.6: "Allocations may be listed filtered by
    `commitment_id`, `campaign_id`, and `status`." Each foreign-key filter
    returns exactly the matching allocation, and an unknown id matches nothing.

    Design: Corner/endpoints/allocations_filtered_by_commitment_and_campaign
    """
    chain = setup_supply_chain_with_allocation(alloc_units=1000)
    data, meta = validate_paginated(
        api_client.list_allocations(PLANNER, {"commitment_id": chain.commitment["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == chain.allocation["id"]

    _, meta = validate_paginated(
        api_client.list_allocations(PLANNER, {"campaign_id": chain.campaign["id"]})
    )
    assert meta["total_count"] == 1

    data, meta = validate_paginated(
        api_client.list_allocations(PLANNER, {"commitment_id": NON_EXISTENT_UUID})
    )
    assert meta["total_count"] == 0
    assert data == []


def test_auto_allocate_waterfall_fills_in_tier_order():
    """PRD section 3.6: "then by coverage tier descending, `TIER_A` above
    `TIER_B` above `TIER_C`" and "for each candidate it computes the remaining
    need — `committed_units` minus the units of its allocations in `RESERVED`
    or `FULFILLED` — and grants the smaller of that need and the remaining
    headroom." The TIER_A commitment (need 5000) is filled fully; the TIER_B
    commitment (need 2000) receives only the remaining 1200 of the 6200-unit
    pool; a second run finds no headroom and creates nothing.

    Design: Corner/endpoints/auto_allocate_waterfall_fills_in_tier_order
    """
    chain = setup_supply_chain()  # c1: 5000/5000/2500000 -> TIER_A
    # c2: credit 1300 -> base 3300 over required 3000 -> coverage 1.1 -> TIER_B.
    c2 = create_commitment(chain.program, 2000, 3000, 1300000)
    c2 = sign_commitment(c2, chain.maker)
    c2 = countersign_commitment(c2, "planner-02")
    c2 = confirm_prepayment(c2, "fin-02")

    created = validate_success(api_client.auto_allocate(chain.campaign["id"], headers=PLANNER))
    assert len(created) == 2
    assert created[0]["commitment_id"] == chain.commitment["id"]
    assert created[0]["units"] == 5000
    assert created[1]["commitment_id"] == c2["id"]
    assert created[1]["units"] == 1200

    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 0  # 6200 - 5000 - 1200

    second_run = validate_success(api_client.auto_allocate(chain.campaign["id"], headers=PLANNER))
    assert second_run == []


def test_auto_allocate_with_no_remaining_need_returns_empty():
    """PRD section 3.6: "When no candidate qualifies, no allocations are
    created and the waterfall simply returns success with an empty list." The
    only eligible commitment is already fully allocated, so its need is zero
    and the walk creates nothing.

    Design: Corner/endpoints/auto_allocate_with_no_remaining_need_returns_empty
    """
    chain = setup_supply_chain(
        committed_units=1000, required_units=1000, prepayment_cents=1000000
    )
    create_allocation(chain.commitment, chain.campaign, 1000)
    created = validate_success(api_client.auto_allocate(chain.campaign["id"], headers=PLANNER))
    assert created == []
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 5200  # 6200 - 1000, untouched


def test_allocation_state_trumps_fiscal():
    """PRD section 2.8: "the failure reported is the one with the highest
    priority: checks are evaluated in the fixed order below and the first
    failure wins." PRD section 3.6: "The commitment must be `SECURED` or
    `BREACH_WATCH` and the campaign `SCHEDULED` or `RUNNING`, failing otherwise
    with `ERR_INVALID_STATE`". Allocating 9999 units against a PROPOSED
    commitment fails the state gate (priority 6) before the remaining-need
    fiscal cap (priority 22) is ever reached.

    Design: Difficulty/priority_pair_validation_conflict/allocation_state_trumps_fiscal
    """
    chain = setup_supply_chain()  # SECURED c1 funds the tank and the campaign
    c2 = create_commitment(chain.program, 5000, 5000, 2500000)  # stays PROPOSED
    resp = api_client.create_allocation(
        factories.create_allocation_payload(
            c2["id"],
            chain.campaign["id"],
            expected_commitment_version=c2["version"],
            units=9999,
        ),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    campaign = get_success_data(api_client.get_campaign(chain.campaign["id"], PLANNER))
    assert campaign["unallocated_units"] == 6200  # nothing was created


def test_stale_commitment_version_returns_412():
    """PRD section 2.6: "If the Commitment's current `version` does not match,
    the creation is rejected with `ERR_STALE_COMMITMENT_VERSION` (HTTP 412)".
    The first allocation succeeds and advances the Commitment's version, so the
    second allocation carrying the same observed version is stale.

    Design: Corner/cross_cutting_layers/stale_commitment_version_returns_412
    """
    chain = setup_supply_chain()
    observed = get_commitment_version(chain.commitment["id"])
    first = factories.create_allocation_payload(
        chain.commitment["id"],
        chain.campaign["id"],
        expected_commitment_version=observed,
        units=100,
    )
    validate_created(api_client.create_allocation(first, PLANNER))
    second = factories.create_allocation_payload(
        chain.commitment["id"],
        chain.campaign["id"],
        expected_commitment_version=observed,
        units=100,
    )
    resp = api_client.create_allocation(second, PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_COMMITMENT_VERSION)


def test_correct_commitment_version_succeeds_and_bumps():
    """PRD section 3.6: "A successful creation decrements the campaign's
    `unallocated_units` by the allocated `units`, increments the Commitment's
    `version` by 1, recomputes the commitment's `supply_coverage`" — a fresh
    `expected_commitment_version` passes the OCC guard of PRD section 2.6, the
    allocation starts RESERVED, and the write advances the version by exactly
    one.

    Design: Corner/cross_cutting_layers/correct_commitment_version_succeeds_and_bumps
    """
    chain = setup_supply_chain()
    observed = get_commitment_version(chain.commitment["id"])
    allocation = validate_created(
        api_client.create_allocation(
            _allocation_payload(chain.commitment["id"], chain.campaign["id"], 100),
            PLANNER,
        )
    )
    assert allocation["status"] == "RESERVED"
    commitment = get_success_data(api_client.get_commitment(chain.commitment["id"], PLANNER))
    assert commitment["version"] == observed + 1
