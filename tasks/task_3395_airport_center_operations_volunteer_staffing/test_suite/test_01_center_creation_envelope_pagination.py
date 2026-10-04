"""Creation defaults, not-found and missing-field handling, response
envelope shape, and list pagination."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_center,
    assert_guest,
    assert_volunteer,
    create_center,
    create_guest,
    create_volunteer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_center_create_returns_computed_defaults(api: ApiClient):
    """PRD §2.6: "A freshly created center starts `CLOSED` with `current_occupancy` 0, `coverage_ratio` 0, an empty `expense_ledger`, `ops_run_count` 0, and `active_agreement_id` null."

    Design: Corner/entities/center_create_returns_defaults
    """
    set_clock()
    resp = api.create_center(
        {
            "name": "Tau Center",
            "airport_code": "PHL",
            "occupancy_cap": 25,
            "required_daily_confirmed_assignments": 2,
        },
        ADMIN,
    )
    center = validate_success(resp, 201)
    assert_center(center)
    assert center["posture"] == "CLOSED", (
        f"fresh center must start CLOSED, got {center['posture']!r}"
    )
    assert center["current_occupancy"] == 0
    assert center["coverage_ratio"] == 0
    assert center["ops_run_count"] == 0
    assert center["active_agreement_id"] is None
    assert center["expense_ledger"] == [], "expense_ledger must start empty"


def test_volunteer_register_initial_applied(api: ApiClient):
    """PRD §3.2: "Anyone may apply: the public intake records a volunteer's `full_name`, `email`, and `home_center_id`, and the application rests in `APPLIED`, with `no_show_strikes` and `total_hours` both starting at 0."

    Design: Corner/entities/volunteer_register_initial_applied
    """
    set_clock()
    center = create_center(name="Upsilon Center", airport_code="MDW")
    resp = api.create_volunteer(
        {
            "full_name": "V New",
            "email": "vn@example.org",
            "home_center_id": center["id"],
        },
        ANON,
    )
    volunteer = validate_success(resp, 201)
    assert_volunteer(volunteer)
    assert volunteer["status"] == "APPLIED", (
        f"new volunteer must rest in APPLIED, got {volunteer['status']!r}"
    )
    assert volunteer["no_show_strikes"] == 0
    assert volunteer["total_hours"] == 0


def test_guest_register_default_eligible(api: ApiClient):
    """PRD §3.4: "Unlike other creation-time dates, an already-past `verification_expires_on` is accepted at registration — eligibility lapse is applied lazily — and the guest starts `ELIGIBLE`."

    Design: Corner/entities/guest_register_default_eligible
    """
    set_clock()
    resp = api.create_guest(
        {
            "full_name": "G New",
            "category": "GUARD_RESERVE",
            "verification_expires_on": "2028-05-01",
        },
        ANON,
    )
    guest = validate_success(resp, 201)
    assert_guest(guest)
    assert guest["eligibility_status"] == "ELIGIBLE", (
        f"new guest must start ELIGIBLE, got {guest['eligibility_status']!r}"
    )


def test_get_center_not_found_returns_404(api: ApiClient):
    """PRD §2.7: "Fourth, existence: path resources are validated left to right — the center first, then the child within it — and a missing resource yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_center_not_found_returns_404
    """
    resp = api.get_center(NON_EXISTENT_UUID, MGR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_center_create_missing_required_returns_400(api: ApiClient):
    """PRD §2.7: "Third, request shape: required fields present, enums in range, dates well-formed, `end_at` later than `start_at`, quantities at least 1, a renewal's new end date later than the current one, and creation-time dates not in the past where this document requires it — else `ERR_VALIDATION`."
    PRD §3.1: "A `PlatformAdmin` opens a new center by supplying its `name`, its `airport_code` (the IATA airport or installation code, such as LAX), an `occupancy_cap` of at least 1 (the maximum number of simultaneously checked-in guests), and a `required_daily_confirmed_assignments` of at least 1 (the confirmed assignment slots on the current day's shifts that constitute full coverage)."

    Design: Corner/entities/center_create_missing_required_returns_400
    """
    resp = api.create_center(
        {
            "name": "No Code Center",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_response_envelope_shape(api: ApiClient):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/endpoints/response_envelope_shape
    """
    ok = api.create_center(
        {
            "name": "Ayin Center",
            "airport_code": "GUM",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        },
        ADMIN,
    )
    assert ok.status_code == 201, f"expected 201, got {ok.status_code}: {ok.text}"
    body = ok.json()
    request_id = body["meta"].get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id must be a string starting with 'req_', got {request_id!r}"
    )
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object", (
        f"single-resource response_type must be 'object', got {body['response_type']!r}"
    )
    assert isinstance(body["data"], dict) and body["data"].get("id")

    err = api.get_center(NON_EXISTENT_UUID, MGR)
    assert err.status_code == 404
    ebody = err.json()
    assert ebody["response_type"] == "error"
    assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"
    message = ebody["data"].get("message")
    assert isinstance(message, str) and message.strip(), (
        "error responses must carry a non-empty human-readable message"
    )


def test_volunteers_pagination_defaults(api: ApiClient):
    """PRD §2.3: "List endpoints accept the optional query parameters `limit` and `offset`. `limit` defaults to 10 and must be between 1 and 100 inclusive; `offset` defaults to 0. Every list is sorted by `created_at` ascending. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` so clients can page deterministically through a collection."

    Design: Corner/endpoints/volunteers_pagination_defaults
    """
    set_clock()
    center = create_center(
        name="Samekh Center",
        airport_code="GSP",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    for i in range(1, 12):
        create_volunteer(center["id"], full_name=f"V P{i:02d}")

    page1, meta1 = validate_paginated(api.list_volunteers(MGR))
    assert len(page1) == 10, (
        f"default page must hold 10 rows (limit default), got {len(page1)}"
    )
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 11
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_volunteers(MGR, params={"limit": 10, "offset": 10})
    )
    assert len(page2) == 1, (
        f"offset 10 must expose exactly the 11th row, got {len(page2)}"
    )
    assert meta2["total_count"] == 11
    assert meta2["has_more"] is False
