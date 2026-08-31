"""The physical estate: docks, fare-zone stops, vessels, inspections and crew."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dock,
    assert_ride_pass,
    assert_vessel_inspection,
    create_dock_payload,
    create_inspection_payload,
    create_ride_pass_payload,
    create_stop_payload,
    create_trip_payload,
    create_vessel_payload,
    setup_harbor_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["marine_inspector_headers"]
RIDER = TEST_USERS["rider_headers"]

MISSING_UUID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_dock_initialises_its_landing_fee_accrual(api):
    """PRD §3.1: "A newly registered dock starts with `accrued_fee_cents` at 0 and
    `fee_status` at `ACCRUING`, the other permissible value being `CAPPED`."
    PRD §2.4: "Most resources additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that starts
    at 1 when the row is created and increments by exactly 1 on every mutation of
    that row."

    Design: Corner/entities/create_dock_returns_201_with_accrual_fields_initialised
    """
    payload = create_dock_payload(name="Pier One", berth_count=2,
                                  min_turnaround_minutes=15,
                                  landing_fee_per_pax_cents=120,
                                  berth_minute_rate_cents=40,
                                  monthly_fee_cap_cents=1_000_000,
                                  shared_operator_count=2)
    dock = validate_success(api.create_dock(payload, ADMIN), 201)

    assert_dock(dock)
    assert dock["berth_count"] == 2, f"Expected berth_count 2, got {dock['berth_count']}"
    assert dock["accrued_fee_cents"] == 0, (
        f"A new dock must start at 0 accrual, got {dock['accrued_fee_cents']}"
    )
    assert dock["fee_status"] == "ACCRUING", (
        f"A new dock must start ACCRUING, got {dock['fee_status']}"
    )
    assert dock["version"] == 1, f"Expected version 1 on creation, got {dock['version']}"


def test_dock_created_without_turnaround_uses_the_declared_defaults(api):
    """PRD §3.1: "Registering a dock records its `name` (a required string of 1 to 80
    characters), its `berth_count` (at least 1 — the number of berths that can be
    occupied at once), and its `min_turnaround_minutes` (whole minutes, at least 0,
    defaulting to 15 when omitted), which is the buffer the operator needs between
    two boats using the same berth."
    PRD §3.1: "A seventh field, `shared_operator_count` (at least 1, defaulting to 1),
    records how many operators share the dock."

    Design: Corner/entities/create_dock_without_min_turnaround_applies_the_declared_default
    """
    dock = validate_success(
        api.create_dock({"name": "Default Dock", "berth_count": 1,
                         "landing_fee_per_pax_cents": 100,
                         "berth_minute_rate_cents": 30,
                         "monthly_fee_cap_cents": 500_000}, ADMIN),
        201,
    )

    assert dock["min_turnaround_minutes"] == 15, (
        f"Omitted min_turnaround_minutes must default to 15, got "
        f"{dock['min_turnaround_minutes']}"
    )
    assert dock["shared_operator_count"] == 1, (
        f"Omitted shared_operator_count must default to 1, got "
        f"{dock['shared_operator_count']}"
    )


def test_vessel_registration_without_draft_is_rejected(api):
    """PRD §3.1: "Vessels are registered with a `name` of 1 to 80 characters, a
    `seat_capacity` of at least 1 (the certificated seated passenger capacity), a
    `draft_m` strictly greater than 0.00 metres to two decimals, a `hull_class` of
    either `HARBOR` or `OFFSHORE`, and a `required_endorsement` of either
    `MASTER_25T` or `MASTER_100T` naming the minimum licence a master needs to take
    her out."
    PRD §2.8: "**Payload validity.** All required fields present, of the declared
    type, inside the declared numeric range, and every enum value a declared member
    — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_vessel_missing_required_draft_returns_invalid_request
    """
    response = api.create_vessel({"name": "No Draft", "seat_capacity": 20,
                                  "hull_class": "HARBOR",
                                  "required_endorsement": "MASTER_25T"}, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_ride_pass_with_an_undeclared_zone_tier_is_rejected(api):
    """PRD §3.5: "The purchase declares a `zone_tier` of `INNER`, `OUTER`, or
    `ALL_ZONE`; a `rides_purchased` count of at least 1; a `purchase_price_cents` of
    at least 0, being what the rider actually paid; and a `valid_until` calendar
    date, the last date inclusive on which the pass may be redeemed."
    PRD §2.8: "**Payload validity.** All required fields present, of the declared
    type, inside the declared numeric range, and every enum value a declared member
    — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_ride_pass_with_undeclared_zone_tier_returns_invalid_request
    """
    response = api.create_ride_pass(
        create_ride_pass_payload(zone_tier="MIDDLE", rides_purchased=5,
                                 purchase_price_cents=5000, valid_until="2026-12-31"),
        RIDER,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_ride_pass_creation_derives_its_balance_fields(api):
    """PRD §3.5: "A fresh pass has `rides_remaining` equal to `rides_purchased`,
    `rides_consumed` at 0, `status` `ACTIVE`, `refund_basis` null, and
    `refund_amount_cents` at 0."
    PRD §3.5: "The pass's `rider_user_id` is stamped from the acting `X-User-ID` and
    is the value every later ownership check compares against — it is never matched
    against any entity's `id`."

    Design: Corner/entities/ride_pass_creation_derives_balance_fields_and_ignores_client_supplied_ones
    """
    ride_pass = validate_success(
        api.create_ride_pass(
            create_ride_pass_payload(zone_tier="OUTER", rides_purchased=8,
                                     purchase_price_cents=12000,
                                     valid_until="2026-12-31"),
            RIDER,
        ),
        201,
    )

    assert_ride_pass(ride_pass)
    assert ride_pass["rides_remaining"] == 8
    assert ride_pass["rides_consumed"] == 0
    assert ride_pass["status"] == "ACTIVE"
    assert ride_pass["rider_user_id"] == "rider-ann", (
        f"rider_user_id must be stamped from X-User-ID, got {ride_pass['rider_user_id']}"
    )
    assert ride_pass["refund_amount_cents"] == 0
    assert ride_pass["refund_basis"] is None


def test_filing_an_inspection_stamps_the_inspector_and_derives_the_expiry(api):
    """PRD §3.1: "On filing, the server computes `expires_on` as `performed_on` plus
    365 days for an `ANNUAL` row and leaves it null for a `PRE_DEPARTURE` row; stamps
    `inspector_user_id` from the acting `X-User-ID`; re-derives the vessel's
    `service_state` and `annual_inspection_expires_on`; and increments the vessel's
    `version` by 1."
    PRD §2.4: "`VesselInspection` is the single exception: an inspection is an
    immutable event record, so it carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and neither field appears in its representation."

    Design: Corner/entities/vessel_inspection_stamps_inspector_and_derives_expiry_and_carries_no_version
    """
    vessel = validate_success(api.create_vessel(create_vessel_payload(), ADMIN), 201)

    annual = validate_success(
        api.create_inspection(vessel["id"],
                              create_inspection_payload(inspection_type="ANNUAL",
                                                        result="PASS",
                                                        deficiency_count=0,
                                                        performed_on="2026-08-01"),
                              INSPECTOR),
        201,
    )
    pre_departure = validate_success(
        api.create_inspection(vessel["id"],
                              create_inspection_payload(inspection_type="PRE_DEPARTURE",
                                                        result="PASS",
                                                        deficiency_count=0,
                                                        performed_on="2026-08-02"),
                              INSPECTOR),
        201,
    )

    assert_vessel_inspection(annual)
    assert annual["inspector_user_id"] == "insp-1"
    assert annual["expires_on"] == "2027-08-01", (
        f"ANNUAL expires_on must be performed_on + 365 days, got {annual['expires_on']}"
    )
    assert pre_departure["expires_on"] is None, (
        f"PRE_DEPARTURE expires_on must be null, got {pre_departure['expires_on']}"
    )

    refreshed = validate_success(api.get_vessel(vessel["id"], ADMIN))
    assert refreshed["annual_inspection_expires_on"] == "2027-08-01"
    assert refreshed["service_state"] == "IN_SERVICE"


def test_reading_a_trip_that_does_not_exist_returns_trip_not_found(api):
    """PRD §2.8: "**Path resolution.** Every id embedded in the URL path resolves to
    an existing row, validated left to right, so an outer id that does not resolve is
    reported before any inner id is looked at."
    PRD §2.8: "The error is the one belonging to the missing resource type:
    `ERR_DOCK_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`, `ERR_SERVICE_DAY_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_DOCK_SLOT_NOT_FOUND`, `ERR_RIDE_PASS_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_REFUND_CLAIM_NOT_FOUND`, or `ERR_CREW_NOT_FOUND`,
    each HTTP 404."

    Design: Corner/entities/get_trip_with_unknown_id_returns_trip_not_found
    """
    validate_error(api.get_trip(MISSING_UUID, DISPATCHER),
                   ApiErrorId.ERR_TRIP_NOT_FOUND.value, 404)


def test_adding_a_stop_under_an_unknown_dock_returns_dock_not_found(api):
    """PRD §2.8: "**Path resolution.** Every id embedded in the URL path resolves to
    an existing row, validated left to right, so an outer id that does not resolve is
    reported before any inner id is looked at."
    PRD §3.1: "The stop's `dock_id` is taken from the dock addressed in the request
    rather than from the payload, which is how a stop comes to know which berths it
    lands at."

    Design: Corner/entities/create_stop_under_unknown_dock_returns_dock_not_found
    """
    response = api.create_stop(MISSING_UUID,
                               create_stop_payload(name="Ghost Stop", zone_index=1,
                                                   charted_depth_m=3.00),
                               ADMIN)

    validate_error(response, ApiErrorId.ERR_DOCK_NOT_FOUND.value, 404)


def test_planning_a_sailing_with_an_unknown_master_returns_crew_not_found(api):
    """PRD §2.8: "**Body foreign-key resolution.** Every foreign key supplied in the
    request body resolves, validated in the order the fields are listed for that
    endpoint in §3, yielding `ERR_STOP_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_SERVICE_DAY_NOT_FOUND`, `ERR_DOCK_NOT_FOUND`, or
    `ERR_RIDE_PASS_NOT_FOUND` (all 404)."

    Design: Corner/entities/create_trip_with_unknown_master_crew_returns_crew_not_found
    """
    world = setup_harbor_world(annual_inspection=False, clock=None)

    response = api.create_trip(
        create_trip_payload(world["day_id"], world["vessel_id"], MISSING_UUID,
                            world["stop1_id"], world["stop2_id"]),
        DISPATCHER,
    )

    validate_error(response, ApiErrorId.ERR_CREW_NOT_FOUND.value, 404)

    trips, meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"service_day_id": world["day_id"]})
    )
    assert meta["total_count"] == 0, (
        f"A rejected creation must not persist a trip, got total_count "
        f"{meta['total_count']}"
    )


def test_trip_listing_reports_total_count_and_has_more(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1, and
    may not exceed 100."
    PRD §2.3: "List responses populate `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` envelope, where `total_count` is the number of rows
    matching the filters before the window is applied and `has_more` indicates
    whether rows remain beyond the current window."

    Design: Corner/entities/list_trips_paginates_with_total_count_and_has_more
    """
    world = setup_harbor_world()
    for departure, arrival in (("14:00", "14:25"), ("15:00", "15:25"), ("16:00", "16:25")):
        validate_success(
            api.create_trip(
                create_trip_payload(
                    world["day_id"], world["vessel_id"], world["crew_id"],
                    world["stop1_id"], world["stop2_id"],
                    scheduled_departure_utc=f"2026-09-12T{departure}:00Z",
                    scheduled_arrival_utc=f"2026-09-12T{arrival}:00Z",
                ),
                DISPATCHER,
            ),
            201,
        )

    first_page, first_meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"service_day_id": world["day_id"],
                                           "limit": 2, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"service_day_id": world["day_id"],
                                           "limit": 2, "offset": 2})
    )

    assert len(first_page) == 2, f"Expected 2 rows in the first window, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(second_page) == 1, f"Expected 1 row in the second window, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False


