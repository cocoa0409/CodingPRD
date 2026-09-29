"""Deploying gear onto a plot (PRD §3.6).

Deployment is the most heavily guarded write in the system. Three rules meet
here: the upstream seed-plantability gate that is ordered ahead of the
allocation gate, the date-granular fallow buffer that follows the true-overlap
test, and the void that reverses every counter the deployment moved and releases
the plot's occupation interval outright.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    design_world,
    dw_deploy_unit,
    dw_unit_payload_overrides,
    FALLOW_DAYS,
    get_success_data,
    growout_unit_payload,
    plus_days,
    retrieve_payload,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    void_payload,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _deploy(world, **unit_overrides):
    return api_client.create_growout_unit(
        growout_unit_payload(
            world["lease"]["id"], world["seed_lot"]["id"],
            **dw_unit_payload_overrides(**unit_overrides)),
        OPERATOR)


# --------------------------------------------------------------------------
# The upstream seed-plantability gate
# --------------------------------------------------------------------------
def _world_with_an_unscreened_seed_lot():
    """The seed lot was received but never screened, so it is still RECEIVED and
    its `unallocated_seed_count` is 0 -- both the plantability rung and the
    allocation rung are violated by the same deployment."""
    return design_world(stage="seed", seed_stage="received")


def test_deployment_names_the_unplantable_seed_lot_not_the_empty_seed_pool():
    """The plantability gate is ordered ahead of the occupancy, capacity and
    allocation checks, so a deployment against a lot still in RECEIVED is
    answered ERR_SEED_LOT_NOT_PLANTABLE even though the requested 25 000 seed
    also exceeds the lot's `unallocated_seed_count` of 0.

    Design: Difficulty/cross_entity_state_dependency/growout_deploy_blocked_by_unscreened_seed_lot
    """
    world = _world_with_an_unscreened_seed_lot()

    response = _deploy(world)

    body = validate_error(response, ApiErrorId.ERR_SEED_LOT_NOT_PLANTABLE, 409)
    assert body["error_id"] != ApiErrorId.ERR_SEED_ALLOCATION_EXCEEDED


def test_the_blocked_deployment_creates_no_unit_and_moves_no_counter():
    """The seed lot is untouched -- still RECEIVED with `screening_result` null
    and `allocated_seed_count` 0 -- the lease's `deployed_gear_units` stays 0,
    and no grow-out unit exists.

    Design: Difficulty/cross_entity_state_dependency/growout_deploy_blocked_by_unscreened_seed_lot
    """
    world = _world_with_an_unscreened_seed_lot()
    _deploy(world)

    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    _rows, meta = validate_paginated(api_client.list_growout_units(OPERATOR))

    assert seed_lot["status"] == "RECEIVED"
    assert seed_lot["screening_result"] is None
    assert seed_lot["allocated_seed_count"] == 0
    assert lease["deployed_gear_units"] == 0
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# The fallow buffer after the retrieved unit's effective end
# --------------------------------------------------------------------------
EFFECTIVE_END = "2026-08-20"
INSIDE_BUFFER = "2026-09-01"
BUFFER_EXPIRES = plus_days(EFFECTIVE_END, FALLOW_DAYS)  # 2026-09-03


def _plot_p1_retrieved_on_its_effective_end():
    """One unit occupied plot P1 from 2026-05-05 and was retrieved on
    2026-08-20, which becomes its effective end; the plot must then rest for
    `FALLOW_DAYS` 14 days."""
    world = design_world(stage="seed")
    world["unit"] = dw_deploy_unit(
        world["lease"], world["seed_lot"], OPERATOR,
        {"planned_retrieval_on": EFFECTIVE_END}, husbandry=False)
    set_clock(EFFECTIVE_END + "T00:00:00Z")
    world["unit"] = validate_success(api_client.retrieve_growout_unit(
        world["unit"]["id"], retrieve_payload(EFFECTIVE_END), OPERATOR))
    return world


def test_redeploying_inside_the_fallow_buffer_is_a_fallow_conflict():
    """2026-09-01 lies after the retrieved unit's effective end 2026-08-20, so
    the intervals do not truly overlap and ERR_PLOT_OCCUPIED is silent; it is
    still strictly before effective end plus 14 days, so the more general
    ERR_PLOT_FALLOW_CONFLICT answers.

    Design: Difficulty/resource_temporal_overlap/plot_redeployment_inside_fallow_buffer_rejected
    """
    world = _plot_p1_retrieved_on_its_effective_end()
    set_clock(INSIDE_BUFFER + "T00:00:00Z")

    response = _deploy(world, deployed_on=INSIDE_BUFFER,
                       planned_retrieval_on="2027-02-01")

    body = validate_error(response, ApiErrorId.ERR_PLOT_FALLOW_CONFLICT, 409)
    assert body["error_id"] != ApiErrorId.ERR_PLOT_OCCUPIED

    unit = get_success_data(
        api_client.get_growout_unit(world["unit"]["id"], OPERATOR))
    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))
    _rows, meta = validate_paginated(api_client.list_growout_units(OPERATOR))

    assert unit["status"] == "RETRIEVED"
    assert unit["retrieved_on"] == EFFECTIVE_END
    assert lease["deployed_gear_units"] == 0
    assert seed_lot["allocated_seed_count"] == 25000
    assert seed_lot["unallocated_seed_count"] == 35000
    assert meta["total_count"] == 1


def test_redeploying_exactly_at_the_end_of_the_buffer_succeeds():
    """The fallow right-hand boundary is exclusive, so a `deployed_on` of exactly
    effective end plus `FALLOW_DAYS` -- 2026-09-03 -- satisfies the rule and the
    deployment is accepted with HTTP 201. The clock is advanced to that same
    date because `deployed_on` describes something that has already happened and
    the temporal ladder rung, which is ordered ahead of the fallow rung, would
    otherwise answer ERR_FUTURE_DATED_EVENT first.

    Design: Difficulty/resource_temporal_overlap/plot_redeployment_inside_fallow_buffer_rejected
    """
    world = _plot_p1_retrieved_on_its_effective_end()
    set_clock(BUFFER_EXPIRES + "T00:00:00Z")

    unit = validate_success(_deploy(
        world, deployed_on=BUFFER_EXPIRES,
        planned_retrieval_on="2027-02-01"), 201)

    assert unit["status"] == "DEPLOYED"
    assert unit["deployed_on"] == BUFFER_EXPIRES
    assert unit["plot_code"] == "P1"
    _rows, meta = validate_paginated(api_client.list_growout_units(OPERATOR))
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------
# Voiding a deployment as a true compensation
# --------------------------------------------------------------------------
FULL_POOL = 60000


def _plot_p1_deployed_with_the_whole_seed_pool():
    """A single deployment consumes the entire 60 000-seed pool, so the lot moves
    to PLANTED and `unallocated_seed_count` reaches 0."""
    world = design_world(stage="seed")
    world["unit"] = dw_deploy_unit(
        world["lease"], world["seed_lot"], OPERATOR,
        {"seed_count_planted": FULL_POOL}, husbandry=False)
    return world


def test_voiding_a_deployment_reverses_both_parents_counters():
    """The void subtracts exactly what the deployment added on two different
    parents -- the lease's `deployed_gear_units` returns to 0 and the lot's
    `allocated_seed_count` to 0 with `unallocated_seed_count` back at 60 000 --
    and drags the lot from PLANTED back to READY_FOR_PLANTING, while the nursery
    figures it earned are untouched.

    Design: Difficulty/compensating_invariant/growout_void_restores_lease_gear_and_seed_lot_counters
    """
    world = _plot_p1_deployed_with_the_whole_seed_pool()

    voided = validate_success(api_client.void_growout_unit(
        world["unit"]["id"], void_payload(void_note="wrong plot recorded"),
        OPERATOR))

    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))

    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "OPERATOR_CORRECTION"
    assert lease["deployed_gear_units"] == 0
    assert seed_lot["allocated_seed_count"] == 0
    assert seed_lot["unallocated_seed_count"] == FULL_POOL
    assert seed_lot["status"] == "READY_FOR_PLANTING"
    assert seed_lot["surviving_seed_count"] == FULL_POOL
    assert seed_lot["survival_rate_pct"] == 60.00


def test_the_voided_unit_releases_the_plot_so_an_identical_redeployment_works():
    """A void excludes the unit from the plot's occupation intervals entirely, so
    the identical deployment on plot P1 with the same `deployed_on` 2026-05-05
    is accepted with HTTP 201 -- neither ERR_PLOT_OCCUPIED nor
    ERR_PLOT_FALLOW_CONFLICT fires -- and the counters land back exactly where
    the first deployment had put them, with no drift.

    Design: Difficulty/compensating_invariant/growout_void_restores_lease_gear_and_seed_lot_counters
    """
    world = _plot_p1_deployed_with_the_whole_seed_pool()
    validate_success(api_client.void_growout_unit(
        world["unit"]["id"], void_payload(void_note="wrong plot recorded"),
        OPERATOR))

    redeployed = validate_success(
        _deploy(world, seed_count_planted=FULL_POOL), 201)

    lease = get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))
    seed_lot = get_success_data(
        api_client.get_seed_lot(world["seed_lot"]["id"], OPERATOR))

    assert redeployed["status"] == "DEPLOYED"
    assert redeployed["plot_code"] == "P1"
    assert redeployed["deployed_on"] == "2026-05-05"
    assert lease["deployed_gear_units"] == 40
    assert seed_lot["status"] == "PLANTED"
    assert seed_lot["unallocated_seed_count"] == 0
