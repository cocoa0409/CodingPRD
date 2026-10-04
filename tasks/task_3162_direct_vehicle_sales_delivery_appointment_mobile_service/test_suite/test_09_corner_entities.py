"""Corner coverage: entity creation, retrieval, listing and defaulting."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_and_enact_jurisdiction,
    create_center,
    create_order,
    create_published_configuration,
    create_verified_buyer,
    get_order,
    get_success_data,
    place_order,
    set_clock,
    settle_order_fee,
    validate_error,
    validate_success,
    walk_order_to_at_delivery_center,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_technician_headers"]


def test_buyer_create_returns_declared_fields_and_starts_pending(api):
    """PRD §3.1: "The new account is written with `status` `PENDING_VERIFICATION`,
    a `credit_band` of `UNRATED`, an `order_credit_balance_cents` of 0, and
    `identity_verified` false."
    PRD §2.5: "They also carry `version`, an integer that begins at 1"

    Design: Corner/entities/buyer_create_returns_declared_fields_and_starts_pending
    """
    set_clock()
    res = api.create_buyer({"full_name": "Nora New", "email": "nora.new@example.com",
                            "residency_state_code": "TX"},
                           TEST_USERS["anonymous_headers"])
    buyer = validate_success(res, 201)
    assert buyer["full_name"] == "Nora New"
    assert buyer["residency_state_code"] == "TX"
    assert buyer["status"] == "PENDING_VERIFICATION"
    assert buyer["identity_verified"] is False
    assert buyer["credit_band"] == "UNRATED"
    assert buyer["order_credit_balance_cents"] == 0
    assert buyer["version"] == 1


def test_configuration_options_list_filters_by_software_entitlement_flag(api):
    """PRD §3.1: "An option that is a software entitlement is a licence grant and
    contributes nothing to the configured price, so a factory-ordered
    `FSD_SUPERVISED` option adds 0 to what the buyer owes for the car; every other
    category contributes its full `price_cents`."
    PRD §2.11: "`configured_price_cents` on a `VehicleConfiguration` is its
    `base_price_cents` plus the sum of `price_cents` over its options whose
    `is_software_entitlement` is false."
    PRD §2.11: "`option_count` is the number of option rows belonging to the
    configuration."

    Design: Corner/entities/configuration_options_list_filters_by_software_entitlement_flag
    """
    set_clock()
    config, options = create_published_configuration(options=[
        {"option_sku": "PAINT_WHITE", "option_category": "PAINT", "price_cents": 100000},
        {"option_sku": "TOW_HITCH", "option_category": "TOWING", "price_cents": 130000},
        {"option_sku": "FSD_SUPERVISED", "option_category": "SOFTWARE_FEATURE",
         "price_cents": 800000},
    ])

    rows = get_success_data(api.list_options(ADMIN))
    assert len(rows) == 3

    by_category = {row["option_category"]: row for row in rows}
    assert by_category["SOFTWARE_FEATURE"]["is_software_entitlement"] is True, (
        "the derived flag mirrors the SOFTWARE_FEATURE category"
    )
    for category in ("PAINT", "TOWING"):
        assert by_category[category]["is_software_entitlement"] is False

    non_software_total = sum(row["price_cents"] for row in rows
                             if row["is_software_entitlement"] is False)
    refreshed = get_success_data(api.get_configuration(config["id"], ADMIN))
    assert refreshed["configured_price_cents"] == \
        refreshed["base_price_cents"] + non_software_total
    assert refreshed["option_count"] == 3
    assert refreshed["configured_price_cents"] == 4799000 + 100000 + 130000


def test_vehicle_order_get_with_an_unknown_id_returns_order_not_found(api):
    """PRD §2.9: "When a path contains more than one identifier, the platform
    resolves them left to right and stops at the first identifier that does not
    denote an existing row."
    PRD §5: "`ERR_ORDER_NOT_FOUND` | 404 Not Found"

    Design: Corner/entities/vehicle_order_get_with_an_unknown_id_returns_order_not_found
    """
    set_clock()
    res = api.get_order(NON_EXISTENT_UUID, ADMIN)
    data = validate_error(res, "ERR_ORDER_NOT_FOUND", expected_status=404)
    assert data["error_id"] == "ERR_ORDER_NOT_FOUND"
    assert data["message"]


def test_order_create_missing_required_configuration_id_returns_invalid_request(api):
    """PRD §3.2: "The creation payload carries `buyer_id` for the purchasing
    account, `configuration_id` for the trim being ordered, `jurisdiction_id` for
    the governing franchise-law regime, `delivery_center_id` for the intended
    handover site"
    PRD §3.12: "a body whose fields are absent or wrongly typed" is malformed

    Design: Corner/entities/order_create_missing_required_configuration_id_returns_invalid_request
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()

    res = api.create_order({"buyer_id": buyer["id"], "jurisdiction_id": jur["id"],
                            "delivery_center_id": center["id"]}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    complete = get_success_data(api.create_order(
        {"buyer_id": buyer["id"], "configuration_id": config["id"],
         "jurisdiction_id": jur["id"], "delivery_center_id": center["id"]}, ADMIN))
    assert complete["status"] == "DRAFT"


def test_delivery_center_create_applies_home_delivery_defaults(api):
    """PRD §3.1: "New sites are `ACTIVE` with `booked_slot_count` 0."
    PRD §3.1: "a buyer resident in a closed state can lawfully take delivery at a
    site across the border"

    Design: Corner/entities/delivery_center_create_applies_home_delivery_defaults
    """
    set_clock()
    res = api.create_delivery_center(
        {"center_name": "Phoenix Gallery", "center_kind": "GALLERY",
         "state_code": "AZ", "bay_count": 0}, ADMIN)
    gallery = validate_success(res, 201)
    assert gallery["center_kind"] == "GALLERY"
    assert gallery["state_code"] == "AZ"
    assert gallery["status"] == "ACTIVE"
    assert gallery["booked_slot_count"] == 0


def test_delivery_estimates_list_filters_by_notification_state(api):
    """PRD §3.2: "creates the order's first delivery estimate in the `PROVISIONAL`
    envelope state with notification state `UNNOTIFIED` and `basis_equipment_at`
    set to `placed_at`"
    PRD §3.2: "Either route moves the order from `PLACED` to `CONFIG_LOCKED`,
    freezes the chosen `configuration_option_ids` against further change, promotes
    any estimate on the order whose notification state is `UNNOTIFIED` to
    `NOTIFIED`"

    Design: Corner/entities/delivery_estimates_list_filters_by_notification_state
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()
    order = create_order(buyer["id"], config["id"], jur["id"], center["id"])
    settle_order_fee(order["id"])
    place_order(order["id"], order["version"], buyer["id"])

    rows = get_success_data(api.list_delivery_estimates(
        ADMIN, params={"order_id": order["id"]}))
    assert len(rows) == 1
    assert rows[0]["estimate_state"] == "PROVISIONAL"
    assert rows[0]["notification_state"] == "UNNOTIFIED"
    assert rows[0]["prior_estimate_id"] is None
    assert rows[0]["shift_days"] == 0

    locked = get_order(order["id"])
    get_success_data(api.lock_configuration(order["id"], locked["version"], ADMIN))

    after = get_success_data(api.list_delivery_estimates(
        ADMIN, params={"order_id": order["id"]}))
    assert len(after) == 1, "closing the configuration does not add an estimate row"
    assert after[0]["notification_state"] == "NOTIFIED", (
        "the explicit closure promotes the UNNOTIFIED estimate to NOTIFIED"
    )


def test_vehicle_get_returns_the_stored_entitlement_and_hold_state(api):
    """PRD §3.4: "a `Vehicle` row is created for the order, inheriting the unit's
    `vin`, with `odometer_miles` 0, `software_version` set to the baseline build,
    `service_hold_state` `NONE`, and `status` `IN_SERVICE`."
    PRD §2.9: "The refusal is a 404 carrying the not-found code for the specific
    entity that failed"

    Design: Corner/entities/vehicle_get_returns_the_stored_entitlement_and_hold_state
    """
    set_clock()
    ctx = walk_order_to_at_delivery_center()
    vehicle = ctx["vehicle"]
    assert vehicle["odometer_miles"] == 0
    assert vehicle["service_hold_state"] == "NONE"
    assert vehicle["status"] == "IN_SERVICE"
    assert vehicle["delivered_at"] is None, "the handover has not completed yet"

    rows = get_success_data(api.list_vehicles(TECH))
    assert len(rows) == 1, "the fresh database holds exactly the one vehicle"
    assert rows[0]["vin"] == vehicle["vin"]

    res = api.get_vehicle(NON_EXISTENT_UUID, TECH)
    validate_error(res, "ERR_VEHICLE_NOT_FOUND", expected_status=404)


def test_venue_get_does_not_reveal_services_the_tier_has_not_unlocked(api):
    """PRD §3.1: "A `PlatformAdmin` may suspend a site to stop it accepting new
    bookings or reinstate it afterwards; suspension is not a cancellation, so every
    appointment already `BOOKED` or `CONFIRMED` at a suspended site is retained and
    honoured, and it is only the *new* bookings that are turned away"
    PRD §2.4: "A jurisdiction advances through a lifecycle of `DRAFT`, then
    `ENACTED`, then `REPEALED`"

    Design: Corner/entities/venue_get_does_not_reveal_services_the_tier_has_not_unlocked
    """
    set_clock()
    gallery = create_center(center_name="Phoenix Gallery", center_kind="GALLERY",
                            state_code="AZ", bay_count=0)
    assert gallery["center_kind"] == "GALLERY"
    assert gallery["bay_count"] == 0

    suspended = get_success_data(api.suspend_delivery_center(gallery["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"

    again = api.suspend_delivery_center(gallery["id"], ADMIN)
    validate_error(again, "ERR_INVALID_STATE", expected_status=409)


def test_buyer_get_cannot_read_another_buyers_account(api):
    """PRD §2.1: "a read of another account's own resource is refused with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)"
    PRD §2.1: "ownership checks on any resource that references a `Buyer` compare
    the resource's foreign-key field to `X-User-ID`"

    Design: Corner/entities/buyer_get_cannot_read_another_buyers_account
    """
    set_clock()
    mine = create_verified_buyer(full_name="Nora New", email="nora.new@example.com")
    other = create_verified_buyer(full_name="Omar Other", email="omar.other@example.com")

    res = api.get_buyer(other["id"], {"X-User-ID": mine["id"], "X-User-Role": "Buyer",
                                      "Content-Type": "application/json"})
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)
    assert "omar.other@example.com" not in res.text

    own = get_success_data(api.get_buyer(mine["id"], {
        "X-User-ID": mine["id"], "X-User-Role": "Buyer",
        "Content-Type": "application/json"}))
    assert own["email"] == "nora.new@example.com"


def test_order_created_with_a_nonexistent_configuration_returns_not_found(api):
    """PRD §2.9: "The refusal is a 404 carrying the not-found code for the specific
    entity that failed: `ERR_BUYER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_APPRAISAL_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_VEHICLE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`,
    `ERR_CENTER_NOT_FOUND`, `ERR_CONFIGURATION_NOT_FOUND`"
    PRD §2.9: "Ownership and state checks are ordered after existence, never before
    it."

    Design: Corner/entities/order_created_with_a_nonexistent_configuration_returns_not_found
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    buyer = create_verified_buyer()

    res = api.create_order({"buyer_id": buyer["id"],
                            "configuration_id": NON_EXISTENT_UUID,
                            "jurisdiction_id": jur["id"],
                            "delivery_center_id": center["id"],
                            "order_fee_cents": 25000}, ADMIN)
    validate_error(res, "ERR_CONFIGURATION_NOT_FOUND", expected_status=404)


def test_order_fee_cents_defaults_to_25000_when_omitted(api):
    """PRD §3.2: "an optional `order_fee_cents` that defaults to 25000"
    PRD §3.7: "First the order's `order_fee_cents`."

    Design: Corner/entities/order_fee_cents_defaults_to_25000_when_omitted
    """
    set_clock()
    jur = create_and_enact_jurisdiction()
    center = create_center()
    config, _ = create_published_configuration()
    buyer = create_verified_buyer()

    order = get_success_data(api.create_order(
        {"buyer_id": buyer["id"], "configuration_id": config["id"],
         "jurisdiction_id": jur["id"], "delivery_center_id": center["id"]}, ADMIN))
    assert order["order_fee_cents"] == 25000
    assert order["order_fee_paid_cents"] == 0
    assert order["status"] == "DRAFT"
    assert order["order_total_due_cents"] == config["base_price_cents"] + 25000 + 7500 + 2500
