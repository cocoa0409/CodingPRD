"""Entity shape, declared defaults and identity rules of the Hotel Channel Distribution API.

This module pins what the contract says a row *is*: the exact serialized field set of a
property, a room type, an inventory day, a channel, a connection, a rate plan, a channel
mapping and a freeze window; the value each optional input takes when it is omitted from
the body; the derived fields a client may not supply; the page block a list read carries;
and the refusals that guard a create path whose parent, body or enum value does not hold.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    CHANNEL_OPS_ENGINEER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    REVENUE_DIRECTOR_HEADERS,
    REVENUE_MANAGER_HEADERS,
    assert_channel_ledger,
    assert_common_fields,
    assert_create_only_fields,
    assert_field_set,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    assert_pagination_meta,
    factories,
    fixtures,
)

# ── The serialized field sets the contract declares, entity by entity ──────

PROPERTY_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "code",
    "name",
    "currency_code",
    "overbooking_pct_bp",
    "booking_horizon_days",
    "mix_window_days",
    "rate_mismatch_tolerance_cents",
    "required_image_count",
]

ROOM_TYPE_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "property_id",
    "code",
    "name",
    "physical_capacity_units",
    "overbooking_pct_bp",
    "master_description_hash",
    "master_image_count",
    "effective_overbooking_pct_bp",
]

INVENTORY_DAY_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "room_type_id",
    "stay_date",
    "physical_capacity_units",
    "overbooking_ceiling_units",
    "allocated_units",
    "shared_pool_units",
    "committed_units",
    "pooled_state",
]

CHANNEL_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "property_id",
    "code",
    "channel_kind",
    "commission_bp",
    "sell_adjustment_bp",
    "allows_member_rate",
    "allows_opaque_rate",
    "geo_market_codes",
    "requires_content_parity",
    "gross_revenue_cents",
    "commission_accrued_cents",
    "net_revenue_cents",
    "room_nights_sold",
    "bookings_count",
    "cancellations_count",
    "mismatch_alert_count",
]

EMPTY_LEDGER = {
    "gross_revenue_cents": 0,
    "commission_accrued_cents": 0,
    "net_revenue_cents": 0,
    "room_nights_sold": 0,
    "bookings_count": 0,
    "cancellations_count": 0,
    "mismatch_alert_count": 0,
}

CONNECTION_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "channel_id",
    "protocol",
    "endpoint_url",
    "heartbeat_interval_minutes",
    "connection_state",
    "consecutive_failures",
    "last_heartbeat_at",
    "last_failure_code",
    "suspended_at",
]

RATE_PLAN_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "version",
    "property_id",
    "code",
    "rate_class",
    "parent_rate_plan_id",
    "base_amount_cents",
    "offset_kind",
    "offset_bp",
    "offset_amount_cents",
    "floor_amount_cents",
    "ceiling_amount_cents",
    "package_inclusion_cents",
    "member_only",
    "negotiated_account_code",
    "plan_state",
    "derivation_depth",
    "resolved_base_amount_cents",
]

MAPPING_FIELDS = [
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
]

# A freeze window is the one entity with no updated_at and no version at all.
FREEZE_WINDOW_FIELDS = [
    "id",
    "created_at",
    "connection_id",
    "starts_at",
    "ends_at",
    "reason",
    "effective_starts_at",
]

ERROR_DATA_FIELDS = ["error_id", "message"]


# ── Property ───────────────────────────────────────────────────────────────


def test_property_create_echoes_every_input_and_adds_the_common_fields(api):
    """A property created with every optional field supplied serializes exactly the twelve
    declared fields, echoes each supplied value, and carries a server-generated id, a
    creation instant read from the logical clock, and version 1.

    Design: Corner/entities/property_create_returns_full_entity_with_common_fields
    """
    fixtures.set_clock(api)
    payload = factories.property_payload(
        code="HTL-SFO",
        name="Harborview SFO",
        currency_code="USD",
        overbooking_pct_bp=1000,
        booking_horizon_days=365,
        mix_window_days=30,
        rate_mismatch_tolerance_cents=200,
        required_image_count=5,
    )

    created = validate_success(api.create_property(payload, PLATFORM_ADMIN_HEADERS), 201)

    assert_field_set(created, PROPERTY_FIELDS, "property")
    assert_common_fields(created, "property")
    assert_fields(
        created,
        {
            "code": "HTL-SFO",
            "name": "Harborview SFO",
            "currency_code": "USD",
            "overbooking_pct_bp": 1000,
            "booking_horizon_days": 365,
            "mix_window_days": 30,
            "rate_mismatch_tolerance_cents": 200,
            "required_image_count": 5,
            "version": 1,
        },
        "property",
    )
    assert_instant_equals(created["created_at"], fixtures.FIXTURE_CLOCK, "property.created_at")
    assert_instant_equals(created["updated_at"], fixtures.FIXTURE_CLOCK, "property.updated_at")

    # The read of the same row returns the same field set holding the same values.
    read = validate_success(api.get_property(created["id"], REVENUE_MANAGER_HEADERS))
    assert_field_set(read, PROPERTY_FIELDS, "property read")
    assert_fields(read, created, "property read")


def test_property_defaults_applied_when_every_optional_field_is_omitted(api):
    """A property created with only a code and a name takes the declared defaults: USD, no
    overbooking allowance, a 365-day horizon, a 30-day mix window, a zero mismatch tolerance
    and no required images.

    Design: Corner/entities/property_defaults_applied_when_optional_fields_omitted
    """
    fixtures.set_clock(api)
    payload = factories.property_payload(code="HTL-LAX", name="Harborview LAX")
    assert set(payload) == {"code", "name"}

    created = validate_success(api.create_property(payload, PLATFORM_ADMIN_HEADERS), 201)

    assert_field_set(created, PROPERTY_FIELDS, "property")
    assert_fields(
        created,
        {
            "code": "HTL-LAX",
            "currency_code": "USD",
            "overbooking_pct_bp": 0,
            "booking_horizon_days": 365,
            "mix_window_days": 30,
            "rate_mismatch_tolerance_cents": 0,
            "required_image_count": 0,
            "version": 1,
        },
        "property",
    )

    read = validate_success(api.get_property(created["id"], REVENUE_MANAGER_HEADERS))
    assert_fields(read, created, "property read")


def test_room_type_omitted_overbooking_override_is_null_and_inherits_the_property(api):
    """A room type created without an overbooking override stores null there, meaning inherit,
    so its effective allowance is the property's. A night opened on that room type takes its
    ceiling from the effective allowance rather than from the omitted override.

    Design: Corner/entities/property_defaults_applied_when_optional_fields_omitted
    """
    fixtures.set_clock(api)
    prop = fixtures.create_property(api, code="HTL-LAX", name="Harborview LAX")

    room_type = validate_success(
        api.create_room_type(
            prop["id"],
            factories.room_type_payload(code="KING", name="King Room", physical_capacity_units=10),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )

    assert_field_set(room_type, ROOM_TYPE_FIELDS, "room type")
    assert_common_fields(room_type, "room type")
    assert_fields(
        room_type,
        {
            "property_id": prop["id"],
            "code": "KING",
            "physical_capacity_units": 10,
            "overbooking_pct_bp": None,
            "effective_overbooking_pct_bp": 0,  # inherited from the property's default of 0
            "version": 1,
        },
        "room type",
    )

    day = validate_success(
        api.create_inventory_day(
            room_type["id"],
            factories.inventory_day_payload(fixtures.STAY_DATE),
            REVENUE_MANAGER_HEADERS,
        ),
        201,
    )
    # 10 + floor(10 x 0 / 10000) = 10 ceiling; 10 - 0 - 0 = 10 shared.
    assert_inventory_day(
        day, capacity=10, ceiling=10, allocated=0, committed=0, shared=10, pooled_state="OPEN"
    )


# ── Channel and connectivity ───────────────────────────────────────────────


def test_channel_defaults_applied_when_optional_flags_are_omitted(api):
    """A channel created with only a code, a kind and a commission takes the declared flag
    defaults — no sell adjustment, no member rates, no opaque rates, an empty geo-market list
    and content parity required — and opens with an all-zero lifetime ledger.

    Design: Corner/entities/channel_defaults_applied_when_optional_flags_omitted
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    payload = factories.channel_payload(code="OTA1", channel_kind="OTA_PUBLIC", commission_bp=1750)
    assert set(payload) == {"code", "channel_kind", "commission_bp"}

    channel = validate_success(
        api.create_channel(prop["id"], payload, PLATFORM_ADMIN_HEADERS), 201
    )

    assert_field_set(channel, CHANNEL_FIELDS, "channel")
    assert_common_fields(channel, "channel")
    assert_fields(
        channel,
        {
            "property_id": prop["id"],
            "code": "OTA1",
            "channel_kind": "OTA_PUBLIC",
            "commission_bp": 1750,
            "sell_adjustment_bp": 0,
            "allows_member_rate": False,
            "allows_opaque_rate": False,
            "geo_market_codes": [],
            "requires_content_parity": True,
            "version": 1,
        },
        "channel",
    )
    assert_channel_ledger(channel, EMPTY_LEDGER)


