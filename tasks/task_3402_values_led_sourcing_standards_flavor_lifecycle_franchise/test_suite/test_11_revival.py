"""Fan-driven revival: window, threshold, board decision (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_revival_request_payload,
    make_flavor, make_limited_run_flavor, make_retired_flavor,
    make_revival_request, sign_revival, make_qualified_revival,
    make_independent_board_member_headers,
    CLOCK_DEFAULT_ISO,
)

FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]
FAN = TEST_USERS["fan_headers"]



def test_revival_create_requires_retired_flavor(api):
    """PRD §3.6: "first the flavor's `status` must be `RETIRED`, failing with
    `ERR_FLAVOR_NOT_RETIRED` (HTTP 409)".

    Design: Corner/state_machines/revival_create_requires_retired_flavor
    """
    flavor = make_limited_run_flavor(name="Still Selling")
    resp = api.create_revival_request(
        flavor["id"],
        create_revival_request_payload(fan_email="eager@example.com",
                                       title="Too soon"), FAN)
    validate_error(resp, ApiErrorId.ERR_FLAVOR_NOT_RETIRED)


def test_revival_create_after_window_rejected(api):
    """PRD §3.6: "and then the current logical time must be no later than
    `retired_at` plus 730 days — two full years — failing with
    `ERR_REVIVAL_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/state_machines/revival_create_after_window_rejected
    """
    flavor = make_retired_flavor(name="Long Gone")  # retired at the clock default
    validate_success(api.set_clock({"to_iso8601": "2028-09-02T00:00:00Z"}, POC))
    resp = api.create_revival_request(
        flavor["id"],
        create_revival_request_payload(fan_email="late@example.com",
                                       title="Too late"), FAN)
    validate_error(resp, ApiErrorId.ERR_REVIVAL_WINDOW_EXPIRED)


def test_revival_decline_from_open_valid(api):
    """PRD §3.6: "The board may instead decline a request in `OPEN` or
    `QUALIFIED`, moving it to the terminal `DECLINED` with no effect on the
    flavor."

    Design: Corner/state_machines/revival_decline_from_open_valid
    """
    flavor = make_retired_flavor(name="Nope Nugget")
    request = make_revival_request(flavor["id"], fan_email="start@example.com")
    assert request["status"] == "OPEN"
    resp = api.decline_revival_request(
        request["id"], make_independent_board_member_headers("board-1"))
    data = validate_success(resp)
    assert data["status"] == "DECLINED"


def test_revival_sign_after_qualified_rejected(api):
    """PRD §3.6: "A `Fan` signs an `OPEN` request with their `fan_email` and an
    optional `count` of signatures being contributed".
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/revival_sign_after_qualified_rejected
    """
    flavor = make_retired_flavor(name="Threshold Treat")
    request = make_revival_request(flavor["id"], fan_email="start@example.com")
    qualified = sign_revival(request["id"], "mass@example.com", 500)
    assert qualified["status"] == "QUALIFIED"

    resp = api.sign_revival_request(
        request["id"], {"fan_email": "late@example.com", "count": 1}, FAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_revival_adopt_from_open_rejected(api):
    """PRD §3.6: "An `IndependentBoardMember` adopts a `QUALIFIED` request,
    moving it to the terminal `ADOPTED` and transitioning the flavor itself
    from `RETIRED` to `REVIVED`".
    PRD §2.6: "the requested transition must be defined for the resource's current state, failing with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/validations/revival_adopt_from_open_rejected
    """
    flavor = make_retired_flavor(name="Almost Famous")
    request = make_revival_request(flavor["id"], fan_email="start@example.com")
    sign_revival(request["id"], "hundred@example.com", 100)
    resp = api.adopt_revival_request(
        request["id"], make_independent_board_member_headers("board-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_duplicate_signature_rejected(api):
    """PRD §3.6: "the request enforces one signature per email per request, and
    a repeat signature from the same `fan_email` is rejected with
    `ERR_DUPLICATE_SIGNATURE` (HTTP 409)."

    Design: Corner/validations/duplicate_signature_rejected
    """
    flavor = make_retired_flavor(name="Dupes Delight")
    request = make_revival_request(flavor["id"], fan_email="start@example.com")
    first = sign_revival(request["id"], "fan-a@example.com", 1)
    assert first["signature_count"] == 1

    resp = api.sign_revival_request(
        request["id"], {"fan_email": "fan-a@example.com", "count": 3}, FAN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNATURE)
    after = get_success_data(api.get_flavor(flavor["id"], FM))  # flavor untouched
    assert after["status"] == "RETIRED"


def test_parent_ops_cannot_adopt_revival(api):
    """PRD §3.6: "Adoption is a social-mission decision reserved to the
    independent board."
    PRD §2.9: "Neither role can perform the other's exclusive operations, and a
    role not listed for an operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/parent_ops_cannot_adopt_revival
    """
    flavor = make_retired_flavor(name="Adoption Gate")
    request = make_qualified_revival(flavor["id"])
    assert request["status"] == "QUALIFIED"
    resp = api.adopt_revival_request(request["id"], POC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_revival_threshold_exact_500(api):
    """PRD §3.6: "The moment the running total reaches at least 500 — the threshold is inclusive, so exactly 500 qualifies while 499 does not — the system moves the request from `OPEN` to `QUALIFIED` and stamps `qualified_at` from the logical clock."
    PRD §2.5: "Before any client touches it, the clock reads exactly
    `2026-09-01T00:00:00Z`".

    Design: Difficulty/boundary_precision_check/revival_threshold_exact_500
    """
    flavor = make_retired_flavor(name="Gone But Loved")
    request = make_revival_request(flavor["id"], fan_email="starter@example.com")

    mid = sign_revival(request["id"], "fan-a@example.com", 499)
    assert mid["signature_count"] == 499
    assert mid["status"] == "OPEN", "499 does not qualify"

    end = sign_revival(request["id"], "fan-b@example.com", 1)
    assert end["signature_count"] == 500
    assert end["status"] == "QUALIFIED", "exactly 500 qualifies; threshold is >="
    assert end["qualified_at"], "qualified_at must be stamped from the logical clock"
    assert str(end["qualified_at"]).startswith("2026-09-01")


def test_revival_threshold_crossed_by_multi_signature(api):
    """PRD §3.6: "The moment the running total reaches at least 500 — the threshold is inclusive, so exactly 500 qualifies while 499 does not — the system moves the request from `OPEN` to `QUALIFIED` and stamps `qualified_at` from the logical clock."

    Design: Difficulty/boundary_precision_check/revival_threshold_exact_500
    """
    flavor = make_retired_flavor(name="Surge Sorbet")
    request = make_revival_request(flavor["id"], fan_email="starter@example.com")

    mid = sign_revival(request["id"], "fan-a@example.com", 250)
    assert mid["signature_count"] == 250
    assert mid["status"] == "OPEN"

    end = sign_revival(request["id"], "fan-b@example.com", 251)
    assert end["signature_count"] == 501
    assert end["status"] == "QUALIFIED", "crossing the threshold qualifies"
    assert str(end["qualified_at"]).startswith("2026-09-01")
