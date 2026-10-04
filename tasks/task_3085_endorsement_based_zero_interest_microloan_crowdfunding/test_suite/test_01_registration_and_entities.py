"""Registration, defaults, and entity shape tests (PRD §3.1, §2.5, §2.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_borrower,
    assert_lender,
    make_borrower_headers,
    make_lender_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)

ADMIN = TEST_USERS["admin_headers"]


def test_borrower_registration_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A new borrower starts in `REGISTERED` status with both loan
    counters — `completed_loan_count` and `defaulted_loan_count` — at 0, a
    `social_underwriting_score` of 0, an `underwriting_variant` of `NONE`, and
    `restricted_since` null."
    PRD §3.1: "optionally a self-declared `prior_repaid_loans_count` of
    previously fully repaid microloans (defaulting to 0 when omitted)."

    Design: Corner/entities/borrower_register_returns_defaults_and_system_fields
    """
    fx.set_clock()
    resp = client.create_borrower(
        {
            "legal_name": "Ana Ruiz",
            "business_name": "Ruiz Bakery",
            "email": "ana-reg@example.com",
            "business_tenure_months": 24,
        },
        TEST_USERS["anonymous_headers"],
    )
    borrower = validate_success(resp, expected_status=201)
    assert_borrower(borrower)
    assert borrower["status"] == "REGISTERED"
    assert borrower["prior_repaid_loans_count"] == 0, "default applies when omitted"
    assert borrower["social_underwriting_score"] == 0
    assert borrower["underwriting_variant"] == "NONE"
    assert borrower["completed_loan_count"] == 0
    assert borrower["defaulted_loan_count"] == 0
    assert borrower["restricted_since"] is None
    assert borrower["version"] == 1


def test_lender_registration_round_trips_with_zeroed_counters(api):
    """PRD §3.1: "Lender self-registration requires only a `display_name` and an
    `email`, and opens a lending account whose `lending_balance_cents`,
    `total_deposited_cents`, `lifetime_lent_cents`, and `lifetime_repaid_cents`
    all start at 0."

    Design: Corner/entities/lender_register_and_get_round_trip
    """
    fx.set_clock()
    created = validate_success(
        client.create_lender(
            {"display_name": "Ola P", "email": "ola-rt@example.com"},
            TEST_USERS["anonymous_headers"],
        ),
        expected_status=201,
    )
    lender = validate_success(
        client.get_lender(created["id"], make_lender_headers(created["id"]))
    )
    assert_lender(lender)
    assert lender["lending_balance_cents"] == 0
    assert lender["total_deposited_cents"] == 0
    assert lender["lifetime_lent_cents"] == 0
    assert lender["lifetime_repaid_cents"] == 0


