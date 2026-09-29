"""Three kinds of interval that share a resource and disagree about what "overlap"
means: restriction date ranges are closed and mutually exclusive within one scope
key, allotment date ranges may overlap each other freely and are policed only by
an aggregate per-date ceiling, and connectivity freeze windows are half-open
instant intervals widened an hour earlier than announced by a pre-buffer. Each
module test pairs an interval that must be refused with the adjacent interval that
must go the other way.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    MAX_PAGE_LIMIT,
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_batch_counters,
    assert_create_only_fields,
    assert_field_set,
    assert_fields,
    assert_id_set,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_version,
)
from test_helpers import factories, fixtures

# The five September stay dates the interval scenarios are built on.
SEP_10 = fixtures.STAY_DATE
SEP_11 = fixtures.STAY_DATE_2
SEP_12 = fixtures.STAY_DATE_3
SEP_13 = fixtures.STAY_DATE_4
SEP_14 = fixtures.date_offset(fixtures.STAY_DATE, 4)


def _active_restrictions_page(api, room_type_id):
    """The ACTIVE restrictions of one room type, as rows plus the page meta."""
    params = factories.page_params(
        limit=MAX_PAGE_LIMIT,
        room_type_id=room_type_id,
        restriction_state="ACTIVE",
    )
    return validate_paginated(api.list_restrictions(REVENUE_MANAGER_HEADERS, params))


def test_restrictions_sharing_one_date_on_the_same_scope_key_are_refused(api, world):
    """Restriction windows are closed intervals holding both endpoints, so a second
    MIN_STAY on the same room type, plan scope and origin that reuses the first
    window's end date overlaps it and is refused with ERR_RESTRICTION_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/restriction_closed_date_ranges_are_mutually_exclusive_per_scope_key
    """
    first = fixtures.create_restriction(
        api,
        world["room_type_id"],
        "MIN_STAY",
        SEP_10,
        SEP_12,
        value_nights=2,
    )
    assert_fields(
        first,
        {
            "restriction_type": "MIN_STAY",
            "start_date": SEP_10,
            "end_date": SEP_12,
            "value_nights": 2,
            "rate_plan_id": None,
            "origin": "MANUAL",
            "restriction_state": "ACTIVE",
            "lifted_at": None,
            "lift_reason": None,
        },
        "restriction",
    )

    # 2026-09-12 is the closed end of the first window and the closed start of the
    # second, so the two ranges share a date and the scope key is identical.
    validate_error(
        api.create_restriction(
            factories.min_stay_payload(
                room_type_id=world["room_type_id"],
                start_date=SEP_12,
                end_date=SEP_14,
                value_nights=3,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        ApiErrorId.RESTRICTION_WINDOW_OVERLAP.value,
        409,
    )

    rows, meta = _active_restrictions_page(api, world["room_type_id"])
    assert meta["total_count"] == 1, (
        f"the refused placement must create nothing, got {meta['total_count']} rows"
    )
    assert_id_set(rows, [first["id"]], "active restrictions")

    surviving = fixtures.read_restriction(api, first["id"])
    assert_version(surviving, 1, "restriction")
    assert_fields(surviving, {"restriction_state": "ACTIVE"}, "restriction")


def test_adjacent_restriction_windows_on_the_same_scope_key_are_accepted(api, world):
    """Adjacency is not overlap: a second MIN_STAY on the identical scope key that
    starts the day after the first window's closed end shares no date with it and is
    accepted, leaving two ACTIVE restrictions on the room type.

    Design: Difficulty/resource_temporal_overlap/restriction_closed_date_ranges_are_mutually_exclusive_per_scope_key
    """
    first = fixtures.create_restriction(
        api, world["room_type_id"], "MIN_STAY", SEP_10, SEP_12, value_nights=2
    )

    # 2026-09-13 is the day after the first window's closed end of 2026-09-12.
    second = validate_success(
        api.create_restriction(
            factories.min_stay_payload(
                room_type_id=world["room_type_id"],
                start_date=SEP_13,
                end_date=SEP_14,
                value_nights=3,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        second,
        {
            "restriction_type": "MIN_STAY",
            "start_date": SEP_13,
            "end_date": SEP_14,
            "value_nights": 3,
            "rate_plan_id": None,
            "origin": "MANUAL",
            "restriction_state": "ACTIVE",
        },
        "restriction",
    )

    rows, meta = _active_restrictions_page(api, world["room_type_id"])
    assert meta["total_count"] == 2, (
        f"both adjacent windows should stand, got {meta['total_count']} rows"
    )
    assert_id_set(rows, [first["id"], second["id"]], "active restrictions")


def test_the_same_restriction_dates_are_free_again_under_a_different_scope_key(api, world):
    """The exclusion is keyed on room_type_id, rate_plan_id, restriction_type and
    origin together, so the identical closed range is accepted again once any one
    part of that key differs -- narrowed to a single plan, or placed as a different
    restriction type, which then carries no value_nights at all.

    Design: Difficulty/resource_temporal_overlap/restriction_closed_date_ranges_are_mutually_exclusive_per_scope_key
    """
    unscoped = fixtures.create_restriction(
        api, world["room_type_id"], "MIN_STAY", SEP_10, SEP_12, value_nights=2
    )
    assert_fields(unscoped, {"rate_plan_id": None}, "restriction")

    # Same dates, same type, same origin -- but scoped to one plan, so a new key.
    plan_scoped = validate_success(
        api.create_restriction(
            factories.min_stay_payload(
                room_type_id=world["room_type_id"],
                start_date=SEP_10,
                end_date=SEP_12,
                value_nights=2,
                rate_plan_id=world["rate_plan_id"],
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        plan_scoped,
        {
            "rate_plan_id": world["rate_plan_id"],
            "restriction_type": "MIN_STAY",
            "start_date": SEP_10,
            "end_date": SEP_12,
            "value_nights": 2,
            "origin": "MANUAL",
            "restriction_state": "ACTIVE",
        },
        "restriction",
    )

    # Same dates, same unscoped plan -- but a different restriction type.
    other_type = validate_success(
        api.create_restriction(
            factories.closed_to_arrival_payload(
                room_type_id=world["room_type_id"],
                start_date=SEP_10,
                end_date=SEP_12,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        other_type,
        {
            "restriction_type": "CLOSED_TO_ARRIVAL",
            "rate_plan_id": None,
            "start_date": SEP_10,
            "end_date": SEP_12,
            "value_nights": None,
            "origin": "MANUAL",
            "restriction_state": "ACTIVE",
        },
        "restriction",
    )

    rows, meta = _active_restrictions_page(api, world["room_type_id"])
    assert meta["total_count"] == 3, (
        f"three distinct scope keys should coexist, got {meta['total_count']} rows"
    )
    assert_id_set(
        rows,
        [unscoped["id"], plan_scoped["id"], other_type["id"]],
        "active restrictions",
    )


def _open_four_nights_and_three_channels(api, world):
    """Nights 2026-09-10 through 09-13 open on KING, plus a brand and an opaque channel."""
    fixtures.open_inventory_range(api, world["room_type_id"], SEP_10, SEP_13)
    brand = fixtures.create_brand_channel(api, world["property_id"])
    opaque = fixtures.create_opaque_channel(api, world["property_id"])
    return {
        "ota_channel_id": world["channel_id"],
        "brand_channel_id": brand["channel"]["id"],
        "opaque_channel_id": opaque["channel"]["id"],
    }


def _carve_the_overlapping_pair(api, world, channels):
    """Six units 09-10..09-12 for OTA1 and five 09-11..09-13 for BRAND.

    The two ranges overlap on 09-11 and 09-12, where the held total reaches
    6 + 5 = 11, exactly the ceiling of 10 + floor(10 x 1000 / 10000) = 11.
    """
    ota = fixtures.create_allocation(
        api, world["room_type_id"], channels["ota_channel_id"], 6, SEP_10, SEP_12
    )
    brand = fixtures.create_allocation(
        api, world["room_type_id"], channels["brand_channel_id"], 5, SEP_11, SEP_13
    )
    return ota, brand


def test_overlapping_allotments_are_accepted_up_to_the_aggregate_ceiling(api, world):
    """Overlapping allotments are legal, and the guard is an aggregate per-date sum
    rather than a pairwise test: two ranges that overlap on two nights are both
    accepted because the held total there lands exactly on the ceiling, which
    exhausts the shared pool on those nights and leaves the others open.

    Design: Difficulty/resource_temporal_overlap/allotment_ranges_may_overlap_freely_until_the_aggregate_ceiling_binds
    """
    channels = _open_four_nights_and_three_channels(api, world)
    version_before = fixtures.room_type_version(api, world["room_type_id"])

    ota, brand = _carve_the_overlapping_pair(api, world, channels)
    assert_fields(
        ota,
        {
            "channel_id": channels["ota_channel_id"],
            "allocated_units": 6,
            "start_date": SEP_10,
            "end_date": SEP_12,
            "consumed_units": 0,
            "allocation_state": "OPEN",
            "superseded_at": None,
            "recalled_at": None,
        },
        "allotment",
    )
    assert_fields(
        brand,
        {
            "channel_id": channels["brand_channel_id"],
            "allocated_units": 5,
            "start_date": SEP_11,
            "end_date": SEP_13,
            "consumed_units": 0,
            "allocation_state": "OPEN",
        },
        "allotment",
    )

    # Each accepted allotment spends the echo by bumping the room type once.
    assert fixtures.room_type_version(api, world["room_type_id"]) == version_before + 2

    def day(stay_date):
        return fixtures.inventory_day_on(api, world["room_type_id"], stay_date)

    # 09-10: only OTA1 holds -> 6 held, 5 of pool left, 6 < 10 so still OPEN.
    assert_inventory_day(
        day(SEP_10),
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=6,
        committed=0,
        shared=5,
        pooled_state="OPEN",
    )
    # 09-11 and 09-12: both hold -> 11 held, pool exactly 0, so EXHAUSTED wins.
    for overlapped in (SEP_11, SEP_12):
        assert_inventory_day(
            day(overlapped),
            ceiling=fixtures.KING_CEILING,
            allocated=11,
            committed=0,
            shared=0,
            pooled_state="EXHAUSTED",
        )
    # 09-13: only BRAND holds -> 5 held, 6 of pool left, OPEN again.
    assert_inventory_day(
        day(SEP_13),
        ceiling=fixtures.KING_CEILING,
        allocated=5,
        committed=0,
        shared=6,
        pooled_state="OPEN",
    )


def test_a_third_allotment_is_refused_only_on_the_night_where_the_ceiling_binds(api, world):
    """The aggregate check runs per date, so one further unit is refused with
    ERR_ALLOCATION_EXCEEDS_CEILING on the saturated night and accepted on the night
    of the very same overlap family that still has pool -- and the refusal creates
    nothing at all, not even a version bump on the room type.

    Design: Difficulty/resource_temporal_overlap/allotment_ranges_may_overlap_freely_until_the_aggregate_ceiling_binds
    """
    channels = _open_four_nights_and_three_channels(api, world)
    _carve_the_overlapping_pair(api, world, channels)
    version_after_pair = fixtures.room_type_version(api, world["room_type_id"])

    # 09-12 already holds 11 of an 11 ceiling: 11 + 0 committed + 1 = 12 > 11.
    validate_error(
        api.create_allocation(
            world["room_type_id"],
            factories.allocation_payload(
                channel_id=channels["opaque_channel_id"],
                allocated_units=1,
                start_date=SEP_12,
                end_date=SEP_12,
                expected_room_type_version=version_after_pair,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        ApiErrorId.ALLOCATION_EXCEEDS_CEILING.value,
        409,
    )
    assert fixtures.room_type_version(api, world["room_type_id"]) == version_after_pair, (
        "a refused allotment must not spend the room type's version echo"
    )
    assert (
        fixtures.list_allocations(api, channel_id=channels["opaque_channel_id"]) == []
    ), "a refused allotment must not create a row"
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], SEP_12),
        allocated=11,
        committed=0,
        shared=0,
        pooled_state="EXHAUSTED",
    )

    # 09-10 holds only 6 of the same 11 ceiling: 6 + 0 committed + 1 = 7, accepted.
    accepted = fixtures.create_allocation(
        api, world["room_type_id"], channels["opaque_channel_id"], 1, SEP_10, SEP_10
    )
    assert_fields(
        accepted,
        {
            "channel_id": channels["opaque_channel_id"],
            "allocated_units": 1,
            "start_date": SEP_10,
            "end_date": SEP_10,
            "consumed_units": 0,
            "allocation_state": "OPEN",
        },
        "allotment",
    )
    assert fixtures.room_type_version(api, world["room_type_id"]) == version_after_pair + 1
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], SEP_10),
        allocated=7,
        committed=0,
        shared=4,
        pooled_state="OPEN",
    )


# One freeze day, three declared windows, and the buffered starts they imply.
# The pre-buffer is sixty minutes, so a window announced for 10:00 already blocks
# from 09:00, and the blocking interval runs to ends_at exclusive.
_FREEZE_DAY = "2026-08-26"
_FW1_START = fixtures.instant(_FREEZE_DAY, "10:00:00.000")
_FW1_END = fixtures.instant(_FREEZE_DAY, "12:00:00.000")
_FW1_EFFECTIVE = fixtures.instant(_FREEZE_DAY, "09:00:00.000")
_FW2_START = fixtures.instant(_FREEZE_DAY, "12:30:00.000")
_FW2_END = fixtures.instant(_FREEZE_DAY, "13:30:00.000")
_FW3_START = fixtures.instant(_FREEZE_DAY, "13:00:00.000")
_FW3_END = fixtures.instant(_FREEZE_DAY, "14:00:00.000")
_FW3_EFFECTIVE = fixtures.instant(_FREEZE_DAY, "12:00:00.000")

# A freeze window is immutable: no updated_at and no version.
_FREEZE_WINDOW_FIELDS = (
    "id",
    "created_at",
    "connection_id",
    "starts_at",
    "ends_at",
    "reason",
    "effective_starts_at",
)


def _declare_window(api, connection_id, starts_at, ends_at, reason=factories.OMIT):
    return api.create_freeze_window(
        connection_id,
        factories.freeze_window_payload(starts_at, ends_at, reason),
        CHANNEL_OPS_ENGINEER_HEADERS,
    )


def _freeze_window_page(api, connection_id):
    return validate_paginated(
        api.list_freeze_windows(
            connection_id, REVENUE_MANAGER_HEADERS, factories.page_params(limit=MAX_PAGE_LIMIT)
        )
    )


def test_a_freeze_window_whose_buffered_start_falls_inside_a_live_window_is_refused(api, world):
    """Overlap is judged on the buffered interval, not the announced one: a window
    declared for 12:30 is effectively live from 11:30, which sits inside the first
    window's [09:00, 12:00), so it is refused with ERR_FREEZE_WINDOW_OVERLAP even
    though the two announced intervals do not touch.

    Design: Difficulty/resource_temporal_overlap/freeze_windows_are_half_open_instants_widened_by_a_pre_buffer
    """
    first = validate_success(
        _declare_window(api, world["connection_id"], _FW1_START, _FW1_END), 201
    )
    assert_fields(
        first,
        {"connection_id": world["connection_id"], "reason": "MAINTENANCE"},
        "freeze window",
    )
    assert_instant_equals(first["starts_at"], _FW1_START, "freeze window.starts_at")
    assert_instant_equals(first["ends_at"], _FW1_END, "freeze window.ends_at")
    # 10:00 announced minus the sixty-minute pre-buffer is 09:00.
    assert_instant_equals(
        first["effective_starts_at"], _FW1_EFFECTIVE, "freeze window.effective_starts_at"
    )
    assert_create_only_fields(first, "freeze window")
    assert_field_set(first, _FREEZE_WINDOW_FIELDS, "freeze window")

    validate_error(
        _declare_window(
            api, world["connection_id"], _FW2_START, _FW2_END, reason="CERTIFICATION"
        ),
        ApiErrorId.FREEZE_WINDOW_OVERLAP.value,
        409,
    )

    rows, meta = _freeze_window_page(api, world["connection_id"])
    assert meta["total_count"] == 1, (
        f"the refused declaration must create nothing, got {meta['total_count']} rows"
    )
    assert_id_set(rows, [first["id"]], "freeze windows")


def test_a_freeze_window_whose_buffered_start_meets_the_exclusive_end_is_accepted(api, world):
    """The blocking interval is half open, so a second window whose buffered start
    is exactly the first window's exclusive end touches it without overlapping and
    is accepted, leaving two back-to-back windows on the one connection.

    Design: Difficulty/resource_temporal_overlap/freeze_windows_are_half_open_instants_widened_by_a_pre_buffer
    """
    first = validate_success(
        _declare_window(api, world["connection_id"], _FW1_START, _FW1_END), 201
    )
    assert_instant_equals(
        first["effective_starts_at"], _FW1_EFFECTIVE, "freeze window.effective_starts_at"
    )

    # 13:00 announced minus the pre-buffer is 12:00, the first window's exclusive end.
    second = validate_success(
        _declare_window(api, world["connection_id"], _FW3_START, _FW3_END, reason="INCIDENT"),
        201,
    )
    assert_fields(second, {"reason": "INCIDENT"}, "freeze window")
    assert_instant_equals(second["starts_at"], _FW3_START, "freeze window.starts_at")
    assert_instant_equals(second["ends_at"], _FW3_END, "freeze window.ends_at")
    assert_instant_equals(
        second["effective_starts_at"], _FW3_EFFECTIVE, "freeze window.effective_starts_at"
    )
    assert_create_only_fields(second, "freeze window")

    rows, meta = _freeze_window_page(api, world["connection_id"])
    assert meta["total_count"] == 2, (
        f"two touching windows should both stand, got {meta['total_count']} rows"
    )
    assert_id_set(rows, [first["id"], second["id"]], "freeze windows")


def test_dispatch_is_frozen_across_the_buffered_interval_and_released_at_its_end(api, world):
    """The buffered interval is what actually blocks distribution: a queued rate
    batch is refused with ERR_CONNECTION_FROZEN at the buffered start of the first
    window and again at the buffered start of the touching second window, is left
    completely untouched by both refusals, and is applied once the clock reaches the
    second window's exclusive end.

    Design: Difficulty/resource_temporal_overlap/freeze_windows_are_half_open_instants_widened_by_a_pre_buffer
    """
    mapping = fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code="BAR_OTA1_KING",
    )
    assert_fields(
        mapping,
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY", "last_push_at": None},
        "mapping",
    )

    # Lifting the ceiling to 41000 queues a rate batch; the distributed rate itself
    # is unchanged at 25000 x (10000 + 0) / 10000 = 25000, still inside the band.
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], ceiling_amount_cents=41000)
    batch = fixtures.only_batch(api)
    assert_fields(
        batch,
        {
            "payload_kind": "RATE",
            "source_ref_kind": "RATE_PLAN",
            "source_ref_id": world["rate_plan_id"],
            "dispatched_at": None,
        },
        "batch",
    )
    assert_batch_counters(
        batch, batch_state="QUEUED", total_jobs=1, applied_jobs=0, rejected_jobs=0
    )
    job = fixtures.jobs_of(api, batch["id"])[0]
    assert_job(job, job_state="QUEUED", attempt_count=0, channel_mapping_id=mapping["id"])
    assert job["sequence_index"] == 1, "fan-out numbers the first child 1"

    validate_success(_declare_window(api, world["connection_id"], _FW1_START, _FW1_END), 201)
    validate_success(_declare_window(api, world["connection_id"], _FW3_START, _FW3_END), 201)

    # 09:00 is the first window's buffered start, and the start is inclusive.
    fixtures.set_clock(api, _FW1_EFFECTIVE)
    validate_error(
        api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CONNECTION_FROZEN.value,
        409,
    )

    # 12:00 is past the first window's exclusive end, but it is exactly the second
    # window's buffered start, so the connection is still frozen.
    fixtures.set_clock(api, _FW3_EFFECTIVE)
    validate_error(
        api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CONNECTION_FROZEN.value,
        409,
    )

    frozen_batch = fixtures.read_batch(api, batch["id"])
    assert_batch_counters(
        frozen_batch,
        batch_state="QUEUED",
        total_jobs=1,
        applied_jobs=0,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_fields(frozen_batch, {"dispatched_at": None}, "batch")
    frozen_job = fixtures.read_job(api, job["id"])
    assert_job(frozen_job, job_state="QUEUED", attempt_count=0, failure_reason=None)
    assert frozen_job["applied_at"] is None, "a frozen dispatch must apply nothing"

    # 14:00 is the second window's exclusive end, so the thaw is immediate.
    fixtures.set_clock(api, _FW3_END)
    dispatched = validate_success(
        api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_batch_counters(
        dispatched,
        batch_state="APPLIED",
        total_jobs=1,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_instant_equals(dispatched["dispatched_at"], _FW3_END, "batch.dispatched_at")

    applied_job = fixtures.read_job(api, job["id"])
    assert_job(applied_job, job_state="APPLIED", attempt_count=1, failure_reason=None)
    assert_instant_equals(applied_job["applied_at"], _FW3_END, "job.applied_at")

    pushed = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        pushed,
        {
            "last_pushed_rate_cents": fixtures.BAR_BASE_CENTS,
            "mismatch_state": "UNKNOWN",  # nothing observed yet, so no verdict
            "mismatch_delta_cents": None,
        },
        "mapping",
    )
    assert_instant_equals(pushed["last_push_at"], _FW3_END, "mapping.last_push_at")
