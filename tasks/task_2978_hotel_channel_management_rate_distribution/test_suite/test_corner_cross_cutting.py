"""Cross-cutting layers: optimistic concurrency echoes and the failure-streak threshold.

Two room-type writes and two rate-plan writes share one counter each, so this module
pins what actually spends a version echo (§2.4, §2.8), what a refused write is forbidden
to touch (§2.7's "no side effect of any kind"), what an accepted repricing re-derives and
fans out (§3.2), and where the three-consecutive-failure suspension boundary sits once an
OK heartbeat is allowed to reset the run (§3.3).
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CHANNEL_OPS_ENGINEER_HEADERS,
    REVENUE_DIRECTOR_HEADERS,
    REVENUE_MANAGER_HEADERS,
    assert_batch_counters,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_performance,
    assert_sequence_indices_one_based,
    assert_version,
)
from test_helpers import factories, fixtures

# A full page, so a list read of a scenario's rows is never truncated at the default 10.
FULL_PAGE = 100

# A later "today" than the fixture clock. Parking the clock here between a write and the
# refusal that follows it makes an unwanted version bump visible: the refused write would
# have refreshed ``updated_at`` to this instant, and the assertions demand the earlier one.
LATER_CLOCK = "2026-08-26T00:00:00.000Z"


# ── Local scenario builders, composed from the shared fixtures ─────────────


def _attempt_allocation(
    api: Any,
    room_type_id: str,
    channel_id: str,
    allocated_units: int,
    start_date: str,
    end_date: str,
    expected_room_type_version: int,
) -> Any:
    """Carve an allotment echoing an explicit room-type version, returning the raw response.

    The shared builder re-reads the room type's current version for the caller, which is
    exactly what a test of a *stale* echo must not do, so this one sends the number it is
    given and leaves the status assertion to the test.
    """
    payload = factories.allocation_payload(
        channel_id=channel_id,
        allocated_units=allocated_units,
        start_date=start_date,
        end_date=end_date,
        expected_room_type_version=expected_room_type_version,
    )
    return api.create_allocation(room_type_id, payload, REVENUE_MANAGER_HEADERS)


def _attempt_reprice(
    api: Any, rate_plan_id: str, expected_rate_plan_version: int, **fields: Any
) -> Any:
    """Reprice a plan echoing an explicit version, returning the raw response."""
    payload = factories.reprice_payload(
        expected_rate_plan_version=expected_rate_plan_version, **fields
    )
    return api.patch_rate_plan(rate_plan_id, payload, REVENUE_MANAGER_HEADERS)


def _allocation_page(api: Any, room_type_id: str) -> Tuple[list, dict]:
    """Every allotment of one room type, as a validated page."""
    params = factories.page_params(limit=FULL_PAGE, room_type_id=room_type_id)
    return validate_paginated(api.list_allocations(REVENUE_MANAGER_HEADERS, params))


def _rate_batch_page(api: Any, property_id: str) -> Tuple[list, dict]:
    """The property's RATE distribution batches, as a validated page."""
    params = factories.page_params(limit=FULL_PAGE, property_id=property_id, payload_kind="RATE")
    return validate_paginated(api.list_batches(REVENUE_MANAGER_HEADERS, params))


def _job_page(api: Any, **filters: Any) -> Tuple[list, dict]:
    """Distribution jobs matching the filters, as a validated page."""
    params = factories.page_params(limit=FULL_PAGE, **filters)
    return validate_paginated(api.list_jobs(REVENUE_MANAGER_HEADERS, params))


def _seed_derived_plan_chain(api: Any, world: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """An ACTIVE child plan derived from the canonical plan, plus one VERIFIED mapping.

    CORP takes its base from BAR at -1500 basis points, so its stored resolved amount is
    25000 x 8500 / 10000 = 21250. Only BAR carries a mapping, so a fan-out driven from BAR
    reaches exactly one channel even though the re-derivation reaches two plans.
    """
    corp = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        code="CORP",
        rate_class="NEGOTIATED",
        negotiated_account_code="ACME",
        offset_kind="PERCENT",
        offset_bp=-1500,
        floor_amount_cents=15000,
        ceiling_amount_cents=40000,
    )
    corp = fixtures.activate_rate_plan(api, corp["id"])
    mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    return corp, mapping


