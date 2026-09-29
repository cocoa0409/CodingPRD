"""Immediate consistency across the distribution write paths.

Nothing in this contract is deferred. A repricing re-derives its resolved amount
and queues its distribution work inside the request that asked for it; a dispatch
resolves every child job, refreshes the target mapping's pushed rate and reworks
the mismatch verdict before it answers; a booking recomputes the night it touches
before it returns. These tests therefore never poll, never sleep and never
re-dispatch: the write's own response already carries the derived values, the very
next read agrees with it field by field, and a second read of the same row returns
the same numbers again.
"""

from typing import Any, Mapping

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    REVENUE_MANAGER_HEADERS,
    assert_batch_counters,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_nightly_breakdown,
    assert_reservation_totals,
    assert_sequence_indices_one_based,
)
from test_helpers import factories, fixtures

# The canonical OTA serves only this market, so its bookings must name it.
OTA_MARKET = fixtures.OTA_GEO_MARKET

# The repriced amount, inside the plan's 18000-40000 band.
REPRICED_CENTS = 26000


def _assert_agrees(write_response: Mapping[str, Any], read_back: Mapping[str, Any], entity: str):
    """Every field of a write's own response equals the same field of the next read."""
    assert set(write_response) == set(read_back), (
        f"the {entity} write response and the read-back should carry the same field set; "
        f"write-only {sorted(set(write_response) - set(read_back))}, "
        f"read-only {sorted(set(read_back) - set(write_response))}"
    )
    for field, value in write_response.items():
        assert read_back[field] == value, (
            f"{entity}.{field} was {value!r} in the write response but {read_back[field]!r} "
            f"in the immediately following read"
        )


def _verified_mapping(api, world):
    """One VERIFIED mapping of the canonical plan on the canonical channel."""
    return fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        content_description_hash=fixtures.KING_HASH,
        content_image_count=fixtures.KING_IMAGE_COUNT,
    )


