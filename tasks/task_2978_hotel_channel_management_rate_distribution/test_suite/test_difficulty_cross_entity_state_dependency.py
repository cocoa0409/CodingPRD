"""Writes whose admission is decided by the lifecycle state of a *neighbouring*
entity: a stay depends on its channel's connection being sellable, a promotion
load depends on the content parity of the mappings it would fan out to, and a
mapping verification depends on its rate plan being ACTIVE. In each case the row
being written never changes, yet the same request flips between accepted and
refused as the neighbour moves through its own state machine.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_batch_counters,
    assert_field_set,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    assert_nightly_breakdown,
    assert_reservation_totals,
    assert_unchanged,
    assert_version,
)
from test_helpers import factories, fixtures

# BAR sells at 25000 on OTA1: 25000 x (10000 + 0) / 10000 = 25000, inside the
# [18000, 40000] band, plus a package inclusion of 0 -> a sell rate of 25000.
# Commission is 25000 x 1750 / 10000 = 4375, so the net is 25000 - 4375 = 20625.
_SELL_RATE_CENTS = 25000
_COMMISSION_CENTS = 4375
_NET_CENTS = 20625

_ONE_NIGHT_AT_BAR = [
    {
        "stay_date": fixtures.STAY_DATE,
        "sell_rate_cents": _SELL_RATE_CENTS,
        "commissionable_cents": _SELL_RATE_CENTS,
        "commission_cents": _COMMISSION_CENTS,
    }
]


def _scene_with_pending_connection(api):
    """The canonical world, except the OTA's connection is left unactivated.

    Everything a stay needs is present -- an open night, an ACTIVE public plan
    and a channel that serves US-CA -- so the only thing standing between a
    booking and a confirmation is the connection's own state.
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
        allows_member_rate=True,
        geo_market_codes=[fixtures.OTA_GEO_MARKET],
    )
    connection = fixtures.create_connection(
        api, channel["id"], url=factories.endpoint_url(channel["code"])
    )
    rate_plan = fixtures.create_active_rate_plan(
        api,
        property_row["id"],
        code=fixtures.BAR_CODE,
        rate_class="PUBLIC",
        base_amount_cents=fixtures.BAR_BASE_CENTS,
        floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
        ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
    )
    fixtures.open_inventory_day(api, room_type["id"], fixtures.STAY_DATE)
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": channel["id"],
        "connection_id": connection["id"],
        "rate_plan_id": rate_plan["id"],
    }


