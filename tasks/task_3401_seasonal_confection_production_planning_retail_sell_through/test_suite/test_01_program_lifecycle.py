"""Program lifecycle: creation contract, window-chain uniqueness, terminal
lockdown, the single-reopen budget, OCC on advance, immediate consistency,
and the production-scheduled gate.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AT_COMMITMENT_CLOSE,
    CLOCK_BASELINE,
    ProgramAdvanceTarget,
    SeasonalProgramStatus,
    TEST_USERS,
    advance_program_to,
    api_client,
    assert_seasonal_program,
    cancel_program,
    create_program_payload,
    get_program,
    set_clock,
    setup_locked_program,
    setup_open_program,
    setup_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_program_create_returns_every_field_and_starts_planning(api):
    """PRD §3.1: "The program is born in `PLANNING` status with `reopen_count`
    0, all computed totals (`produced_units_total`, `committed_units_total`,
    `shipped_units_total`, `disposed_units_total`) at 0, and `version` 1."

    Design: Corner/entities/program_create_returns_every_field_and_starts_planning
    """
    set_clock(CLOCK_BASELINE)
    resp = api_client.create_seasonal_program(create_program_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert_seasonal_program(data)
    assert data["status"] == SeasonalProgramStatus.PLANNING.value
    assert data["reopen_count"] == 0
    assert data["produced_units_total"] == 0
    assert data["committed_units_total"] == 0
    assert data["shipped_units_total"] == 0
    assert data["disposed_units_total"] == 0
    assert data["version"] == 1
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_program_create_missing_pull_on_returns_invalid_request(api):
    """PRD §2.8: "a request with a missing required field, a wrong-typed value,
    an out-of-enum value, or a violated field constraint (for example an end
    instant not after its start instant, or a unit count of zero or less where
    a positive count is required) is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/program_create_missing_pull_on_returns_invalid_request
    """
    set_clock(CLOCK_BASELINE)
    payload = create_program_payload(season_code="EASTER")
    del payload["pull_on"]
    resp = api_client.create_seasonal_program(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert "id" not in (resp.json().get("data") or {}), (
        "no program row may be persisted on a 400"
    )


def test_duplicate_program_season_and_year_returns_duplicate_resource(api):
    """PRD §2.5: "The pair of `season_code` and `season_year` is unique across
    programs; a second program for the same season and year is rejected with
    `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/validations/duplicate_program_season_and_year_returns_duplicate_resource
    """
    set_clock(CLOCK_BASELINE)
    first = api_client.create_seasonal_program(create_program_payload(), ADMIN)
    validate_success(first, 201)

    dup = api_client.create_seasonal_program(
        create_program_payload(forecast_units=90000), ADMIN,
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_RESOURCE)

    other_year = api_client.create_seasonal_program(
        create_program_payload(
            season_year=2028,
            commitment_open_on="2028-01-10T00:00:00Z",
            commitment_close_on="2028-02-15T00:00:00Z",
            production_deadline_on="2028-06-30T00:00:00Z",
            ship_window_open_on="2028-07-15T00:00:00Z",
            ship_window_close_on="2028-09-15T00:00:00Z",
            on_shelf_on="2028-09-20T00:00:00Z",
            pull_on="2028-11-15T00:00:00Z",
            destroy_by_on="2028-12-31T00:00:00Z",
            retail_price_cents=519,
            forecast_units=90000,
        ),
        ADMIN,
    )
    data = validate_success(other_year, 201)
    assert data["status"] == SeasonalProgramStatus.PLANNING.value


def test_program_cancelled_is_terminal_lockdown(api):
    """PRD §3.1: "`CLOSED` and `CANCELLED` are the terminal program states; any
    advance attempted from a state where the requested target is not defined —
    including any transition out of a terminal state — is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/program_cancelled_is_terminal_lockdown
    """
    program = setup_program()
    cancelled = cancel_program(program["id"])
    assert cancelled["status"] == SeasonalProgramStatus.CANCELLED.value

    resp = api_client.advance_program(
        program["id"],
        {
            "to_state": ProgramAdvanceTarget.OPEN_FOR_COMMITMENTS.value,
            "expected_program_version": cancelled["version"],
        },
        ADMIN,
    )
    # Fresh version, so the rejection is the terminal state, not OCC.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_program(program["id"])["status"] == SeasonalProgramStatus.CANCELLED.value


def test_program_reopen_loop_consumes_single_reopen_budget(api):
    """PRD §3.4: "the program supports a single sanctioned reopen from `LOCKED`
    back to `OPEN_FOR_COMMITMENTS`, usable at most once — the reopen budget
    `MAX_REOPEN` is 1." and "a second attempt, finding `reopen_count` already
    at the budget, is rejected with `ERR_PROGRAM_REOPEN_EXHAUSTED` (HTTP 422)."

    Design: Corner/state_machines/program_reopen_loop_consumes_single_reopen_budget
    """
    world = setup_open_program()
    program_id = world["program"]["id"]

    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    advance_program_to(program_id, ProgramAdvanceTarget.LOCKED.value)
    reopened = advance_program_to(
        program_id, ProgramAdvanceTarget.OPEN_FOR_COMMITMENTS.value,
    )
    assert reopened["reopen_count"] == 1
    advance_program_to(program_id, ProgramAdvanceTarget.LOCKED.value)

    current = get_program(program_id)
    resp = api_client.advance_program(
        program_id,
        {
            "to_state": ProgramAdvanceTarget.OPEN_FOR_COMMITMENTS.value,
            "expected_program_version": current["version"],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_REOPEN_EXHAUSTED)
    final = get_program(program_id)
    assert final["status"] == SeasonalProgramStatus.LOCKED.value
    assert final["reopen_count"] == 1


def test_program_advance_with_stale_version_returns_412(api):
    """PRD §2.7: "If another writer has advanced the program's `version` since
    the caller last read it, the advance is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the caller from re-driving a transition — such as
    consuming the single reopen budget or re-running allocation — against a
    snapshot it has not observed."

    Design: Corner/cross_cutting_complexity_layers/program_advance_with_stale_version_returns_412
    """
    world = setup_open_program()
    program = world["program"]
    assert program["version"] == 2

    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    resp = api_client.advance_program(
        program["id"],
        {
            "to_state": ProgramAdvanceTarget.LOCKED.value,
            "expected_program_version": 1,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_program(program["id"])
    assert after["status"] == SeasonalProgramStatus.OPEN_FOR_COMMITMENTS.value
    assert after["version"] == 2


def test_advance_response_carries_the_mutation_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §2.4: "The `version` is an integer starting at 1 on creation
    and incremented by exactly 1 on every mutation".

    Design: Corner/consistency_model/advance_response_carries_the_mutation_immediately
    """
    program = setup_program()
    resp = api_client.advance_program(
        program["id"],
        {
            "to_state": ProgramAdvanceTarget.OPEN_FOR_COMMITMENTS.value,
            "expected_program_version": program["version"],
        },
        ADMIN,
    )
    data = validate_success(resp, 200)
    assert data["status"] == SeasonalProgramStatus.OPEN_FOR_COMMITMENTS.value
    assert data["version"] == program["version"] + 1

    reread = get_program(program["id"])
    assert reread["status"] == data["status"]
    assert reread["version"] == data["version"]


def test_advance_to_in_production_without_runs_returns_no_production_scheduled(api):
    """PRD §3.2: "A program leaves `LOCKED` for `IN_PRODUCTION` only when at
    least one non-`CANCELLED` production run exists for it; advancing otherwise
    is rejected with `ERR_NO_PRODUCTION_SCHEDULED` (HTTP 422)."

    Design: Corner/errors/advance_to_in_production_without_runs_returns_no_production_scheduled
    """
    world = setup_locked_program()
    program = world["program"]
    assert program["status"] == SeasonalProgramStatus.LOCKED.value

    resp = api_client.advance_program(
        program["id"],
        {
            "to_state": ProgramAdvanceTarget.IN_PRODUCTION.value,
            "expected_program_version": program["version"],
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NO_PRODUCTION_SCHEDULED)
    assert get_program(program["id"])["status"] == SeasonalProgramStatus.LOCKED.value