def test_loan_applications_list_paginates(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a
    maximum of 100; `offset` defaults to 0. List responses include `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object."

    Design: Corner/entities/loan_applications_list_paginates
    """
    fx.set_clock()
    b1 = fx.create_borrower()
    b2 = fx.create_borrower()
    fx.create_application(b1)
    fx.create_application(b2)

    rows, meta = validate_paginated(
        client.list_applications(ADMIN, params={"limit": 1, "offset": 0})
    )
    assert len(rows) == 1, f"limit=1 must return one row, got {len(rows)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(
        client.list_applications(ADMIN, params={"limit": 1, "offset": 1})
    )
    assert len(rows2) == 1
    assert meta2["has_more"] is False
    assert rows[0]["id"] != rows2[0]["id"], "pages must not overlap"


def test_get_missing_borrower_returns_not_found(api):
    """PRD §2.8: "Any reference that does not resolve to an existing record is
    rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_missing_borrower_returns_not_found
    """
    fx.set_clock()
    resp = client.get_borrower(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ERR_NOT_FOUND, expected_status=404)


def test_application_missing_term_months_returns_invalid_request(api):
    """PRD §2.9: "Fifth, request shape — required fields present, values
    well-typed, enum members valid, numeric ranges respected
    (`ERR_INVALID_REQUEST`)."
    PRD §3.3: "A borrower begins by creating a draft application with their
    `borrower_id`, the `requested_amount_cents`, a `term_months` repayment
    term, and a free-text `business_purpose`."

    Design: Corner/entities/application_missing_term_months_returns_invalid_request
    """
    fx.set_clock()
    borrower = fx.create_borrower()
    resp = client.create_application(
        {
            "borrower_id": borrower["id"],
            "requested_amount_cents": 100_000,
            "business_purpose": "x",
        },
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ERR_INVALID_REQUEST, expected_status=400)


def test_term_months_out_of_range_rejected(api):
    """PRD §2.9: "`requested_amount_cents` must be a positive multiple of
    100; `term_months` must be an integer from 3 to 36 inclusive; a payment's
    `amount_cents` must be at least 100."
    PRD §2.9: "Violations of these are `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/term_months_out_of_range_rejected
    """
    fx.set_clock()
    borrower = fx.create_borrower()
    headers = make_borrower_headers(borrower["id"])
    for bad_term in (2, 37):
        resp = client.create_application(
            {
                "borrower_id": borrower["id"],
                "requested_amount_cents": 100_000,
                "term_months": bad_term,
                "business_purpose": "x",
            },
            headers,
        )
        validate_error(resp, ERR_INVALID_REQUEST, expected_status=400)
    for good_term in (3, 36):
        application = validate_success(
            client.create_application(
                {
                    "borrower_id": borrower["id"],
                    "requested_amount_cents": 100_000,
                    "term_months": good_term,
                    "business_purpose": "x",
                },
                headers,
            ),
            expected_status=201,
        )
        assert application["term_months"] == good_term


def test_application_creation_starts_fundraising_counters_at_zero(api):
    """PRD §3.3: "The draft starts in `DRAFT` with all fundraising counters —
    `distinct_endorser_count`, `private_total_cents`, `public_total_cents`,
    and `funded_total_cents` — at 0 and all lifecycle timestamps null."

    Design: Corner/entities/computed_fields_ignore_client_input
    """
    fx.set_clock()
    borrower = fx.create_borrower()
    application = validate_success(
        client.create_application(
            {
                "borrower_id": borrower["id"],
                "requested_amount_cents": 100_000,
                "term_months": 3,
                "business_purpose": "x",
            },
            make_borrower_headers(borrower["id"]),
        ),
        expected_status=201,
    )
    assert application["private_total_cents"] == 0
    assert application["public_total_cents"] == 0
    assert application["funded_total_cents"] == 0
    assert application["distinct_endorser_count"] == 0


def test_underwriting_invite_is_lean_and_has_no_version(api):
    """PRD §2.5: "Two resource types are intentionally leaner: an
    `UnderwritingInvite` and a `Payment` carry only `id` and `created_at`.
    Both `updated_at` and `version` are absent from these two entities, and
    no optimistic-concurrency field ever references them."

    Design: Corner/entities/underwriting_invite_immutability_no_update_endpoint
    """
    fx.set_clock()
    borrower = fx.create_borrower()
    invite = validate_success(
        client.create_invite(
            borrower["id"],
            {"invitee_email": "lean-invitee@example.com"},
            make_borrower_headers(borrower["id"]),
        ),
        expected_status=201,
    )
    assert invite["id"], "invite must carry a server-minted id"
    assert invite["created_at"], "invite must carry created_at"
    assert "version" not in invite, "UnderwritingInvite must not carry version"
    assert "updated_at" not in invite, "UnderwritingInvite must not carry updated_at"
    assert invite["status"] == "SENT"


def test_application_reverse_lists_start_empty(api):
    """PRD §4 (endpoint catalogue): "| GET | `/loan-applications/{id}/endorsements` | List endorsements on an application | Borrower, Lender, Trustee, PlatformAdmin |"
    PRD §4 (endpoint catalogue): "| GET | `/loan-applications/{id}/contributions` | List contributions on an application | Borrower, Lender, Trustee, PlatformAdmin |"
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/entities/fk_reverse_reachability_lists
    """
    fx.set_clock()
    borrower = fx.create_borrower()
    application = fx.create_application(borrower)

    endorsements, _ = validate_paginated(
        client.list_application_endorsements(application["id"], ADMIN)
    )
    contributions, _ = validate_paginated(
        client.list_application_contributions(application["id"], ADMIN)
    )
    assert endorsements == [], "nothing lent yet"
    assert contributions == [], "nothing contributed yet"