def test_inspection_listing_returns_only_that_vessels_rows(api):
    """PRD §3.1: "The inspection listing for a vessel returns rows newest
    `performed_on` first and accepts an `inspection_type` filter alongside `limit`
    and `offset`."
    PRD §3.1: "The `vessel_id` comes from the vessel addressed in the request."

    Design: Corner/endpoints/vessel_inspection_sub_resource_lists_only_the_rows_of_that_vessel
    """
    vessel_one = validate_success(api.create_vessel(create_vessel_payload(), ADMIN), 201)
    vessel_two = validate_success(
        api.create_vessel(create_vessel_payload(name="Kestrel", seat_capacity=24,
                                                draft_m=1.00, hull_class="HARBOR"),
                          ADMIN),
        201,
    )
    annual_one = validate_success(
        api.create_inspection(vessel_one["id"], create_inspection_payload(), INSPECTOR), 201
    )
    validate_success(
        api.create_inspection(vessel_one["id"],
                              create_inspection_payload(inspection_type="PRE_DEPARTURE",
                                                        performed_on="2026-08-05"),
                              INSPECTOR),
        201,
    )
    validate_success(
        api.create_inspection(vessel_two["id"],
                              create_inspection_payload(deficiency_count=1), INSPECTOR),
        201,
    )

    rows, meta = validate_paginated(api.list_inspections(vessel_one["id"], INSPECTOR))
    assert meta["total_count"] == 2, (
        f"Expected the two rows of vessel one, got {meta['total_count']}"
    )
    assert all(row["vessel_id"] == vessel_one["id"] for row in rows), (
        "The listing must only return inspections of the addressed vessel"
    )

    annual_rows, annual_meta = validate_paginated(
        api.list_inspections(vessel_one["id"], INSPECTOR,
                             params={"inspection_type": "ANNUAL"})
    )
    assert annual_meta["total_count"] == 1
    assert annual_rows[0]["id"] == annual_one["id"]

    second = validate_success(api.get_vessel(vessel_two["id"], ADMIN))
    assert second["annual_inspection_expires_on"] == "2027-08-01"