def _book_one_night(api, scene):
    """Post the same one-night stay on OTA1, returning the raw response.

    OTA1 serves only US-CA, so the geo market is always declared; without it the
    contract would refuse the stay for the wrong reason.
    """
    payload = factories.reservation_payload(
        channel_id=scene["channel_id"],
        rate_plan_id=scene["rate_plan_id"],
        room_type_id=scene["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    return api.create_reservation(payload, REVENUE_MANAGER_HEADERS)


def test_booking_admission_sweeps_the_connection_state_machine(api):
    """Only a HEALTHY or DEGRADED connection is sellable: the identical one-night
    stay is refused with ERR_CONNECTION_NOT_SELLABLE while its channel's
    connection is PENDING, SUSPENDED or RETIRED, and confirmed in between.

    Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_channel_connection_state
    """
    scene = _scene_with_pending_connection(api)

    pending = fixtures.read_connection(api, scene["connection_id"])
    assert_fields(
        pending,
        {"connection_state": "PENDING", "consecutive_failures": 0, "suspended_at": None},
        "connection",
    )

    # PENDING is not sellable, and the refusal leaves the night untouched.
    validate_error(
        _book_one_night(api, scene),
        ApiErrorId.CONNECTION_NOT_SELLABLE.value,
        409,
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, scene["room_type_id"], fixtures.STAY_DATE),
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    healthy = fixtures.activate_connection(api, scene["connection_id"])
    assert_fields(
        healthy,
        {"connection_state": "HEALTHY", "consecutive_failures": 0, "suspended_at": None},
        "connection",
    )

    # HEALTHY is sellable: 25000 gross, 4375 commission, 20625 net on one night.
    reservation = validate_success(_book_one_night(api, scene), 201)
    assert_fields(
        reservation,
        {"reservation_state": "CONFIRMED", "overbooking_overridden": False},
        "reservation",
    )
    assert_nightly_breakdown(reservation, _ONE_NIGHT_AT_BAR)
    assert_reservation_totals(
        reservation,
        gross=_SELL_RATE_CENTS,
        commission=_COMMISSION_CENTS,
        net=_NET_CENTS,
        loyalty_credit=0,  # gross 25000 is below the 50000 tier-1 floor
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, scene["room_type_id"], fixtures.STAY_DATE),
        allocated=0,
        committed=1,
        shared=fixtures.KING_CEILING - 1,
        pooled_state="OPEN",
    )

    # One failure event degrades the connection, which stays sellable.
    degraded = fixtures.fail_connection(api, scene["connection_id"], failure_code="TIMEOUT")
    assert_fields(
        degraded,
        {
            "connection_state": "DEGRADED",
            "consecutive_failures": 1,
            "last_failure_code": "TIMEOUT",
            "suspended_at": None,
        },
        "connection",
    )
    second = validate_success(_book_one_night(api, scene), 201)
    assert_fields(second, {"reservation_state": "CONFIRMED"}, "reservation")
    assert_inventory_day(
        fixtures.inventory_day_on(api, scene["room_type_id"], fixtures.STAY_DATE),
        committed=2,
        shared=fixtures.KING_CEILING - 2,
    )

    # The second and third failures take the streak to the threshold of three.
    suspended = fixtures.fail_connection(
        api, scene["connection_id"], times=2, failure_code="TIMEOUT"
    )
    assert_fields(
        suspended,
        {
            "connection_state": "SUSPENDED",
            "consecutive_failures": 3,
            "last_failure_code": "TIMEOUT",
        },
        "connection",
    )
    assert_instant_equals(
        suspended["suspended_at"], fixtures.FIXTURE_CLOCK, "connection.suspended_at"
    )
    validate_error(
        _book_one_night(api, scene),
        ApiErrorId.CONNECTION_NOT_SELLABLE.value,
        409,
    )

    retired = validate_success(
        api.retire_connection(scene["connection_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert_fields(retired, {"connection_state": "RETIRED"}, "connection")
    validate_error(
        _book_one_night(api, scene),
        ApiErrorId.CONNECTION_NOT_SELLABLE.value,
        409,
    )

    # Neither refusal committed a unit, and both confirmed stays survive.
    assert_inventory_day(
        fixtures.inventory_day_on(api, scene["room_type_id"], fixtures.STAY_DATE),
        allocated=0,
        committed=2,
        shared=fixtures.KING_CEILING - 2,
        pooled_state="OPEN",
    )
    assert len(fixtures.list_reservations(api, reservation_state="CONFIRMED")) == 2


def test_suspending_the_connection_under_a_confirmed_stay_refuses_the_next_booking(api, world):
    """Sellability is read at admission time, so the same request that was
    confirmed is refused once three failure events suspend the connection, and is
    admitted again once revalidation returns it to DEGRADED -- while the stay
    already on the books is never touched.

    Design: Difficulty/cross_entity_state_dependency/booking_admission_depends_on_channel_connection_state
    """
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)

    first = validate_success(_book_one_night(api, world), 201)
    assert_fields(first, {"reservation_state": "CONFIRMED"}, "reservation")
    assert_version(first, 1, "reservation")
    assert_reservation_totals(
        first, gross=_SELL_RATE_CENTS, commission=_COMMISSION_CENTS, net=_NET_CENTS
    )

    # Three consecutive failure events on the neighbouring connection.
    suspended = fixtures.suspend_connection(api, world["connection_id"], failure_code="TIMEOUT")
    assert_fields(
        suspended,
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        "connection",
    )

    validate_error(
        _book_one_night(api, world),
        ApiErrorId.CONNECTION_NOT_SELLABLE.value,
        409,
    )

    # Nothing about the booked row moved, and the night still holds one unit.
    unchanged = fixtures.read_reservation(api, first["id"])
    assert_unchanged(
        first,
        unchanged,
        [
            "reservation_state",
            "version",
            "gross_amount_cents",
            "commission_amount_cents",
            "net_amount_cents",
            "cancelled_at",
        ],
        "reservation",
    )
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        allocated=0,
        committed=1,
        shared=fixtures.KING_CEILING - 1,
    )

    # Revalidation puts the connection back to DEGRADED, one below the threshold,
    # and the identical request is admitted again with no change of its own.
    revalidated = fixtures.revalidate_connection(api, world["connection_id"])
    assert_fields(
        revalidated,
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        "connection",
    )

    third = validate_success(_book_one_night(api, world), 201)
    assert_fields(third, {"reservation_state": "CONFIRMED"}, "reservation")
    assert_nightly_breakdown(third, _ONE_NIGHT_AT_BAR)
    assert_inventory_day(
        fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE),
        committed=2,
        shared=fixtures.KING_CEILING - 2,
    )


# A September member offer, ten percent off, well inside the booking horizon.
_PROMO_START = "2026-09-01"
_PROMO_END = "2026-09-30"
_PROMO_DISCOUNT_BP = 1000


def test_promotion_load_is_blocked_until_mapping_parity_is_repaired(api, world):
    """A load fans out to every VERIFIED mapping of the plan, so on a channel that
    demands content parity it is refused with ERR_CONTENT_PARITY_BLOCKED while one
    of those mappings is OUT_OF_PARITY, and queues its batch once the content is
    repaired -- without ever touching the promotion's approval axis.

    Design: Difficulty/cross_entity_state_dependency/promotion_load_depends_on_channel_mapping_parity_state
    """
    assert world["channel"]["requires_content_parity"] is True

    mapping = fixtures.create_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code="BAR_OTA1_KING",
        content_description_hash=fixtures.KING_HASH,
        # 4 images, one short of the property's required_image_count of 5
        content_image_count=fixtures.PROPERTY_REQUIRED_IMAGE_COUNT - 1,
    )
    verified = fixtures.verify_mapping(api, mapping["id"])
    assert_fields(
        verified,
        {"mapping_state": "VERIFIED", "parity_state": "OUT_OF_PARITY"},
        "mapping",
    )

    promotion = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date=_PROMO_START,
        end_date=_PROMO_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=_PROMO_DISCOUNT_BP,
    )
    assert_fields(
        promotion,
        {"approval_status": "DRAFT", "distribution_status": "NOT_LOADED"},
        "promotion",
    )

    validate_error(
        api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CONTENT_PARITY_BLOCKED.value,
        409,
    )
    refused = fixtures.read_promotion(api, promotion["id"])
    assert_fields(refused, {"distribution_status": "NOT_LOADED"}, "promotion")
    assert_version(refused, 1, "promotion")
    assert fixtures.list_batches(api) == [], "a refused load must queue nothing"

    # Publishing the fifth image puts the mapping exactly at the floor, which passes.
    repaired = fixtures.patch_mapping_content(
        api, mapping["id"], content_image_count=fixtures.PROPERTY_REQUIRED_IMAGE_COUNT
    )
    assert_fields(
        repaired,
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "mapping",
    )

    loaded = validate_success(
        api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        loaded,
        {"distribution_status": "LOADING", "approval_status": "DRAFT"},
        "promotion",
    )
    assert_version(loaded, 2, "promotion")

    batch = fixtures.only_batch(api)
    assert_fields(
        batch,
        {
            "payload_kind": "PROMOTION",
            "source_ref_kind": "PROMOTION",
            "source_ref_id": promotion["id"],
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
    jobs = fixtures.jobs_of(api, batch["id"])
    assert len(jobs) == 1, f"the load should fan out one job, got {len(jobs)}"
    assert_job(jobs[0], job_state="QUEUED", attempt_count=0, channel_mapping_id=mapping["id"])


def test_breaking_room_type_content_under_a_verified_mapping_blocks_the_next_load(api, world):
    """Parity is a comparison and either side of it can move: republishing the room
    type's master description hash re-evaluates the mapping to OUT_OF_PARITY with
    no write to the mapping or to any promotion, and the next load on that plan
    turns from accepted into ERR_CONTENT_PARITY_BLOCKED.

    Design: Difficulty/cross_entity_state_dependency/promotion_load_depends_on_channel_mapping_parity_state
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
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "mapping",
    )

    first = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date=_PROMO_START,
        end_date=_PROMO_END,
        code="MEMBER10",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=_PROMO_DISCOUNT_BP,
    )
    second = fixtures.create_promotion(
        api,
        world["rate_plan_id"],
        start_date=_PROMO_START,
        end_date=_PROMO_END,
        code="MEMBER15",
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1500,
    )

    # While the mapping is in parity the load is admitted.
    loaded = validate_success(api.load_promotion(first["id"], CHANNEL_OPS_ENGINEER_HEADERS))
    assert_fields(loaded, {"distribution_status": "LOADING"}, "promotion")

    moved = validate_success(
        api.patch_room_type(
            world["room_type_id"],
            factories.room_type_patch_payload(master_description_hash="kingv2"),
            REVENUE_MANAGER_HEADERS,
        )
    )
    assert_fields(moved, {"master_description_hash": "kingv2"}, "room type")

    # The mapping's own content is untouched; only the master it is compared to moved.
    broken = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        broken,
        {
            "mapping_state": "VERIFIED",
            "parity_state": "OUT_OF_PARITY",
            "content_description_hash": fixtures.KING_HASH,
            "content_image_count": fixtures.KING_IMAGE_COUNT,
        },
        "mapping",
    )

    validate_error(
        api.load_promotion(second["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CONTENT_PARITY_BLOCKED.value,
        409,
    )
    untouched = fixtures.read_promotion(api, second["id"])
    assert_fields(
        untouched,
        {"distribution_status": "NOT_LOADED", "approval_status": "DRAFT"},
        "promotion",
    )
    assert_version(untouched, 1, "promotion")

    # Only the admitted load ever produced a batch.
    batches = fixtures.list_batches(api)
    assert len(batches) == 1, f"exactly one load should have queued a batch, got {len(batches)}"
    assert_fields(batches[0], {"source_ref_id": first["id"]}, "batch")


# The mapping's serialized form: a verified mapping carries no verification instant.
_MAPPING_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "rate_plan_id",
    "channel_id",
    "room_type_id",
    "external_rate_code",
    "mapping_state",
    "content_description_hash",
    "content_image_count",
    "parity_state",
    "last_push_at",
    "last_pushed_rate_cents",
    "observed_rate_cents",
    "observed_stay_date",
    "mismatch_state",
    "mismatch_delta_cents",
)


def _scene_with_draft_plan(api):
    """The canonical world with two room types, except BAR is left in DRAFT."""
    fixtures.set_clock(api)
    property_row = fixtures.create_canonical_property(api)
    king = fixtures.create_king_room_type(api, property_row["id"])
    twin = fixtures.create_twin_room_type(api, property_row["id"])
    ota = fixtures.create_ota_channel(api, property_row["id"])
    rate_plan = fixtures.create_canonical_rate_plan(api, property_row["id"])
    return {
        "property_id": property_row["id"],
        "king_room_type_id": king["id"],
        "twin_room_type_id": twin["id"],
        "channel_id": ota["channel"]["id"],
        "connection_id": ota["connection"]["id"],
        "rate_plan_id": rate_plan["id"],
    }


def test_mapping_verification_sweeps_the_rate_plan_lifecycle(api):
    """A draft product is not verifiable: creating the mapping against a DRAFT plan
    is allowed, verifying it is refused with ERR_RATE_PLAN_STATE_INVALID and spends
    no version, and the identical verification succeeds once the plan is ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/mapping_verification_depends_on_rate_plan_lifecycle_state
    """
    scene = _scene_with_draft_plan(api)
    drafted_plan = fixtures.read_rate_plan(api, scene["rate_plan_id"])
    assert_fields(drafted_plan, {"plan_state": "DRAFT"}, "rate plan")
    assert_version(drafted_plan, 1, "rate plan")

    mapping = fixtures.create_mapping_in_parity(
        api,
        scene["rate_plan_id"],
        scene["channel_id"],
        scene["king_room_type_id"],
        external_rate_code="BAR_OTA1_KING",
    )
    assert_fields(
        mapping,
        {"mapping_state": "DRAFT", "parity_state": "IN_PARITY"},
        "mapping",
    )
    assert_version(mapping, 1, "mapping")

    validate_error(
        api.verify_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.RATE_PLAN_STATE_INVALID.value,
        409,
    )
    refused = fixtures.read_mapping(api, mapping["id"])
    assert_fields(
        refused,
        {"mapping_state": "DRAFT", "parity_state": "IN_PARITY"},
        "mapping",
    )
    assert_version(refused, 1, "mapping")

    activated = fixtures.activate_rate_plan(api, scene["rate_plan_id"])
    assert_fields(activated, {"plan_state": "ACTIVE"}, "rate plan")
    assert_version(activated, 2, "rate plan")

    verified = validate_success(
        api.verify_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS)
    )
    assert_fields(
        verified,
        {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
        "mapping",
    )
    assert_version(verified, 2, "mapping")
    assert_field_set(verified, _MAPPING_FIELDS, "mapping")


def test_activating_the_plan_under_two_untouched_mappings_admits_both_verifications(api):
    """Verifiability lives on the parent plan, not on the mapping: two mappings of
    one DRAFT plan are both refused, a single activation of the plan flips both to
    verifiable, and neither mapping's own fields or version moved in between.

    Design: Difficulty/cross_entity_state_dependency/mapping_verification_depends_on_rate_plan_lifecycle_state
    """
    scene = _scene_with_draft_plan(api)

    king_mapping = fixtures.create_mapping_in_parity(
        api,
        scene["rate_plan_id"],
        scene["channel_id"],
        scene["king_room_type_id"],
        external_rate_code="BAR_OTA1_KING",
    )
    twin_mapping = fixtures.create_mapping_in_parity(
        api,
        scene["rate_plan_id"],
        scene["channel_id"],
        scene["twin_room_type_id"],
        external_rate_code="BAR_OTA1_TWIN",
    )

    for mapping in (king_mapping, twin_mapping):
        assert_fields(
            mapping,
            {"mapping_state": "DRAFT", "parity_state": "IN_PARITY"},
            "mapping",
        )
        validate_error(
            api.verify_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS),
            ApiErrorId.RATE_PLAN_STATE_INVALID.value,
            409,
        )
        after_refusal = fixtures.read_mapping(api, mapping["id"])
        assert_unchanged(
            mapping,
            after_refusal,
            [
                "mapping_state",
                "parity_state",
                "version",
                "updated_at",
                "content_description_hash",
                "content_image_count",
            ],
            "mapping",
        )

    # One write, on the parent, with nothing written to either child.
    activated = fixtures.activate_rate_plan(api, scene["rate_plan_id"])
    assert_fields(activated, {"plan_state": "ACTIVE"}, "rate plan")
    assert_version(activated, 2, "rate plan")

    for mapping in (king_mapping, twin_mapping):
        verified = validate_success(
            api.verify_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS)
        )
        assert_fields(
            verified,
            {"mapping_state": "VERIFIED", "parity_state": "IN_PARITY"},
            "mapping",
        )
        # Version 1 on creation, and 2 spent by the one verification that stuck.
        assert_version(verified, 2, "mapping")

    assert len(fixtures.list_mappings(api, mapping_state="VERIFIED")) == 2
