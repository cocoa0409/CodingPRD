"""Partner pipeline tests: creation defaults, required fields, listing,
and the 52-week training tenure boundary (inclusive)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    ApiErrorId,
    create_partner_payload,
    create_partner,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]


def test_partner_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A new partner begins in `CANDIDATE` status."
    PRD §2.4: "`version` is an integer starting at 1 on creation and incremented
    by exactly 1 on every mutation of the resource."
    PRD §3.1: "when `training_started_at` has never been set, the accrued weeks
    are zero."

    Design: Corner/entities/partner_create_returns_defaults_and_system_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_partner(
        create_partner_payload(
            full_name="Trainee Ann", email="ta@x.com", role_in_program="MANAGING_PARTNER"
        ),
        HR,
    )
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id")
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert data["status"] == "CANDIDATE"
    assert data["version"] == 1
    assert data["training_started_at"] is None
    assert data["certified_at"] is None
    assert data["placed_restaurant_id"] is None
    assert data["training_weeks_accrued"] == 0


def test_partner_create_missing_email_returns_invalid_request(api):
    """PRD §3.1: "Every partner enters the system when an `HRRecruiter` registers
    a candidate with a `full_name`, a unique contact `email`, and a
    `role_in_program` of either `MANAGING_PARTNER` or `MARKET_PARTNER`."
    PRD §2.5 item 8: "Structural constraints — malformed fields, bad enums,
    inverted date intervals, non-positive amounts, out-of-range percentages
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/partner_create_missing_email_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    resp_missing = api.create_partner(
        {"full_name": "No Email", "role_in_program": "MANAGING_PARTNER"}, HR
    )
    validate_error(resp_missing, ApiErrorId.ERR_INVALID_REQUEST)
    resp_enum = api.create_partner(
        {"full_name": "Bad Enum", "email": "be@x.com", "role_in_program": "SUPER_PARTNER"},
        HR,
    )
    validate_error(resp_enum, ApiErrorId.ERR_INVALID_REQUEST)
    _, meta = validate_paginated(api.list_partners(HR))
    assert meta["total_count"] == 0


def test_partner_list_paginates_and_filters_by_role_and_status(api):
    """PRD §2.3: "limit caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100. offset skips that many items from
    the front of the result set and defaults to 0."
    PRD §2.3: "The meta object of a list response carries four pagination
    fields: limit, offset, total_count, and has_more."

    Design: Corner/entities/partner_list_paginates_and_filters_by_role_and_status
    """
    set_clock("2026-09-01T00:00:00Z")
    create_partner(full_name="A One", email="a1@x.com", role_in_program="MANAGING_PARTNER")
    create_partner(full_name="B Two", email="b2@x.com", role_in_program="MANAGING_PARTNER")
    pc = create_partner(full_name="C Three", email="c3@x.com", role_in_program="MARKET_PARTNER")
    validate_success(api.withdraw_partner(pc["id"], HR))

    rows, meta = validate_paginated(api.list_partners(HR, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(api.list_partners(HR, params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_partners(HR, params={"role_in_program": "MARKET_PARTNER"})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(api.list_partners(HR, params={"status": "WITHDRAWN"}))
    assert len(rows) == 1
    assert rows[0]["id"] == pc["id"]

    rows, meta = validate_paginated(api.list_partners(HR))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(rows) == 3


def test_certify_at_52_weeks_minus_1_day_rejected(api):
    """PRD §3.1: "An HRRecruiter certifies a partner in IN_TRAINING or
    TRAINING_EXTENDED, but only once training_weeks_accrued has reached at
    least 52 weeks; certifying earlier is rejected with
    ERR_TRAINING_TENURE_INSUFFICIENT."
    PRD §3.1: "the number of full seven-day weeks elapsed between
    training_started_at and the logical clock, using floor division with no
    rounding up."

    Design: Difficulty/boundary_precision_check/training_certify_at_exactly_52_weeks
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner(full_name="Trainee Ann", email="ta@x.com")
    validate_success(api.start_training(partner["id"], HR))
    set_clock("2027-08-30T00:00:00Z")  # 364 days = 51 full weeks + 6 days
    resp = api.certify_partner(partner["id"], HR)
    validate_error(resp, ApiErrorId.ERR_TRAINING_TENURE_INSUFFICIENT)
    data = validate_success(api.get_partner(partner["id"], HR))
    assert data["training_weeks_accrued"] == 51
    assert data["status"] == "IN_TRAINING"


def test_certify_at_exactly_52_weeks_succeeds(api):
    """PRD §3.1: "An HRRecruiter certifies a partner in IN_TRAINING or
    TRAINING_EXTENDED, but only once training_weeks_accrued has reached at
    least 52 weeks; certifying earlier is rejected with
    ERR_TRAINING_TENURE_INSUFFICIENT."
    PRD §3.1: "A successful certification stamps certified_at with the logical
    clock and moves the partner to CERTIFIED."

    Design: Difficulty/boundary_precision_check/training_certify_at_exactly_52_weeks
    """
    set_clock("2026-09-01T00:00:00Z")
    partner = create_partner(full_name="Trainee Bob", email="tb@x.com")
    validate_success(api.start_training(partner["id"], HR))
    set_clock("2027-08-31T00:00:00Z")  # exactly 365 days = 52 full weeks
    data = validate_success(api.certify_partner(partner["id"], HR))
    assert data["status"] == "CERTIFIED"
    assert data["training_weeks_accrued"] == 52
    assert data["certified_at"] == "2027-08-31T00:00:00.000Z"
