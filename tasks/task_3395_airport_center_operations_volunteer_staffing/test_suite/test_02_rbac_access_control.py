"""Role-based access control: role denial on exclusive endpoints,
entity-backed scoping, and authentication failures."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_center,
    create_center_with_active_agreement,
    create_guest,
    create_volunteer,
    get_center,
    make_guest_headers,
    make_volunteer_headers,
    set_clock,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]
# Fallback Volunteer identity for a pure role-denial probe (no ownership
# of the target resource is involved, so the shared constant is correct).
VOLUNTEER_FALLBACK = TEST_USERS["volunteer_headers"]


def test_volunteer_cannot_create_center(api: ApiClient):
    """PRD §3.1: "A `PlatformAdmin` opens a new center by supplying its `name`, its `airport_code` (the IATA airport or installation code, such as LAX), an `occupancy_cap` of at least 1 (the maximum number of simultaneously checked-in guests), and a `required_daily_confirmed_assignments` of at least 1 (the confirmed assignment slots on the current day's shifts that constitute full coverage)."
    PRD §2.1: "A request whose role is declared but not permitted for the target endpoint — or that violates an entity-backed ownership scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/volunteer_cannot_create_center
    """
    resp = api.create_center(
        {
            "name": "Rogue Center",
            "airport_code": "XXX",
            "occupancy_cap": 5,
            "required_daily_confirmed_assignments": 1,
        },
        VOLUNTEER_FALLBACK,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_anonymous_cannot_run_ops(api: ApiClient):
    """PRD §2.9: "Each center is swept by an operations checkpoint that a `CenterManager` triggers for one center at a time."
    PRD §2.1: "A request whose role is declared but not permitted for the target endpoint — or that violates an entity-backed ownership scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "Incoming requests pass through a fixed pipeline of checks, and an earlier failure always masks every later one."

    Design: Corner/rbac/anonymous_cannot_run_ops
    """
    set_clock()
    center = create_center(
        name="Pe Center",
        airport_code="MAF",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    resp = api.run_ops(center["id"], ANON)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = get_center(center["id"])
    assert after["ops_run_count"] == 0, (
        "a rejected run_ops must not execute the sweep; "
        f"ops_run_count should stay 0, got {after['ops_run_count']}"
    )


def test_guest_cannot_create_shift(api: ApiClient):
    """PRD §3.3: "A `CenterManager` shapes the day's coverage by creating shifts with a `start_at` strictly before `end_at` (`ERR_VALIDATION` otherwise), a `role_required` of `DESK`, `KITCHEN`, `EVENTS`, or `FAMILY`, and a `capacity` of at least 1 (the maximum number of `CONFIRMED` assignments the shift will hold)."
    PRD §2.1: "A request whose role is declared but not permitted for the target endpoint — or that violates an entity-backed ownership scope — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/guest_cannot_create_shift
    """
    set_clock()
    center = create_center(
        name="Tsadi Center",
        airport_code="PIE",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    guest = create_guest(full_name="G Role")
    resp = api.create_shift(
        center["id"],
        {
            "start_at": "2026-09-02T08:00:00Z",
            "end_at": "2026-09-02T12:00:00Z",
            "role_required": "DESK",
            "capacity": 1,
        },
        make_guest_headers(guest["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_volunteer_cannot_list_other_assignments(api: ApiClient):
    """PRD §3.3: "Assignments can be listed filtered by `shift_id` and/or `volunteer_id`; a `Volunteer` caller is scoped to its own identity, and passing any other `volunteer_id` is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/volunteer_cannot_list_other_assignments
    """
    set_clock()
    center = create_center(
        name="Resh Center",
        airport_code="ELP",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    v1 = create_volunteer(center["id"], full_name="V Self")
    v2 = create_volunteer(center["id"], full_name="V Other")
    resp = api.list_assignments(
        make_volunteer_headers(v1["id"]), params={"volunteer_id": v2["id"]}
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_guest_cannot_book_for_other(api: ApiClient):
    """PRD §3.5: "A `Guest` caller may book only for itself — the `guest_id` must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN` — while a `CenterManager` books on any guest's behalf."

    Design: Corner/rbac/guest_cannot_book_for_other
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Shin Center",
            "airport_code": "AMA",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    g1 = create_guest(full_name="G Self")
    g2 = create_guest(full_name="G Other", category="DEPENDENT")
    resp = api.create_service_booking(
        center["id"],
        {
            "guest_id": g2["id"],
            "service_type": "CONNECTIVITY",
            "start_at": "2026-09-01T10:00:00Z",
            "end_at": "2026-09-01T11:00:00Z",
        },
        make_guest_headers(g1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_request_missing_auth_headers_unauthenticated(api: ApiClient):
    """PRD §2.1: "A request missing either header, or carrying a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "First, authentication: both identity headers must be present and the role declared, else `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/request_missing_auth_headers_unauthenticated
    """
    # headers=None sends no X-User-ID / X-User-Role at all; authentication
    # precedes existence, so even a nonexistent resource yields 401.
    resp = api.get_center(NON_EXISTENT_UUID, headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
