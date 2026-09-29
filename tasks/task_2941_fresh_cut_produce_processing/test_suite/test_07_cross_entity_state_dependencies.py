"""Actions whose legality is decided entirely by a neighbouring entity's state.

Each pair issues the identical request twice with nothing about the target
resource changed between the attempts - only the state of a sibling or an
ancestor - so the dependency is demonstrated rather than assumed.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    SHIPPING_CLERK_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_TECH_B,
    USER_SANITATION_TECH_A,
    make_qa_technician_headers,
)


def _run_ready_to_start_behind_an_unvalidated_clean(api):
    """A startable run on a line whose only clean still awaits validation."""
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)

    event = fx.schedule_sanitation(api, world.line_id)
    fx.start_sanitation(api, event["id"], USER_SANITATION_TECH_A)
    submitted = fx.submit_sanitation(api, event["id"], USER_SANITATION_TECH_A)
    assert submitted["status"] == c.SANITATION_AWAITING_VALIDATION
    assert submitted["performed_by_user_id"] == USER_SANITATION_TECH_A

    world.sanitation_event = submitted
    world.run = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    world.readings.append(
        fx.create_reading(
            api, world.wash_system_id, c.READING_PRE_START_AT, c.READING_PRE_START_PPM
        )
    )
    fx.set_clock(api, c.CLOCK_START)

    line = fx.read_line(api, world.line_id)
    assert line["posture"] == c.POSTURE_RESTRICTED
    assert line["last_validated_sanitation_at"] is None
    return world


def test_a_run_cannot_start_while_its_line_awaits_a_validation(api):
    """The start reads no field of the run: the sibling clean decides.

    PRD: The line's derived `posture` must be `OPEN`. A `RESTRICTED` or `FROZEN` line is refused with `ERR_LINE_NOT_OPEN` (HTTP 409). Since posture requires the line's latest sanitation event to be `VALIDATED` and no unverified corrective action to exist, this single gate carries the whole sanitation and corrective-action programme into every start.
    PRD: Validation is a `QATechnician` decision carrying an `outcome` of `PASS` or `FAIL`, and it is where segregation of duties bites: the validating `X-User-ID` must differ from the event's `performed_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`.

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_validated_sanitation_on_line
    """
    world = _run_ready_to_start_behind_an_unvalidated_clean(api)

    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.LINE_NOT_OPEN,
    )
    assert fx.read_run(api, world.run_id)["run_status"] == c.RUN_SETUP

    # The technician who performed the clean cannot unlock the line themselves,
    # even wearing the QATechnician role.
    validate_error(
        api.validate_sanitation_event(
            world.sanitation_event["id"],
            f.outcome_payload(c.OUTCOME_PASS),
            make_qa_technician_headers(USER_SANITATION_TECH_A),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    still_shut = fx.read_line(api, world.line_id)
    assert still_shut["posture"] == c.POSTURE_RESTRICTED
    assert still_shut["last_validated_sanitation_at"] is None
    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.LINE_NOT_OPEN,
    )


def test_validating_the_clean_lets_the_identical_start_call_through(api):
    """One write to the sanitation event opens the line and the run starts.

    PRD: On validation the server stamps `validated_at` and `validated_by_user_id`, sets the line's `last_validated_sanitation_at` to that instant, and recomputes the line's `posture`, which can move the line `RESTRICTED → OPEN`.
    PRD: When a recomputation moves a line `RESTRICTED → OPEN`, the server also sets `last_validated_sanitation_at` to the `validated_at` of the newest `VALIDATED` sanitation event on the line, and run starts become possible.

    Design: Difficulty/cross_entity_state_dependency/run_start_requires_validated_sanitation_on_line
    """
    world = _run_ready_to_start_behind_an_unvalidated_clean(api)

    validated = fx.validate_sanitation(api, world.sanitation_event["id"])
    assert validated["status"] == c.SANITATION_VALIDATED
    a.assert_instant_equals(validated["validated_at"], c.CLOCK_START, "validated_at")

    opened = fx.read_line(api, world.line_id)
    assert opened["posture"] == c.POSTURE_OPEN
    a.assert_instant_equals(
        opened["last_validated_sanitation_at"], c.CLOCK_START,
        "last_validated_sanitation_at",
    )

    started = fx.start_run(api, world.run_id)
    assert started["run_status"] == c.RUN_RUNNING
    # Nothing has been consumed, so the flume is still on its base tier.
    assert started["target_ppm_at_start"] == c.TARGET_PPM_TIER_BASE
    assert started["required_dwell_seconds_at_start"] == c.DWELL_FLOOR_SECONDS
    a.assert_instant_equals(started["started_at"], c.CLOCK_START, "started_at")


def test_a_case_on_a_held_run_reports_the_run_level_cause(api):
    """The case is refused for its grandparent's disposition, not its own status.

    PRD: First, the parent run's `disposition_status` must be `UNRESTRICTED` or `RELEASED`; a run that is `HELD` or `REJECTED` cannot ship and the attempt is refused with `ERR_HOLD_NOT_RELEASED` (HTTP 409). This precedes the case's own state check deliberately, so that a held case reports the run-level cause rather than the case-level symptom.
    PRD: Within shipping specifically, the run-level cause is reported before the case-level symptom: `ERR_HOLD_NOT_RELEASED` precedes `ERR_CASE_NOT_IN_INVENTORY`.

    Design: Difficulty/cross_entity_state_dependency/case_ship_requires_released_hold_on_run
    """
    world = fx.closed_world(api)
    first_case = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]

    assert first_case["status"] == c.CASE_ON_HOLD
    assert first_case["code_date"] == c.BASE_PROVISIONAL_CODE_DATE
    assert world.run["disposition_status"] == c.DISPOSITION_HELD

    validate_error(
        api.ship_finished_case(first_case["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.HOLD_NOT_RELEASED,
    )
    unmoved = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    assert unmoved["status"] == c.CASE_ON_HOLD
    assert unmoved["shipped_at"] is None
    a.assert_version_is(unmoved, first_case["version"], "finished case")


def test_releasing_the_hold_ships_the_case_and_lets_its_own_state_speak(api):
    """After the release the same case ships once, and the second attempt reports itself.

    PRD: Second, the case's own `status` must be `IN_INVENTORY`; an already `SHIPPED` or `DESTROYED` case on a run whose disposition permits shipping is refused with `ERR_CASE_NOT_IN_INVENTORY` (HTTP 409).
    PRD: A successful shipment stamps `shipped_at` from the logical clock, decrements the run's `cases_available`, increments its `cases_shipped`, and increments the case's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/case_ship_requires_released_hold_on_run
    """
    world = fx.closed_world(api)
    first_case = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]

    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )
    released = fx.read_run(api, world.run_id)
    assert released["disposition_status"] == c.DISPOSITION_RELEASED

    # The release re-dated the case before it ever left the plant.
    ready = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    assert ready["status"] == c.CASE_IN_INVENTORY
    assert ready["code_date"] == c.FINAL_CODE_DATE_LOW_APC

    shipped = fx.ship_case(api, first_case["id"])
    assert shipped["status"] == c.CASE_SHIPPED
    a.assert_instant_equals(shipped["shipped_at"], c.CLOCK_CLOSE, "shipped_at")

    validate_error(
        api.ship_finished_case(first_case["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.CASE_NOT_IN_INVENTORY,
    )

    counted = fx.read_run(api, world.run_id)
    a.assert_case_counters(
        counted,
        available=c.CLOSE_CASES_PRODUCED - 1,
        on_hold=0,
        shipped=1,
        destroyed=0,
    )
    a.assert_case_counters_conserved(counted)
