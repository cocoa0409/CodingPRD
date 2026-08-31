"""Yards, equipment classes and units: the reference layer the whole book of
business stands on."""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_branch,
    assert_maintenance_event,
    assert_trailer,
    branch_payload,
    create_branch,
    create_trailer,
    create_trailer_type,
    is_valid_uuid,
    read_branch,
    read_trailer,
    setup_reference_data,
    trailer_payload,
    trailer_type_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def test_register_yard_starts_with_zeroed_counters(api):
    """PRD §3.1: "A newly registered yard begins with both of its live counters,
    `on_hand_count` and `serviceable_available_count`, at zero."
    PRD §2.5: "`version` (integer): a counter that starts at 1 on creation and
    increments by exactly 1 on every mutation of that record."

    Design: Corner/entities/create_branch_returns_201_with_zeroed_counters
    """
    west = create_branch()

    response = api.create_branch(
        branch_payload(
            code="EST-01", name="East Yard", region="EAST", yard_capacity=8,
            peak_season_start_date="2026-06-01", peak_season_end_date="2026-08-31",
            lease_reserve_pct=0.20,
        ),
        ADMIN,
    )
    east = validate_success(response, 201)
    assert_branch(east)

    assert east["on_hand_count"] == 0, "a brand new yard holds nothing"
    assert east["serviceable_available_count"] == 0
    assert east["version"] == 1
    assert float(east["lease_reserve_pct"]) == pytest.approx(0.20, abs=0.001)
    assert east["id"] != west["id"]
    assert is_valid_uuid(east["id"]) and len(east["id"]) == 36, (
        "the id is a bare UUID carrying no type prefix"
    )


def test_register_yard_without_lease_reserve_pct_defaults_to_zero(api):
    """PRD §3.1: "Finally, an optional `lease_reserve_pct` records the fraction of
    the serviceable idle pool the yard holds back for full-service lease demand
    during that peak window; it defaults to 0.00 and must lie between 0.00 and
    1.00 inclusive."
    PRD §3.5: "`lease_reserved_count` is that serviceable idle count multiplied by
    the yard's `lease_reserve_pct` and rounded upward to a whole unit when the
    requested product is `SHORT_TERM_RENTAL` and the requested window intersects
    the yard's peak window, and is zero in every other case."

    Design: Corner/entities/create_branch_without_lease_reserve_pct_defaults_to_zero
    """
    trailer_type = create_trailer_type()

    payload = branch_payload(code="DEF-01", name="Default Yard", region="CENTRAL")
    payload.pop("lease_reserve_pct")
    branch = validate_success(api.create_branch(payload, ADMIN), 201)
    assert float(branch["lease_reserve_pct"]) == pytest.approx(0.0, abs=0.0001)

    create_trailer(trailer_type["id"], branch["id"], unit_number="T-9001", hub_miles=1000)

    availability = validate_success(
        api.get_branch_availability(
            branch["id"], ADMIN,
            params={
                "trailer_type_id": trailer_type["id"],
                "product": "SHORT_TERM_RENTAL",
                "window_start_date": "2026-09-05",
                "window_end_date": "2026-09-12",
            },
        )
    )
    assert availability["lease_reserved_count"] == 0, (
        "a zero reserve holds nothing back"
    )
    assert availability["rental_available_count"] == 1


def test_duplicate_yard_code_is_rejected(api):
    """PRD §3.1: "Registration supplies a short yard `code` of between 1 and 16
    characters that must be unique across all yards — a collision is rejected with
    `ERR_DUPLICATE_BRANCH_CODE`"

    Design: Corner/entities/create_branch_with_duplicate_code_rejected
    """
    create_branch()

    response = api.create_branch(
        branch_payload(code="WST-01", name="West Yard Annex", region="CENTRAL",
                       yard_capacity=4),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BRANCH_CODE.value)

    rows, meta = validate_paginated(api.list_branches(ADMIN, params={"limit": 100}))
    assert len([b for b in rows if b["code"] == "WST-01"]) == 1


