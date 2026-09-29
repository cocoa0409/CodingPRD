"""State-machine corners of the Hotel Channel Distribution contract.

These scenarios pin the declared initial state of every row the service mints,
the terminal states that refuse every further transition, the transitions that
are not idempotent setters, the probation streak a revalidated connection is
parked on, the mapping cycle that runs VERIFIED to ERRORED and back, and the
derived posture an inventory day moves through as held units come and go.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    REVENUE_DIRECTOR_HEADERS,
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_batch_counters,
    assert_channel_ledger,
    assert_common_fields,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_version,
    factories,
    fixtures,
)

# ── Module-local scenario builders ─────────────────────────────────────────
#
# Each one composes the shared fixtures into the exact starting world one group
# of scenarios needs, in an order in which no later hop invalidates an earlier
# one: a plan is ACTIVE and its connection sellable before a mapping is
# verified, and every allotment re-reads the room type's version echo.


def _closed_rate_plan(api) -> Dict[str, Any]:
    """A public plan driven all the way to CLOSED, its only terminal state."""
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    plan = fixtures.create_canonical_rate_plan(api, property_row["id"])
    fixtures.activate_rate_plan(api, plan["id"])
    return fixtures.close_rate_plan(api, plan["id"])


def _draft_promotion(api, rate_plan_id: str) -> Dict[str, Any]:
    """A freshly authored promotion, so DRAFT on the approval axis."""
    return fixtures.create_promotion(
        api,
        rate_plan_id,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )


def _suspended_connection_with_recalled_allotment(api) -> Dict[str, Any]:
    """Three failure events suspend a live connection, recalling its allotment.

    The room type holds ten rooms under a 10% allowance, so the night's ceiling
    is 11; a four-unit allotment leaves seven units in the shared pool until the
    suspension recalls it.
    """
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    ota = fixtures.create_ota_channel(api, property_row["id"])
    day = fixtures.open_inventory_day(api, room_type["id"], fixtures.STAY_DATE)
    allocation = fixtures.create_allocation(
        api,
        room_type["id"],
        ota["channel"]["id"],
        4,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    fixtures.suspend_connection(api, ota["connection"]["id"], failure_code="TIMEOUT")
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": ota["channel"]["id"],
        "connection_id": ota["connection"]["id"],
        "inventory_day_id": day["id"],
        "allocation_id": allocation["id"],
    }


def _verified_mapping_with_a_queued_job_and_broken_parity(api) -> Dict[str, Any]:
    """A VERIFIED mapping whose published content has fallen out of parity.

    The repricing queues one RATE batch carrying a single job against the
    mapping; the content is then cut to four images, one below the property's
    required five, so the mapping is still VERIFIED but no longer in parity.
    """
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    ota = fixtures.create_ota_channel(api, property_row["id"])
    plan = fixtures.create_canonical_rate_plan(api, property_row["id"])
    plan = fixtures.activate_rate_plan(api, plan["id"])
    mapping = fixtures.create_verified_mapping(
        api, plan["id"], ota["channel"]["id"], room_type["id"]
    )
    fixtures.reprice_rate_plan(api, plan["id"], ceiling_amount_cents=41000)
    batch = fixtures.only_batch(api, payload_kind="RATE")
    fixtures.patch_mapping_content(api, mapping["id"], content_image_count=4)
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": ota["channel"]["id"],
        "connection_id": ota["connection"]["id"],
        "rate_plan_id": plan["id"],
        "mapping_id": mapping["id"],
        "batch_id": batch["id"],
    }


def _cancelled_pool_reservation(api) -> Dict[str, Any]:
    """One pool-drawn night booked on the brand channel and then cancelled."""
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    brand = fixtures.create_brand_channel(api, property_row["id"])
    plan = fixtures.create_canonical_rate_plan(api, property_row["id"])
    plan = fixtures.activate_rate_plan(api, plan["id"])
    day = fixtures.open_inventory_day(api, room_type["id"], fixtures.STAY_DATE)
    reservation = fixtures.create_reservation(
        api,
        brand["channel"]["id"],
        plan["id"],
        room_type["id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
    )
    cancelled = fixtures.cancel_reservation(api, reservation["id"])
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": brand["channel"]["id"],
        "rate_plan_id": plan["id"],
        "inventory_day_id": day["id"],
        "reservation_id": reservation["id"],
        "cancelled": cancelled,
    }


def _room_type_with_one_open_night(api) -> Dict[str, Any]:
    """Ten rooms under a 10% allowance with a single night open for sale."""
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    ota = fixtures.create_ota_channel(api, property_row["id"])
    day = fixtures.open_inventory_day(api, room_type["id"], fixtures.STAY_DATE)
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": ota["channel"]["id"],
        "inventory_day_id": day["id"],
    }


# ── Declared initial states ────────────────────────────────────────────────


def test_new_rows_start_in_their_declared_initial_states(api):
    """Every row the contract mints starts in its declared initial state at
    version 1: a connection PENDING with a clean failure record, a rate plan
    DRAFT, a mapping DRAFT with its rate comparison still UNKNOWN, a promotion
    DRAFT on the approval axis and NOT_LOADED on the distribution axis, and a
    night OPEN with its whole ceiling still in the shared pool.

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    room_type = fixtures.create_king_room_type(api, property_row["id"])
    channel = fixtures.create_channel(
        api,
        property_row["id"],
        code=fixtures.OTA_CODE,
        channel_kind="OTA_PUBLIC",
        commission_bp=fixtures.OTA_COMMISSION_BP,
    )

    connection = validate_success(
        api.create_connection(
            channel["id"],
            factories.connection_payload(url=factories.endpoint_url(fixtures.OTA_CODE)),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )
    assert_common_fields(connection, "connection")
    assert_fields(
        connection,
        {
            "connection_state": "PENDING",
            "consecutive_failures": 0,
            "last_heartbeat_at": None,
            "last_failure_code": None,
            "suspended_at": None,
        },
        "connection",
    )
    assert_version(connection, 1, "connection")

    rate_plan = validate_success(
        api.create_rate_plan(
            property_row["id"],
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
    assert_fields(
        rate_plan,
        {
            "plan_state": "DRAFT",
            "derivation_depth": 0,  # a root plan names no parent
            "resolved_base_amount_cents": fixtures.BAR_BASE_CENTS,
        },
        "rate plan",
    )
    assert_version(rate_plan, 1, "rate plan")

    mapping = validate_success(
        api.create_mapping(
            factories.mapping_payload(
                rate_plan["id"],
                channel["id"],
                room_type["id"],
                external_rate_code="BAR-OTA1-KING",
                content_description_hash=fixtures.KING_HASH,
                content_image_count=fixtures.KING_IMAGE_COUNT,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )
    assert_fields(
        mapping,
        {
            "mapping_state": "DRAFT",
            # content matches the master hash and clears the 5-image floor
            "parity_state": "IN_PARITY",
            "mismatch_state": "UNKNOWN",
            "mismatch_delta_cents": None,
            "last_push_at": None,
            "last_pushed_rate_cents": None,
            "observed_rate_cents": None,
            "observed_stay_date": None,
        },
        "mapping",
    )
    assert_version(mapping, 1, "mapping")

    promotion = validate_success(
        api.create_promotion(
            rate_plan["id"],
            factories.promotion_payload(
                start_date="2026-09-01",
                end_date="2026-09-30",
                code="MEMBER10",
                promo_kind="MEMBER_RATE",
                discount_kind="PERCENT",
                discount_bp=1000,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        promotion,
        {
            "approval_status": "DRAFT",
            "distribution_status": "NOT_LOADED",
            "revision_count": 0,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "reject_reason": None,
        },
        "promotion",
    )
    assert_version(promotion, 1, "promotion")

    inventory_day = validate_success(
        api.create_inventory_day(
            room_type["id"],
            factories.inventory_day_payload(fixtures.STAY_DATE),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    # 10 rooms + floor(10 x 1000 / 10000) = 11 units of ceiling, none of it held
    assert_inventory_day(
        inventory_day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )
    assert_version(inventory_day, 1, "inventory day")


# ── Terminal states refuse every further transition ────────────────────────


def test_closed_rate_plan_refuses_reactivation(api):
    """CLOSED is terminal, so activation is refused even though the plan was
    ACTIVE moments earlier; activation requires DRAFT and nothing else.

    Design: Corner/state_machines/closed_rate_plan_is_terminal_and_cannot_be_reactivated_or_patched
    """
    plan = _closed_rate_plan(api)
    assert_fields(plan, {"plan_state": "CLOSED"}, "rate plan")
    assert_version(plan, 3, "rate plan")  # created 1, activated 2, closed 3

    validate_error(
        api.activate_rate_plan(plan["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.RATE_PLAN_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_rate_plan(api, plan["id"])
    assert_fields(after, {"plan_state": "CLOSED"}, "rate plan")
    assert_version(after, 3, "rate plan")


def test_closed_rate_plan_refuses_a_second_closure(api):
    """Closure requires an ACTIVE plan, so a closed plan cannot be closed again
    and the rejected call leaves its version untouched.

    Design: Corner/state_machines/closed_rate_plan_is_terminal_and_cannot_be_reactivated_or_patched
    """
    plan = _closed_rate_plan(api)

    validate_error(
        api.close_rate_plan(plan["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.RATE_PLAN_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_rate_plan(api, plan["id"])
    assert_fields(after, {"plan_state": "CLOSED"}, "rate plan")
    assert_version(after, 3, "rate plan")


def test_closed_rate_plan_refuses_repricing_even_with_the_right_version_echo(api):
    """Repricing a closed plan is refused on its state, not on concurrency: the
    echo carries the plan's true version, so the state check is what fires, and
    the plan's price is left exactly as the closure found it.

    Design: Corner/state_machines/closed_rate_plan_is_terminal_and_cannot_be_reactivated_or_patched
    """
    plan = _closed_rate_plan(api)

    payload = factories.reprice_payload(
        expected_rate_plan_version=plan["version"],  # 3, the current version
        base_amount_cents=26000,
    )
    validate_error(
        api.patch_rate_plan(plan["id"], payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.RATE_PLAN_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_rate_plan(api, plan["id"])
    assert_fields(
        after,
        {
            "plan_state": "CLOSED",
            "base_amount_cents": fixtures.BAR_BASE_CENTS,  # still 25000
            "resolved_base_amount_cents": fixtures.BAR_BASE_CENTS,
        },
        "rate plan",
    )
    assert_version(after, 3, "rate plan")


# ── Transitions are not idempotent setters ─────────────────────────────────


def test_second_activation_of_a_live_connection_is_refused(api):
    """Activation moves a connection out of PENDING, so activating an already
    HEALTHY connection is refused and spends no version.

    Design: Corner/state_machines/connection_activate_twice_second_attempt_rejected
    """
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    channel = fixtures.create_channel(
        api,
        property_row["id"],
        code=fixtures.OTA_CODE,
        commission_bp=fixtures.OTA_COMMISSION_BP,
    )
    connection = fixtures.create_connection(
        api, channel["id"], url=factories.endpoint_url(fixtures.OTA_CODE)
    )
    activated = fixtures.activate_connection(api, connection["id"])
    assert_fields(
        activated,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "last_failure_code": None},
        "connection",
    )
    assert_version(activated, 2, "connection")  # created 1, activated 2

    validate_error(
        api.activate_connection(connection["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CONNECTION_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_connection(api, connection["id"])
    assert_fields(after, {"connection_state": "HEALTHY", "consecutive_failures": 0}, "connection")
    assert_version(after, 2, "connection")


def test_approving_a_draft_promotion_is_refused(api, world):
    """Approval requires a SUBMITTED promotion, so a promotion that was never
    submitted cannot be approved and records no approver.

    Design: Corner/state_machines/promotion_approve_without_submit_rejected
    """
    promotion = _draft_promotion(api, world["rate_plan_id"])
    assert_fields(
        promotion,
        {"approval_status": "DRAFT", "distribution_status": "NOT_LOADED"},
        "promotion",
    )

    validate_error(
        api.approve_promotion(promotion["id"], REVENUE_DIRECTOR_HEADERS),
        ApiErrorId.PROMOTION_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        after,
        {
            "approval_status": "DRAFT",
            "distribution_status": "NOT_LOADED",
            "approved_by_user_id": None,
            "submitted_by_user_id": None,
        },
        "promotion",
    )
    assert_version(after, 1, "promotion")


def test_rejecting_a_draft_promotion_is_refused(api, world):
    """Rejection is the other half of the approval decision and equally requires
    a SUBMITTED promotion, so no reason is recorded against a draft.

    Design: Corner/state_machines/promotion_approve_without_submit_rejected
    """
    promotion = _draft_promotion(api, world["rate_plan_id"])

    validate_error(
        api.reject_promotion(
            promotion["id"],
            REVENUE_DIRECTOR_HEADERS,
            factories.reject_payload("priced too aggressively"),
        ),
        ApiErrorId.PROMOTION_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        after,
        {"approval_status": "DRAFT", "reject_reason": None, "revision_count": 0},
        "promotion",
    )
    assert_version(after, 1, "promotion")


def test_revising_a_draft_promotion_is_refused(api, world):
    """Revision returns a REJECTED promotion to DRAFT, so it has nothing to do
    with a promotion that is already DRAFT and the revision count stays 0.

    Design: Corner/state_machines/promotion_approve_without_submit_rejected
    """
    promotion = _draft_promotion(api, world["rate_plan_id"])

    validate_error(
        api.revise_promotion(promotion["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.PROMOTION_STATE_INVALID.value,
        409,
    )

    after = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        after,
        {"approval_status": "DRAFT", "distribution_status": "NOT_LOADED", "revision_count": 0},
        "promotion",
    )
    assert_version(after, 1, "promotion")


# ── Revalidation is probation, not a reset ─────────────────────────────────


def test_revalidation_parks_the_connection_on_degraded_one_failure_from_suspension(api):
    """Revalidation brings a SUSPENDED connection back to DEGRADED rather than to
    HEALTHY and sets the streak to two, one below the threshold of three, so a
    single further failure event suspends it again immediately.

    Design: Corner/state_machines/revalidate_moves_suspended_connection_to_degraded_without_restoring_allotments
    """
    scenario = _suspended_connection_with_recalled_allotment(api)

    suspended = fixtures.read_connection(api, scenario["connection_id"])
    assert_fields(
        suspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,  # the suspension threshold
            "last_failure_code": "TIMEOUT",
        },
        "connection",
    )
    assert_instant_equals(
        suspended["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )

    revalidated = validate_success(
        api.revalidate_connection(scenario["connection_id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        revalidated,
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "connection",
    )

    # 2 + 1 = 3, so one failure event is enough to suspend the probationer again
    resuspended = fixtures.record_heartbeat(
        api, scenario["connection_id"], status="ERROR", failure_code="AUTH_REJECTED"
    )
    assert_fields(
        resuspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "AUTH_REJECTED",
        },
        "connection",
    )


def test_revalidation_does_not_restore_the_recalled_allotment(api):
    """The units a suspension recalls are gone for good: revalidation moves the
    connection but leaves the allotment RECALLED and the night's held units at
    zero, so the operator must carve a new allotment to get them back.

    Design: Corner/state_machines/revalidate_moves_suspended_connection_to_degraded_without_restoring_allotments
    """
    scenario = _suspended_connection_with_recalled_allotment(api)

    recalled = fixtures.read_allocation(api, scenario["allocation_id"])
    assert_fields(
        recalled,
        {"allocation_state": "RECALLED", "allocated_units": 4, "consumed_units": 0},
        "allocation",
    )
    assert_instant_equals(
        recalled["recalled_at"], fixtures.FIXTURE_CLOCK, "allocation.recalled_at"
    )
    # the recall returns all four held units to the shared pool: 0 + 0 + 11 = 11
    before = fixtures.read_inventory_day(api, scenario["inventory_day_id"])
    assert_inventory_day(
        before,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    validate_success(
        api.revalidate_connection(scenario["connection_id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )

    after_allocation = fixtures.read_allocation(api, scenario["allocation_id"])
    assert_fields(after_allocation, {"allocation_state": "RECALLED"}, "allocation")
    assert_instant_equals(
        after_allocation["recalled_at"], fixtures.FIXTURE_CLOCK, "allocation.recalled_at"
    )
    after_day = fixtures.read_inventory_day(api, scenario["inventory_day_id"])
    assert_inventory_day(
        after_day,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )


# ── The mapping health cycle runs both ways ────────────────────────────────


def test_parity_blocked_rejection_knocks_a_verified_mapping_to_errored(api):
    """A rejected job whose reason is PARITY_BLOCKED drives the reverse edge
    VERIFIED to ERRORED, marks the connection's failure code MAPPING_REJECTED,
    and pushes nothing: the batch fails with its single job rejected.

    Design: Corner/state_machines/mapping_cycles_verified_errored_verified_after_parity_repair
    """
    scenario = _verified_mapping_with_a_queued_job_and_broken_parity(api)

    before = fixtures.read_mapping(api, scenario["mapping_id"])
    assert_fields(
        before,
        {
            "mapping_state": "VERIFIED",
            # 4 images is one short of the property's required 5
            "parity_state": "OUT_OF_PARITY",
            "last_pushed_rate_cents": None,
        },
        "mapping",
    )

    validate_success(api.dispatch_batch(scenario["batch_id"], CHANNEL_OPS_ENGINEER_HEADERS))

    jobs = fixtures.jobs_of(api, scenario["batch_id"])
    assert len(jobs) == 1, f"the repricing should have fanned out one job, got {len(jobs)}"
    assert_job(
        jobs[0],
        job_state="REJECTED",
        attempt_count=1,
        failure_reason="PARITY_BLOCKED",
        channel_mapping_id=scenario["mapping_id"],
    )
    assert jobs[0]["applied_at"] is None, "a rejected job leaves applied_at null"
    assert jobs[0]["sequence_index"] == 1, "fan-out numbers the first child 1"

    batch = fixtures.read_batch(api, scenario["batch_id"])
    assert_batch_counters(
        batch,
        batch_state="FAILED",  # no job applied and none still open
        total_jobs=1,
        applied_jobs=0,
        rejected_jobs=1,
        abandoned_jobs=0,
    )

    mapping = fixtures.read_mapping(api, scenario["mapping_id"])
    assert_fields(
        mapping,
        {
            "mapping_state": "ERRORED",
            "parity_state": "OUT_OF_PARITY",
            "last_pushed_rate_cents": None,
            "last_push_at": None,
        },
        "mapping",
    )
    connection = fixtures.read_connection(api, scenario["connection_id"])
    assert_fields(
        connection,
        {
            "connection_state": "DEGRADED",  # first failure event on a HEALTHY connection
            "consecutive_failures": 1,
            "last_failure_code": "MAPPING_REJECTED",
        },
        "connection",
    )


def test_repairing_the_content_lets_an_errored_mapping_verify_again(api):
    """The cycle closes: repairing the published content puts the mapping back
    IN_PARITY without moving it out of ERRORED, and an explicit verification is
    what returns it to VERIFIED.

    Design: Corner/state_machines/mapping_cycles_verified_errored_verified_after_parity_repair
    """
    scenario = _verified_mapping_with_a_queued_job_and_broken_parity(api)
    validate_success(api.dispatch_batch(scenario["batch_id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_fields(
        fixtures.read_mapping(api, scenario["mapping_id"]),
        {"mapping_state": "ERRORED"},
        "mapping",
    )

    # back to the master image count, so the parity verdict flips on its own
    repaired = fixtures.patch_mapping_content(
        api, scenario["mapping_id"], content_image_count=fixtures.KING_IMAGE_COUNT
    )
    assert_fields(
        repaired,
        {"parity_state": "IN_PARITY", "mapping_state": "ERRORED"},
        "mapping",
    )

    verified = validate_success(
        api.verify_mapping(scenario["mapping_id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        verified,
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "mapping",
    )


# ── A cancelled reservation is terminal ────────────────────────────────────


def test_second_cancellation_of_a_reservation_is_refused(api):
    """CANCELLED is terminal for a reservation, so a second cancellation is
    refused and the original cancellation instant is left exactly as it was.

    Design: Corner/state_machines/reservation_cancel_twice_second_attempt_rejected
    """
    scenario = _cancelled_pool_reservation(api)
    first = scenario["cancelled"]
    assert_fields(first, {"reservation_state": "CANCELLED"}, "reservation")
    assert_instant_equals(
        first["cancelled_at"], fixtures.FIXTURE_CLOCK, "reservation.cancelled_at"
    )

    validate_error(
        api.cancel_reservation(scenario["reservation_id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.RESERVATION_NOT_CANCELLABLE.value,
        409,
    )

    after = fixtures.read_reservation(api, scenario["reservation_id"])
    assert_fields(after, {"reservation_state": "CANCELLED"}, "reservation")
    assert_version(after, 2, "reservation")  # booked 1, cancelled 2
    assert_instant_equals(
        after["cancelled_at"], fixtures.FIXTURE_CLOCK, "reservation.cancelled_at"
    )


def test_second_cancellation_credits_nothing_back_twice(api):
    """The refused second cancellation applies no side effect: the night's
    committed unit was already returned to the shared pool by the first, and the
    channel ledger still shows one booking against one cancellation.

    Design: Corner/state_machines/reservation_cancel_twice_second_attempt_rejected
    """
    scenario = _cancelled_pool_reservation(api)

    validate_error(
        api.cancel_reservation(scenario["reservation_id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.RESERVATION_NOT_CANCELLABLE.value,
        409,
    )

    # the single committed unit went back once: 0 + 0 + 11 = 11
    day = fixtures.inventory_day_on(api, scenario["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    channel = fixtures.read_channel(api, scenario["channel_id"])
    assert_channel_ledger(
        channel,
        {
            # the cancellation reverses the 25000 the booking accrued
            "gross_revenue_cents": 0,
            "commission_accrued_cents": 0,
            "net_revenue_cents": 0,
            "room_nights_sold": 0,
            "bookings_count": 1,  # the lifetime booking count is never reversed
            "cancellations_count": 1,
        },
    )


# ── The pooled posture of a night is derived, and it moves both ways ───────


def test_allotment_that_consumes_the_capacity_moves_the_night_to_tight(api):
    """Holding all ten physical units leaves one unit of the overbooking
    allowance in the shared pool, which is TIGHT rather than EXHAUSTED: the
    night is at capacity but still sellable.

    Design: Corner/state_machines/inventory_day_moves_open_to_tight_when_capacity_is_reached_but_pool_remains
    """
    scenario = _room_type_with_one_open_night(api)
    version = fixtures.room_type_version(api, scenario["room_type_id"])

    allocation = validate_success(
        api.create_allocation(
            scenario["room_type_id"],
            factories.allocation_payload(
                channel_id=scenario["channel_id"],
                allocated_units=fixtures.KING_CAPACITY,  # 10 + 0 + 0 = 10, within the ceiling of 11
                start_date=fixtures.STAY_DATE,
                end_date=fixtures.STAY_DATE,
                expected_room_type_version=version,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        allocation,
        {
            "allocation_state": "OPEN",
            "allocated_units": fixtures.KING_CAPACITY,
            "consumed_units": 0,
        },
        "allocation",
    )

    # allocated 10 + committed 0 >= capacity 10, and 1 unit of pool remains
    day = fixtures.read_inventory_day(api, scenario["inventory_day_id"])
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=fixtures.KING_CAPACITY,
        committed=0,
        shared=1,
        pooled_state="TIGHT",
    )
    assert_version(day, 2, "inventory day")  # opened 1, recomputed by the allotment 2


def test_releasing_the_allotment_returns_the_night_to_open(api):
    """Releasing the held units runs the edge back the other way: the pool
    recovers the whole ceiling and the night is OPEN again.

    Design: Corner/state_machines/inventory_day_moves_open_to_tight_when_capacity_is_reached_but_pool_remains
    """
    scenario = _room_type_with_one_open_night(api)
    allocation = fixtures.create_allocation(
        api,
        scenario["room_type_id"],
        scenario["channel_id"],
        fixtures.KING_CAPACITY,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    assert_inventory_day(
        fixtures.read_inventory_day(api, scenario["inventory_day_id"]),
        allocated=fixtures.KING_CAPACITY,
        shared=1,
        pooled_state="TIGHT",
    )

    released = validate_success(
        api.release_allocation(allocation["id"], REVENUE_MANAGER_HEADERS)
    )
    assert_fields(released, {"allocation_state": "RELEASED"}, "allocation")

    # all ten held units go back: 0 + 0 + 11 = 11, and 0 + 0 < 10 is OPEN again
    day = fixtures.read_inventory_day(api, scenario["inventory_day_id"])
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )
