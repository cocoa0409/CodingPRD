"""Breadth tests for the entity surface: required fields, declared defaults,
server-minted identity, enum membership, not-found reads, listing metadata and
computed balances.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import TEST_USERS, api_client, fixtures as F

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_technician_hire_requires_a_name_and_a_shift(api):
    """PRD §3.1: "Technicians are hired into a branch by a `PlatformAdmin`, who supplies a
    `name`, a five-digit `postal_code` describing where the technician works, a
    `daily_capacity_hours` ceiling above zero, at least one `shift_segments` element".
    PRD §3.14: "A request missing a required field entirely, or carrying one that cannot be
    parsed at all, is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/technician_hire_rejects_missing_name
    """
    branch = F.create_branch()

    response = api_client.hire_technician(
        branch["id"],
        {"postal_code": "78701", "skill_codes": ["HVAC"], "daily_capacity_hours": 8},
        ADMIN,
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    roster = validate_success(api_client.list_branch_technicians(branch["id"], DISPATCHER))
    if isinstance(roster, dict) and "items" in roster:
        roster = roster["items"]
    assert roster == [], "no technician row may be created by a refused hire"


def test_branch_capacity_defaults_to_eighty_hours(api):
    """PRD §3.1: "An optional `daily_dispatch_capacity_hours`, defaulting to 80, sets the
    technician-hours the branch may consume in one dispatch day and must be greater than
    zero."
    PRD §3.1: "A branch is born with its `capacity_consumed_hours` and its
    `membership_count_active` both at 0".

    Design: Corner/entities/branch_capacity_defaults_to_eighty_hours
    """
    created = validate_success(
        api_client.create_branch({"name": "Dallas", "postal_code": "75201"}, ADMIN),
        expected_status=201,
    )
    assert created["daily_dispatch_capacity_hours"] == 80, (
        f"the declared default is 80, got {created['daily_dispatch_capacity_hours']}"
    )
    assert created["capacity_consumed_hours"] == 0
    assert created["membership_count_active"] == 0


def test_appointment_identity_is_server_minted_and_versioned(api):
    """PRD §2.4: "Every resource exposes an integer `version` that begins at 1 when the row
    is created and is incremented by exactly 1 on each write that changes the row".
    PRD §2.4: "The identifier is a UUID and carries no type prefix".
    PRD §3.3: "Its `status` begins `SCHEDULED`, its `dispatch_status` begins `UNASSIGNED`
    and its `pricing_status` begins `NOT_QUOTED`."

    Design: Corner/entities/appointment_version_starts_at_one
    """
    branch = F.create_branch()
    created = validate_success(
        api_client.create_appointment(
            {
                "branch_id": branch["id"],
                "customer_name": "Ada",
                "postal_code": "78701",
                "window_start_utc": "2026-09-10T09:00:00Z",
                "window_end_utc": "2026-09-10T11:00:00Z",
            },
            DISPATCHER,
        ),
        expected_status=201,
    )

    assert created["version"] == 1, f"a fresh row starts at version 1, got {created['version']}"
    assert created["pricing_status"] == "NOT_QUOTED"
    assert created["status"] == "SCHEDULED"
    assert created["dispatch_status"] == "UNASSIGNED"
    assert created["quoted_price_cents"] == 0
    assert created["estimated_hours"] == 0

    reread = F.get_appointment(created["id"])
    assert reread["version"] == 1, "a read must not advance the version"


def test_campaign_channel_must_be_a_declared_member(api):
    """PRD §2.9: "A campaign's `channel` is one of `SEARCH`, `YARD_SIGN`, `REFERRAL`,
    `DIRECT_MAIL` or `ORGANIC`."
    PRD §3.14: "A request missing a required field entirely, or carrying one that cannot be
    parsed at all, is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/campaign_channel_rejects_unknown_enum_member
    """
    response = api_client.create_campaign(
        {"name": "Billboard Push", "channel": "BILLBOARD", "spend_cents": 1000}, ADMIN
    )
    validate_error(response, "ERR_INVALID_REQUEST")

    accepted = validate_success(
        api_client.create_campaign({"name": "Search Push", "channel": "SEARCH", "spend_cents": 1000}, ADMIN),
        expected_status=201,
    )
    assert accepted["channel"] == "SEARCH"


def test_reading_an_unknown_appointment_reports_not_found(api):
    """PRD §3.14: "Any request that carries an identifier in its path resolves that
    identifier before anything else, so a request against a nonexistent branch,
    technician, appointment, pricebook revision, override request, membership plan,
    agreement, visit, campaign or call record is refused with `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.2: "the `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/entities/find_appointment_that_does_not_exist
    """
    response = api_client.get_appointment(
        "00000000-0000-4000-8000-000000000000", DISPATCHER
    )
    error = validate_error(response, "ERR_NOT_FOUND")
    assert error["error_id"] == "ERR_NOT_FOUND"


def test_appointment_listing_reports_paging_metadata(api):
    """PRD §2.3: "`total_count` is the size of the full filtered result set before the page
    is cut, and `has_more` is true exactly when `offset + limit` is strictly less than
    `total_count`."
    PRD §2.3: "its permitted range is 1 to 100 inclusive, so a `limit` below 1 or above 100
    is not a valid request."

    Design: Corner/entities/appointment_list_reports_pagination_metadata
    """
    branch = F.create_branch()
    for index, day in enumerate((10, 11, 12), start=10):
        F.book_appointment(
            branch["id"],
            customer_name=f"Homeowner{index}",
            window_start_utc=f"2026-09-{day}T09:00:00Z",
            window_end_utc=f"2026-09-{day}T11:00:00Z",
        )

    rows, meta = validate_paginated(
        api_client.list_appointments(DISPATCHER, params={"branch_id": branch["id"], "limit": 2, "offset": 0})
    )
    assert len(rows) == 2, f"a page of 2 was requested, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    response = api_client.list_appointments(DISPATCHER, params={"limit": 200})
    validate_error(response, "ERR_INVALID_REQUEST")


def test_membership_agreement_starts_with_zero_balances(api):
    """PRD §3.8: "The agreement's `annual_price_cents` captures the plan's
    `annual_price_cents` at that moment and is frozen for the life of the agreement".
    PRD §3.8: "Its `collected_amount_cents`, `revenue_recognized_cents` and
    `unearned_revenue_balance_cents` all begin at zero".

    Design: Corner/entities/membership_agreement_response_exposes_deferred_balances
    """
    branch = F.create_branch()
    plan = F.create_plan(annual_price_cents=100000)
    seller = F.hire_technician(branch["id"], name="Seller")

    created = validate_success(
        api_client.sell_membership(
            {
                "membership_plan_id": plan["id"],
                "branch_id": branch["id"],
                "homeowner_name": "Ada",
                "homeowner_postal_code": "78701",
                "term_months": 12,
            },
            F.make_technician_headers(seller["id"]),
        ),
        expected_status=201,
    )
    assert created["annual_price_cents"] == 100000, (
        "the price is captured from the plan, not supplied by the caller"
    )
    assert created["unearned_revenue_balance_cents"] == 0
    assert created["revenue_recognized_cents"] == 0
    assert created["status"] == "PENDING_PAYMENT"