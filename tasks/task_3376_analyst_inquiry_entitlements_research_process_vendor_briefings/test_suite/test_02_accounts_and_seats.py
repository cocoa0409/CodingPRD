"""Client account onboarding, seat provisioning and seat administration."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_client_account,
    assert_entitlement_matrix,
    create_account,
    create_active_seat,
    create_seat,
    get_success_data,
    make_client_admin_headers,
    make_seat_holder_headers,
    revoke_seat,
    set_clock,
    setup_account_with_active_seat,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_account_starts_active_with_empty_counters_and_full_remainders():
    """PRD §3.1: "The new account starts in `contract_status` `ACTIVE`. Its
    `active_seat_count`, `provisioned_seat_count` and `revoked_seat_count` all start
    at 0, both ledger remainders start equal to `inquiry_allowance_total`,
    `utilization_score` and `utilization_score_active_weighted` are computed by the
    standard scoring rules, and `renewal_posture` is derived from the score."

    Design: Corner/entities/client_account_create_returns_declared_fields_and_starts_active
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_client(
        {
            "legal_name": "Acme Industrial Group",
            "industry": "Manufacturing",
            "region": "NA",
            "contract_start_utc": "2026-07-01T00:00:00Z",
            "contract_end_utc": "2027-06-30T00:00:00Z",
            "seat_count_contracted": 10,
            "inquiry_allowance_total": 10,
            "reprint_tier": "STANDARD",
        },
        TEST_USERS["platform_admin_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert_client_account(data)
    assert data["contract_status"] == "ACTIVE"
    assert data["active_seat_count"] == 0
    assert data["provisioned_seat_count"] == 0
    assert data["revoked_seat_count"] == 0
    assert data["consumed_inquiry_units"] == 0
    assert data["reserved_inquiry_units"] == 0
    assert data["remaining_consumed_units"] == 10
    assert data["remaining_reserved_units"] == 10
    assert data["renewal_decided_at"] is None
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_seat_entitlements_are_derived_from_the_role_matrix_and_overrides():
    """PRD §3.1: "The `research_role` selects a base set of document types, and any
    `entitlement_override_types` are appended in the order supplied and de-duplicated
    into `entitlement_document_types`."
    PRD §3.1: "An `ARCHITECT` seat may open `MARKET_GUIDE`, `COMPARATIVE_MATRIX`,
    `HYPE_PROFILE` and `CRITICAL_CAPABILITIES` documents."

    Design: Corner/entities/seat_get_returns_entitlement_matrix_derived_from_research_role
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    seat = create_seat(
        account,
        seat_email="arch@acme.example",
        research_role="ARCHITECT",
        seat_kind="NAMED",
        entitlement_override_types=["HYPE_PROFILE", "MARKET_GUIDE"],
    )
    activated = get_success_data(
        api_client.activate_seat(seat["id"], make_client_admin_headers(account["id"]))
    )
    assert_entitlement_matrix("ARCHITECT", ["HYPE_PROFILE", "MARKET_GUIDE"],
                              activated["entitlement_document_types"])

    read = get_success_data(
        api_client.get_seat(seat["id"], make_client_admin_headers(account["id"]))
    )
    assert read["entitlement_document_types"] == [
        "MARKET_GUIDE", "COMPARATIVE_MATRIX", "HYPE_PROFILE", "CRITICAL_CAPABILITIES",
    ]
    assert read["status"] == "ACTIVE"
    assert read["activated_at"] is not None
    assert read["client_account_id"] == account["id"]


def test_seat_created_without_seat_kind_defaults_to_named():
    """PRD §3.1: "The optional `seat_kind` distinguishes a `NAMED` seat from a
    `SHARED` pool seat and defaults to `NAMED`; the optional
    `entitlement_override_types` list grants extra document types on top of the role
    matrix and defaults to an empty list."
    PRD §3.1: "A new seat begins in status `PROVISIONED`, with `activated_at` and
    `revoked_at` null and `last_inquiry_at` null; the owning account's
    `provisioned_seat_count` is incremented and its utilization score is recomputed."

    Design: Corner/entities/seat_create_omitting_seat_kind_defaults_to_named
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    resp = api_client.create_seat(
        {
            "client_account_id": account["id"],
            "seat_email": "defaulted@acme.example",
            "research_role": "PRACTITIONER",
        },
        make_client_admin_headers(account["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["seat_kind"] == "NAMED"
    assert data["status"] == "PROVISIONED"
    assert data["entitlement_override_types"] == []
    assert data["activated_at"] is None
    assert data["revoked_at"] is None
    assert data["last_inquiry_at"] is None

    account_data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert account_data["provisioned_seat_count"] == 1
    assert account_data["active_seat_count"] == 0


def test_client_created_with_a_region_outside_the_enum_is_rejected():
    """PRD §3.1: "its contracting `region` (one of `NA`, `EMEA`, `APAC`)"
    PRD §2.11: "Request shape: every required input field is present, enum members
    are in range, and integers satisfy their declared bounds — including the
    requirement that evaluation weights sum to exactly 1.00. Failure is
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/client_create_with_unknown_region_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_client(
        {
            "legal_name": "Andes Holdings",
            "industry": "Mining",
            "region": "LATAM",
            "contract_start_utc": "2026-07-01T00:00:00Z",
            "contract_end_utc": "2027-06-30T00:00:00Z",
            "seat_count_contracted": 5,
            "inquiry_allowance_total": 5,
            "reprint_tier": "NONE",
        },
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_revoking_an_active_seat_rederives_account_counters_and_posture():
    """PRD §3.1: "An `ACTIVE` seat that is revoked also has its
    `entitlement_document_types` emptied, and the account's `active_seat_count` is
    decremented; a `PROVISIONED` seat that is revoked instead decrements the
    account's `provisioned_seat_count`. Both paths increment the account's
    `revoked_seat_count` and recompute the account's `utilization_score` with the
    SEAT_WEIGHTED variant and its `renewal_posture`."
    PRD §3.1: "First, if the recomputed utilization score falls below 40, the
    account's posture becomes `AT_RISK`. Second, if the account's `active_seat_count`
    falls below half of `seat_count_contracted` rounded up to the next whole number,
    the account's `contract_status` moves from `ACTIVE` to `RENEWAL_REVIEW` and its
    `updated_at` is refreshed."

    Design: Corner/state_machines/seat_revoke_side_effects_rederive_account_counters_and_posture
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(
        legal_name="Meridian Health Network", industry="Healthcare",
        seat_count_contracted=4, inquiry_allowance_total=4, reprint_tier="PREMIUM",
    )
    first = create_active_seat(account, seat_email="seat1@meridian.example",
                               research_role="ARCHITECT")
    create_active_seat(account, seat_email="seat2@meridian.example",
                       research_role="PRACTITIONER")

    revoked = revoke_seat(account, first)
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_at"] is not None
    assert revoked["entitlement_document_types"] == []

    data = get_success_data(
        api_client.get_client(account["id"], make_client_admin_headers(account["id"]))
    )
    assert data["active_seat_count"] == 1
    assert data["revoked_seat_count"] == 1
    assert data["utilization_score"] == 32.24
    assert data["renewal_posture"] == "AT_RISK"
    assert data["contract_status"] == "RENEWAL_REVIEW"


def test_seat_holder_cannot_create_a_client_account():
    """PRD §2.1: "A request whose `X-User-Role` value is not listed among the roles
    authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."
    PRD §4: "| POST | `/research/clients` | Create a client account with its contract
    terms | PlatformAdmin |"

    Design: Corner/validations/seat_holder_calling_client_create_returns_unauthorized
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, _ = setup_account_with_active_seat()

    resp = api_client.create_client(
        {
            "legal_name": "Shadow Account",
            "industry": "Retail",
            "region": "NA",
            "contract_start_utc": "2026-07-01T00:00:00Z",
            "contract_end_utc": "2027-06-30T00:00:00Z",
            "seat_count_contracted": 5,
            "inquiry_allowance_total": 5,
            "reprint_tier": "NONE",
        },
        make_seat_holder_headers(seat["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_duplicate_seat_email_is_scoped_to_the_owning_account():
    """PRD §3.1: "the named user's `seat_email` — which must be unique within the
    account, or the request is rejected with `ERR_DUPLICATE_SEAT_EMAIL` (HTTP 409)"
    PRD §2.11: "Uniqueness, capacity and overlap: `seat_email` must be unique within
    its account (`ERR_DUPLICATE_SEAT_EMAIL`)".

    Design: Corner/validations/duplicate_seat_email_is_scoped_to_the_account
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    second_account = create_account(
        legal_name="Second Account", industry="Retail", region="EMEA",
        seat_count_contracted=2, inquiry_allowance_total=2, reprint_tier="NONE",
    )
    create_seat(account, seat_email="shared@example.com")

    duplicate = api_client.create_seat(
        {
            "client_account_id": account["id"],
            "seat_email": "shared@example.com",
            "research_role": "ARCHITECT",
            "seat_kind": "NAMED",
        },
        make_client_admin_headers(account["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_SEAT_EMAIL)

    seats, meta = validate_paginated(
        api_client.list_seats(
            make_client_admin_headers(account["id"]),
            params={"client_account_id": account["id"]},
        )
    )
    assert len(seats) == 1
    assert meta["total_count"] == 1

    accepted = api_client.create_seat(
        {
            "client_account_id": second_account["id"],
            "seat_email": "shared@example.com",
            "research_role": "PRACTITIONER",
            "seat_kind": "NAMED",
        },
        make_client_admin_headers(second_account["id"]),
    )
    data = validate_success(accepted, expected_status=201)
    assert data["client_account_id"] == second_account["id"]