def _seed_two_draft_mappings(api: Any, world: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Two DRAFT mappings on the one live connection, one per room type.

    Both publish the master content of their room type, so content parity is never the
    thing that decides whether a verification is admitted — the connection's sellability is.
    """
    twin = fixtures.create_twin_room_type(api, world["property_id"])
    king_mapping = fixtures.create_mapping_in_parity(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    twin_mapping = fixtures.create_mapping_in_parity(
        api, world["rate_plan_id"], world["channel_id"], twin["id"]
    )
    return king_mapping, twin_mapping


def _heartbeat(api: Any, connection_id: str, status: str, **fields: Any) -> Dict[str, Any]:
    """Report one heartbeat and pin its 200, returning the updated connection."""
    payload = factories.heartbeat_payload(status=status, **fields)
    response = api.record_heartbeat(connection_id, payload, CHANNEL_OPS_ENGINEER_HEADERS)
    return validate_success(response, 200)


def _property_only(api: Any) -> Dict[str, Any]:
    """Park the clock and register the canonical property, and nothing else."""
    fixtures.set_clock(api)
    return fixtures.create_canonical_property(api)


# ── The room type's version echo ───────────────────────────────────────────


def test_stale_room_type_echo_after_an_interleaved_patch_is_refused_and_applies_nothing(api, world):
    """A room-type modification bumps the room type's version, so an allotment echoing the
    version the client read beforehand is refused with ERR_STALE_ROOM_TYPE_VERSION at 412,
    and the refusal creates no allotment, recomputes no inventory day and moves neither the
    room type's version nor its updated_at.

    Design: Corner/cross_cutting_complexity_layers/stale_room_type_version_is_refused_and_a_matching_echo_is_spent_by_the_write
    """
    room_type_id = world["room_type_id"]
    fixtures.open_inventory_day(api, room_type_id, fixtures.STAY_DATE)

    # The version the client observed before anybody else wrote to the room type.
    assert_version(world["room_type"], 1, "room type")
    observed_version = world["room_type"]["version"]

    patched = validate_success(
        api.patch_room_type(
            room_type_id,
            factories.room_type_patch_payload(name="King Room Harbour View"),
            REVENUE_MANAGER_HEADERS,
        ),
        200,
    )
    assert_version(patched, 2, "room type")

    # Move the clock on, so a version bump on the refused write would be visible in
    # updated_at as well as in the counter.
    fixtures.set_clock(api, LATER_CLOCK)

    refusal = _attempt_allocation(
        api,
        room_type_id,
        world["channel_id"],
        2,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
        observed_version,
    )
    validate_error(refusal, ApiErrorId.STALE_ROOM_TYPE_VERSION.value, 412)

    rows, meta = _allocation_page(api, room_type_id)
    assert meta["total_count"] == 0, (
        f"the refused allotment should have created no row, found {meta['total_count']}"
    )
    assert rows == [], f"the refused allotment should have created no row, found {rows}"

    # 10 physical rooms at the property's 1000 bp allowance -> floor(10 x 1000 / 10000) = 1
    # of uplift, so the ceiling is 11 and every unit of it is still in the shared pool.
    day = fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE)
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    after = fixtures.read_room_type(api, room_type_id)
    assert_version(after, 2, "room type")
    assert_instant_equals(after["updated_at"], patched["updated_at"], "room type.updated_at")
    assert_fields(after, {"name": "King Room Harbour View"}, "room type")


def test_matching_room_type_echo_is_accepted_and_is_spent_by_the_write(api, world):
    """An allotment whose echo equals the room type's current version is accepted, holds its
    units out of the shared pool and bumps the room type's version by exactly one — which
    spends that echo, so replaying the same number is refused and leaves the first allotment
    OPEN and unsuperseded.

    Design: Corner/cross_cutting_complexity_layers/stale_room_type_version_is_refused_and_a_matching_echo_is_spent_by_the_write
    """
    room_type_id = world["room_type_id"]
    fixtures.open_inventory_day(api, room_type_id, fixtures.STAY_DATE)

    observed_version = fixtures.room_type_version(api, room_type_id)
    assert observed_version == 1, (
        f"an unmodified room type should still be at version 1, got {observed_version}"
    )

    accepted = validate_success(
        _attempt_allocation(
            api,
            room_type_id,
            world["channel_id"],
            2,
            fixtures.STAY_DATE,
            fixtures.STAY_DATE,
            observed_version,
        ),
        201,
    )
    assert_fields(
        accepted,
        {
            "room_type_id": room_type_id,
            "channel_id": world["channel_id"],
            "allocated_units": 2,
            "consumed_units": 0,
            "allocation_state": "OPEN",
            "superseded_at": None,
            "recalled_at": None,
        },
        "allotment",
    )
    assert_version(accepted, 1, "allotment")

    # The accepted write spent the echo: 1 -> 2, by exactly one.
    assert_version(fixtures.read_room_type(api, room_type_id), observed_version + 1, "room type")

    # Two of the eleven ceiling units are now held for the channel.
    assert_inventory_day(
        fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE),
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=2,
        committed=0,
        shared=fixtures.KING_CEILING - 2,
        pooled_state="OPEN",
    )

    replay = _attempt_allocation(
        api,
        room_type_id,
        world["channel_id"],
        3,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
        observed_version,
    )
    validate_error(replay, ApiErrorId.STALE_ROOM_TYPE_VERSION.value, 412)

    rows, meta = _allocation_page(api, room_type_id)
    assert meta["total_count"] == 1, (
        f"the replayed echo should have created no second row, found {meta['total_count']}"
    )
    assert_fields(
        rows[0],
        {"id": accepted["id"], "allocated_units": 2, "allocation_state": "OPEN", "superseded_at": None},
        "allotment",
    )
    assert_version(rows[0], 1, "allotment")
    assert_version(fixtures.read_room_type(api, room_type_id), 2, "room type")
    assert_inventory_day(
        fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE),
        allocated=2,
        committed=0,
        shared=fixtures.KING_CEILING - 2,
        pooled_state="OPEN",
    )


# ── The rate plan's version echo ───────────────────────────────────────────


def test_stale_rate_plan_echo_is_refused_and_suppresses_the_whole_fan_out(api, world):
    """Activation bumps a plan's version, so a repricing that echoes the version the plan
    carried while it was DRAFT is refused with ERR_STALE_RATE_PLAN_VERSION at 412 — not with
    a state error — and the 412 suppresses everything downstream of the write: no field
    changes, no descendant is re-derived, and no batch or job is created.

    Design: Corner/cross_cutting_complexity_layers/stale_rate_plan_version_is_refused_and_a_correct_echo_rederives_and_fans_out
    """
    corp, _mapping = _seed_derived_plan_chain(api, world)
    bar_id = world["rate_plan_id"]

    # The plan was created at version 1 and activation already spent that number.
    draft_version = 1
    bar_before = fixtures.read_rate_plan(api, bar_id)
    assert_version(bar_before, 2, "rate plan")
    assert_fields(
        corp,
        {"resolved_base_amount_cents": 21250, "offset_bp": -1500, "plan_state": "ACTIVE"},
        "derived plan",
    )

    fixtures.set_clock(api, LATER_CLOCK)

    refusal = _attempt_reprice(api, bar_id, draft_version, base_amount_cents=30000)
    validate_error(refusal, ApiErrorId.STALE_RATE_PLAN_VERSION.value, 412)

    bar_after = fixtures.read_rate_plan(api, bar_id)
    assert_fields(
        bar_after,
        {
            "base_amount_cents": fixtures.BAR_BASE_CENTS,
            "resolved_base_amount_cents": fixtures.BAR_BASE_CENTS,
            "plan_state": "ACTIVE",
        },
        "rate plan",
    )
    assert_version(bar_after, 2, "rate plan")
    assert_instant_equals(bar_after["updated_at"], bar_before["updated_at"], "rate plan.updated_at")

    corp_after = fixtures.read_rate_plan(api, corp["id"])
    assert_fields(corp_after, {"resolved_base_amount_cents": 21250}, "derived plan")
    assert_version(corp_after, corp["version"], "derived plan")
    assert_instant_equals(
        corp_after["updated_at"], corp["updated_at"], "derived plan.updated_at"
    )

    _batches, batch_meta = _rate_batch_page(api, world["property_id"])
    assert batch_meta["total_count"] == 0, (
        f"the refused repricing should have queued no RATE batch, found {batch_meta['total_count']}"
    )
    _jobs, job_meta = _job_page(api)
    assert job_meta["total_count"] == 0, (
        f"the refused repricing should have fanned out no job, found {job_meta['total_count']}"
    )


def test_correct_rate_plan_echo_rederives_the_descendant_and_fans_out_one_job_per_verified_mapping(
    api, world
):
    """A repricing that echoes the plan's current version is accepted: the submitted fields
    are written, the descendant plan's resolved amount is re-derived in the same request, one
    QUEUED RATE batch is created carrying one job per VERIFIED mapping of the plan or of any
    descendant, numbered from 1, and the plan's version is bumped by exactly one.

    Design: Corner/cross_cutting_complexity_layers/stale_rate_plan_version_is_refused_and_a_correct_echo_rederives_and_fans_out
    """
    corp, mapping = _seed_derived_plan_chain(api, world)
    bar_id = world["rate_plan_id"]

    current_version = fixtures.rate_plan_version(api, bar_id)
    assert current_version == 2, (
        f"an activated plan should stand at version 2, got {current_version}"
    )

    accepted = validate_success(
        _attempt_reprice(api, bar_id, current_version, base_amount_cents=30000), 200
    )
    assert_fields(
        accepted,
        {
            "base_amount_cents": 30000,
            "resolved_base_amount_cents": 30000,
            "plan_state": "ACTIVE",
        },
        "rate plan",
    )
    assert_version(accepted, current_version + 1, "rate plan")

    # The child is re-derived parent-before-child inside the same request:
    # round_half_up(30000 x (10000 - 1500) / 10000) = 25500, and its own offset is untouched.
    corp_after = fixtures.read_rate_plan(api, corp["id"])
    assert_fields(
        corp_after,
        {
            "resolved_base_amount_cents": 25500,
            "offset_kind": "PERCENT",
            "offset_bp": -1500,
            "plan_state": "ACTIVE",
        },
        "derived plan",
    )
    assert_version(corp_after, corp["version"] + 1, "derived plan")

    batches, batch_meta = _rate_batch_page(api, world["property_id"])
    assert batch_meta["total_count"] == 1, (
        f"one accepted repricing should queue exactly one RATE batch, "
        f"found {batch_meta['total_count']}"
    )
    batch = batches[0]
    assert_fields(
        batch,
        {
            "property_id": world["property_id"],
            "payload_kind": "RATE",
            "source_ref_kind": "RATE_PLAN",
            "source_ref_id": bar_id,
            "dispatched_at": None,
        },
        "batch",
    )
    assert_batch_counters(
        batch,
        batch_state="QUEUED",
        total_jobs=1,
        applied_jobs=0,
        rejected_jobs=0,
        abandoned_jobs=0,
    )

    # The one VERIFIED mapping is BAR x OTA1 x KING; the derived plan carries no mapping, so
    # the fan-out that reaches two plans still reaches one channel.
    jobs, job_meta = _job_page(api, batch_id=batch["id"])
    assert job_meta["total_count"] == 1, (
        f"the batch should carry one child job, found {job_meta['total_count']}"
    )
    assert_sequence_indices_one_based(jobs)
    assert jobs[0]["sequence_index"] == 1, (
        f"the first fanned-out job should sit at sequence_index 1, got {jobs[0]['sequence_index']}"
    )
    # The pushed rate is promotion-free: 30000 x (10000 + 0) / 10000 = 30000, inside the
    # 18000-40000 band, plus a package inclusion of 0.
    assert_job(
        jobs[0],
        job_state="QUEUED",
        attempt_count=0,
        failure_reason=None,
        payload_rate_cents=30000,
        channel_mapping_id=mapping["id"],
    )
    assert_fields(
        jobs[0], {"batch_id": batch["id"], "payload_kind": "RATE", "applied_at": None}, "job"
    )


# ── One counter, four accepted writes ──────────────────────────────────────


def test_each_accepted_rate_plan_write_bumps_the_version_by_one_and_reads_never_move_it(api):
    """A plan's version starts at 1 and advances by exactly one on each accepted mutation, and
    activation and closure are mutations too even though neither carries a concurrency echo:
    create 1, activate 2, reprice 3, close 4. The reads interleaved between them move nothing.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_accepted_write_and_on_no_read_or_refusal
    """
    prop = _property_only(api)

    created = validate_success(
        api.create_rate_plan(
            prop["id"],
            factories.rate_plan_payload(
                code=fixtures.BAR_CODE,
                rate_class="PUBLIC",
                base_amount_cents=fixtures.BAR_BASE_CENTS,
                floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
                ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_version(created, 1, "rate plan")
    assert_fields(created, {"plan_state": "DRAFT"}, "rate plan")
    plan_id = created["id"]

    # A read is not a write, whoever issues it.
    read_back = validate_success(api.get_rate_plan(plan_id, REVENUE_DIRECTOR_HEADERS), 200)
    assert_version(read_back, 1, "rate plan")

    activated = validate_success(api.activate_rate_plan(plan_id, REVENUE_MANAGER_HEADERS), 200)
    assert_fields(activated, {"plan_state": "ACTIVE"}, "rate plan")
    assert_version(activated, 2, "rate plan")

    repriced = validate_success(
        _attempt_reprice(api, plan_id, activated["version"], ceiling_amount_cents=45000), 200
    )
    assert_fields(
        repriced,
        {"ceiling_amount_cents": 45000, "plan_state": "ACTIVE"},
        "rate plan",
    )
    assert_version(repriced, 3, "rate plan")

    closed = validate_success(api.close_rate_plan(plan_id, REVENUE_MANAGER_HEADERS), 200)
    assert_fields(
        closed,
        {"plan_state": "CLOSED", "ceiling_amount_cents": 45000},
        "rate plan",
    )
    assert_version(closed, 4, "rate plan")

    final = validate_success(api.get_rate_plan(plan_id, REVENUE_MANAGER_HEADERS), 200)
    assert_fields(
        final,
        {"plan_state": "CLOSED", "ceiling_amount_cents": 45000},
        "rate plan",
    )
    assert_version(final, 4, "rate plan")


def test_a_refused_repricing_contributes_nothing_to_the_version_counter(api):
    """A repricing that replays an already-spent version is refused, and the refusal contributes
    nothing: the counter, the submitted field and updated_at all stay where the accepted write
    left them, and the closure that follows still takes the plan to version 4 rather than 5.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_accepted_write_and_on_no_read_or_refusal
    """
    prop = _property_only(api)
    plan = fixtures.create_canonical_rate_plan(api, prop["id"])
    assert_version(plan, 1, "rate plan")

    activated = fixtures.activate_rate_plan(api, plan["id"])
    assert_version(activated, 2, "rate plan")
    spent_version = activated["version"]

    accepted = validate_success(
        _attempt_reprice(api, plan["id"], spent_version, ceiling_amount_cents=45000), 200
    )
    assert_fields(accepted, {"ceiling_amount_cents": 45000}, "rate plan")
    assert_version(accepted, 3, "rate plan")

    # Move the clock on, so a version bump on the refused write would also show up as a
    # refreshed updated_at.
    fixtures.set_clock(api, LATER_CLOCK)

    refusal = _attempt_reprice(api, plan["id"], spent_version, ceiling_amount_cents=50000)
    validate_error(refusal, ApiErrorId.STALE_RATE_PLAN_VERSION.value, 412)

    after = fixtures.read_rate_plan(api, plan["id"])
    assert_fields(after, {"ceiling_amount_cents": 45000, "plan_state": "ACTIVE"}, "rate plan")
    assert_version(after, 3, "rate plan")
    assert_instant_equals(after["updated_at"], accepted["updated_at"], "rate plan.updated_at")

    # A read after the refusal moves it no further either.
    assert_version(
        validate_success(api.get_rate_plan(plan["id"], REVENUE_DIRECTOR_HEADERS), 200),
        3,
        "rate plan",
    )

    # Three accepted writes so far, so the fourth lands on 4 and not on 5.
    closed = fixtures.close_rate_plan(api, plan["id"])
    assert_fields(
        closed, {"plan_state": "CLOSED", "ceiling_amount_cents": 45000}, "rate plan"
    )
    assert_version(closed, 4, "rate plan")


# ── The failure streak and its reset ───────────────────────────────────────


def test_two_failures_leave_the_connection_sellable_and_an_ok_heartbeat_resets_the_run(api, world):
    """Two consecutive failures leave the streak strictly below the suspension threshold of
    three, so the connection is DEGRADED but still sellable and a mapping verification on it
    succeeds. An OK heartbeat then resets the streak to 0 and returns the connection to
    HEALTHY, so the failure that follows is the first of a fresh run rather than the third.

    Design: Corner/cross_cutting_complexity_layers/connection_suspends_exactly_on_the_third_consecutive_failure_and_an_ok_heartbeat_resets_the_run
    """
    king_mapping, _twin_mapping = _seed_two_draft_mappings(api, world)
    connection_id = world["connection_id"]

    baseline = fixtures.read_connection(api, connection_id)
    assert_fields(
        baseline,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "last_failure_code": None},
        "connection",
    )
    live_version = baseline["version"]

    first = _heartbeat(api, connection_id, "ERROR", failure_code="TIMEOUT")
    assert_fields(
        first,
        {"connection_state": "DEGRADED", "consecutive_failures": 1, "last_failure_code": "TIMEOUT"},
        "connection",
    )
    assert_version(first, live_version + 1, "connection")

    second = _heartbeat(api, connection_id, "ERROR", failure_code="TIMEOUT")
    assert_fields(
        second,
        {"connection_state": "DEGRADED", "consecutive_failures": 2, "last_failure_code": "TIMEOUT"},
        "connection",
    )
    assert_version(second, live_version + 2, "connection")

    # Two is strictly below three, so the connection is still in the sellable set.
    verified = validate_success(
        api.verify_mapping(king_mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS), 200
    )
    assert_fields(
        verified,
        {"id": king_mapping["id"], "mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "mapping",
    )

    recovered = _heartbeat(api, connection_id, "OK")
    assert_fields(
        recovered,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "last_failure_code": None},
        "connection",
    )
    assert_version(recovered, live_version + 3, "connection")
    assert_instant_equals(
        recovered["last_heartbeat_at"], fixtures.FIXTURE_CLOCK, "connection.last_heartbeat_at"
    )

    # The run was reset rather than paused: the next failure counts as one, not as three.
    resumed = _heartbeat(api, connection_id, "ERROR", failure_code="AUTH_REJECTED")
    assert_fields(
        resumed,
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 1,
            "last_failure_code": "AUTH_REJECTED",
        },
        "connection",
    )
    assert_version(resumed, live_version + 4, "connection")


def test_the_third_failure_of_the_run_suspends_the_connection_and_blocks_verification(api, world):
    """Five failure events with one OK heartbeat in the middle suspend the connection on the
    fifth, because that one is the third of the run that began after the reset. A SUSPENDED
    connection is not sellable, so verifying the remaining mapping is refused with
    ERR_CONNECTION_NOT_SELLABLE and that mapping stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/connection_suspends_exactly_on_the_third_consecutive_failure_and_an_ok_heartbeat_resets_the_run
    """
    king_mapping, twin_mapping = _seed_two_draft_mappings(api, world)
    connection_id = world["connection_id"]

    fixtures.fail_connection(api, connection_id, times=2, failure_code="TIMEOUT")
    fixtures.verify_mapping(api, king_mapping["id"])
    reset = _heartbeat(api, connection_id, "OK")
    assert_fields(reset, {"connection_state": "HEALTHY", "consecutive_failures": 0}, "connection")

    rebuilt = fixtures.fail_connection(api, connection_id, times=2, failure_code="AUTH_REJECTED")
    assert_fields(
        rebuilt,
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 2,
            "last_failure_code": "AUTH_REJECTED",
        },
        "connection",
    )

    # The fifth ERROR overall is only the third of this run, and it is the one that suspends.
    suspended = _heartbeat(api, connection_id, "ERROR", failure_code="AUTH_REJECTED")
    assert_fields(
        suspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "AUTH_REJECTED",
        },
        "connection",
    )
    assert_instant_equals(
        suspended["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )

    refusal = api.verify_mapping(twin_mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    validate_error(refusal, ApiErrorId.CONNECTION_NOT_SELLABLE.value, 409)
    assert_fields(
        fixtures.read_mapping(api, twin_mapping["id"]),
        {"id": twin_mapping["id"], "mapping_state": "DRAFT"},
        "mapping",
    )
    assert_version(fixtures.read_mapping(api, twin_mapping["id"]), twin_mapping["version"], "mapping")

    # Heartbeats feed the failure counter, not the health-score denominator: no distribution
    # job ever resolved, so the score is null even after five failure events.
    performance = fixtures.channel_performance(
        api, world["channel_id"], fixtures.FIXTURE_TODAY, fixtures.STAY_DATE
    )
    assert_performance(
        performance,
        {
            "channel_id": world["channel_id"],
            "basis": "STAY",
            "room_nights": 0,
            "health_score_bp": None,
        },
    )