def test_a_repricing_carries_its_own_derivation_and_queues_its_batch_at_once(api, world):
    """An accepted repricing re-derives `resolved_base_amount_cents` and creates its
    QUEUED rate batch with the fanned-out job inside the same request, so the PATCH
    response already shows the new amount and the very next read agrees with it.

    Design: Corner/consistency_model/every_write_is_immediately_visible_in_its_own_response_and_in_the_next_read
    """
    mapping = _verified_mapping(api, world)

    # Creation put the plan at version 1 and activation took it to 2.
    before = fixtures.read_rate_plan(api, world["rate_plan_id"])
    assert_fields(
        before,
        {
            "plan_state": "ACTIVE",
            "version": 2,
            "base_amount_cents": fixtures.BAR_BASE_CENTS,
            "resolved_base_amount_cents": fixtures.BAR_BASE_CENTS,
        },
        entity_name="rate plan",
    )

    # A root plan's resolved base amount is simply its own base amount, so the
    # repriced 26000 is resolved to 26000 within this same request.
    written = validate_success(
        api.patch_rate_plan(
            world["rate_plan_id"],
            factories.reprice_payload(
                expected_rate_plan_version=before["version"],
                base_amount_cents=REPRICED_CENTS,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        200,
    )
    assert_fields(
        written,
        {
            "plan_state": "ACTIVE",
            "base_amount_cents": REPRICED_CENTS,
            "resolved_base_amount_cents": REPRICED_CENTS,
            "version": 3,
        },
        entity_name="rate plan",
    )

    # No read-after-write was needed above; this read merely has to agree.
    _assert_agrees(written, fixtures.read_rate_plan(api, world["rate_plan_id"]), "rate plan")

    # The batch and its child job exist by the time the next request is served.
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")
    assert_fields(
        batch,
        {
            "property_id": world["property_id"],
            "payload_kind": "RATE",
            "source_ref_kind": "RATE_PLAN",
            "source_ref_id": world["rate_plan_id"],
            "dispatched_at": None,
        },
        entity_name="distribution batch",
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
    assert len(jobs) == 1, f"one VERIFIED mapping means one child job, got {len(jobs)}"
    assert_sequence_indices_one_based(jobs)
    assert_job(
        jobs[0],
        job_state="QUEUED",
        attempt_count=0,
        failure_reason=None,
        payload_rate_cents=REPRICED_CENTS,
        channel_mapping_id=mapping["id"],
    )


def test_a_dispatch_resolves_and_publishes_its_jobs_inside_the_same_request(api, world):
    """A dispatch walks its children, refreshes the target mapping's pushed rate and
    mismatch verdict and settles its own state before it answers, so the dispatch
    response is already final and two later reads cannot disagree with it.

    Design: Corner/consistency_model/every_write_is_immediately_visible_in_its_own_response_and_in_the_next_read
    """
    mapping = _verified_mapping(api, world)
    assert_fields(
        mapping,
        {
            "mapping_state": "VERIFIED",
            "last_push_at": None,
            "last_pushed_rate_cents": None,
            "observed_rate_cents": None,
            "mismatch_state": "UNKNOWN",
            "mismatch_delta_cents": None,
        },
        entity_name="channel mapping",
    )

    fixtures.reprice_rate_plan(api, world["rate_plan_id"], base_amount_cents=REPRICED_CENTS)
    # Activation queues no distribution work of its own, so the repricing's batch
    # is the only RATE batch on the property.
    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="RATE")

    dispatched = validate_success(
        api.dispatch_batch(batch["id"], CHANNEL_OPS_ENGINEER_HEADERS), 200
    )
    # The one child job pushes to a VERIFIED, in-parity mapping on a HEALTHY
    # connection, so it applies and the batch settles inside this call.
    assert_batch_counters(
        dispatched,
        batch_state="APPLIED",
        total_jobs=1,
        applied_jobs=1,
        rejected_jobs=0,
        abandoned_jobs=0,
    )
    assert_instant_equals(dispatched["dispatched_at"], fixtures.FIXTURE_CLOCK, "dispatched_at")

    # The surveillance fields were written during that same dispatch: the pushed
    # rate is the promotion-free rate card, 26000 x (10000 + 0) / 10000 = 26000,
    # inside the 18000-40000 clamp with no package inclusion to add.
    pushed = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        pushed,
        {
            "mapping_state": "VERIFIED",
            "last_pushed_rate_cents": REPRICED_CENTS,
            # No rate has ever been observed on the partner side, so the verdict
            # cannot be formed and the delta stays null.
            "observed_rate_cents": None,
            "mismatch_state": "UNKNOWN",
            "mismatch_delta_cents": None,
        },
        entity_name="channel mapping",
    )
    assert_instant_equals(pushed["last_push_at"], fixtures.FIXTURE_CLOCK, "last_push_at")

    job = fixtures.jobs_of(api, batch["id"])[0]
    assert_job(
        job,
        job_state="APPLIED",
        attempt_count=1,
        failure_reason=None,
        payload_rate_cents=REPRICED_CENTS,
        channel_mapping_id=mapping["id"],
    )
    assert_instant_equals(job["applied_at"], fixtures.FIXTURE_CLOCK, "applied_at")

    # There is no convergence window: the dispatch response, the first read and a
    # second read of the same batch all carry the same derived values.
    first_read = fixtures.read_batch(api, batch["id"])
    _assert_agrees(dispatched, first_read, "distribution batch")
    _assert_agrees(first_read, fixtures.read_batch(api, batch["id"]), "distribution batch")
    _assert_agrees(pushed, fixtures.read_mapping(api, mapping["id"]), "channel mapping")


def test_a_booking_recomputes_its_night_before_it_answers(api, world):
    """A confirmed booking prices itself and recomputes every night it touches inside
    the creating request, so its own 201 body already holds the totals and the
    breakdown, and the inventory-day read that follows shows the recomputed pool.

    Design: Corner/consistency_model/every_write_is_immediately_visible_in_its_own_response_and_in_the_next_read
    """
    day = fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    # Ten physical rooms with the property's 1000 bp allowance: floor(10 x 1.1) = 11.
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    # 25000 for the single night, 1750 bp of the whole commissionable amount is
    # 4375, net 20625, and the 25000 gross is below the 50000 loyalty floor.
    written = validate_success(
        api.create_reservation(
            factories.reservation_payload(
                channel_id=world["channel_id"],
                rate_plan_id=world["rate_plan_id"],
                room_type_id=world["room_type_id"],
                arrival_date=fixtures.STAY_DATE,
                nights=1,
                geo_market_code=OTA_MARKET,
            ),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    assert_fields(
        written,
        {
            "reservation_state": "CONFIRMED",
            "departure_date": fixtures.STAY_DATE_2,
            "cancelled_at": None,
            "overbooking_overridden": False,
            "version": 1,
        },
        entity_name="reservation",
    )
    assert_reservation_totals(written, gross=25000, commission=4375, net=20625, loyalty_credit=0)
    assert_nightly_breakdown(
        written,
        [
            {
                "stay_date": fixtures.STAY_DATE,
                "sell_rate_cents": 25000,
                "commissionable_cents": 25000,
                "commission_cents": 4375,
            }
        ],
    )

    # The read that immediately follows the write agrees with it field by field.
    _assert_agrees(written, fixtures.read_reservation(api, written["id"]), "reservation")

    # 11 - 0 - 1 = 10 units of shared pool, recomputed by the booking itself.
    recomputed = fixtures.read_inventory_day(api, day["id"])
    assert_inventory_day(
        recomputed,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=1,
        shared=10,
        pooled_state="OPEN",
    )
    _assert_agrees(recomputed, fixtures.read_inventory_day(api, day["id"]), "inventory day")
    _assert_agrees(
        recomputed,
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        "inventory day",
    )
