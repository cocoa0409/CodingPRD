"""District and rider read surface: declared defaults, required fields and
the computed masked contact digest."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_minimally_registered_district_starts_active_and_owing_nothing():
    """PRD §3.1: "Registration seeds the district's `outstanding_balance_cents`
    and `credit_balance_cents` at zero, sets `account_status` to `ACTIVE`,
    initialises `trips_scheduled_total` at zero, and stamps the district's first
    `version`".
    PRD §3.1: "optionally, a per-trip `minimum_billable_cents` floor that
    defaults to zero".

    Design: Corner/entities/district_create_returns_every_declared_default_and_starts_active
    """
    resp = api_client.create_district(
        {
            "name": "Aldine ISD",
            "billing_email": "ap@aldine.example",
            "contract_rate_per_ride_cents": 5300,
            "contract_rate_per_mile_cents": 215,
        },
        TEST_USERS["anonymous_headers"],
    )
    district = validate_success(resp, 201)

    assert district["name"] == "Aldine ISD"
    assert district["billing_email"] == "ap@aldine.example"
    assert district["account_status"] == "ACTIVE"
    assert district["credit_balance_cents"] == 0
    assert district["outstanding_balance_cents"] == 0
    assert district["trips_scheduled_total"] == 0
    assert district["minimum_billable_cents"] == 0
    assert district["version"] == 1
    assert district["id"] and district["created_at"] and district["updated_at"]


def test_a_district_round_trips_its_calendar_and_alert_flag_unchanged():
    """PRD §3.1: "a list of `no_school_dates`, the district's earliest bell time
    as a `HH:MM` local string in `bell_schedule_start`".
    PRD §3.1: "a `support_center_alert_enabled` switch that defaults to true and
    decides whether `HIGH`-severity alerts also page the support desk."

    Design: Corner/entities/district_get_round_trips_optional_arrays_and_flags
    """
    created = get_success_data(
        api_client.create_district(
            {
                "name": "Spring Branch ISD",
                "billing_email": "ap@sb.example",
                "contract_rate_per_ride_cents": 4900,
                "contract_rate_per_mile_cents": 200,
                "minimum_billable_cents": 500,
                "no_school_dates": ["2026-11-26", "2026-11-27"],
                "bell_schedule_start": "08:15",
                "support_center_alert_enabled": False,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    read = get_success_data(
        api_client.get_district(created["id"], TEST_USERS["district_admin_headers"])
    )
    assert read["no_school_dates"] == ["2026-11-26", "2026-11-27"]
    assert read["support_center_alert_enabled"] is False
    assert read["bell_schedule_start"] == "08:15"
    assert read["minimum_billable_cents"] == 500


def test_district_rider_listing_pages_with_total_count_and_has_more():
    """PRD §2.3: "`limit` caps how many items a single response may carry; it
    defaults to 10, must be at least 1, and must not exceed 100. `offset` states
    how many leading items to skip and defaults to 0."
    PRD §2.3: "Paged and non-paged list responses alike report `limit`,
    `offset`, `total_count` and `has_more` inside the `meta` object".

    Design: Corner/entities/district_list_paginates_with_total_count_and_has_more
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    for name, program, phone in (
        ("Ana Ruiz", "GENERAL", "5550101"),
        ("Beto Lane", "FOSTER_CARE", "5550102"),
        ("Cara Voss", "SPECIAL_EDUCATION", "5550103"),
    ):
        get_success_data(
            api_client.create_rider(
                {
                    "district_id": district["id"],
                    "full_name": name,
                    "date_of_birth": "2014-04-02",
                    "program_type": program,
                    "home_address": "12 Oak St",
                    "school_name": "Lincoln Elementary",
                    "emergency_contact_phone": phone,
                },
                TEST_USERS["district_admin_headers"],
            ),
            201,
        )

    first_page = api_client.list_district_riders(
        district["id"], TEST_USERS["district_admin_headers"],
        params={"limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page = api_client.list_district_riders(
        district["id"], TEST_USERS["district_admin_headers"],
        params={"limit": 2, "offset": 2},
    )
    rows_two, meta_two = validate_paginated(second_page)
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(rows_two) == 1


def test_an_unminted_rider_id_is_reported_as_not_found():
    """PRD §2.11: "The first identifier that does not resolve produces
    `ERR_NOT_FOUND` (HTTP 404), and no later identifier in the same path is
    consulted."

    Design: Corner/entities/rider_get_with_an_unknown_id_returns_not_found
    """
    resp = api_client.get_rider(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
        TEST_USERS["district_admin_headers"],
    )
    error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error["message"].strip(), "an error response carries a human-readable message"


def test_a_rider_registered_without_a_school_of_record_is_refused():
    """PRD §3.2: "A `DistrictAdmin` registers a student by supplying the
    district's identifier together with the student's `full_name`,
    `date_of_birth`, `program_type`, `home_address`, `school_name`,
    `emergency_contact_phone`".
    PRD §2.1: "A request whose role is recognised but is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/entities/rider_create_missing_the_school_of_record_returns_invalid_request
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    resp = api_client.create_rider(
        {
            "district_id": district["id"],
            "full_name": "Ana Ruiz",
            "date_of_birth": "2014-04-02",
            "program_type": "GENERAL",
            "home_address": "12 Oak St",
            "emergency_contact_phone": "5550101",
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    after = get_success_data(
        api_client.list_district_riders(
            district["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert after == [], "no Rider row may be created by the rejected request"


def test_a_rider_posted_without_optional_fields_takes_every_declared_default():
    """PRD §3.2: "optionally a `spi_level` that defaults to 1, a list of
    `authorized_adults`, and the two notification switches `notify_on_pickup`
    and `notify_on_dropoff`, both of which default to true."
    PRD §3.2: "A new student record begins in `ACTIVE` status with a zero
    `active_ride_request_count`".

    Design: Corner/entities/rider_create_defaults_the_notification_flags_and_the_priority_level
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    rider = get_success_data(
        api_client.create_rider(
            {
                "district_id": district["id"],
                "full_name": "Ana Ruiz",
                "date_of_birth": "2014-04-02",
                "program_type": "GENERAL",
                "home_address": "12 Oak St",
                "school_name": "Lincoln Elementary",
                "emergency_contact_phone": "5550101",
            },
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert rider["spi_level"] == 1
    assert rider["notify_on_pickup"] is True
    assert rider["notify_on_dropoff"] is True
    assert rider["authorized_adults"] == []
    assert rider["status"] == "ACTIVE"
    assert rider["active_ride_request_count"] == 0


def test_the_masked_contact_digest_is_rederived_when_the_raw_number_changes():
    """PRD §3.2: "the platform derives the student's masked contact digest
    `support_center_phone_masked` from the emergency contact number by retaining
    only the final four digits."
    PRD §3.2: "a `DistrictAdmin` may update a student's `home_address`,
    `school_name`, `emergency_contact_phone`, `authorized_adults`,
    `notify_on_pickup`, `notify_on_dropoff` or `spi_level` after registration".

    Design: Corner/entities/rider_masked_contact_is_computed_and_the_raw_number_still_round_trips
    """
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )
    rider = get_success_data(
        api_client.create_rider(
            {
                "district_id": district["id"],
                "full_name": "Ana Ruiz",
                "date_of_birth": "2014-04-02",
                "program_type": "GENERAL",
                "home_address": "12 Oak St",
                "school_name": "Lincoln Elementary",
                "emergency_contact_phone": "5551234567",
            },
            TEST_USERS["district_admin_headers"],
        ),
        201,
    )
    assert rider["support_center_phone_masked"].endswith("4567")
    assert rider["emergency_contact_phone"] == "5551234567"

    updated = validate_success(
        api_client.update_rider(
            rider["id"],
            {"emergency_contact_phone": "5559876543"},
            TEST_USERS["district_admin_headers"],
        )
    )
    assert updated["emergency_contact_phone"] == "5559876543"
    assert updated["support_center_phone_masked"].endswith("6543")
    assert updated["support_center_phone_masked"] != updated["emergency_contact_phone"], (
        "the digest masks all but the final four digits of the raw number"
    )
    assert updated["version"] > rider["version"], (
        "an update advances the student's version"
    )