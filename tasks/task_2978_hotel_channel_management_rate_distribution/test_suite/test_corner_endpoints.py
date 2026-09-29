"""Endpoint-level behaviour of the distribution surface and the logical clock.

These scenarios pin the parts of the contract that live in the endpoints
themselves rather than in a calculation: which job states admit a retry, when a
settled batch stops being dispatchable, what a manual restriction lift records
and queues, the third-entity prerequisite that mapping creation checks, the pace
read that derives its own "today" from the logical clock, and the clock move
itself, which rewrites no stored row.
"""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_MANAGER_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_batch_counters,
    assert_common_fields,
    assert_fields,
    assert_ids,
    assert_instant_equals,
    assert_job,
    assert_pace,
    assert_pagination_meta,
    assert_sequence_indices_one_based,
    assert_unchanged,
    assert_version,
)
from test_helpers import factories, fixtures

# The canonical world parks the clock here, so every instant a scenario writes
# before it moves the clock again carries this value.
FIXTURE_CLOCK = fixtures.FIXTURE_CLOCK

# The instant the clock scenarios move to: a week and a half later, at a time of
# day that is not midnight, so a sub-second-precise echo is observable.
MOVED_CLOCK = "2026-09-01T12:30:00.000Z"
MOVED_CLOCK_DATE = "2026-09-01"

# The promotion-free distributed rate of the canonical plan on the canonical OTA:
# resolved base 25000, channel adjustment 0 bp -> 25000, inside the band
# 18000..41000 -> 25000, package inclusion 0 -> 25000.
DISTRIBUTED_RATE_CENTS = 25000

# A full page, so a list read in an assertion can never be truncated.
FULL_PAGE = 100


def _verified_mapping(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """The canonical plan mapped onto the canonical OTA, in parity and verified."""
    return fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code="BAR-OTA1-KING",
    )


def _rate_batches(api: ApiClient, world: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every RATE batch of the canonical property, in creation order."""
    return fixtures.list_batches(
        api, property_id=world["property_id"], payload_kind="RATE"
    )


def _restriction_batches(api: ApiClient, world: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every RESTRICTION batch of the canonical property, in creation order."""
    return fixtures.list_batches(
        api, property_id=world["property_id"], payload_kind="RESTRICTION"
    )


def _applied_and_queued_jobs(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """Two rate batches: the first dispatched to APPLIED, the second left QUEUED.

    Each repricing of the active plan queues its own RATE batch that fans out one
    job over the single VERIFIED mapping, so dispatching only the first leaves one
    settled job and one job that has never been attempted.
    """
    mapping = _verified_mapping(api, world)

    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=41000)
    first_batch = fixtures.only_batch(
        api, property_id=world["property_id"], payload_kind="RATE"
    )
    fixtures.dispatch_batch(api, first_batch["id"])

    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=42000)
    later = [
        batch for batch in _rate_batches(api, world) if batch["id"] != first_batch["id"]
    ]
    assert len(later) == 1, f"the second repricing should queue one further batch, got {len(later)}"
    second_batch = later[0]

    applied_jobs = fixtures.jobs_of(api, first_batch["id"])
    queued_jobs = fixtures.jobs_of(api, second_batch["id"])
    assert len(applied_jobs) == 1, f"batch one should hold one job, got {len(applied_jobs)}"
    assert len(queued_jobs) == 1, f"batch two should hold one job, got {len(queued_jobs)}"

    return {
        "mapping": mapping,
        "first_batch": fixtures.read_batch(api, first_batch["id"]),
        "second_batch": fixtures.read_batch(api, second_batch["id"]),
        "applied_job": applied_jobs[0],
        "queued_job": queued_jobs[0],
    }


# ── Job retry ──────────────────────────────────────────────────────────────


