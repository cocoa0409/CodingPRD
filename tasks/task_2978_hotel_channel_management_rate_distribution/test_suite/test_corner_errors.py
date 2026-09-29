"""Refusals the Hotel Channel Distribution contract owes its callers.

This module pins the error surface of the ordered validation of §2.7: the
family-specific 404 each unresolved path and body identifier earns, the
single-property scope rule that refuses a request whose identifiers all resolve
but do not share one property, the explicit sellable calendar that refuses any
date nobody opened, the six scoped uniqueness keys that all report one duplicate
code, the promotion-load prerequisite that counts only verified mappings, and the
state gates that a released allotment, a lifted restriction and a disabled
mapping enforce against the very transition that produced them. Every assertion
names the `error_id` the catalogue of §5 declares together with its HTTP status,
so a refusal that returns the right status with the wrong identifier still fails.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_MANAGER_HEADERS,
    ApiErrorId,
    assert_batch_counters,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_job,
    factories,
    fixtures,
)

# List reads here always ask for a full page, because the default page size is 10
# and a probe that silently truncated its page would assert nothing.
FULL_PAGE = 100


def _page(**filters):
    """Pagination controls asking for one full page, plus any list filters."""
    return factories.page_params(limit=FULL_PAGE, **filters)


def _total_count(response) -> int:
    """The `meta.total_count` of a list read: rows matching the filter."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


# ── Path identifiers resolve, each with its own 404 (§2.7 check 4) ──────────

