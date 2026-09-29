"""Transitive cascades of the Hotel Channel Distribution contract.

One accepted write in this contract can travel a long way. A single rejected
distribution job suspends a connection, which recalls that channel's allotments
and recomputes the nights they held; an oversold night queues guard stop-sells
that a later cancellation lifts again; and one patch to a root rate plan
re-derives a whole chain of children before fanning out to the mappings that
actually carry the product. These tests follow each chain to its end, and pin
what the chain must leave alone.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_batch_counters,
    assert_channel_ledger,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_reservation_totals,
    assert_sequence_indices_one_based,
    assert_unchanged,
    assert_version,
    find_by,
)
from test_helpers import fixtures

# One night of the canonical public plan on the canonical OTA:
# 25000 x (10000 + 0) / 10000 = 25000, inside [18000, 40000], plus 0 inclusion.
NIGHTLY_SELL_CENTS = 25000
# 25000 x 1750 / 10000 = 4375, so the net is 25000 - 4375 = 20625.
NIGHTLY_COMMISSION_CENTS = 4375
NIGHTLY_NET_CENTS = 20625
# The repriced rate card used by the rejection scenarios.
REPRICED_BASE_CENTS = 26000


def _mapping_out_of_parity(api, rate_plan_id, channel_id, room_type_id):
    """A VERIFIED mapping knocked out of parity by dropping one image."""
    mapping = fixtures.create_verified_mapping(api, rate_plan_id, channel_id, room_type_id)
    fixtures.patch_mapping_content(api, mapping["id"], content_image_count=4)
    broken = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        broken,
        {"mapping_state": "VERIFIED", "parity_state": "OUT_OF_PARITY"},
        "mapping with thin content",
    )
    return broken


# ── A rejected job, a suspended connection, a recalled allotment ───────────


def test_one_rejection_cascades_through_connection_allotment_and_inventory(api, world):
    """A single parity-blocked job rejection is the head of the deepest chain in the
    contract: it errors the mapping, carries the connection to its third failure and
    suspends it, recalls that channel's allotment, and recomputes the night the
    allotment held so the released units land back in the shared pool.

    Design: Difficulty/transitive_cascade/job_rejection_suspends_connection_recalls_allotment_and_recomputes_inventory
    """
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    mapping = _mapping_out_of_parity(
        api, world["rate_plan_id"], world["channel_id"], world["room_type_id"]
    )
    allotment = fixtures.create_allocation(
        api,
        world["room_type_id"],
        world["channel_id"],
        4,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    assert_fields(
        allotment,
        {"allocation_state": "OPEN", "consumed_units": 0, "recalled_at": None},
        "allotment",
    )
    # 10 rooms at a 10% allowance: ceiling 11, of which 4 are held for the channel.
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        capacity=10,
        ceiling=11,
        allocated=4,
        committed=0,
        shared=7,
        pooled_state="OPEN",
    )

    # Park the connection one failure short of suspension, then queue the push.
    fixtures.fail_connection(api, world["connection_id"], times=2, failure_code="TIMEOUT")
    assert_fields(
        fixtures.read_connection(api, world["connection_id"]),
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "connection before the dispatch",
    )
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], base_amount_cents=REPRICED_BASE_CENTS)
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    assert_fields(
        batch,
        {"source_ref_kind": "RATE_PLAN", "source_ref_id": world["rate_plan_id"], "total_jobs": 1},
        "rate batch",
    )
    jobs = fixtures.jobs_of(api, batch["id"])
    assert_sequence_indices_one_based(jobs)
    assert_job(jobs[0], job_state="QUEUED", attempt_count=0, channel_mapping_id=mapping["id"])

    # One dispatch call, and every hop of the chain below is a consequence of it.
    settled = validate_success(api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_batch_counters(
        settled,
        batch_state="FAILED",
        total_jobs=1,
        applied_jobs=0,
        rejected_jobs=1,
        abandoned_jobs=0,
    )

    # Hop 1: the job itself.
    rejected_job = fixtures.read_job(api, jobs[0]["id"])
    assert_job(
        rejected_job, job_state="REJECTED", attempt_count=1, failure_reason="PARITY_BLOCKED"
    )
    assert rejected_job["applied_at"] is None, (
        f"a rejected job leaves applied_at null, got {rejected_job['applied_at']!r}"
    )

    # Hop 2: the mapping loses its verification and keeps no pushed rate.
    errored = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        errored,
        {"mapping_state": "ERRORED", "last_pushed_rate_cents": None, "last_push_at": None},
        "mapping after the rejection",
    )

    # Hop 3: the third consecutive failure suspends the connection.
    suspended = fixtures.read_connection(api, world["connection_id"])
    assert_fields(
        suspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "MAPPING_REJECTED",
        },
        "connection after the rejection",
    )
    assert_instant_equals(
        suspended["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )

    # Hop 4: the suspension recalls the channel's allotment.
    recalled = fixtures.read_allocation(api, allotment["id"])
    assert_fields(recalled, {"allocation_state": "RECALLED"}, "allotment after the suspension")
    assert_instant_equals(
        recalled["recalled_at"], fixtures.FIXTURE_CLOCK, "allocation.recalled_at"
    )

    # Hop 5: the recall gives the held units back to the shared pool.
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        capacity=10,
        ceiling=11,
        allocated=0,
        committed=0,
        shared=11,
        pooled_state="OPEN",
    )

    # The night never went oversold, so the chain stops here: no guard, no new batch.
    assert fixtures.list_restrictions(api, room_type_id=world["room_type_id"]) == [], (
        "a night that was never OVERSOLD has no guard restriction to lift"
    )
    assert [row["id"] for row in fixtures.list_batches(api, property_id=world["property_id"])] == [
        batch["id"]
    ], "the cascade should not queue any further batch"


def test_the_suspension_cascade_spares_the_other_channel_and_its_dates(api, world):
    """The chain is scoped to the channel that failed and to the dates its allotment
    covered: a second channel's job in the same dispatch still applies, its connection
    stays healthy, its allotment keeps its units, and the night outside the recalled
    window is not recomputed at all.

    Design: Difficulty/transitive_cascade/job_rejection_suspends_connection_recalls_allotment_and_recomputes_inventory
    """
    room_type_id = world["room_type_id"]
    fixtures.open_inventory_days(api, room_type_id, [fixtures.STAY_DATE, fixtures.STAY_DATE_2])
    ota_mapping = _mapping_out_of_parity(
        api, world["rate_plan_id"], world["channel_id"], room_type_id
    )
    brand = fixtures.create_brand_channel(api, world["property_id"])
    brand_mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], brand["channel"]["id"], room_type_id
    )
    ota_allotment = fixtures.create_allocation(
        api, room_type_id, world["channel_id"], 4, fixtures.STAY_DATE, fixtures.STAY_DATE
    )
    brand_allotment = fixtures.create_allocation(
        api, room_type_id, brand["channel"]["id"], 3, fixtures.STAY_DATE_2, fixtures.STAY_DATE_2
    )
    fixtures.fail_connection(api, world["connection_id"], times=2, failure_code="TIMEOUT")
    fixtures.reprice_rate_plan(api, world["rate_plan_id"], base_amount_cents=REPRICED_BASE_CENTS)
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    assert_fields(batch, {"total_jobs": 2}, "rate batch over two channels")

    untouched_night_before = fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE_2)
    settled = validate_success(api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_batch_counters(
        settled,
        batch_state="PARTIALLY_APPLIED",
        total_jobs=2,
        applied_jobs=1,
        rejected_jobs=1,
        abandoned_jobs=0,
    )

    jobs = fixtures.jobs_of(api, batch["id"])
    assert_sequence_indices_one_based(jobs)
    assert_job(
        find_by(jobs, channel_mapping_id=ota_mapping["id"]),
        job_state="REJECTED",
        attempt_count=1,
        failure_reason="PARITY_BLOCKED",
    )
    # 26000 x (10000 + 0) / 10000 = 26000, inside [18000, 40000], plus 0 inclusion.
    assert_job(
        find_by(jobs, channel_mapping_id=brand_mapping["id"]),
        job_state="APPLIED",
        attempt_count=1,
        failure_reason=None,
        payload_rate_cents=REPRICED_BASE_CENTS,
    )

    # The chain did run on the failing channel.
    assert_fields(
        fixtures.read_connection(api, world["connection_id"]),
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        "failing connection",
    )
    assert_fields(
        fixtures.read_allocation(api, ota_allotment["id"]),
        {"allocation_state": "RECALLED"},
        "allotment of the suspended channel",
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE),
        allocated=0,
        committed=0,
        shared=11,
        pooled_state="OPEN",
    )

    # And it stopped at the channel boundary.
    assert_fields(
        fixtures.read_connection(api, brand["connection"]["id"]),
        {
            "connection_state": "HEALTHY",
            "consecutive_failures": 0,
            "last_failure_code": None,
            "suspended_at": None,
        },
        "connection of the channel that applied",
    )
    assert_fields(
        fixtures.read_mapping(api, brand_mapping["id"]),
        {
            "mapping_state": "VERIFIED",
            "parity_state": "IN_PARITY",
            "last_pushed_rate_cents": REPRICED_BASE_CENTS,
        },
        "mapping of the channel that applied",
    )
    assert_unchanged(
        brand_allotment,
        fixtures.read_allocation(api, brand_allotment["id"]),
        ["allocation_state", "consumed_units", "recalled_at", "version", "updated_at"],
        "allotment of the untouched channel",
    )
    # The night outside the recalled window keeps its 3 held units and its posture:
    # ceiling 11 = 3 held + 0 committed + 8 shared, and 3 is short of capacity 10.
    untouched_night_after = fixtures.inventory_day_on(api, room_type_id, fixtures.STAY_DATE_2)
    assert_inventory_day(
        untouched_night_after,
        capacity=10,
        ceiling=11,
        allocated=3,
        committed=0,
        shared=8,
        pooled_state="OPEN",
    )
    assert_unchanged(
        untouched_night_before,
        untouched_night_after,
        ["allocated_units", "committed_units", "shared_pool_units", "pooled_state", "version"],
        "night outside the recalled window",
    )

    # No night went oversold, so no guard and no further batch anywhere.
    assert fixtures.list_restrictions(api, room_type_id=room_type_id) == [], (
        "no night reached OVERSOLD, so no guard restriction should exist"
    )
    assert [row["id"] for row in fixtures.list_batches(api, property_id=world["property_id"])] == [
        batch["id"]
    ], "the cascade should not queue any further batch"


# ── An oversold night, its guard, and the cancellation that clears it ───────


def _oversellable_twin(api, world, extra_nights=()):
    """A two-room type at a 50% allowance, mapped and open for business.

    The ceiling is 2 + floor(2 x 5000 / 10000) = 3, so the third confirmed night
    is the one that lands beyond physical capacity.
    """
    twin = fixtures.create_twin_room_type(api, world["property_id"])
    fixtures.open_inventory_days(api, twin["id"], [fixtures.STAY_DATE, *extra_nights])
    mapping = fixtures.create_verified_mapping(
        api, world["rate_plan_id"], world["channel_id"], twin["id"]
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=0,
        shared=3,
        pooled_state="OPEN",
    )
    return twin, mapping


def _book_one_night(api, world, room_type_id, **overrides):
    """One night on the canonical OTA, in the single geo market it serves."""
    return fixtures.create_reservation(
        api,
        world["channel_id"],
        world["rate_plan_id"],
        room_type_id,
        arrival_date=fixtures.STAY_DATE,
        nights=1,
        geo_market_code=fixtures.OTA_GEO_MARKET,
        **overrides,
    )


def test_oversold_night_queues_a_guard_stop_sell_that_the_cancellation_lifts(api, world):
    """The booking that pushes committed units past physical capacity turns the night
    OVERSOLD, and that alone creates the system's own STOP_SELL guard and queues a
    restriction batch for every mapped channel. Cancelling that booking runs the chain
    backwards and the system lifts its own guard with `AUTO_GUARD_CLEARED`.

    Design: Difficulty/transitive_cascade/oversold_day_creates_guard_stop_sell_batch_then_cancellation_lifts_it
    """
    twin, mapping = _oversellable_twin(api, world)

    first = _book_one_night(api, world, twin["id"])
    second = _book_one_night(api, world, twin["id"])
    for booking, label in ((first, "first booking"), (second, "second booking")):
        assert_fields(booking, {"reservation_state": "CONFIRMED", "overbooking_overridden": False}, label)
    # Two of two rooms sold: held plus committed has reached capacity but not the ceiling.
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=2,
        shared=1,
        pooled_state="TIGHT",
    )
    assert fixtures.list_restrictions(api, room_type_id=twin["id"]) == [], (
        "a TIGHT night is not yet guarded"
    )

    # The third night is in the overbooking band, so it needs the override, and
    # consuming that override is what turns the night OVERSOLD.
    third = _book_one_night(api, world, twin["id"], override_overbooking=True)
    assert_fields(
        third,
        {"reservation_state": "CONFIRMED", "overbooking_overridden": True},
        "overbooking booking",
    )
    assert_reservation_totals(
        third,
        gross=NIGHTLY_SELL_CENTS,
        commission=NIGHTLY_COMMISSION_CENTS,
        net=NIGHTLY_NET_CENTS,
        loyalty_credit=0,
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=3,
        shared=0,
        pooled_state="OVERSOLD",
    )

    # One guard per ACTIVE plan on the property, covering that single night.
    guards = fixtures.list_restrictions(api, room_type_id=twin["id"])
    assert len(guards) == 1, f"expected one guard restriction, got {len(guards)}"
    guard = guards[0]
    assert_fields(
        guard,
        {
            "room_type_id": twin["id"],
            "rate_plan_id": world["rate_plan_id"],
            "restriction_type": "STOP_SELL",
            "origin": "AUTO_OVERBOOK_GUARD",
            "restriction_state": "ACTIVE",
            "start_date": fixtures.STAY_DATE,
            "end_date": fixtures.STAY_DATE,
            "value_nights": None,
            "lifted_at": None,
            "lift_reason": None,
        },
        "guard restriction",
    )

    # The guard propagates like any placement: one batch, one job per verified mapping.
    guard_batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RESTRICTION")
    assert_fields(
        guard_batch,
        {
            "source_ref_kind": "RESTRICTION",
            "source_ref_id": guard["id"],
            "batch_state": "QUEUED",
            "total_jobs": 1,
            "dispatched_at": None,
        },
        "guard batch",
    )
    guard_jobs = fixtures.jobs_of(api, guard_batch["id"])
    assert_sequence_indices_one_based(guard_jobs)
    assert_job(
        guard_jobs[0],
        job_state="QUEUED",
        attempt_count=0,
        failure_reason=None,
        payload_rate_cents=None,
        channel_mapping_id=mapping["id"],
    )
    assert_fields(guard_jobs[0], {"payload_kind": "RESTRICTION"}, "guard job")

    # Cancelling the overbooking booking runs the whole chain backwards.
    cancelled = validate_success(api.cancel_reservation(third["id"], REVENUE_MANAGER_HEADERS))
    assert_fields(cancelled, {"reservation_state": "CANCELLED"}, "cancelled reservation")
    assert_instant_equals(
        cancelled["cancelled_at"], fixtures.FIXTURE_CLOCK, "reservation.cancelled_at"
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=2,
        shared=1,
        pooled_state="TIGHT",
    )
    lifted = fixtures.read_restriction(api, guard["id"])
    assert_fields(
        lifted,
        {"restriction_state": "LIFTED", "lift_reason": "AUTO_GUARD_CLEARED"},
        "guard restriction after the cancellation",
    )
    assert_instant_equals(lifted["lifted_at"], fixtures.FIXTURE_CLOCK, "restriction.lifted_at")
    assert lifted["version"] > guard["version"], (
        "the lift should increment the restriction's version, which stayed at "
        f"{guard['version']}"
    )

    # The lift propagates exactly as the placement did: a second restriction batch.
    restriction_batches = fixtures.list_batches(
        api, property_id=world["property_id"], payload_kind="RESTRICTION"
    )
    assert len(restriction_batches) == 2, (
        f"placement and lift should queue one batch each, got {len(restriction_batches)}"
    )
    for batch in restriction_batches:
        assert_fields(
            batch,
            {"source_ref_kind": "RESTRICTION", "source_ref_id": guard["id"], "total_jobs": 1},
            "restriction batch",
        )

    # The money is reversed exactly, and the booking count is not.
    assert_channel_ledger(
        fixtures.read_channel(api, world["channel_id"]),
        {
            "gross_revenue_cents": 2 * NIGHTLY_SELL_CENTS,
            "commission_accrued_cents": 2 * NIGHTLY_COMMISSION_CENTS,
            "net_revenue_cents": 2 * NIGHTLY_NET_CENTS,
            "room_nights_sold": 2,
            "bookings_count": 3,
            "cancellations_count": 1,
        },
    )


def test_the_guard_covers_only_active_plans_and_only_the_oversold_night(api, world):
    """The guard cascade is narrow: it reaches the property's ACTIVE plans only, covers
    the single oversold night and no other, marks only the booking that consumed the
    override, and cannot be undone by a human — a manual lift of the system's own guard
    is refused and changes nothing.

    Design: Difficulty/transitive_cascade/oversold_day_creates_guard_stop_sell_batch_then_cancellation_lifts_it
    """
    twin, _mapping = _oversellable_twin(api, world, extra_nights=(fixtures.STAY_DATE_2,))
    # Two plans on the same property that the cascade must not reach.
    draft_plan = fixtures.create_rate_plan(api, world["property_id"])
    assert_fields(draft_plan, {"plan_state": "DRAFT"}, "draft plan")
    closed_plan = fixtures.create_active_rate_plan(api, world["property_id"])
    closed_plan = fixtures.close_rate_plan(api, closed_plan["id"])
    assert_fields(closed_plan, {"plan_state": "CLOSED"}, "closed plan")

    first = _book_one_night(api, world, twin["id"])
    second = _book_one_night(api, world, twin["id"])
    third = _book_one_night(api, world, twin["id"], override_overbooking=True)
    # Only the booking that actually needed the allowance is flagged.
    assert [row["overbooking_overridden"] for row in (first, second, third)] == [
        False,
        False,
        True,
    ], "only the booking that consumed the overbooking allowance is flagged"
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=3,
        shared=0,
        pooled_state="OVERSOLD",
    )

    restrictions = fixtures.list_restrictions(api, room_type_id=twin["id"])
    assert len(restrictions) == 1, (
        "only the property's ACTIVE plans are guarded, so exactly one restriction is "
        f"expected, got {[row['rate_plan_id'] for row in restrictions]}"
    )
    guard = restrictions[0]
    assert_fields(
        guard,
        {
            "rate_plan_id": world["rate_plan_id"],
            "restriction_type": "STOP_SELL",
            "origin": "AUTO_OVERBOOK_GUARD",
            "restriction_state": "ACTIVE",
            "start_date": fixtures.STAY_DATE,
            "end_date": fixtures.STAY_DATE,
        },
        "guard restriction",
    )
    assert guard["rate_plan_id"] not in (draft_plan["id"], closed_plan["id"]), (
        "a plan that is not ACTIVE must not be guarded"
    )

    # The next night shares the room type but was never oversold, so it is untouched.
    assert_inventory_day(
        fixtures.inventory_day_on(api, twin["id"], fixtures.STAY_DATE_2),
        capacity=2,
        ceiling=3,
        allocated=0,
        committed=0,
        shared=3,
        pooled_state="OPEN",
    )

    # Only the system lifts what the system placed.
    validate_error(
        api.lift_restriction(guard["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.OVERRIDE_NOT_PERMITTED.value,
        403,
    )
    still_active = fixtures.read_restriction(api, guard["id"])
    assert_fields(
        still_active,
        {"restriction_state": "ACTIVE", "lifted_at": None, "lift_reason": None},
        "guard restriction after the refused lift",
    )
    assert_version(still_active, guard["version"], "guard restriction")
    assert len(fixtures.list_batches(api, property_id=world["property_id"], payload_kind="RESTRICTION")) == 1, (
        "a refused lift queues no distribution work"
    )

    # The bookings all stand, so nothing has been reversed.
    assert_channel_ledger(
        fixtures.read_channel(api, world["channel_id"]),
        {
            "gross_revenue_cents": 3 * NIGHTLY_SELL_CENTS,
            "commission_accrued_cents": 3 * NIGHTLY_COMMISSION_CENTS,
            "net_revenue_cents": 3 * NIGHTLY_NET_CENTS,
            "room_nights_sold": 3,
            "bookings_count": 3,
            "cancellations_count": 0,
        },
    )


# ── One patch at the root of a derivation chain ─────────────────────────────

# CORP sits 15% under its parent, CORP2 five dollars over CORP.
CORP_OFFSET_BP = -1500
CORP2_OFFSET_CENTS = 500
ROOT_PATCH_BASE_CENTS = 30000
# 30000 x (10000 - 1500) / 10000 = 25500, and 25500 + 500 = 26000.
REDERIVED_CHILD_CENTS = 25500
REDERIVED_GRANDCHILD_CENTS = 26000


def _derivation_chain(api, world):
    """The canonical plan with a child and a grandchild hung off it, all ACTIVE.

    A root plan sits at depth 0, its child at depth 1 and its grandchild at the
    depth cap of 2.
    """
    child = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        world["rate_plan_id"],
        offset_kind="PERCENT",
        offset_bp=CORP_OFFSET_BP,
    )
    child = fixtures.activate_rate_plan(api, child["id"])
    grandchild = fixtures.create_derived_rate_plan(
        api,
        world["property_id"],
        child["id"],
        offset_kind="AMOUNT",
        offset_amount_cents=CORP2_OFFSET_CENTS,
    )
    grandchild = fixtures.activate_rate_plan(api, grandchild["id"])
    # 25000 x (10000 - 1500) / 10000 = 21250, and 21250 + 500 = 21750.
    assert_fields(
        fixtures.read_rate_plan(api, world["rate_plan_id"]),
        {"derivation_depth": 0, "resolved_base_amount_cents": fixtures.BAR_BASE_CENTS},
        "root plan",
    )
    assert_fields(
        child,
        {"derivation_depth": 1, "resolved_base_amount_cents": 21250, "plan_state": "ACTIVE"},
        "child plan",
    )
    assert_fields(
        grandchild,
        {"derivation_depth": 2, "resolved_base_amount_cents": 21750, "plan_state": "ACTIVE"},
        "grandchild plan",
    )
    return child, grandchild


def test_root_patch_rederives_the_grandchild_and_pushes_its_mapping(api, world):
    """One repricing of the root of a chain re-derives every plan whose parent chain
    reaches it, parent before child, and the batch it queues fans out to the mappings of
    the descendants rather than to the repriced plan's own — so a grandchild's mapping
    receives a job carrying the grandchild's freshly re-derived rate.

    Design: Difficulty/transitive_cascade/root_plan_patch_rederives_grandchild_and_fans_out_only_mapped_descendants
    """
    child, grandchild = _derivation_chain(api, world)
    # The product actually sold sits two hops below the plan that is about to move.
    grandchild_mapping = fixtures.create_verified_mapping(
        api, grandchild["id"], world["channel_id"], world["room_type_id"]
    )
    root_before = fixtures.read_rate_plan(api, world["rate_plan_id"])

    repriced = fixtures.reprice_rate_plan(
        api, world["rate_plan_id"], base_amount_cents=ROOT_PATCH_BASE_CENTS
    )
    assert_fields(
        repriced,
        {
            "plan_state": "ACTIVE",
            "base_amount_cents": ROOT_PATCH_BASE_CENTS,
            "resolved_base_amount_cents": ROOT_PATCH_BASE_CENTS,
            "derivation_depth": 0,
        },
        "repriced root plan",
    )
    assert_version(repriced, root_before["version"] + 1, "repriced root plan")

    # The whole chain settles in the one pass, parent before child.
    assert_fields(
        fixtures.read_rate_plan(api, child["id"]),
        {"resolved_base_amount_cents": REDERIVED_CHILD_CENTS, "derivation_depth": 1},
        "child plan after the root patch",
    )
    assert_fields(
        fixtures.read_rate_plan(api, grandchild["id"]),
        {"resolved_base_amount_cents": REDERIVED_GRANDCHILD_CENTS, "derivation_depth": 2},
        "grandchild plan after the root patch",
    )

    # One batch, sourced at the plan that moved, not at the plan that is mapped.
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    assert_fields(
        batch,
        {
            "source_ref_kind": "RATE_PLAN",
            "source_ref_id": world["rate_plan_id"],
            "batch_state": "QUEUED",
            "total_jobs": 1,
            "dispatched_at": None,
        },
        "rate batch",
    )
    jobs = fixtures.jobs_of(api, batch["id"])
    assert_sequence_indices_one_based(jobs)
    # The pushed quote is the grandchild's rate card: 26000 x (10000 + 0) / 10000 = 26000,
    # inside the grandchild's [18000, 40000] band, plus 0 package inclusion.
    assert_job(
        jobs[0],
        job_state="QUEUED",
        attempt_count=0,
        failure_reason=None,
        payload_rate_cents=REDERIVED_GRANDCHILD_CENTS,
        channel_mapping_id=grandchild_mapping["id"],
    )
    assert_fields(jobs[0], {"payload_kind": "RATE"}, "rate job")


def test_the_root_patch_fans_out_only_to_verified_descendant_mappings(api, world):
    """Re-derivation and fan-out have different reach. The patch re-derives every plan in
    its own chain and nothing outside it, while the batch it queues carries a job only for
    a mapping that is both on that chain and VERIFIED — a sibling plan's mapping and an
    unverified mapping on the chain are both left alone.

    Design: Difficulty/transitive_cascade/root_plan_patch_rederives_grandchild_and_fans_out_only_mapped_descendants
    """
    child, grandchild = _derivation_chain(api, world)
    child_mapping = fixtures.create_verified_mapping(
        api, child["id"], world["channel_id"], world["room_type_id"]
    )
    # Same chain, but never verified, so it carries no product yet.
    brand = fixtures.create_brand_channel(api, world["property_id"])
    unverified_mapping = fixtures.create_mapping_in_parity(
        api, child["id"], brand["channel"]["id"], world["room_type_id"]
    )
    assert_fields(unverified_mapping, {"mapping_state": "DRAFT"}, "unverified mapping")
    # A second root plan on the same property: sellable, mapped, and unrelated.
    outsider = fixtures.create_active_rate_plan(api, world["property_id"], base_amount_cents=22000)
    outsider_mapping = fixtures.create_verified_mapping(
        api, outsider["id"], world["channel_id"], world["room_type_id"]
    )
    assert_fields(
        outsider,
        {"resolved_base_amount_cents": 22000, "derivation_depth": 0, "parent_rate_plan_id": None},
        "unrelated root plan",
    )

    fixtures.reprice_rate_plan(
        api, world["rate_plan_id"], base_amount_cents=ROOT_PATCH_BASE_CENTS
    )

    # Re-derivation followed the parent chain, and stopped at its edge.
    assert_fields(
        fixtures.read_rate_plan(api, child["id"]),
        {"resolved_base_amount_cents": REDERIVED_CHILD_CENTS},
        "child plan",
    )
    # The grandchild is re-derived even though nothing is mapped to it.
    assert_fields(
        fixtures.read_rate_plan(api, grandchild["id"]),
        {"resolved_base_amount_cents": REDERIVED_GRANDCHILD_CENTS},
        "grandchild plan",
    )
    assert_unchanged(
        outsider,
        fixtures.read_rate_plan(api, outsider["id"]),
        ["base_amount_cents", "resolved_base_amount_cents", "version", "updated_at"],
        "unrelated root plan",
    )

    # The fan-out is narrower still: one job, on the one VERIFIED mapping in the chain.
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    assert_fields(batch, {"source_ref_id": world["rate_plan_id"], "total_jobs": 1}, "rate batch")
    jobs = fixtures.jobs_of(api, batch["id"])
    assert_sequence_indices_one_based(jobs)
    # 25500 x (10000 + 0) / 10000 = 25500, inside [18000, 40000], plus 0 inclusion.
    assert_job(
        jobs[0],
        job_state="QUEUED",
        attempt_count=0,
        payload_rate_cents=REDERIVED_CHILD_CENTS,
        channel_mapping_id=child_mapping["id"],
    )
    pushed_to = {row["channel_mapping_id"] for row in jobs}
    assert unverified_mapping["id"] not in pushed_to, (
        "a mapping that is not VERIFIED receives no distribution job"
    )
    assert outsider_mapping["id"] not in pushed_to, (
        "a mapping on a plan outside the repriced chain receives no distribution job"
    )
    for mapping, label in (
        (unverified_mapping, "unverified mapping"),
        (outsider_mapping, "mapping of the unrelated plan"),
    ):
        assert_unchanged(
            mapping,
            fixtures.read_mapping(api, mapping["id"]),
            ["mapping_state", "last_pushed_rate_cents", "last_push_at", "version"],
            label,
        )

    # And one patch means one batch, whatever the shape of the chain below it.
    assert [row["id"] for row in fixtures.list_batches(api, property_id=world["property_id"])] == [
        batch["id"]
    ], "one accepted repricing creates exactly one batch"