def test_retrying_an_applied_job_is_refused(api: ApiClient, world: Dict[str, Any]) -> None:
    """A retry is admitted only from REJECTED, so a job that already succeeded is
    refused with ERR_JOB_NOT_RETRYABLE at 409, keeps its applied_at, and leaves the
    parent batch's counters and the mapping's pushed rate exactly as they were.

    Design: Corner/endpoints/job_retry_is_refused_for_an_applied_job_and_for_a_still_queued_job
    """
    scenario = _applied_and_queued_jobs(api, world)
    applied_job = scenario["applied_job"]
    assert_job(
        applied_job,
        job_state="APPLIED",
        attempt_count=1,
        failure_reason=None,
        payload_rate_cents=DISTRIBUTED_RATE_CENTS,
        channel_mapping_id=scenario["mapping"]["id"],
    )
    mapping_before = fixtures.read_mapping(api, scenario["mapping"]["id"])

    response = api.retry_job(applied_job["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    validate_error(response, ApiErrorId.JOB_NOT_RETRYABLE.value, 409)

    job_after = fixtures.read_job(api, applied_job["id"])
    assert_job(job_after, job_state="APPLIED", attempt_count=1, failure_reason=None)
    assert_instant_equals(job_after["applied_at"], FIXTURE_CLOCK, "job.applied_at")
    assert_unchanged(
        applied_job,
        job_after,
        ["job_state", "attempt_count", "failure_reason", "applied_at", "version"],
        "job",
    )

    batch_after = fixtures.read_batch(api, scenario["first_batch"]["id"])
    assert_batch_counters(
        batch_after,
        batch_state="APPLIED",
        total_jobs=1,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_unchanged(
        scenario["first_batch"],
        batch_after,
        ["batch_state", "total_jobs", "applied_jobs", "rejected_jobs", "abandoned_jobs", "version"],
        "batch",
    )

    mapping_after = fixtures.read_mapping(api, scenario["mapping"]["id"])
    assert_fields(
        mapping_after,
        {"last_pushed_rate_cents": DISTRIBUTED_RATE_CENTS, "mapping_state": "VERIFIED"},
        "mapping",
    )
    assert_unchanged(
        mapping_before,
        mapping_after,
        ["last_pushed_rate_cents", "last_push_at", "mismatch_state", "version"],
        "mapping",
    )


def test_retrying_a_still_queued_job_is_refused(api: ApiClient, world: Dict[str, Any]) -> None:
    """Retry is not a shortcut for dispatch: a job that has never been attempted is
    not REJECTED either, so it draws the same ERR_JOB_NOT_RETRYABLE at 409 and its
    attempt_count stays at zero while its parent batch stays QUEUED.

    Design: Corner/endpoints/job_retry_is_refused_for_an_applied_job_and_for_a_still_queued_job
    """
    scenario = _applied_and_queued_jobs(api, world)
    queued_job = scenario["queued_job"]
    assert_job(
        queued_job,
        job_state="QUEUED",
        attempt_count=0,
        failure_reason=None,
        channel_mapping_id=scenario["mapping"]["id"],
    )
    assert queued_job["applied_at"] is None, "a never-dispatched job should carry no applied_at"
    assert_sequence_indices_one_based([queued_job])

    response = api.retry_job(queued_job["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    validate_error(response, ApiErrorId.JOB_NOT_RETRYABLE.value, 409)

    job_after = fixtures.read_job(api, queued_job["id"])
    assert_job(job_after, job_state="QUEUED", attempt_count=0, failure_reason=None)
    assert_unchanged(
        queued_job,
        job_after,
        ["job_state", "attempt_count", "failure_reason", "applied_at", "sequence_index", "version"],
        "job",
    )

    batch_after = fixtures.read_batch(api, scenario["second_batch"]["id"])
    assert_batch_counters(
        batch_after,
        batch_state="QUEUED",
        total_jobs=1,
        applied_jobs=0,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert batch_after["dispatched_at"] is None, (
        "a batch that has never been dispatched should carry no dispatched_at"
    )
    assert_unchanged(
        scenario["second_batch"],
        batch_after,
        ["batch_state", "total_jobs", "applied_jobs", "rejected_jobs", "abandoned_jobs", "version"],
        "batch",
    )

    mapping_after = fixtures.read_mapping(api, scenario["mapping"]["id"])
    assert_fields(
        mapping_after, {"last_pushed_rate_cents": DISTRIBUTED_RATE_CENTS}, "mapping"
    )


# ── Batch dispatch ─────────────────────────────────────────────────────────


def test_second_dispatch_of_a_settled_batch_is_refused(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Dispatch is not idempotent. Once the only child job has settled the batch is
    APPLIED with no QUEUED child left, so a second dispatch is refused with
    ERR_BATCH_NOT_DISPATCHABLE at 409, dispatched_at keeps its first value and the
    mapping is not pushed a second time.

    Design: Corner/endpoints/batch_dispatch_is_refused_once_the_batch_has_settled
    """
    mapping = _verified_mapping(api, world)
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=41000)
    batch = fixtures.only_batch(
        api, property_id=world["property_id"], payload_kind="RATE"
    )
    assert_batch_counters(batch, batch_state="QUEUED", total_jobs=1, applied_jobs=0)

    first = api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    dispatched = validate_success(first, 200)
    assert_batch_counters(
        dispatched,
        batch_state="APPLIED",
        total_jobs=1,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_instant_equals(dispatched["dispatched_at"], FIXTURE_CLOCK, "batch.dispatched_at")

    settled = fixtures.read_batch(api, batch["id"])
    mapping_before = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        mapping_before,
        {"last_pushed_rate_cents": DISTRIBUTED_RATE_CENTS, "mapping_state": "VERIFIED"},
        "mapping",
    )

    second = api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    validate_error(second, ApiErrorId.BATCH_NOT_DISPATCHABLE.value, 409)

    batch_after = fixtures.read_batch(api, batch["id"])
    assert_unchanged(
        settled,
        batch_after,
        [
            "batch_state",
            "total_jobs",
            "applied_jobs",
            "rejected_jobs",
            "abandoned_jobs",
            "dispatched_at",
            "updated_at",
            "version",
        ],
        "batch",
    )

    jobs_after = fixtures.jobs_of(api, batch["id"])
    assert len(jobs_after) == 1, f"the batch should still hold one job, got {len(jobs_after)}"
    assert_job(jobs_after[0], job_state="APPLIED", attempt_count=1, failure_reason=None)

    mapping_after = fixtures.read_mapping(api, mapping["id"])
    assert_unchanged(
        mapping_before,
        mapping_after,
        ["last_pushed_rate_cents", "last_push_at", "mismatch_state", "updated_at", "version"],
        "mapping",
    )


# ── Restriction lifting ────────────────────────────────────────────────────

# The closed range the stop-sell covers, comfortably inside the 365-day horizon
# that starts at the fixture clock's date.
RESTRICTION_START = "2026-09-15"
RESTRICTION_END = "2026-09-16"


def _lifted_stop_sell(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """A manual stop-sell on the canonical room type, placed and then lifted."""
    mapping = _verified_mapping(api, world)
    restriction = fixtures.create_restriction(
        api,
        world["room_type_id"],
        "STOP_SELL",
        RESTRICTION_START,
        RESTRICTION_END,
    )
    assert_fields(
        restriction,
        {"origin": "MANUAL", "restriction_state": "ACTIVE", "lifted_at": None, "lift_reason": None},
        "restriction",
    )
    response = api.lift_restriction(restriction["id"], REVENUE_MANAGER_HEADERS)
    lifted = validate_success(response, 200)
    return {"mapping": mapping, "placed": restriction, "lifted": lifted}


def test_manual_lift_records_lifted_at_and_the_manual_lift_reason(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Lifting is not a delete. The row survives as LIFTED with lifted_at at the
    logical clock, lift_reason MANUAL_LIFT, its MANUAL origin and its date range
    intact, and its version bumped once; it simply stops matching an ACTIVE filter.

    Design: Corner/endpoints/restriction_lift_records_the_reason_and_queues_a_second_restriction_batch
    """
    scenario = _lifted_stop_sell(api, world)
    lifted = scenario["lifted"]

    assert_common_fields(lifted, "restriction")
    assert_fields(
        lifted,
        {
            "restriction_state": "LIFTED",
            "lift_reason": "MANUAL_LIFT",
            "origin": "MANUAL",
            "restriction_type": "STOP_SELL",
            "room_type_id": world["room_type_id"],
            "rate_plan_id": None,
            "value_nights": None,
            "start_date": RESTRICTION_START,
            "end_date": RESTRICTION_END,
        },
        "restriction",
    )
    assert_instant_equals(lifted["lifted_at"], FIXTURE_CLOCK, "restriction.lifted_at")
    assert_version(lifted, 2, "restriction")

    reread = validate_success(
        api.get_restriction(scenario["placed"]["id"], REVENUE_MANAGER_HEADERS), 200
    )
    assert_unchanged(
        scenario["placed"],
        reread,
        ["id", "created_at", "room_type_id", "restriction_type", "start_date", "end_date", "origin"],
        "restriction",
    )
    assert_fields(reread, {"restriction_state": "LIFTED", "lift_reason": "MANUAL_LIFT"}, "restriction")

    active_rows, active_meta = validate_paginated(
        api.list_restrictions(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(
                limit=FULL_PAGE, room_type_id=world["room_type_id"], restriction_state="ACTIVE"
            ),
        )
    )
    assert active_rows == [], f"no restriction should still be ACTIVE, got {active_rows}"
    assert_pagination_meta(active_meta, total_count=0, has_more=False)

    all_rows, all_meta = validate_paginated(
        api.list_restrictions(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=FULL_PAGE, room_type_id=world["room_type_id"]),
        )
    )
    assert_pagination_meta(all_meta, total_count=1, has_more=False)
    assert_ids(all_rows, [scenario["placed"]["id"]], "restriction list")


def test_manual_lift_queues_a_second_restriction_batch(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """A lift is itself a distribution event: alongside the batch the placement
    queued, the lift queues a second QUEUED RESTRICTION batch on the same
    restriction, each fanning out one job over the single VERIFIED mapping of the
    room type, with sequence_index numbered from 1 and no payload rate.

    Design: Corner/endpoints/restriction_lift_records_the_reason_and_queues_a_second_restriction_batch
    """
    scenario = _lifted_stop_sell(api, world)
    restriction_id = scenario["placed"]["id"]

    batches = _restriction_batches(api, world)
    assert len(batches) == 2, (
        f"placement and lift should have queued two restriction batches, got {len(batches)}"
    )
    placement_batch, lift_batch = batches
    assert placement_batch["id"] != lift_batch["id"], "the lift should queue a batch of its own"

    for batch in batches:
        assert_fields(
            batch,
            {
                "payload_kind": "RESTRICTION",
                "source_ref_kind": "RESTRICTION",
                "source_ref_id": restriction_id,
                "property_id": world["property_id"],
                "dispatched_at": None,
            },
            "restriction batch",
        )
        assert_batch_counters(
            batch,
            batch_state="QUEUED",
            total_jobs=1,
            applied_jobs=0,
            rejected_jobs=0,
            abandoned_jobs=0,
        )
        jobs = fixtures.jobs_of(api, batch["id"])
        assert len(jobs) == 1, f"the batch should fan out one job, got {len(jobs)}"
        assert_sequence_indices_one_based(jobs)
        assert_job(
            jobs[0],
            job_state="QUEUED",
            attempt_count=0,
            failure_reason=None,
            payload_rate_cents=None,
            channel_mapping_id=scenario["mapping"]["id"],
        )
        assert jobs[0]["payload_kind"] == "RESTRICTION", (
            f"the job should mirror its parent's payload kind, got {jobs[0]['payload_kind']!r}"
        )


# ── Mapping creation ───────────────────────────────────────────────────────

# A second channel on the canonical property, created without any connectivity
# session, so that mapping creation's prerequisite can be observed in isolation.
UNCONNECTED_CHANNEL_CODE = "NOCONN"
UNCONNECTED_COMMISSION_BP = 1500
UNCONNECTED_RATE_CODE = "BAR-NOCONN-KING"


def _unconnected_channel(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """A public OTA on the canonical property that has no connection at all."""
    return fixtures.create_channel(
        api,
        world["property_id"],
        code=UNCONNECTED_CHANNEL_CODE,
        channel_kind="OTA_PUBLIC",
        commission_bp=UNCONNECTED_COMMISSION_BP,
    )


def _unconnected_mapping_payload(
    world: Dict[str, Any], channel: Dict[str, Any]
) -> Dict[str, Any]:
    """The mapping body for that channel, its content matching the master exactly."""
    return factories.mapping_payload(
        world["rate_plan_id"],
        channel["id"],
        world["room_type_id"],
        external_rate_code=UNCONNECTED_RATE_CODE,
        content_description_hash=fixtures.KING_HASH,
        content_image_count=fixtures.KING_IMAGE_COUNT,
    )


def test_mapping_creation_on_a_channel_with_no_connection_is_refused(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Creating a mapping requires the channel to already carry a connectivity
    session. A channel that has none is refused with ERR_CHANNEL_CONNECTION_MISSING
    at 409 and no mapping row is left behind.

    Design: Corner/endpoints/mapping_creation_requires_an_existing_connection_on_the_channel
    """
    channel = _unconnected_channel(api, world)
    assert_fields(
        channel,
        {"code": UNCONNECTED_CHANNEL_CODE, "commission_bp": UNCONNECTED_COMMISSION_BP},
        "channel",
    )

    response = api.create_mapping(
        _unconnected_mapping_payload(world, channel), CHANNEL_OPS_ENGINEER_HEADERS
    )
    validate_error(response, ApiErrorId.CHANNEL_CONNECTION_MISSING.value, 409)

    rows, meta = validate_paginated(
        api.list_mappings(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=FULL_PAGE, channel_id=channel["id"]),
        )
    )
    assert rows == [], f"the refused creation should have left no mapping, got {rows}"
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_mapping_creation_accepts_a_connection_that_is_still_pending(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Only the existence of a connection gates creation; sellability gates
    verification instead. So the very same body that was refused succeeds at 201
    against a connection still sitting in PENDING, and the mapping is born DRAFT
    with an empty surveillance record.

    Design: Corner/endpoints/mapping_creation_requires_an_existing_connection_on_the_channel
    """
    channel = _unconnected_channel(api, world)
    connection = fixtures.create_connection(api, channel["id"])
    assert_fields(
        connection,
        {
            "channel_id": channel["id"],
            "connection_state": "PENDING",
            "consecutive_failures": 0,
            "last_heartbeat_at": None,
            "last_failure_code": None,
            "suspended_at": None,
        },
        "connection",
    )

    response = api.create_mapping(
        _unconnected_mapping_payload(world, channel), CHANNEL_OPS_ENGINEER_HEADERS
    )
    mapping = validate_success(response, 201)
    assert_common_fields(mapping, "mapping")
    assert_fields(
        mapping,
        {
            "rate_plan_id": world["rate_plan_id"],
            "channel_id": channel["id"],
            "room_type_id": world["room_type_id"],
            "external_rate_code": UNCONNECTED_RATE_CODE,
            "mapping_state": "DRAFT",
            "content_description_hash": fixtures.KING_HASH,
            "content_image_count": fixtures.KING_IMAGE_COUNT,
            "parity_state": "IN_PARITY",
            "last_push_at": None,
            "last_pushed_rate_cents": None,
            "observed_rate_cents": None,
            "observed_stay_date": None,
            "mismatch_state": "UNKNOWN",
            "mismatch_delta_cents": None,
        },
        "mapping",
    )
    assert_version(mapping, 1, "mapping")

    rows, meta = validate_paginated(
        api.list_mappings(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=FULL_PAGE, channel_id=channel["id"]),
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert_ids(rows, [mapping["id"]], "mapping list")


# ── Booking pace ───────────────────────────────────────────────────────────

# The clock sits on 2026-08-25, so a target of 2026-09-10 is 6 days to the end of
# August plus 10 days into September: days_out 16.
PACE_TARGET_DATE = "2026-09-10"
PACE_TARGET_DAYS_OUT = 16


def test_pace_derives_as_of_date_and_days_out_from_the_logical_clock(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """The pace read takes no "today" from the caller: as_of_date is the date part of
    the logical clock and days_out is the whole-day distance from it to the target.
    With nothing on the books the rolling baseline is empty, so pace_state is
    NO_BASELINE and pace_index_bp is null.

    Design: Corner/endpoints/pace_read_is_computed_from_the_clock_and_refuses_a_target_that_is_not_in_the_future
    """
    room_type_before = fixtures.read_room_type(api, world["room_type_id"])

    response = api.get_pace(
        world["room_type_id"],
        REVENUE_MANAGER_HEADERS,
        factories.pace_params(PACE_TARGET_DATE),
    )
    pace = validate_success(response, 200)
    assert_pace(
        pace,
        {
            "room_type_id": world["room_type_id"],
            "target_stay_date": PACE_TARGET_DATE,
            "baseline": "ROLLING",
            "as_of_date": fixtures.FIXTURE_TODAY,
            "days_out": PACE_TARGET_DAYS_OUT,
            "target_room_nights": 0,
            "baseline_room_nights": 0,
            "pace_index_bp": None,
            "pace_state": "NO_BASELINE",
        },
    )

    room_type_after = fixtures.read_room_type(api, world["room_type_id"])
    assert_unchanged(
        room_type_before,
        room_type_after,
        ["physical_capacity_units", "effective_overbooking_pct_bp", "updated_at", "version"],
        "room type",
    )


def test_pace_refuses_a_target_that_is_not_strictly_in_the_future(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """days_out is at least 1, so the clock's own date is not a legal target: a
    target_stay_date equal to as_of_date is refused with ERR_ANALYTICS_WINDOW_INVALID
    at 422 rather than reported as a pace of zero days out.

    Design: Corner/endpoints/pace_read_is_computed_from_the_clock_and_refuses_a_target_that_is_not_in_the_future
    """
    response = api.get_pace(
        world["room_type_id"],
        REVENUE_MANAGER_HEADERS,
        factories.pace_params(fixtures.FIXTURE_TODAY),
    )
    validate_error(response, ApiErrorId.ANALYTICS_WINDOW_INVALID.value, 422)

    earlier = api.get_pace(
        world["room_type_id"],
        REVENUE_MANAGER_HEADERS,
        factories.pace_params(fixtures.date_offset(fixtures.FIXTURE_TODAY, -1)),
    )
    validate_error(earlier, ApiErrorId.ANALYTICS_WINDOW_INVALID.value, 422)


# ── The logical clock ──────────────────────────────────────────────────────


def test_setting_the_clock_modifies_no_stored_row(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Moving the clock only echoes the instant it was given. Rows written before the
    move keep their own created_at and updated_at and their versions do not move, so
    the clock is a reading of the present, not a rewrite of the past.

    Design: Corner/endpoints/clock_set_moves_every_later_timestamp_without_touching_stored_rows
    """
    property_before = fixtures.read_property(api, world["property_id"])
    room_type_before = fixtures.read_room_type(api, world["room_type_id"])
    assert_instant_equals(property_before["created_at"], FIXTURE_CLOCK, "property.created_at")
    assert_version(property_before, 1, "property")

    response = api.set_clock(factories.clock_payload(MOVED_CLOCK), PLATFORM_ADMIN_HEADERS)
    echo = validate_success(response, 200)
    assert_instant_equals(echo["current_utc"], MOVED_CLOCK, "clock.current_utc")

    property_after = fixtures.read_property(api, world["property_id"])
    assert_unchanged(
        property_before,
        property_after,
        [
            "id",
            "code",
            "name",
            "overbooking_pct_bp",
            "booking_horizon_days",
            "mix_window_days",
            "rate_mismatch_tolerance_cents",
            "required_image_count",
            "created_at",
            "updated_at",
            "version",
        ],
        "property",
    )

    room_type_after = fixtures.read_room_type(api, world["room_type_id"])
    assert_unchanged(
        room_type_before,
        room_type_after,
        [
            "id",
            "code",
            "name",
            "physical_capacity_units",
            "master_description_hash",
            "master_image_count",
            "created_at",
            "updated_at",
            "version",
        ],
        "room type",
    )


def test_rows_written_after_the_clock_move_carry_the_later_instant(
    api: ApiClient, world: Dict[str, Any]
) -> None:
    """Every instant the server stamps comes from the logical clock, so a row created
    after the move carries the moved instant as both its created_at and its
    updated_at, and the pace read now measures its distances from the moved date.

    Design: Corner/endpoints/clock_set_moves_every_later_timestamp_without_touching_stored_rows
    """
    fixtures.set_clock(api, MOVED_CLOCK)

    later_room_type = fixtures.create_room_type(
        api, world["property_id"], code="QUEEN", name="Queen Room"
    )
    assert_common_fields(later_room_type, "room type")
    assert_instant_equals(later_room_type["created_at"], MOVED_CLOCK, "room type.created_at")
    assert_instant_equals(later_room_type["updated_at"], MOVED_CLOCK, "room type.updated_at")
    assert_version(later_room_type, 1, "room type")

    # One day past the moved clock's date, so days_out is exactly 1.
    next_day = fixtures.date_offset(MOVED_CLOCK_DATE, 1)
    pace = validate_success(
        api.get_pace(
            later_room_type["id"], REVENUE_MANAGER_HEADERS, factories.pace_params(next_day)
        ),
        200,
    )
    assert_pace(
        pace,
        {
            "room_type_id": later_room_type["id"],
            "target_stay_date": next_day,
            "baseline": "ROLLING",
            "as_of_date": MOVED_CLOCK_DATE,
            "days_out": 1,
        },
    )
