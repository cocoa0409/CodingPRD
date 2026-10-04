"""Advisor entity rules, pagination envelope, and contact resource shape."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    get_success_data, api_client, ApiErrorId, NON_EXISTENT_UUID,
    create_advisor, create_advisor_payload, create_territory,
    post_production, make_advisor_headers, assert_contact,
)

ADMIN = TEST_USERS["home_office_admin_headers"]


def test_create_advisor_missing_email_returns_invalid_request():
    """PRD §3.1: "The advisor pipeline begins when a `HomeOfficeAdmin`
    registers a candidate with a `full_name`, an `email`, and a `hire_date`
    marking the day the advisor entered the training pipeline."

    Design: Corner/entities/create_advisor_missing_email_returns_invalid_request
    """
    payload = create_advisor_payload()
    payload.pop("email")
    validate_error(
        api_client.create_advisor(payload, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


def test_create_advisor_duplicate_email_rejected():
    """PRD §3.1: "Advisor emails are unique across the network; registering a
    duplicate address is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/create_advisor_duplicate_email_rejected
    """
    validate_success(
        api_client.create_advisor(
            create_advisor_payload(email="dup@example.com"), ADMIN
        ),
        expected_status=201,
    )
    validate_error(
        api_client.create_advisor(
            create_advisor_payload(email="dup@example.com"), ADMIN
        ),
        ApiErrorId.ERR_DUPLICATE,
    )


def test_advisor_cumulative_commissions_after_reversal():
    """PRD §3.4: "Both posting and reversal recompute the advisor's
    `cumulative_commissions_cents`, which is always the sum of
    `commissions_cents` across that advisor's `POSTED` records since
    `hire_date` — reversed records drop out of the cumulative total."

    Design: Corner/entities/advisor_computed_cumulative_commissions
    """
    advisor = create_advisor()
    first = post_production(advisor["id"], 100, "2026-02-01T00:00:00Z")
    post_production(advisor["id"], 250, "2026-02-02T00:00:00Z")

    mid = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert mid["cumulative_commissions_cents"] == 350

    validate_success(api_client.reverse_production_record(first["id"], ADMIN))
    after = get_success_data(api_client.get_advisor(advisor["id"], ADMIN))
    assert after["cumulative_commissions_cents"] == 250


def test_get_advisor_not_found():
    """PRD §2.5: "A missing identifier anywhere in the chain yields
    `ERR_NOT_FOUND` for the first unresolvable segment."

    Design: Corner/entities/get_advisor_not_found
    """
    validate_error(
        api_client.get_advisor(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_NOT_FOUND,
    )


def test_list_advisors_pagination_envelope():
    """PRD §2.3: "List endpoints accept two query parameters. `limit` controls
    the maximum number of items returned; it defaults to 10, with a minimum of
    1 and a maximum of 100. `offset` controls how many items are skipped and
    defaults to 0."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/list_advisors_pagination_envelope
    """
    create_advisor()
    create_advisor()

    data, meta = validate_paginated(api_client.list_advisors(ADMIN))
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    page, meta2 = validate_paginated(
        api_client.list_advisors(ADMIN, params={"limit": 1})
    )
    assert len(page) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is True


def test_contact_response_has_no_version_field():
    """PRD §2.4: "Three resources are deliberately leaner: DoorKnockContact,
    MilestoneEvaluation, and ProductShelfEntry carry only `id` and
    `created_at` — they have no `updated_at` and no `version`, because they
    are either append-only or transition only through dedicated endpoints."

    Design: Corner/entities/contact_immutable_entity_shape
    """
    advisor = create_advisor()
    territory = create_territory(household_capacity=10)
    validate_success(api_client.assign_territory(
        territory["id"],
        {
            "advisor_id": advisor["id"],
            "assignment_start": "2026-01-01T00:00:00Z",
            "assignment_end": "2027-01-01T00:00:00Z",
        },
        ADMIN,
    ))

    contact = validate_success(api_client.create_contact(
        territory["id"],
        {
            "household_address": "1 Elm",
            "contact_outcome": "PITCHED",
            "contacted_at": "2026-03-01T10:00:00Z",
        },
        make_advisor_headers(advisor["id"]),
    ), expected_status=201)
    assert_contact(contact)