def test_latest_annual_inspection_ignores_a_newer_pre_departure_failure(api):
    """PRD §3.1: "Take the vessel's inspections whose `inspection_type` is `ANNUAL`,
    ignoring `PRE_DEPARTURE` rows entirely no matter how recent they are, and sort
    them by `performed_on` descending with ties broken by `created_at` descending;
    the first row is the latest annual inspection, and there may be none."
    PRD §3.1: "`PRE_DEPARTURE` rows are advisory and gate nothing at any point in
    this system."

    Design: Corner/calculations/latest_annual_inspection_ignores_a_newer_pre_departure_failure
    """
    vessel = validate_success(api.create_vessel(create_vessel_payload(), ADMIN), 201)
    validate_success(
        api.create_inspection(vessel["id"], create_inspection_payload(), INSPECTOR), 201
    )
    validate_success(
        api.create_inspection(vessel["id"],
                              create_inspection_payload(inspection_type="PRE_DEPARTURE",
                                                        result="FAIL",
                                                        deficiency_count=4,
                                                        performed_on="2026-09-10"),
                              INSPECTOR),
        201,
    )

    refreshed = validate_success(api.get_vessel(vessel["id"], DISPATCHER))
    assert refreshed["service_state"] == "IN_SERVICE", (
        f"A PRE_DEPARTURE FAIL must not change service_state, got "
        f"{refreshed['service_state']}"
    )
    assert refreshed["annual_inspection_expires_on"] == "2027-08-01"

    _rows, meta = validate_paginated(api.list_inspections(vessel["id"], INSPECTOR))
    assert meta["total_count"] == 2