# One entry per entity family addressed by its own identifier segment, with the
# `error_id` §2.7 check 4 pairs with that family.
_UNKNOWN_PATH_READS = [
    (
        "room_type",
        lambda api: api.get_room_type(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.ROOM_TYPE_NOT_FOUND,
    ),
    (
        "inventory_day",
        lambda api: api.get_inventory_day(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.INVENTORY_DAY_NOT_FOUND,
    ),
    (
        "channel",
        lambda api: api.get_channel(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.CHANNEL_NOT_FOUND,
    ),
    (
        "channel_connection",
        lambda api: api.get_connection(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.CONNECTION_NOT_FOUND,
    ),
    (
        "rate_plan",
        lambda api: api.get_rate_plan(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.RATE_PLAN_NOT_FOUND,
    ),
    (
        "channel_mapping",
        lambda api: api.get_mapping(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.CHANNEL_MAPPING_NOT_FOUND,
    ),
    (
        "allocation",
        lambda api: api.get_allocation(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.ALLOCATION_NOT_FOUND,
    ),
    (
        "restriction",
        lambda api: api.get_restriction(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.RESTRICTION_NOT_FOUND,
    ),
    (
        "promotion",
        lambda api: api.get_promotion(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.PROMOTION_NOT_FOUND,
    ),
    (
        "distribution_batch",
        lambda api: api.get_batch(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.BATCH_NOT_FOUND,
    ),
    (
        "distribution_job",
        lambda api: api.get_job(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.JOB_NOT_FOUND,
    ),
]


def _initialised_property(api):
    """The clock parked and one property registered; nothing else exists."""
    fixtures.set_clock(api)
    return fixtures.create_canonical_property(api)


@pytest.mark.parametrize(
    "read, expected_error",
    [pytest.param(read, error, id=name) for name, read, error in _UNKNOWN_PATH_READS],
)
def test_unknown_path_identifier_reports_its_own_not_found_error(api, read, expected_error):
    """A well-formed identifier that resolves to no row is refused at §2.7 check 4
    with the 404 that names the entity family which failed to resolve, and the
    error body carries nothing under `data` but `error_id` and `message`.

    Design: Corner/errors/every_path_scoped_entity_returns_its_own_not_found_error
    """
    _initialised_property(api)

    error_data = validate_error(read(api), expected_error.value, 404)

    assert set(error_data) == {"error_id", "message"}, (
        f"error data should carry only error_id and message, got {sorted(error_data)}"
    )


def test_the_eleven_path_not_found_errors_are_all_distinct(api):
    """The contract gives each entity family its own 404 rather than one shared
    generic code, so eleven unresolved identifier segments produce eleven
    different `error_id` values and leave the registered property untouched.

    Design: Corner/errors/every_path_scoped_entity_returns_its_own_not_found_error
    """
    _initialised_property(api)

    seen = []
    for _name, read, expected_error in _UNKNOWN_PATH_READS:
        seen.append(validate_error(read(api), expected_error.value, 404)["error_id"])

    assert len(seen) == 11, f"expected eleven probes, ran {len(seen)}"
    assert len(set(seen)) == 11, f"the eleven not-found codes should all differ, got {seen}"

    # A failed existence check has no side effect: the one property still stands.
    assert _total_count(api.list_properties(PLATFORM_ADMIN_HEADERS, _page())) == 1


# ── Body-borne foreign keys resolve too (§2.7 check 8) ──────────────────────


def test_unknown_rate_plan_id_in_a_mapping_body_is_a_rate_plan_not_found(api, world):
    """A mapping body names three foreign keys; when the rate plan does not
    resolve the contract refuses with the rate plan's own 404, even though the
    channel and room type both resolve.

    Design: Corner/errors/body_referenced_ids_resolve_to_their_own_not_found_error
    """
    payload = factories.mapping_payload(
        rate_plan_id=NON_EXISTENT_UUID,
        channel_id=world["channel_id"],
        room_type_id=world["room_type_id"],
        external_rate_code="X-1",
    )

    validate_error(
        api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.RATE_PLAN_NOT_FOUND.value,
        404,
    )

    assert fixtures.list_mappings(api) == []


def test_unknown_channel_id_in_a_mapping_body_is_a_channel_not_found(api, world):
    """The same body with an unresolvable channel reports the channel's own 404:
    each body-borne foreign key answers for itself rather than sharing one code.

    Design: Corner/errors/body_referenced_ids_resolve_to_their_own_not_found_error
    """
    payload = factories.mapping_payload(
        rate_plan_id=world["rate_plan_id"],
        channel_id=NON_EXISTENT_UUID,
        room_type_id=world["room_type_id"],
        external_rate_code="X-2",
    )

    validate_error(
        api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CHANNEL_NOT_FOUND.value,
        404,
    )

    assert fixtures.list_mappings(api) == []


def test_unknown_room_type_id_in_a_mapping_body_is_a_room_type_not_found(api, world):
    """The third foreign key of the mapping body behaves like the other two: an
    unresolvable room type is the room type's own 404.

    Design: Corner/errors/body_referenced_ids_resolve_to_their_own_not_found_error
    """
    payload = factories.mapping_payload(
        rate_plan_id=world["rate_plan_id"],
        channel_id=world["channel_id"],
        room_type_id=NON_EXISTENT_UUID,
        external_rate_code="X-3",
    )

    validate_error(
        api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.ROOM_TYPE_NOT_FOUND.value,
        404,
    )

    assert fixtures.list_mappings(api) == []


def test_unknown_parent_rate_plan_id_is_a_rate_plan_not_found_and_stores_nothing(api, world):
    """A derived plan's `parent_rate_plan_id` is resolved like any other foreign
    key, so a parent that does not exist is `ERR_RATE_PLAN_NOT_FOUND` and the
    derived plan is not stored.

    Design: Corner/errors/body_referenced_ids_resolve_to_their_own_not_found_error
    """
    payload = factories.derived_rate_plan_payload(
        parent_rate_plan_id=NON_EXISTENT_UUID,
        code="ORPHAN",
        offset_kind="AMOUNT",
        offset_amount_cents=1000,
        rate_class="PACKAGE",
        floor_amount_cents=20000,
        ceiling_amount_cents=60000,
    )

    validate_error(
        api.create_rate_plan(world["property_id"], payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.RATE_PLAN_NOT_FOUND.value,
        404,
    )

    codes = {plan["code"] for plan in fixtures.list_rate_plans(api)}
    assert codes == {fixtures.BAR_CODE}, f"only the seeded plan should exist, found {sorted(codes)}"


def test_unknown_channel_on_a_booking_outranks_the_missing_inventory_day(api, world):
    """Booking through an unresolvable channel on a night that was never opened
    could fail two ways; identifier resolution is priority 8 and the sellable-day
    prerequisite is priority 15, so the contract requires the channel's 404 and
    not `ERR_INVENTORY_DAY_NOT_OPEN`.

    Design: Corner/errors/body_referenced_ids_resolve_to_their_own_not_found_error
    """
    payload = factories.reservation_payload(
        channel_id=NON_EXISTENT_UUID,
        rate_plan_id=world["rate_plan_id"],
        room_type_id=world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
    )

    validate_error(
        api.create_reservation(payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.CHANNEL_NOT_FOUND.value,
        404,
    )

    assert fixtures.list_reservations(api) == []


# ── One request, one property (§2.7 check 9) ─────────────────────────────────


def _second_property(api):
    """A second property with its own room type and its own sellable channel.

    Nothing here is related to the seeded property, so any request that mixes the
    two has resolvable identifiers that nonetheless span two properties.
    """
    other = fixtures.create_property(
        api,
        code="HTL-LAX",
        name="Harborview LAX",
        currency_code="USD",
        overbooking_pct_bp=0,
        booking_horizon_days=365,
        mix_window_days=30,
        rate_mismatch_tolerance_cents=0,
        required_image_count=0,
    )
    room_type = fixtures.create_room_type(
        api,
        other["id"],
        code="LAXKING",
        name="LAX King",
        physical_capacity_units=4,
        master_description_hash="laxv1",
        master_image_count=3,
    )
    channel = fixtures.create_sellable_channel(
        api, other["id"], code="LAXCH", channel_kind="OTA_PUBLIC", commission_bp=1500
    )
    return {
        "property_id": other["id"],
        "room_type_id": room_type["id"],
        "channel_id": channel["channel"]["id"],
    }


def test_mapping_across_two_properties_is_a_scope_mismatch(api, world):
    """A mapping whose channel belongs to one property while its plan and room
    type belong to another has three resolvable identifiers, so the refusal is
    not a 404: the contract requires `ERR_PROPERTY_SCOPE_MISMATCH` at 409.

    Design: Corner/errors/cross_property_ids_in_one_request_are_refused
    """
    other = _second_property(api)

    payload = factories.mapping_payload(
        rate_plan_id=world["rate_plan_id"],
        channel_id=other["channel_id"],
        room_type_id=world["room_type_id"],
        external_rate_code="BAR-LAXCH-KING",
    )

    validate_error(
        api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.PROPERTY_SCOPE_MISMATCH.value,
        409,
    )

    assert fixtures.list_mappings(api) == []


def test_cross_property_booking_reports_scope_before_the_missing_inventory_day(api, world):
    """A booking that names another property's room type on this property's
    channel and plan is refused for scope, not for inventory: the single-property
    check is priority 9 and the sellable-day prerequisite is priority 15, and no
    night has been opened at all here.

    Design: Corner/errors/cross_property_ids_in_one_request_are_refused
    """
    other = _second_property(api)

    payload = factories.reservation_payload(
        channel_id=world["channel_id"],
        rate_plan_id=world["rate_plan_id"],
        room_type_id=other["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )

    validate_error(
        api.create_reservation(payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.PROPERTY_SCOPE_MISMATCH.value,
        409,
    )

    assert fixtures.list_reservations(api) == []


def test_cross_property_restriction_is_refused_and_queues_no_batch(api, world):
    """A restriction naming another property's room type alongside this
    property's rate plan is refused with `ERR_PROPERTY_SCOPE_MISMATCH`, and
    because the write never happens no distribution batch is queued for it.

    Design: Corner/errors/cross_property_ids_in_one_request_are_refused
    """
    other = _second_property(api)

    payload = factories.stop_sell_payload(
        room_type_id=other["room_type_id"],
        start_date="2026-09-15",
        end_date="2026-09-16",
        rate_plan_id=world["rate_plan_id"],
    )

    validate_error(
        api.create_restriction(payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.PROPERTY_SCOPE_MISMATCH.value,
        409,
    )

    assert fixtures.list_restrictions(api) == []
    assert fixtures.list_batches(api) == []


# ── The sellable calendar is explicit, per date (§2.7 check 15) ──────────────


def _world_with_only_the_first_night_open(api, world):
    """The canonical world with an inventory day on the first stay date only."""
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    return world


def test_two_night_booking_whose_second_night_is_closed_is_refused(api, world):
    """The sellable-day prerequisite is evaluated for every date the stay touches,
    so a two-night stay whose first night is open and whose second was never
    opened is refused with `ERR_INVENTORY_DAY_NOT_OPEN` and no reservation exists.

    Design: Corner/errors/booking_and_allotment_require_an_inventory_day_row_for_every_date_touched
    """
    _world_with_only_the_first_night_open(api, world)

    payload = factories.reservation_payload(
        channel_id=world["channel_id"],
        rate_plan_id=world["rate_plan_id"],
        room_type_id=world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=2,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )

    validate_error(
        api.create_reservation(payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.INVENTORY_DAY_NOT_OPEN.value,
        409,
    )

    assert fixtures.list_reservations(api) == []


def test_allotment_over_a_closed_night_is_refused_and_spends_no_version(api, world):
    """An allotment covering a date with no inventory day is refused for the same
    reason a booking is, and because the write never happened the room type's
    `version` is untouched, so the same echoed version still works afterwards.

    Design: Corner/errors/booking_and_allotment_require_an_inventory_day_row_for_every_date_touched
    """
    _world_with_only_the_first_night_open(api, world)
    version_before = fixtures.room_type_version(api, world["room_type_id"])

    payload = factories.allocation_payload(
        channel_id=world["channel_id"],
        allocated_units=2,
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE_2,
        expected_room_type_version=version_before,
    )

    validate_error(
        api.create_allocation(world["room_type_id"], payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.INVENTORY_DAY_NOT_OPEN.value,
        409,
    )

    assert fixtures.list_allocations(api) == []
    assert fixtures.room_type_version(api, world["room_type_id"]) == version_before


def test_opening_the_missing_night_admits_the_identical_allotment_and_booking(api, world):
    """Once the one missing night is opened, the identical allotment and the
    identical two-night booking are both accepted, the booking draws one held unit
    from the allotment on each night, and both nights balance the pool identity
    `ceiling == allocated + committed + shared`.

    Design: Corner/errors/booking_and_allotment_require_an_inventory_day_row_for_every_date_touched
    """
    _world_with_only_the_first_night_open(api, world)
    version_before = fixtures.room_type_version(api, world["room_type_id"])

    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE_2)

    # The refused allotment above spent no version, so the same echo is still current.
    allocation_payload = factories.allocation_payload(
        channel_id=world["channel_id"],
        allocated_units=2,
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE_2,
        expected_room_type_version=version_before,
    )
    allocation = validate_success(
        api.create_allocation(world["room_type_id"], allocation_payload, REVENUE_MANAGER_HEADERS),
        201,
    )

    reservation_payload = factories.reservation_payload(
        channel_id=world["channel_id"],
        rate_plan_id=world["rate_plan_id"],
        room_type_id=world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=2,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )
    validate_success(api.create_reservation(reservation_payload, REVENUE_MANAGER_HEADERS), 201)

    # Ceiling 11 = 10 + floor(10 x 1000 / 10000); the stay draws one of the two
    # held units on each night, so 1 stays held, 1 is committed and 9 are shared.
    for stay_date in (fixtures.STAY_DATE, fixtures.STAY_DATE_2):
        day = fixtures.inventory_day_on(api, world["room_type_id"], stay_date)
        assert_inventory_day(
            day,
            capacity=fixtures.KING_CAPACITY,
            ceiling=fixtures.KING_CEILING,
            allocated=1,
            committed=1,
            shared=9,
            pooled_state="OPEN",
        )

    drawn = fixtures.read_allocation(api, allocation["id"])
    assert_fields(drawn, {"consumed_units": 1, "allocation_state": "OPEN"}, "allocation")


# ── Six uniqueness keys, one duplicate error (§2.7 check 17) ─────────────────


PROMOTION_CODE = "MEMBER10"
MAPPING_CODE = "BAR-OTA1-KING"


def _world_with_one_of_everything(api):
    """One row per uniqueness-bearing family, all under one property.

    The channel's single connection is deliberately left `PENDING`: it is not
    `RETIRED`, so it still occupies the channel's one connection slot, and the
    rate plan is left in `DRAFT` because neither state participates in the
    uniqueness keys under test.
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
    fixtures.create_connection(
        api, channel["id"], protocol="JSON_PUSH", url=factories.endpoint_url(fixtures.OTA_CODE)
    )
    rate_plan = fixtures.create_canonical_rate_plan(api, property_row["id"])
    fixtures.open_inventory_day(api, room_type["id"], fixtures.STAY_DATE)
    fixtures.create_mapping_in_parity(
        api,
        rate_plan["id"],
        channel["id"],
        room_type["id"],
        external_rate_code=MAPPING_CODE,
    )
    fixtures.create_promotion(
        api,
        rate_plan["id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        code=PROMOTION_CODE,
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    return {
        "property_id": property_row["id"],
        "room_type_id": room_type["id"],
        "channel_id": channel["id"],
        "rate_plan_id": rate_plan["id"],
    }


def _duplicate_room_type(api, ctx):
    """Same `(property_id, code)`, every other field different."""
    payload = factories.room_type_payload(
        code=fixtures.KING_CODE,
        name="King Room Twin Bedded",
        physical_capacity_units=6,
        master_description_hash="kingv2",
        master_image_count=7,
    )
    return api.create_room_type(ctx["property_id"], payload, REVENUE_MANAGER_HEADERS)


def _duplicate_channel(api, ctx):
    """Same `(property_id, code)` under a different channel kind."""
    payload = factories.channel_payload(
        code=fixtures.OTA_CODE, channel_kind="OTA_OPAQUE", commission_bp=2500
    )
    return api.create_channel(ctx["property_id"], payload, PLATFORM_ADMIN_HEADERS)


def _duplicate_rate_plan(api, ctx):
    """Same `(property_id, code)` at a different base amount."""
    payload = factories.rate_plan_payload(
        code=fixtures.BAR_CODE,
        rate_class="PUBLIC",
        base_amount_cents=31000,
        floor_amount_cents=fixtures.BAR_FLOOR_CENTS,
        ceiling_amount_cents=fixtures.BAR_CEILING_CENTS,
    )
    return api.create_rate_plan(ctx["property_id"], payload, REVENUE_MANAGER_HEADERS)


def _duplicate_inventory_day(api, ctx):
    """Same `(room_type_id, stay_date)`."""
    payload = factories.inventory_day_payload(fixtures.STAY_DATE)
    return api.create_inventory_day(ctx["room_type_id"], payload, REVENUE_MANAGER_HEADERS)


def _duplicate_mapping(api, ctx):
    """Same (plan, channel, room type) triple under a different external code."""
    payload = factories.mapping_payload(
        rate_plan_id=ctx["rate_plan_id"],
        channel_id=ctx["channel_id"],
        room_type_id=ctx["room_type_id"],
        external_rate_code="BAR-OTA1-KING-ALT",
        content_description_hash=fixtures.KING_HASH,
        content_image_count=fixtures.KING_IMAGE_COUNT,
    )
    return api.create_mapping(payload, CHANNEL_OPS_ENGINEER_HEADERS)


def _duplicate_connection(api, ctx):
    """A second connection while the first is still not retired."""
    payload = factories.connection_payload(
        protocol="XML_PUSH", url="https://ota1-backup.example.com/ari"
    )
    return api.create_connection(ctx["channel_id"], payload, CHANNEL_OPS_ENGINEER_HEADERS)


def _duplicate_promotion(api, ctx):
    """Same `(rate_plan_id, code)` with a different discount and window."""
    payload = factories.amount_promotion_payload(
        start_date="2026-10-01",
        end_date="2026-10-31",
        discount_amount_cents=2000,
        code=PROMOTION_CODE,
        promo_kind="MEMBER_RATE",
    )
    return api.create_promotion(ctx["rate_plan_id"], payload, REVENUE_MANAGER_HEADERS)


_DUPLICATE_ATTEMPTS = [
    ("room_type", _duplicate_room_type),
    ("channel", _duplicate_channel),
    ("rate_plan", _duplicate_rate_plan),
    ("inventory_day", _duplicate_inventory_day),
    ("channel_mapping", _duplicate_mapping),
    ("channel_connection", _duplicate_connection),
    ("promotion", _duplicate_promotion),
]


@pytest.mark.parametrize(
    "attempt",
    [pytest.param(attempt, id=name) for name, attempt in _DUPLICATE_ATTEMPTS],
)
def test_duplicate_uniqueness_key_is_refused_for_each_scoped_family(api, attempt):
    """One `ERR_DUPLICATE_RESOURCE` covers six different uniqueness keys — the
    `(property_id, code)` of a room type, a channel and a rate plan, the
    `(rate_plan_id, code)` of a promotion, the `(room_type_id, stay_date)` of an
    inventory day, the (plan, channel, room type) triple of a mapping, and the one
    non-retired connection a channel may hold. The rest of the payload is
    irrelevant: only the key decides.

    Design: Corner/errors/duplicate_uniqueness_keys_are_refused_for_every_scoped_entity
    """
    ctx = _world_with_one_of_everything(api)

    validate_error(attempt(api, ctx), ApiErrorId.DUPLICATE_RESOURCE.value, 409)


def test_seven_refused_duplicates_leave_every_row_count_at_one(api):
    """Seven refusals in a row change nothing: the property still holds exactly one
    room type, one channel with one connection, one rate plan, one inventory day,
    one mapping and one promotion.

    Design: Corner/errors/duplicate_uniqueness_keys_are_refused_for_every_scoped_entity
    """
    ctx = _world_with_one_of_everything(api)

    for _name, attempt in _DUPLICATE_ATTEMPTS:
        validate_error(attempt(api, ctx), ApiErrorId.DUPLICATE_RESOURCE.value, 409)

    property_page = _page(property_id=ctx["property_id"])
    assert _total_count(api.list_room_types(REVENUE_MANAGER_HEADERS, property_page)) == 1
    assert _total_count(api.list_channels(PLATFORM_ADMIN_HEADERS, property_page)) == 1
    assert _total_count(api.list_rate_plans(REVENUE_MANAGER_HEADERS, property_page)) == 1
    assert len(fixtures.list_inventory_days(api, room_type_id=ctx["room_type_id"])) == 1
    assert len(fixtures.list_mappings(api, channel_id=ctx["channel_id"])) == 1
    assert len(fixtures.list_promotions(api, rate_plan_id=ctx["rate_plan_id"])) == 1
    assert (
        _total_count(
            api.list_connections(
                CHANNEL_OPS_ENGINEER_HEADERS, _page(channel_id=ctx["channel_id"])
            )
        )
        == 1
    )


# ── Loading counts verified mappings only (§2.7 check 15) ───────────────────


def _approved_promotion_over_a_draft_mapping(api, world):
    """An approved promotion on the seeded plan, whose only mapping is DRAFT."""
    mapping = fixtures.create_mapping_in_parity(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code=MAPPING_CODE,
    )
    promotion = fixtures.create_approved_promotion(
        api,
        world["rate_plan_id"],
        start_date="2026-09-01",
        end_date="2026-09-30",
        code=PROMOTION_CODE,
        promo_kind="MEMBER_RATE",
        discount_kind="PERCENT",
        discount_bp=1000,
    )
    return mapping, promotion


def test_loading_a_promotion_with_only_a_draft_mapping_is_refused(api, world):
    """The load prerequisite counts mappings in `VERIFIED` only, so a mapping
    still in `DRAFT` is no mapping at all and the load is refused with
    `ERR_CHANNEL_MAPPING_MISSING`; the promotion keeps its approval, its
    `NOT_LOADED` distribution status and its version, and no batch is queued.

    Design: Corner/errors/promotion_load_without_a_verified_mapping_is_refused_then_succeeds_after_verification
    """
    _mapping, promotion = _approved_promotion_over_a_draft_mapping(api, world)

    validate_error(
        api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CHANNEL_MAPPING_MISSING.value,
        409,
    )

    unchanged = fixtures.read_promotion(api, promotion["id"])
    assert_fields(
        unchanged,
        {
            "approval_status": "APPROVED",
            "distribution_status": "NOT_LOADED",
            "version": promotion["version"],
        },
        "promotion",
    )

    assert (
        fixtures.list_batches(api, property_id=world["property_id"], payload_kind="PROMOTION") == []
    )


def test_verifying_the_mapping_lets_the_same_promotion_load(api, world):
    """One verify call turns the same refused load into a success: the load
    queues exactly one `PROMOTION` batch that fans out one job over the
    now-verified mapping, and the distribution axis advances off `NOT_LOADED`
    while the approval axis stays `APPROVED`.

    Design: Corner/errors/promotion_load_without_a_verified_mapping_is_refused_then_succeeds_after_verification
    """
    mapping, promotion = _approved_promotion_over_a_draft_mapping(api, world)

    validate_error(
        api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.CHANNEL_MAPPING_MISSING.value,
        409,
    )

    verified = fixtures.verify_mapping(api, mapping["id"])
    assert_fields(verified, {"mapping_state": "VERIFIED"}, "mapping")

    loaded = validate_success(api.load_promotion(promotion["id"], CHANNEL_OPS_ENGINEER_HEADERS), 200)
    assert loaded["approval_status"] == "APPROVED", "loading must not touch the approval axis"
    assert loaded["distribution_status"] != "NOT_LOADED", (
        "a successful load moves the distribution axis off NOT_LOADED, "
        f"got {loaded['distribution_status']}"
    )

    batch = fixtures.only_batch(api, property_id=world["property_id"], payload_kind="PROMOTION")
    assert_batch_counters(batch, batch_state="QUEUED", total_jobs=1)

    jobs = fixtures.jobs_of(api, batch["id"])
    assert len(jobs) == 1, f"one verified mapping should fan out one job, got {len(jobs)}"
    assert_job(jobs[0], job_state="QUEUED", channel_mapping_id=mapping["id"])


# ── Terminal states refuse the transition that produced them (§2.7 check 11) ─


def _world_with_a_spendable_allotment(api, world):
    """One open night carrying one OPEN allotment of two units."""
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    allocation = fixtures.create_allocation(
        api,
        world["room_type_id"],
        world["channel_id"],
        allocated_units=2,
        start_date=fixtures.STAY_DATE,
        end_date=fixtures.STAY_DATE,
    )
    return allocation


def test_releasing_an_already_released_allotment_is_refused(api, world):
    """Release is `OPEN → RELEASED` and `RELEASED` is terminal, so the second
    release of the same allotment is `ERR_ALLOCATION_STATE_INVALID` and the night
    it had held keeps the pool the first release restored.

    Design: Corner/errors/spent_and_disabled_rows_refuse_their_transitions
    """
    allocation = _world_with_a_spendable_allotment(api, world)

    released = validate_success(
        api.release_allocation(allocation["id"], REVENUE_MANAGER_HEADERS), 200
    )
    assert_fields(released, {"allocation_state": "RELEASED"}, "allocation")

    # Releasing hands the two held units back, so the whole ceiling of 11 is shared.
    after_release = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        after_release,
        capacity=fixtures.KING_CAPACITY,
        ceiling=fixtures.KING_CEILING,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )

    validate_error(
        api.release_allocation(allocation["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.ALLOCATION_STATE_INVALID.value,
        409,
    )

    unchanged = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        unchanged,
        allocated=0,
        committed=0,
        shared=fixtures.KING_CEILING,
        pooled_state="OPEN",
    )


def test_lifting_an_already_lifted_restriction_is_refused(api, world):
    """`LIFTED` is terminal, so a second lift of the same restriction is
    `ERR_RESTRICTION_STATE_INVALID`, the `lifted_at` recorded by the first lift is
    preserved, and the refused call queues nothing — placement and the one
    successful lift account for both restriction batches.

    Design: Corner/errors/spent_and_disabled_rows_refuse_their_transitions
    """
    fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code=MAPPING_CODE,
    )
    restriction = fixtures.create_restriction(
        api,
        world["room_type_id"],
        "STOP_SELL",
        start_date="2026-09-15",
        end_date="2026-09-16",
    )

    lifted = validate_success(api.lift_restriction(restriction["id"], REVENUE_MANAGER_HEADERS), 200)
    assert_fields(
        lifted, {"restriction_state": "LIFTED", "lift_reason": "MANUAL_LIFT"}, "restriction"
    )

    validate_error(
        api.lift_restriction(restriction["id"], REVENUE_MANAGER_HEADERS),
        ApiErrorId.RESTRICTION_STATE_INVALID.value,
        409,
    )

    still_lifted = fixtures.read_restriction(api, restriction["id"])
    assert_instant_equals(still_lifted["lifted_at"], lifted["lifted_at"], "restriction.lifted_at")

    batches = fixtures.list_batches(
        api, property_id=world["property_id"], payload_kind="RESTRICTION"
    )
    assert len(batches) == 2, (
        f"placement and the accepted lift each queue one batch, got {len(batches)}"
    )


def test_a_disabled_mapping_refuses_even_the_verification_that_once_succeeded(api, world):
    """`DISABLED` admits no transition at all: after a verified mapping is
    disabled, verifying it again is `ERR_MAPPING_STATE_INVALID`, even though that
    very call is what made the mapping `VERIFIED` in the first place.

    Design: Corner/errors/spent_and_disabled_rows_refuse_their_transitions
    """
    mapping = fixtures.create_verified_mapping(
        api,
        world["rate_plan_id"],
        world["channel_id"],
        world["room_type_id"],
        external_rate_code=MAPPING_CODE,
    )

    disabled = validate_success(
        api.disable_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS), 200
    )
    assert_fields(disabled, {"mapping_state": "DISABLED"}, "mapping")

    validate_error(
        api.verify_mapping(mapping["id"], CHANNEL_OPS_ENGINEER_HEADERS),
        ApiErrorId.MAPPING_STATE_INVALID.value,
        409,
    )

    assert_fields(
        fixtures.read_mapping(api, mapping["id"]), {"mapping_state": "DISABLED"}, "mapping"
    )