def test_connection_defaults_applied_when_the_heartbeat_interval_is_omitted(api):
    """A connection created with only a protocol and an endpoint opens PENDING with a
    fifteen-minute heartbeat interval, a zero failure streak and no heartbeat, failure code or
    suspension instant recorded yet.

    Design: Corner/entities/channel_defaults_applied_when_optional_flags_omitted
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    channel = fixtures.create_channel(api, prop["id"], code="OTA1")
    payload = factories.connection_payload(
        protocol="JSON_PUSH", url=factories.endpoint_url("OTA1")
    )
    assert set(payload) == {"protocol", "endpoint_url"}

    connection = validate_success(
        api.create_connection(channel["id"], payload, CHANNEL_OPS_ENGINEER_HEADERS), 201
    )

    assert_field_set(connection, CONNECTION_FIELDS, "channel connection")
    assert_common_fields(connection, "channel connection")
    assert_fields(
        connection,
        {
            "channel_id": channel["id"],
            "protocol": "JSON_PUSH",
            "endpoint_url": factories.endpoint_url("OTA1"),
            "heartbeat_interval_minutes": 15,
            "connection_state": "PENDING",
            "consecutive_failures": 0,
            "last_heartbeat_at": None,
            "last_failure_code": None,
            "suspended_at": None,
            "version": 1,
        },
        "channel connection",
    )


def test_channel_create_with_an_undeclared_channel_kind_is_an_invalid_request(api):
    """A channel kind outside the five declared values fails the request-shape check with
    ERR_INVALID_REQUEST, and no channel row is left behind.

    Design: Corner/entities/channel_create_with_invalid_enum_channel_kind_rejected
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    payload = factories.channel_payload(
        code="OTA1", channel_kind="OTA_SEMI_OPAQUE", commission_bp=1750
    )

    error = validate_error(
        api.create_channel(prop["id"], payload, PLATFORM_ADMIN_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )
    assert_field_set(error, ERROR_DATA_FIELDS, "error data")

    rows, meta = validate_paginated(
        api.list_channels(PLATFORM_ADMIN_HEADERS, factories.page_params(property_id=prop["id"]))
    )
    assert rows == []
    assert_pagination_meta(meta, total_count=0, has_more=False)


# ── Rate plans ─────────────────────────────────────────────────────────────


def _property_with_three_plans(api):
    """One property carrying an ACTIVE plan and two DRAFT plans, all public root plans."""
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    active = fixtures.create_canonical_rate_plan(api, prop["id"])
    fixtures.activate_rate_plan(api, active["id"])
    second = fixtures.create_rate_plan(
        api,
        prop["id"],
        code="BAR2",
        base_amount_cents=26000,
        floor_amount_cents=18000,
        ceiling_amount_cents=40000,
    )
    third = fixtures.create_rate_plan(
        api,
        prop["id"],
        code="BAR3",
        base_amount_cents=27000,
        floor_amount_cents=18000,
        ceiling_amount_cents=40000,
    )
    return {
        "property_id": prop["id"],
        "active_id": active["id"],
        "plan_ids": {active["id"], second["id"], third["id"]},
    }


def test_rate_plan_read_returns_its_stored_inputs_with_the_derived_price_fields(api):
    """A read of a public root plan returns exactly the declared rate-plan fields: the amounts
    as supplied, the omitted optionals at their defaults, a DRAFT state at version 1, and the
    derived pair — depth 0 and a resolved base equal to the plan's own base amount.

    Design: Corner/entities/rate_plan_retrieval_returns_stored_and_derived_fields
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    plan = fixtures.create_canonical_rate_plan(api, prop["id"])

    read = validate_success(api.get_rate_plan(plan["id"], REVENUE_DIRECTOR_HEADERS))

    assert_field_set(read, RATE_PLAN_FIELDS, "rate plan")
    assert_common_fields(read, "rate plan")
    assert_fields(
        read,
        {
            "id": plan["id"],
            "property_id": prop["id"],
            "code": "BAR",
            "rate_class": "PUBLIC",
            "parent_rate_plan_id": None,
            "base_amount_cents": 25000,
            "offset_kind": "NONE",
            "offset_bp": None,
            "offset_amount_cents": None,
            "floor_amount_cents": 18000,
            "ceiling_amount_cents": 40000,
            "package_inclusion_cents": 0,
            "member_only": False,
            "negotiated_account_code": None,
            "plan_state": "DRAFT",
            "derivation_depth": 0,  # a root plan sits at the top of its chain
            "resolved_base_amount_cents": 25000,  # a root plan resolves to its own base amount
            "version": 1,
        },
        "rate plan",
    )
    assert_instant_equals(read["created_at"], fixtures.FIXTURE_CLOCK, "rate plan.created_at")
    assert_instant_equals(read["updated_at"], fixtures.FIXTURE_CLOCK, "rate plan.updated_at")


def test_rate_plan_listing_pages_by_limit_and_offset(api):
    """A listing of three plans at a page size of two returns two rows with a total count of
    three and more to come, then one row at the second offset with nothing left; the two pages
    together account for every plan exactly once.

    Design: Corner/entities/rate_plan_listing_paginates_and_filters_by_plan_state
    """
    world = _property_with_three_plans(api)

    first_page, first_meta = validate_paginated(
        api.list_rate_plans(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=2, offset=0, property_id=world["property_id"]),
        )
    )
    assert len(first_page) == 2
    assert_pagination_meta(first_meta, total_count=3, limit=2, offset=0, has_more=True)

    second_page, second_meta = validate_paginated(
        api.list_rate_plans(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(limit=2, offset=2, property_id=world["property_id"]),
        )
    )
    assert len(second_page) == 1
    assert_pagination_meta(second_meta, total_count=3, limit=2, offset=2, has_more=False)

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(paged_ids) == len(set(paged_ids))
    assert set(paged_ids) == world["plan_ids"]


def test_rate_plan_listing_filters_by_plan_state_at_the_default_page_size(api):
    """A listing filtered on plan_state returns only the plans in that state and counts only
    those, and with no page controls supplied it reports the declared default page size of ten
    at offset zero.

    Design: Corner/entities/rate_plan_listing_paginates_and_filters_by_plan_state
    """
    world = _property_with_three_plans(api)

    rows, meta = validate_paginated(
        api.list_rate_plans(
            REVENUE_MANAGER_HEADERS,
            factories.page_params(property_id=world["property_id"], plan_state="ACTIVE"),
        )
    )

    assert len(rows) == 1
    assert rows[0]["id"] == world["active_id"]
    assert rows[0]["plan_state"] == "ACTIVE"
    assert_pagination_meta(meta, total_count=1, limit=10, offset=0, has_more=False)


def test_rate_plan_create_without_a_floor_amount_is_an_invalid_request(api):
    """Both guard rails are required on creation, so a body carrying only a ceiling fails the
    request-shape check with ERR_INVALID_REQUEST and leaves no plan behind.

    Design: Corner/entities/rate_plan_create_missing_floor_amount_invalid_request
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    payload = factories.rate_plan_payload(
        code="BAR",
        rate_class="PUBLIC",
        base_amount_cents=25000,
        floor_amount_cents=factories.OMIT,
        ceiling_amount_cents=40000,
    )
    assert "floor_amount_cents" not in payload

    error = validate_error(
        api.create_rate_plan(prop["id"], payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )
    assert_field_set(error, ERROR_DATA_FIELDS, "error data")

    rows, meta = validate_paginated(
        api.list_rate_plans(
            REVENUE_MANAGER_HEADERS, factories.page_params(property_id=prop["id"])
        )
    )
    assert rows == []
    assert_pagination_meta(meta, total_count=0, has_more=False)


# ── Inventory days ─────────────────────────────────────────────────────────


def test_inventory_day_create_ignores_client_supplied_derived_units(api):
    """Opening a night takes a stay date and nothing else: the ceiling, the allocated and
    committed counts, the shared pool and the posture are all derived, so values a client sends
    for them are unrecognised fields with no effect on the row that is created.

    Design: Corner/entities/inventory_day_computed_units_extra_field_input_ignored
    """
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)  # a 1000 bp overbooking allowance
    room_type = fixtures.create_king_room_type(api, prop["id"])  # ten physical rooms
    payload = dict(factories.inventory_day_payload(fixtures.STAY_DATE))
    payload.update(
        {
            "allocated_units": 99,
            "committed_units": 99,
            "overbooking_ceiling_units": 99,
            "pooled_state": "EXHAUSTED",
        }
    )

    day = validate_success(
        api.create_inventory_day(room_type["id"], payload, REVENUE_MANAGER_HEADERS), 201
    )

    assert_field_set(day, INVENTORY_DAY_FIELDS, "inventory day")
    assert_common_fields(day, "inventory day")
    assert_fields(
        day,
        {"room_type_id": room_type["id"], "stay_date": fixtures.STAY_DATE, "version": 1},
        "inventory day",
    )
    # 10 + floor(10 x 1000 / 10000) = 11 ceiling; 11 - 0 - 0 = 11 shared; nothing sold yet.
    assert_inventory_day(
        day, capacity=10, ceiling=11, allocated=0, committed=0, shared=11, pooled_state="OPEN"
    )
    assert 99 not in {
        day["overbooking_ceiling_units"],
        day["allocated_units"],
        day["committed_units"],
        day["shared_pool_units"],
    }


# ── Connectivity freeze windows ────────────────────────────────────────────


def _connection_for_freeze_windows(api):
    """A PENDING connection on one OTA channel, ready to carry freeze windows."""
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    channel = fixtures.create_channel(api, prop["id"], code="OTA1")
    return fixtures.create_connection(api, channel["id"], url=factories.endpoint_url("OTA1"))


def test_freeze_window_create_carries_no_version_and_no_updated_at(api):
    """A freeze window is the one entity the contract declares immutable: it serializes an id, a
    creation instant, its connection, its bounds, its reason and the effective start that the
    one-hour pre-buffer produces — with no updated_at and no version field at all.

    Design: Corner/entities/freeze_window_is_immutable_and_carries_no_version
    """
    connection = _connection_for_freeze_windows(api)
    tomorrow = fixtures.date_offset(fixtures.FIXTURE_TODAY, 1)
    starts_at = fixtures.instant(tomorrow, "10:00:00.000")
    ends_at = fixtures.instant(tomorrow, "12:00:00.000")

    window = validate_success(
        api.create_freeze_window(
            connection["id"],
            factories.freeze_window_payload(starts_at, ends_at, reason="MAINTENANCE"),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )

    assert_field_set(window, FREEZE_WINDOW_FIELDS, "freeze window")
    assert_create_only_fields(window, "freeze window")
    assert_fields(
        window, {"connection_id": connection["id"], "reason": "MAINTENANCE"}, "freeze window"
    )
    assert_instant_equals(window["starts_at"], starts_at, "freeze window.starts_at")
    assert_instant_equals(window["ends_at"], ends_at, "freeze window.ends_at")
    # The pre-buffer opens the freeze one hour before the declared start.
    assert_instant_equals(
        window["effective_starts_at"],
        fixtures.instant(tomorrow, "09:00:00.000"),
        "freeze window.effective_starts_at",
    )


def test_freeze_window_list_read_returns_the_same_versionless_shape(api):
    """Reading a connection's freeze windows back page by page returns the one declared window
    in the same immutable shape as the create response: the same seven fields, still with no
    updated_at and no version.

    Design: Corner/entities/freeze_window_is_immutable_and_carries_no_version
    """
    connection = _connection_for_freeze_windows(api)
    tomorrow = fixtures.date_offset(fixtures.FIXTURE_TODAY, 1)
    window = fixtures.create_freeze_window(
        api,
        connection["id"],
        fixtures.instant(tomorrow, "10:00:00.000"),
        fixtures.instant(tomorrow, "12:00:00.000"),
        reason="MAINTENANCE",
    )

    rows, meta = validate_paginated(
        api.list_freeze_windows(
            connection["id"], CHANNEL_OPS_ENGINEER_HEADERS, factories.page_params()
        )
    )

    assert_pagination_meta(meta, total_count=1, limit=10, offset=0, has_more=False)
    assert len(rows) == 1
    assert_field_set(rows[0], FREEZE_WINDOW_FIELDS, "listed freeze window")
    assert_create_only_fields(rows[0], "listed freeze window")
    assert_fields(rows[0], window, "listed freeze window")


# ── Absent parents and absent rows ─────────────────────────────────────────


def test_room_type_create_under_an_unknown_property_returns_property_not_found(api):
    """Path identifiers are resolved before the body is examined, so declaring a room type under
    a well-formed but absent property identifier fails with ERR_PROPERTY_NOT_FOUND and creates
    nothing, however valid the body itself is.

    Design: Corner/entities/room_type_create_under_unknown_property_not_found
    """
    fixtures.set_clock(api)
    payload = factories.room_type_payload(
        code="KING",
        name="King Room",
        physical_capacity_units=10,
        master_description_hash=fixtures.KING_HASH,
        master_image_count=5,
    )

    error = validate_error(
        api.create_room_type(NON_EXISTENT_UUID, payload, REVENUE_MANAGER_HEADERS),
        ApiErrorId.PROPERTY_NOT_FOUND.value,
        404,
    )
    assert_field_set(error, ERROR_DATA_FIELDS, "error data")

    rows, meta = validate_paginated(
        api.list_room_types(REVENUE_MANAGER_HEADERS, factories.page_params())
    )
    assert rows == []
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_reservation_read_with_an_unknown_id_returns_reservation_not_found(api):
    """A read of a well-formed but absent reservation identifier answers with the reservation's
    own not-found identifier at 404, and the error payload carries only the identifier and the
    message — no reservation fields at all.

    Design: Corner/entities/reservation_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(api)

    error = validate_error(
        api.get_reservation(NON_EXISTENT_UUID, REVENUE_MANAGER_HEADERS),
        ApiErrorId.RESERVATION_NOT_FOUND.value,
        404,
    )

    assert_field_set(error, ERROR_DATA_FIELDS, "error data")
    assert error["error_id"] == ApiErrorId.RESERVATION_NOT_FOUND.value


# ── Channel mappings: the parentless junction ──────────────────────────────


def _junction_world(api):
    """One property, two room types, one connected OTA channel and one DRAFT public plan."""
    fixtures.set_clock(api)
    prop = fixtures.create_canonical_property(api)
    king = fixtures.create_king_room_type(api, prop["id"])
    twin = fixtures.create_twin_room_type(api, prop["id"], master_description_hash="twinv1")
    channel = fixtures.create_channel(api, prop["id"], code="OTA1")
    fixtures.create_connection(api, channel["id"], url=factories.endpoint_url("OTA1"))
    plan = fixtures.create_canonical_rate_plan(api, prop["id"])
    return {
        "property_id": prop["id"],
        "king_id": king["id"],
        "twin_id": twin["id"],
        "channel_id": channel["id"],
        "rate_plan_id": plan["id"],
    }


def test_channel_mapping_accepts_two_triples_that_differ_only_in_room_type(api):
    """A mapping is a junction with no parent of its own: the same plan and the same channel may
    be mapped twice as long as the room type differs. Each row is born DRAFT at version 1, in
    parity because its content matches the room type's master hash and clears the image floor,
    and both rows are then reachable from the plan.

    Design: Corner/entities/channel_mapping_junction_is_unique_per_plan_channel_room_type_triple
    """
    world = _junction_world(api)

    king_mapping = validate_success(
        api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"],
                world["channel_id"],
                world["king_id"],
                external_rate_code="BAR-OTA1-KING",
                content_description_hash=fixtures.KING_HASH,
                content_image_count=5,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )
    twin_mapping = validate_success(
        api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"],
                world["channel_id"],
                world["twin_id"],
                external_rate_code="BAR-OTA1-TWIN",
                content_description_hash="twinv1",
                content_image_count=5,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )

    for mapping in (king_mapping, twin_mapping):
        assert_field_set(mapping, MAPPING_FIELDS, "channel mapping")
        assert_common_fields(mapping, "channel mapping")
        assert_fields(
            mapping,
            {
                "rate_plan_id": world["rate_plan_id"],
                "channel_id": world["channel_id"],
                "content_image_count": 5,
                "mapping_state": "DRAFT",
                # each mapping's hash matches its own room type's master, 5 images >= 5 required
                "parity_state": "IN_PARITY",
                "last_push_at": None,
                "last_pushed_rate_cents": None,
                "observed_rate_cents": None,
                "observed_stay_date": None,
                "mismatch_state": "UNKNOWN",
                "mismatch_delta_cents": None,
                "version": 1,
            },
            "channel mapping",
        )
    assert king_mapping["room_type_id"] == world["king_id"]
    assert twin_mapping["room_type_id"] == world["twin_id"]
    assert king_mapping["content_description_hash"] == fixtures.KING_HASH
    assert twin_mapping["content_description_hash"] == "twinv1"
    assert king_mapping["external_rate_code"] == "BAR-OTA1-KING"
    assert twin_mapping["external_rate_code"] == "BAR-OTA1-TWIN"

    rows, meta = validate_paginated(
        api.list_mappings(
            CHANNEL_OPS_ENGINEER_HEADERS,
            factories.page_params(rate_plan_id=world["rate_plan_id"]),
        )
    )
    assert_pagination_meta(meta, total_count=2, has_more=False)
    assert {row["id"] for row in rows} == {king_mapping["id"], twin_mapping["id"]}


def test_channel_mapping_repeating_the_whole_triple_is_a_duplicate(api):
    """The uniqueness key is the plan, the channel and the room type together, so repeating all
    three is ERR_DUPLICATE_RESOURCE even when the partner rate code differs, and the original
    mapping is left exactly as it was.

    Design: Corner/entities/channel_mapping_junction_is_unique_per_plan_channel_room_type_triple
    """
    world = _junction_world(api)
    first = validate_success(
        api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"],
                world["channel_id"],
                world["king_id"],
                external_rate_code="BAR-OTA1-KING",
                content_description_hash=fixtures.KING_HASH,
                content_image_count=5,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        201,
    )

    error = validate_error(
        api.create_mapping(
            factories.mapping_payload(
                world["rate_plan_id"],
                world["channel_id"],
                world["king_id"],
                external_rate_code="BAR-OTA1-KING-2",
                content_description_hash=fixtures.KING_HASH,
                content_image_count=5,
            ),
            CHANNEL_OPS_ENGINEER_HEADERS,
        ),
        ApiErrorId.DUPLICATE_RESOURCE.value,
        409,
    )
    assert_field_set(error, ERROR_DATA_FIELDS, "error data")

    rows, meta = validate_paginated(
        api.list_mappings(
            CHANNEL_OPS_ENGINEER_HEADERS,
            factories.page_params(rate_plan_id=world["rate_plan_id"]),
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["external_rate_code"] == "BAR-OTA1-KING"
    assert rows[0]["version"] == 1
