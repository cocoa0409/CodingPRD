"""Entity creation, system fields, and initial-state claims."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_iso8601_timestamp, NON_EXISTENT_UUID, ApiErrorId,
    create_theatre_payload, create_company_payload, create_production_payload,
    create_booking_payload,
    make_company_rep_headers, TEST_USERS,
    assert_theatre, assert_booking, assert_ticket_order,
    setup_active_booking,
)

HM = TEST_USERS["house_manager_headers"]


def test_theatre_create_returns_201_with_system_fields(api):
    """PRD §4: "Operations that create a new resource return `201 Created`".
    PRD §2.4: "`id` (string): a server-minted UUID with no type prefix.
    `created_at` (string): ISO 8601 UTC timestamp with three fractional digits,
    set at creation. `updated_at` (string): ISO 8601 UTC timestamp refreshed on
    every mutation. `version` (integer): starts at its initial value on
    creation and increments by one on every mutation of the resource".

    Design: Corner/entities/theatre_create_returns_201_with_system_fields
    """
    resp = api_client.create_theatre(
        create_theatre_payload(name="Lyceum", capacity=900, size_class="MEDIUM",
                               is_landmark=False, base_weekly_rent_cents=700000),
        HM)
    data = validate_success(resp, expected_status=201)
    assert_theatre(data)
    assert data["version"] == 1, f"new resource version must start at 1, got {data['version']}"
    assert data["size_class"] == "MEDIUM"
    assert is_iso8601_timestamp(data["created_at"])


def test_theatre_get_missing_returns_404(api):
    """PRD §2.5: "the system validates path resources from left to right ...
    and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
    does not exist".

    Design: Corner/entities/theatre_get_missing_returns_404
    """
    resp = api_client.get_theatre(NON_EXISTENT_UUID, HM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_theatre_create_invalid_enum_size_class_returns_400(api):
    """PRD §2.5: "A missing required field, a malformed datetime, or an invalid
    enum value in the request body is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "a `size_class` of `SMALL`, `MEDIUM`, or `LARGE`".

    Design: Corner/entities/theatre_create_invalid_enum_size_class_returns_400
    """
    resp = api_client.create_theatre(
        create_theatre_payload(name="BadClass", capacity=100, size_class="HUGE",
                               is_landmark=False, base_weekly_rent_cents=1000),
        HM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ticket_order_computed_gross_input_ignored(api):
    """PRD §3.5: "The order's `computed_gross_cents` is computed at creation as
    the whole-order value — ticket count times face value times the
    dynamic-pricing factor times one minus the discount percent divided by a
    hundred (or no discount when no code is applied) — rounded half-up to
    integer cents exactly once."

    Design: Corner/entities/ticket_order_computed_gross_input_ignored
    """
    ctx = setup_active_booking()
    resp = api_client.create_ticket_order(
        ctx["booking"]["id"],
        {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 2,
         "is_group_sale": False, "face_value_cents": 5000},
        TEST_USERS["box_office_agent_headers"])
    data = validate_success(resp, expected_status=201)
    assert_ticket_order(data)
    assert data["computed_gross_cents"] == 10000, (
        f"server-computed gross must be 2 x 5000 x 1.0 = 10000, "
        f"got {data['computed_gross_cents']}")


def test_booking_initial_state_is_requested(api):
    """PRD §3.2: "A booking begins life in `REQUESTED` status when a
    `CompanyRep` submits a `production_id`, a `theatre_id`, a future-dated
    `loadin_start`, and a `run_end` strictly after `loadin_start`."

    Design: Corner/entities/booking_initial_state_is_requested
    """
    get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", HM))
    company = get_success_data(api_client.create_company(
        create_company_payload(name="InitCo", contact_email="in@x.com"), HM))
    theatre = get_success_data(api_client.create_theatre(
        create_theatre_payload(name="BijouI"), HM))
    rep = make_company_rep_headers(company["id"])
    production = get_success_data(api_client.create_production(
        create_production_payload(company["id"], title="Show Init"), rep))
    resp = api_client.create_booking(
        create_booking_payload(production["id"], theatre["id"]), rep)
    data = validate_success(resp, expected_status=201)
    assert_booking(data)
    assert data["status"] == "REQUESTED", \
        f"new booking must begin in REQUESTED, got {data['status']}"
