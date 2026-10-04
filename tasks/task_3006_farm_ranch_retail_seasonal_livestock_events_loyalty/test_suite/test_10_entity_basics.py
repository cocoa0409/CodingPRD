"""Entity corners: creation defaults, retrieval round-trip, required fields,
pagination, append-only logs, not-found ids, enum shape."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_care_log_entry,
    create_account,
    create_booking,
    create_chick_order_payload,
    create_loyalty_account_payload,
    create_open_store,
    create_published_event,
    create_service_event_payload,
    create_store,
    make_customer_headers,
    place_chick_order,
    post_care_log,
    set_clock,
    setup_spring_store,
    validate_error,
    validate_paginated,
    validate_success,
)

RA = TEST_USERS["regional_admin_headers"]
MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]
ANON = TEST_USERS["anonymous_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_store_create_returns_offseason_posture_and_version_1(api):
    """PRD §2.6: "A `Store` is created by a `RegionalAdmin` from a `store_name` and a `region_code`; it begins life with `posture` equal to `OFFSEASON`, `active_campaign_id` null, and `version` 1."
    PRD §2.4: "Every persisted resource carries a server-minted `id` — a UUID with no type prefix — assigned at creation."

    Design: Corner/entities/store_create_returns_computed_offseason_posture_and_version_1
    """
    resp = api.create_store(
        {"store_name": "Abilene Farm & Ranch", "region_code": "TX-WEST"}, RA
    )
    data = validate_success(resp, expected_status=201)
    assert data["posture"] == "OFFSEASON"
    assert data["active_campaign_id"] is None
    assert data["hazmat_gallons_used_today"] == 0
    assert data["version"] == 1
    assert data["id"]
    assert data["created_at"]
    assert data["updated_at"]

    fetched = validate_success(api.get_store(data["id"], RA))
    assert fetched["version"] == 1


def test_loyalty_account_create_defaults_and_phone_uniqueness(api):
    """PRD §3.7: "An `Anonymous` caller registers a `LoyaltyAccount` with a `full_name`, a `phone`, and an optional `email`; the phone must be unique across all accounts, with a duplicate rejected as `ERR_PHONE_ALREADY_REGISTERED`. A new account starts `ACTIVE` with `tier` `NEIGHBOR` and `points_balance` 0."

    Design: Corner/entities/loyalty_account_create_defaults_and_phone_uniqueness
    """
    first = validate_success(
        api.create_loyalty_account(
            create_loyalty_account_payload(full_name="Rue Carter", phone="555-0200"),
            ANON,
        ),
        expected_status=201,
    )
    assert first["tier"] == "NEIGHBOR"
    assert first["points_balance"] == 0
    assert first["status"] == "ACTIVE"
    assert first["email"] is None

    dup = api.create_loyalty_account(
        create_loyalty_account_payload(full_name="Rue Carter Jr", phone="555-0200"),
        ANON,
    )
    validate_error(dup, ApiErrorId.ERR_PHONE_ALREADY_REGISTERED)

    second = validate_success(
        api.create_loyalty_account(
            create_loyalty_account_payload(full_name="Rue Carter Jr", phone="555-0201"),
            ANON,
        ),
        expected_status=201,
    )
    assert second["status"] == "ACTIVE"


def test_chick_order_get_returns_stored_snapshot_fields(api):
    """PRD §3.4: "A successful reservation lands in `RESERVED`. The system snapshots `unit_price_cents` from the schedule's `base_price_cents_per_bird`, computes the volume discount bracket, and stores the line total."
    PRD §3.4: "no discount — `discount_pct` 0.00 — for 24 birds or fewer"

    Design: Corner/entities/chick_order_get_returns_stored_snapshot_fields
    """
    ctx = setup_spring_store()
    account = create_account(full_name="Jesse Pruitt")
    order = place_chick_order(
        ctx["store"], ctx["lot"], account, quantity=6,
        lot_version=ctx["lot_version"],
    )

    fetched = validate_success(api.get_chick_order(order["id"], ASSOC))
    assert fetched["unit_price_cents"] == 349
    assert fetched["discount_pct"] == 0.0
    assert fetched["total_cents"] == 2094
    assert fetched["status"] == "RESERVED"
    assert fetched["claim_status"] == "NONE"
    assert fetched["brooder_verified_at"] is None
    assert fetched["fulfilled_at"] is None
    assert fetched["livestock_lot_id"] == ctx["lot"]["id"]
    assert fetched["loyalty_account_id"] == account["id"]


def test_event_bookings_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the full count of matching records and `has_more` indicates whether additional records exist beyond the returned window."

    Design: Corner/entities/event_bookings_list_paginates_with_total_count_and_has_more
    """
    set_clock(FLOOR_NOW)
    store = create_open_store(season="WINTER_HEATING")
    event = create_published_event(store, capacity_per_slot=3)
    a1 = create_account()
    a2 = create_account()
    a3 = create_account()
    create_booking(event, a1, "2026-09-15T09:00:00Z")
    create_booking(event, a2, "2026-09-15T09:30:00Z")
    create_booking(event, a3, "2026-09-15T10:00:00Z")

    page1, meta1 = validate_paginated(
        api.list_event_bookings(
            ASSOC, params={"service_event_id": event["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_event_bookings(
            ASSOC, params={"service_event_id": event["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    default_page, default_meta = validate_paginated(
        api.list_event_bookings(ASSOC, params={"service_event_id": event["id"]})
    )
    assert len(default_page) == 3
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0


def test_weighted_sale_get_unknown_id_returns_sale_not_found(api):
    """PRD §2.9: "every resource identifier in the path, validated left to right, and then foreign-key identifiers in the body must resolve, or the request fails with the matching not-found identifier — `ERR_STORE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_BAY_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_PICKUP_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, or `ERR_BOOKING_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/weighted_sale_get_unknown_id_returns_sale_not_found
    """
    resp = api.get_weighted_sale(
        "11111111-2222-4333-8444-555555555555", ASSOC
    )
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_FOUND, expected_status=404)


def test_chick_order_missing_required_quantity_returns_invalid_request(api):
    """PRD §2.9: "First (priority 0) the request shape is checked — required fields present, types correct, enum values valid — with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400)"
    PRD §3.4: "The customer posts the `store_id`, the `livestock_lot_id` of the lot the birds come from, their own `loyalty_account_id` ... the `quantity`, the intended `pickup_date`, and the OCC field `expected_livestock_lot_version` (§2.7)."

    Design: Corner/entities/chick_order_missing_required_quantity_returns_invalid_request
    """
    ctx = setup_spring_store()
    account = create_account()
    payload = create_chick_order_payload(
        ctx["store"]["id"], ctx["lot"]["id"], account["id"], ctx["lot_version"],
    )
    del payload["quantity"]
    resp = api.create_chick_order(payload, make_customer_headers(account["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_care_log_entry_is_append_only_without_version(api):
    """PRD §2.4: "Two resources are append-only logs and deliberately break this pattern: a `CareLogEntry` and a `LoyaltyLedgerEntry` each carry only `id` and `created_at`; neither has `updated_at` nor `version`, and neither can be modified after creation."
    PRD §3.3: "A `TEMPERATURE` entry must supply `measured_temp_f`, the brooder temperature in Fahrenheit"

    Design: Corner/entities/care_log_entry_has_no_version_and_no_update_path
    """
    ctx = setup_spring_store()
    entry = post_care_log(
        ctx["lot"]["id"], "TEMPERATURE", measured_temp_f=95.5, note="brooder check"
    )
    assert_care_log_entry(entry)

    entries, meta = validate_paginated(
        api.list_care_logs(ctx["lot"]["id"], ASSOC)
    )
    assert len(entries) == 1
    assert entries[0]["id"] == entry["id"]
    assert entries[0]["entry_type"] == "TEMPERATURE"
    assert entries[0]["measured_temp_f"] == 95.5
    assert "version" not in entries[0]
    assert "updated_at" not in entries[0]

    # No update or delete path exists for care log entries.
    for method in ("put", "patch", "delete"):
        resp = getattr(api, method)(
            f"/livestock-lots/{ctx['lot']['id']}/care-logs/{entry['id']}",
            json={},
            headers=ASSOC,
        )
        assert resp.status_code in (404, 405), (
            f"{method.upper()} on a care log entry must not be a supported path, "
            f"got {resp.status_code}"
        )


def test_service_event_invalid_enum_kind_rejected(api):
    """PRD §3.9: "A `StoreManager` creates a `ServiceEvent` in `DRAFT` with the `store_id`, an `event_kind` of `PET_WASH` or `VET_CLINIC`"
    PRD §2.9: "First (priority 0) the request shape is checked — required fields present, types correct, enum values valid — with violations rejected as `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/service_event_invalid_enum_kind_rejected
    """
    set_clock(FLOOR_NOW)
    store = create_store()

    payload = create_service_event_payload(store["id"], event_kind="GOAT_YOGA",
                                           resource_name="barn-1")
    resp = api.create_service_event(payload, MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_ledger_reversal_requires_existing_related_entry(api):
    """PRD §3.7: "A `REVERSAL` requires a `related_entry_id` referencing an existing entry of the same account — a dangling or cross-account reference fails with `ERR_ENTRY_NOT_FOUND`"

    Design: Corner/entities/ledger_entry_reversal_requires_existing_related_entry
    """
    account = create_account()
    resp = api.create_ledger_entry(
        account["id"],
        {
            "entry_type": "REVERSAL",
            "related_entry_id": "11111111-2222-4333-8444-555555555555",
            "points_delta": -50,
        },
        ASSOC,
    )
    validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_FOUND, expected_status=404)

    acct = validate_success(api.get_loyalty_account(account["id"], ASSOC))
    assert acct["points_balance"] == 0