def test_register_unit_without_home_branch_id_is_rejected(api):
    """PRD §3.1: "A unit is created with a fleet `unit_number` that must be unique
    across all trailers — a collision is rejected with `ERR_DUPLICATE_UNIT_NUMBER`
    — a `trailer_type_id` naming its equipment class, a `home_branch_id` naming its
    accounting home yard, an `acquisition_cost_cents` of at least 0 that forms the
    basis for depreciation, an `in_service_date` that starts the depreciation
    clock, a `last_dot_inspection_date` recording its most recent passed federal
    periodic inspection, and an optional `hub_miles` opening hubodometer reading
    that defaults to 0 and must be at least 0."
    PRD §2.9: "Payload shape. Required fields present, enum values members of their
    declared sets, numeric fields inside their declared bounds, `line_items`
    non-empty, and pagination within a `limit` of 1 through 100 and an `offset` of
    at least 0, or `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_trailer_without_home_branch_id_returns_invalid_request
    """
    branch = create_branch()
    trailer_type = create_trailer_type()

    payload = trailer_payload(trailer_type["id"], branch["id"])
    payload.pop("home_branch_id")
    payload.pop("hub_miles")
    response = api.create_trailer(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, _ = validate_paginated(api.list_trailers(ADMIN, params={"limit": 100}))
    assert [t for t in rows if t["unit_number"] == "T-1001"] == []
    assert read_branch(branch["id"])["on_hand_count"] == 0


def test_register_unit_ignores_server_owned_dimensions(api):
    """PRD §3.1: "On creation the server sets `current_branch_id` to the supplied
    `home_branch_id`, sets `availability_status` to `AVAILABLE`, sets
    `last_pm_hub_miles` equal to the opening `hub_miles`, and sets
    `last_dot_passed` to true."
    PRD §3.1: "The `service_status` dimension takes exactly one of `SERVICEABLE`,
    `PM_DUE`, `OOS_DAMAGE` or `OOS_DOT_EXPIRED`, begins at `SERVICEABLE`, and is
    never written directly by a caller; it is derived, and the derivation is
    spelled out in section 3.6."

    Design: Corner/entities/create_trailer_system_fields_input_ignored
    """
    west = create_branch()
    east = create_branch(code="EST-01", name="East Yard", region="EAST",
                         yard_capacity=8, peak_season_start_date="2026-06-01",
                         peak_season_end_date="2026-08-31")
    trailer_type = create_trailer_type()

    payload = trailer_payload(trailer_type["id"], west["id"])
    payload.update({
        "availability_status": "RETIRED",
        "current_branch_id": east["id"],
        "service_status": "OOS_DAMAGE",
        "damage_points": 99,
    })
    trailer = validate_success(api.create_trailer(payload, ADMIN), 201)
    assert_trailer(trailer)

    assert trailer["availability_status"] == "AVAILABLE"
    assert trailer["service_status"] == "SERVICEABLE"
    assert trailer["current_branch_id"] == west["id"]
    assert trailer["damage_points"] == 0
    assert read_branch(west["id"])["on_hand_count"] == 1
    assert read_branch(east["id"])["on_hand_count"] == 0


def test_dot_expiry_is_the_last_inspection_advanced_by_the_class_interval(api):
    """PRD §3.1: "Expiry of the federal periodic inspection is pure date
    arithmetic: `dot_expires_on` is the unit's `last_dot_inspection_date` advanced
    by exactly `dot_inspection_interval_days` calendar days, taken from the unit's
    equipment class."
    PRD §3.1: "On creation the server sets `current_branch_id` to the supplied
    `home_branch_id`, sets `availability_status` to `AVAILABLE`, sets
    `last_pm_hub_miles` equal to the opening `hub_miles`, and sets
    `last_dot_passed` to true."

    Design: Corner/entities/trailer_dot_expires_on_computed_from_type_interval
    """
    branch = create_branch()
    trailer_type = create_trailer_type(dot_inspection_interval_days=365,
                                       pm_interval_miles=30000)

    trailer = validate_success(
        api.create_trailer(trailer_payload(trailer_type["id"], branch["id"]), ADMIN), 201
    )
    assert trailer["dot_expires_on"] == "2027-01-01", (
        "2026-01-01 advanced by 365 days is 2027-01-01"
    )
    assert trailer["last_pm_hub_miles"] == 41000
    assert trailer["service_status"] == "SERVICEABLE"
    assert trailer["last_dot_passed"] is True


def test_shop_event_is_an_immutable_ledger_row(api):
    """PRD §2.5: "Shop events are the one exception. A `MaintenanceEvent` is an
    immutable ledger row: it carries only `id` and `created_at`, and both
    `updated_at` and `version` are absent from it entirely."
    PRD §3.7: "The server stamps the caller's `X-User-ID` onto the event as
    `inspector_user_id`."
    PRD §3.7: "A `PM_SERVICE` event sets the unit's `last_pm_hub_miles` to the
    event's `hub_miles_at_event`, which is what clears a `PM_DUE` unit back to
    `SERVICEABLE` — provided the unit is not simultaneously blocked by an earlier
    clause, meaning its `last_dot_passed` is true, the clock date is still before
    its `dot_expires_on`, and its live damage points are below 25."

    Design: Corner/entities/maintenance_event_is_immutable_and_has_no_version
    """
    ctx = setup_reference_data()

    response = api.create_maintenance_event(
        {
            "trailer_id": ctx["trailer_id"],
            "event_type": "PM_SERVICE",
            "performed_on": "2026-08-02",
            "hub_miles_at_event": 41000,
            "cost_cents": 42000,
        },
        INSPECTOR,
    )
    event = validate_success(response, 201)
    assert_maintenance_event(event)

    read_back = validate_success(api.get_maintenance_event(event["id"], ADMIN))
    assert read_back["event_type"] == "PM_SERVICE"
    assert read_back["inspector_user_id"] == "insp-1"
    assert "version" not in read_back, "a ledger row carries no version"
    assert "updated_at" not in read_back, "a ledger row carries no updated_at"

    assert read_trailer(ctx["trailer_id"])["last_pm_hub_miles"] == 41000


def test_list_units_paginates_and_filters_by_current_yard(api):
    """PRD §3.1: "Units may be listed and narrowed by `trailer_type_id`, by
    `home_branch_id`, by `current_branch_id`, and by either status dimension using
    `availability_status` or `service_status`."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_trailers_paginates_and_filters_by_current_branch
    """
    ctx = setup_reference_data()
    ids = {ctx["trailer_id"]}
    for number, miles in (("T-1002", 52000), ("T-1003", 63000)):
        ids.add(
            create_trailer(ctx["trailer_type_id"], ctx["branch_id"],
                           unit_number=number, hub_miles=miles)["id"]
        )

    rows, meta = validate_paginated(
        api.list_trailers(
            ADMIN,
            params={
                "current_branch_id": ctx["branch_id"],
                "availability_status": "AVAILABLE",
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(rows) == 2
    for row in rows:
        assert row["current_branch_id"] == ctx["branch_id"]
        assert row["availability_status"] == "AVAILABLE"
        assert row["id"] in ids


def test_reading_an_unknown_unit_reports_trailer_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type:
    `ERR_BRANCH_NOT_FOUND`, `ERR_TRAILER_TYPE_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
    `ERR_RATE_CARD_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_AGREEMENT_UNIT_NOT_FOUND`, `ERR_DAMAGE_ASSESSMENT_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_RELOCATION_ORDER_NOT_FOUND` or
    `ERR_MAINTENANCE_EVENT_NOT_FOUND`."

    Design: Corner/entities/get_trailer_by_unknown_id_returns_trailer_not_found
    """
    create_branch()
    validate_error(
        api.get_trailer(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_TRAILER_NOT_FOUND.value,
    )


def test_book_value_is_floored_at_the_class_residual(api):
    """PRD §3.1: "It then charges depreciation at ten percent of
    `acquisition_cost_cents` per year, prorated by those elapsed months over
    twelve, rounding the resulting depreciation charge half-up to whole cents.
    `net_book_value_cents` is then whichever is greater — the equipment class's
    `residual_floor_cents`, or the acquisition cost less that depreciation charge."

    Design: Corner/calculations/net_book_value_floored_at_residual_for_fully_depreciated_unit
    """
    ctx = setup_reference_data()

    old = create_trailer(
        ctx["trailer_type_id"], ctx["branch_id"],
        unit_number="T-OLD-1", acquisition_cost_cents=500_000,
        in_service_date="2016-01-01", hub_miles=900_000,
    )
    read_back = read_trailer(old["id"])
    assert read_back["net_book_value_cents"] == 450_000, (
        "a fully depreciated unit clamps to residual_floor_cents rather than going negative"
    )
    assert read_back["service_status"] == "SERVICEABLE"


def test_yard_counters_are_immediately_consistent_after_adding_a_unit(api):
    """PRD §2.10: "Both are recomputed whenever any trailer's yard, availability or
    service status changes, and both are recomputed at *both* affected yards when a
    movement changes a trailer's yard."
    PRD §3.1: "Both counters at the home yard rise by one."

    Design: Corner/consistency_model/branch_counters_are_immediately_consistent_after_trailer_create
    """
    ctx = setup_reference_data()

    before = read_branch(ctx["branch_id"])
    assert before["on_hand_count"] == 1
    assert before["serviceable_available_count"] == 1

    second = create_trailer(ctx["trailer_type_id"], ctx["branch_id"],
                            unit_number="T-1002", hub_miles=52000)

    after = read_branch(ctx["branch_id"])
    assert after["on_hand_count"] == 2, "the very next read already shows the new unit"
    assert after["serviceable_available_count"] == 2
    assert read_trailer(second["id"])["current_branch_id"] == ctx["branch_id"]


def test_retiring_an_idle_unit_drops_it_from_both_yard_counters(api):
    """PRD §3.1: "Retirement moves `AVAILABLE → RETIRED`, records the supplied
    `reason` into `retired_reason`, and decrements both `on_hand_count` and
    `serviceable_available_count` at the unit's `current_branch_id`."

    Design: Corner/endpoints/retire_removes_unit_from_branch_counters
    """
    ctx = setup_reference_data()
    before = read_branch(ctx["branch_id"])
    assert before["on_hand_count"] == 1
    assert before["serviceable_available_count"] == 1

    trailer = validate_success(
        api.retire_trailer(
            ctx["trailer_id"],
            {"reason": "frame corrosion beyond economic repair"},
            ADMIN,
        )
    )
    assert trailer["availability_status"] == "RETIRED"
    assert trailer["retired_reason"] == "frame corrosion beyond economic repair"

    after = read_branch(ctx["branch_id"])
    assert after["on_hand_count"] == 0
    assert after["serviceable_available_count"] == 0


def test_duplicate_equipment_class_code_is_rejected(api):
    """PRD §3.1: "The class `code` must be one of `DRY_VAN_53`, `REEFER_53`,
    `FLATBED_48` or `CHASSIS_40` and must be unique across all classes; a duplicate
    is rejected with `ERR_DUPLICATE_TRAILER_TYPE_CODE`."

    Design: Corner/errors/create_trailer_type_with_duplicate_code_rejected
    """
    setup_reference_data()

    response = api.create_trailer_type(
        trailer_type_payload(code="DRY_VAN_53", description="duplicate spec",
                             base_daily_rate_cents=4600, base_monthly_rate_cents=96000,
                             residual_floor_cents=460000),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_TRAILER_TYPE_CODE.value)

    rows, _ = validate_paginated(api.list_trailer_types(ADMIN, params={"limit": 100}))
    assert len([t for t in rows if t["code"] == "DRY_VAN_53"]) == 1


def test_duplicate_unit_number_is_rejected(api):
    """PRD §3.1: "A unit is created with a fleet `unit_number` that must be unique
    across all trailers — a collision is rejected with `ERR_DUPLICATE_UNIT_NUMBER`"

    Design: Corner/errors/create_trailer_with_duplicate_unit_number_rejected
    """
    ctx = setup_reference_data()

    response = api.create_trailer(
        trailer_payload(ctx["trailer_type_id"], ctx["branch_id"],
                        unit_number="T-1001", hub_miles=1000),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER.value)

    rows, _ = validate_paginated(api.list_trailers(ADMIN, params={"limit": 100}))
    assert len([t for t in rows if t["unit_number"] == "T-1001"]) == 1
    assert read_branch(ctx["branch_id"])["on_hand_count"] == 1


def test_reading_an_unknown_equipment_class_reports_trailer_type_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type:
    `ERR_BRANCH_NOT_FOUND`, `ERR_TRAILER_TYPE_NOT_FOUND`, `ERR_TRAILER_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_INSURANCE_CERTIFICATE_NOT_FOUND`,
    `ERR_RATE_CARD_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_AGREEMENT_UNIT_NOT_FOUND`, `ERR_DAMAGE_ASSESSMENT_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_RELOCATION_ORDER_NOT_FOUND` or
    `ERR_MAINTENANCE_EVENT_NOT_FOUND`."

    Design: Corner/errors/get_trailer_type_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_trailer_type(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_TRAILER_TYPE_NOT_FOUND.value,
    )
