"""Station registration, election windows, collection reads and the not-found codes."""

from test_helpers import (
    UNKNOWN_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_election,
    assert_station,
    create_election_payload,
    create_rate_class,
    create_station,
    create_station_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_station_registration_applies_every_declared_default(api):
    """PRD §3.1: "The `political_file_posting_deadline_hours` setting fixes how many
    hours after a disclosable event the corresponding public-file entry must be
    posted; it defaults to 24 hours — one full day — and must be an integer of at
    least 1."
    PRD §3.1: "The `daily_political_seconds_cap` setting fixes how many total seconds
    of political spot inventory the station is willing to carry on any single
    broadcast day; it defaults to 300 seconds, which is five minutes of airtime, and
    must be an integer of at least 30."
    PRD §3.1: "Finally `eo_parity_basis` selects which parity algorithm the station
    applies when it grants an equal-opportunity request; it defaults to `SPOT_COUNT`
    and its only other permitted value is `DOLLAR_VALUE`."
    PRD §3.1: "Registration initialises all four compliance counters —
    `pending_file_entry_count`, `overdue_file_entry_count`, `late_posting_count` and
    `open_complaint_count` — to zero, sets `compliance_posture` to `OPEN`, and leaves
    `last_sweep_at` null until the station's first audit checkpoint is run."
    PRD §2.4: "Most resources additionally carry an `updated_at` timestamp in the same
    format and an integer `version` that starts at 1 on creation and increments by
    exactly 1 on every mutation of that resource; `updated_at` is refreshed to the
    logical clock on each such mutation."

    Design: Corner/entities/station_creation_applies_declared_defaults_and_zeroes_every_counter
    """
    set_clock("2026-08-05T09:00:00Z")

    response = api.create_station(
        create_station_payload(
            call_sign="WDEF-TV",
            licensee_name="Default Licensee LLC",
            market_code="DMA-100",
        ),
        ADMIN,
    )
    data = validate_success(response, 201)
    assert_station(data)

    assert data["political_file_posting_deadline_hours"] == 24
    assert data["daily_political_seconds_cap"] == 300
    assert data["eo_parity_basis"] == "SPOT_COUNT"
    assert data["pending_file_entry_count"] == 0
    assert data["overdue_file_entry_count"] == 0
    assert data["late_posting_count"] == 0
    assert data["open_complaint_count"] == 0
    assert data["compliance_posture"] == "OPEN"
    assert data["version"] == 1
    assert data["last_sweep_at"] is None, "last_sweep_at stays null before the first sweep"


def test_general_election_window_is_sixty_days_and_status_tracks_the_clock(api):
    """PRD §3.2: "A `GENERAL` election carries a window of 60 days; `PRIMARY`, `RUNOFF`
    and `SPECIAL` elections each carry a window of 45 days."
    PRD §3.2: "From it the platform derives `window_start_date`, the calendar date
    arrived at by counting `luc_window_days` days backward from the `election_date`,
    which is the first date *inside* the window; and `window_end_date`, which is simply
    equal to the `election_date` and is the last date inside the window."
    PRD §3.2: "While that date is earlier than `window_start_date`, the status reads
    `SCHEDULED`. While it falls on or after `window_start_date` and on or before the
    `election_date`, the status reads `WINDOW_OPEN`. Once it is later than the
    `election_date`, the status reads `CLOSED`."

    Design: Corner/entities/general_election_window_is_sixty_days_and_status_tracks_the_clock
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WGEN-TV", licensee_name="General Election Media", market_code="DMA-101"
    )

    created = validate_success(
        api.create_election(
            create_election_payload(
                station["id"],
                office_sought="US House 4",
                election_type="GENERAL",
                election_date="2026-11-03",
            ),
            ADMIN,
        ),
        201,
    )
    assert_election(created)
    assert created["luc_window_days"] == 60
    assert created["window_start_date"] == "2026-09-04"
    assert created["window_end_date"] == "2026-11-03"
    assert created["status"] == "SCHEDULED", "the clock date is before window_start_date"

    set_clock("2026-09-04T00:00:00Z")
    at_window_start = validate_success(api.get_election(created["id"], ADMIN))
    assert at_window_start["status"] == "WINDOW_OPEN", (
        "window_start_date itself is inside the window"
    )

    set_clock("2026-11-04T00:00:00Z")
    after_election = validate_success(api.get_election(created["id"], ADMIN))
    assert after_election["status"] == "CLOSED"


def test_rate_class_listing_paginates_in_created_at_order(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, its
    minimum accepted value is 1, and its maximum accepted value is 100."
    PRD §2.3: "Collections are always ordered by `created_at` ascending before the page
    window is applied, regardless of any filters supplied."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` counts the rows matching the filters
    before pagination, and `has_more` is true when rows remain beyond the current page."

    Design: Corner/entities/rate_class_listing_paginates_with_total_count_and_has_more
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WPAG-TV", licensee_name="Paginated Media LLC", market_code="DMA-102"
    )
    first = create_rate_class(
        station["id"],
        class_code="RC-1",
        daypart="MORNING",
        preemptible=True,
        preemption_priority=3,
        posted_rate_cents=10000,
    )
    second = create_rate_class(
        station["id"],
        class_code="RC-2",
        daypart="DAYTIME",
        preemptible=True,
        preemption_priority=4,
        posted_rate_cents=20000,
    )
    third = create_rate_class(
        station["id"],
        class_code="RC-3",
        daypart="PRIME",
        preemptible=False,
        preemption_priority=0,
        posted_rate_cents=30000,
    )

    page_one, meta_one = validate_paginated(
        api.list_rate_classes(ADMIN, params={"station_id": station["id"], "limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, f"expected 2 rows on the first page, got {len(page_one)}"
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [first["id"], second["id"]]

    page_two, meta_two = validate_paginated(
        api.list_rate_classes(ADMIN, params={"station_id": station["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert page_two[0]["id"] == third["id"]


def test_pagination_limit_above_the_maximum_is_rejected(api):
    """PRD §2.3: "A `limit` that is not an integer within the inclusive range of 1
    through 100, or an `offset` that is not an integer of zero or greater, is rejected
    with `ERR_INVALID_PAGINATION` (HTTP 422)."

    Design: Corner/validations/pagination_limit_above_the_maximum_rejected_as_invalid_pagination
    """
    set_clock("2026-08-05T09:00:00Z")
    station = create_station(
        call_sign="WPGN-TV", licensee_name="Page Bound Media", market_code="DMA-135"
    )
    rate_class = create_rate_class(station["id"])

    over_limit = api.list_rate_classes(
        ADMIN, params={"station_id": station["id"], "limit": 101, "offset": 0}
    )
    validate_error(over_limit, ApiErrorId.ERR_INVALID_PAGINATION)

    rows, meta = validate_paginated(
        api.list_rate_classes(
            ADMIN, params={"station_id": station["id"], "limit": 100, "offset": 0}
        )
    )
    assert rows[0]["id"] == rate_class["id"], "limit 100 is the highest accepted value"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_order_read_with_an_unknown_identifier_reports_the_order_not_found_code(api):
    """PRD §2.7: "The existence errors are `ERR_STATION_NOT_FOUND` for a station,
    `ERR_ELECTION_NOT_FOUND` for an election, `ERR_ADVERTISER_NOT_FOUND` for an
    advertiser, `ERR_RATE_CLASS_NOT_FOUND` for a rate class, `ERR_ORDER_NOT_FOUND` for
    a commercial order, `ERR_SPOT_NOT_FOUND` for a scheduled spot,
    `ERR_FILE_ENTRY_NOT_FOUND` for a political file entry, `ERR_EO_REQUEST_NOT_FOUND`
    for an equal-opportunity request, `ERR_LUC_DETERMINATION_NOT_FOUND` for a
    lowest-unit-charge determination, `ERR_COMPLAINT_NOT_FOUND` for an FCC complaint,
    and `ERR_REBATE_NOT_FOUND` for a rebate ledger entry. All eleven carry HTTP 404."

    Design: Corner/entities/order_get_with_unknown_uuid_returns_order_not_found
    """
    set_clock("2026-08-05T09:00:00Z")

    response = api.get_order(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_audit_sweep_on_an_unknown_station_reports_the_station_not_found_code(api):
    """PRD §2.7: "Path parameters are resolved strictly left to right, and the first
    identifier that names nothing produces the not-found error for its own resource
    type before any deeper check runs."
    PRD §2.7: "The existence errors are `ERR_STATION_NOT_FOUND` for a station,
    `ERR_ELECTION_NOT_FOUND` for an election, `ERR_ADVERTISER_NOT_FOUND` for an
    advertiser, `ERR_RATE_CLASS_NOT_FOUND` for a rate class, `ERR_ORDER_NOT_FOUND` for
    a commercial order, `ERR_SPOT_NOT_FOUND` for a scheduled spot,
    `ERR_FILE_ENTRY_NOT_FOUND` for a political file entry, `ERR_EO_REQUEST_NOT_FOUND`
    for an equal-opportunity request, `ERR_LUC_DETERMINATION_NOT_FOUND` for a
    lowest-unit-charge determination, `ERR_COMPLAINT_NOT_FOUND` for an FCC complaint,
    and `ERR_REBATE_NOT_FOUND` for a rebate ledger entry. All eleven carry HTTP 404."

    Design: Corner/entities/audit_sweep_on_unknown_station_returns_station_not_found
    """
    set_clock("2026-08-05T09:00:00Z")

    validate_error(api.audit_sweep(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_STATION_NOT_FOUND)


def test_review_on_an_unknown_advertiser_reports_the_advertiser_not_found_code(api):
    """PRD §2.7: "Path parameters are resolved strictly left to right, and the first
    identifier that names nothing produces the not-found error for its own resource
    type before any deeper check runs."
    PRD §2.7: "The existence errors are `ERR_STATION_NOT_FOUND` for a station,
    `ERR_ELECTION_NOT_FOUND` for an election, `ERR_ADVERTISER_NOT_FOUND` for an
    advertiser, `ERR_RATE_CLASS_NOT_FOUND` for a rate class, `ERR_ORDER_NOT_FOUND` for
    a commercial order, `ERR_SPOT_NOT_FOUND` for a scheduled spot,
    `ERR_FILE_ENTRY_NOT_FOUND` for a political file entry, `ERR_EO_REQUEST_NOT_FOUND`
    for an equal-opportunity request, `ERR_LUC_DETERMINATION_NOT_FOUND` for a
    lowest-unit-charge determination, `ERR_COMPLAINT_NOT_FOUND` for an FCC complaint,
    and `ERR_REBATE_NOT_FOUND` for a rebate ledger entry. All eleven carry HTTP 404."

    Design: Corner/errors/review_on_an_unknown_advertiser_returns_advertiser_not_found
    """
    set_clock("2026-08-05T09:00:00Z")

    validate_error(
        api.review_advertiser(UNKNOWN_UUID, TEST_USERS["officer_alpha_headers"]),
        ApiErrorId.ERR_ADVERTISER_NOT_FOUND,
    )


def test_disposition_on_an_unknown_spot_reports_the_spot_not_found_code(api):
    """PRD §2.7: "Path parameters are resolved strictly left to right, and the first
    identifier that names nothing produces the not-found error for its own resource
    type before any deeper check runs."
    PRD §2.9: "3. **Existence.** The eleven not-found checks of Section 2.7, in the
    resource-type order given there."

    Design: Corner/errors/disposition_on_an_unknown_spot_returns_spot_not_found
    """
    set_clock("2026-08-05T09:00:00Z")

    validate_error(
        api.set_spot_disposition(
            UNKNOWN_UUID, {"disposition": "AIRED"}, TEST_USERS["traffic_scheduler_headers"]
        ),
        ApiErrorId.ERR_SPOT_NOT_FOUND,
    )


def test_each_read_endpoint_reports_its_own_domain_not_found_code(api):
    """PRD §2.7: "The existence errors are `ERR_STATION_NOT_FOUND` for a station,
    `ERR_ELECTION_NOT_FOUND` for an election, `ERR_ADVERTISER_NOT_FOUND` for an
    advertiser, `ERR_RATE_CLASS_NOT_FOUND` for a rate class, `ERR_ORDER_NOT_FOUND` for
    a commercial order, `ERR_SPOT_NOT_FOUND` for a scheduled spot,
    `ERR_FILE_ENTRY_NOT_FOUND` for a political file entry, `ERR_EO_REQUEST_NOT_FOUND`
    for an equal-opportunity request, `ERR_LUC_DETERMINATION_NOT_FOUND` for a
    lowest-unit-charge determination, `ERR_COMPLAINT_NOT_FOUND` for an FCC complaint,
    and `ERR_REBATE_NOT_FOUND` for a rebate ledger entry. All eleven carry HTTP 404."

    Design: Corner/errors/unknown_ids_on_the_remaining_read_endpoints_return_their_own_not_found_codes
    """
    set_clock("2026-08-05T09:00:00Z")

    cases = [
        (api.get_election(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_ELECTION_NOT_FOUND),
        (api.get_rate_class(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_RATE_CLASS_NOT_FOUND),
        (api.get_file_entry(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_FILE_ENTRY_NOT_FOUND),
        (api.get_eo_request(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_EO_REQUEST_NOT_FOUND),
        (
            api.get_luc_determination(UNKNOWN_UUID, ADMIN),
            ApiErrorId.ERR_LUC_DETERMINATION_NOT_FOUND,
        ),
        (api.get_complaint(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_rebate(UNKNOWN_UUID, ADMIN), ApiErrorId.ERR_REBATE_NOT_FOUND),
    ]
    for response, expected_error in cases:
        validate_error(response, expected_error)
        assert response.json()["response_type"] == "error"
