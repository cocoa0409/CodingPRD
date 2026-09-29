"""Requests that break two rules at once, and the rule that must answer.

Each pair is proved twice: once with both rules violated, and once with only
the lower-priority rule violated, so the ordering is visible rather than
inferred.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import LINE_OPERATOR_HEADERS

# The stale-water clock stop: 150 minutes after the 06:30 reading.
STALE_CLOCK = "2026-08-03T09:00:00Z"
TOUCHING_PLANNED_START_AT = "2026-08-03T12:00:00Z"
TOUCHING_PLANNED_END_AT = "2026-08-03T13:00:00Z"

# The third load: five thousand pounds, no tare, no trim.
THIRD_LOAD_RECEIVED_AT = "2026-08-03T07:30:00Z"
THIRD_LOAD_GROSS_LB = 5000.00
THIRD_LOAD_NET_LB = 5000.00
IMPOSSIBLE_DRAW_LB = 99999.00


def _running_run_and_a_planned_run_over_stale_water(api):
    """One RUNNING run, one SETUP run, and a wash reading 150 minutes old."""
    world = fx.build_world(api, stop_after=fx.STOP_RUN_RUNNING)

    planned = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=TOUCHING_PLANNED_START_AT,
        planned_end_at=TOUCHING_PLANNED_END_AT,
    )
    assert planned["run_status"] == c.RUN_SETUP
    fx.set_clock(api, STALE_CLOCK)
    return world, planned


def test_the_run_state_gate_answers_before_the_water_freshness_gate(api):
    """A start on a RUNNING run over stale water reports the state, not the water.

    PRD: The run must be in `SETUP`; any other `run_status` is refused with `ERR_RUN_NOT_IN_SETUP` (HTTP 409).
    PRD: The latest reading must be fresh: its `reading_at` must be no earlier than the logical clock's current instant minus 60 minutes.

    Design: Difficulty/priority_pair_validation_conflict/run_start_state_beats_antimicrobial_safety
    """
    world, planned = _running_run_and_a_planned_run_over_stale_water(api)

    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.RUN_NOT_IN_SETUP,
    )

    # Neither run moved: the refusal is a pure read of the state dimension.
    unchanged = fx.read_run(api, world.run_id)
    assert unchanged["run_status"] == c.RUN_RUNNING
    a.assert_instant_equals(unchanged["started_at"], c.CLOCK_START, "started_at")
    assert fx.read_run(api, planned["id"])["run_status"] == c.RUN_SETUP


def test_the_water_freshness_gate_is_live_on_a_run_that_really_is_in_setup(api):
    """The same instant and the same stale reading refuse the startable run.

    PRD: A reading exactly 60 minutes old is still fresh; an older one is refused with `ERR_ANTIMICROBIAL_READING_STALE` (HTTP 422).
    PRD: Starting the run is where every food-safety gate in the plant converges, and it moves the production dimension `SETUP → RUNNING`.

    Design: Difficulty/priority_pair_validation_conflict/run_start_state_beats_antimicrobial_safety
    """
    _world, planned = _running_run_and_a_planned_run_over_stale_water(api)

    validate_error(
        api.start_process_run(planned["id"], LINE_OPERATOR_HEADERS),
        ApiErrorId.ANTIMICROBIAL_READING_STALE,
    )

    refused = fx.read_run(api, planned["id"])
    assert refused["run_status"] == c.RUN_SETUP
    assert refused["started_at"] is None
    assert refused["target_ppm_at_start"] is None
    assert refused["required_dwell_seconds_at_start"] is None


def _running_run_and_an_uninspected_load(api):
    """A RUNNING run with nothing consumed, and a load still awaiting inspection."""
    world = fx.build_world(api, stop_after=fx.STOP_RUN_RUNNING)
    load = fx.create_receipt(
        api,
        world.grower_lot_id,
        received_at=THIRD_LOAD_RECEIVED_AT,
        pulp_temp_c=3.0,
        gross_weight_lb=THIRD_LOAD_GROSS_LB,
        tare_weight_lb=0.00,
    )
    assert load["status"] == c.RECEIPT_PENDING_INSPECTION
    assert load["net_weight_lb"] == THIRD_LOAD_NET_LB
    assert load["remaining_lb"] is None
    return world, load


def test_an_uninspected_load_never_reports_a_pound_balance_problem(api):
    """The food-safety rule answers first; accepting the load lets the fiscal one speak.

    PRD: The load itself must have `status` of `ACCEPTED`. Loads still `PENDING_INSPECTION`, or `REJECTED`, or `QUARANTINED` may never be consumed, and the attempt is refused with `ERR_RECEIPT_NOT_ACCEPTED` (HTTP 422). This precedes the balance rule deliberately, so an unusable load never reports a balance problem.
    PRD: The pounds requested must fit: `consumed_lb` must not exceed the load's `remaining_lb`, which already nets out every earlier `ACTIVE` consumption drawn from that load by *any* run.

    Design: Difficulty/priority_pair_validation_conflict/consumption_receipt_safety_beats_balance_fiscal
    """
    world, load = _running_run_and_an_uninspected_load(api)
    run_version = world.run["version"]

    validate_error(
        api.create_lot_consumption(
            world.run_id,
            f.lot_consumption_payload(load["id"], run_version, IMPOSSIBLE_DRAW_LB),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.RECEIPT_NOT_ACCEPTED,
    )
    # A refused write leaves the run's version alone, so the same guard still holds.
    a.assert_version_is(fx.read_run(api, world.run_id), run_version, "process run")

    accepted = fx.disposition_receipt(
        api, load["id"], c.DECISION_ACCEPT, trim_loss_lb=0.00
    )
    assert accepted["accepted_lb"] == THIRD_LOAD_NET_LB
    assert accepted["remaining_lb"] == THIRD_LOAD_NET_LB

    validate_error(
        api.create_lot_consumption(
            world.run_id,
            f.lot_consumption_payload(load["id"], run_version, IMPOSSIBLE_DRAW_LB),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.INSUFFICIENT_RECEIPT_BALANCE,
    )
    a.assert_version_is(fx.read_run(api, world.run_id), run_version, "process run")


def test_a_draw_of_exactly_the_remaining_balance_passes_and_zeroes_it(api):
    """With both rules satisfied the balance goes to zero rather than negative.

    PRD: Exactly equal passes and drives the balance to zero; anything more is refused with `ERR_INSUFFICIENT_RECEIPT_BALANCE` (HTTP 422).
    PRD: A load's `remaining_lb` is its `accepted_lb` less the total `consumed_lb` of every `ACTIVE` consumption naming that load, rounded half-up to two decimal places.

    Design: Difficulty/priority_pair_validation_conflict/consumption_receipt_safety_beats_balance_fiscal
    """
    world, load = _running_run_and_an_uninspected_load(api)
    fx.disposition_receipt(api, load["id"], c.DECISION_ACCEPT, trim_loss_lb=0.00)

    consumption = fx.consume(
        api,
        world.run_id,
        load["id"],
        world.run["version"],
        consumed_lb=THIRD_LOAD_NET_LB,
    )
    assert consumption["status"] == c.CONSUMPTION_ACTIVE
    assert consumption["consumed_lb"] == THIRD_LOAD_NET_LB

    drained = fx.read_receipt(api, load["id"])
    assert drained["remaining_lb"] == 0.00
    a.assert_pounds(drained["remaining_lb"], "remaining_lb")

    run = fx.read_run(api, world.run_id)
    assert run["input_lb"] == THIRD_LOAD_NET_LB
