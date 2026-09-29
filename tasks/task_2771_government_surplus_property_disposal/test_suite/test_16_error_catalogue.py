"""PRD compliance — the error envelope and the error-identifier catalogue.

Two families of identifiers are exercised here: the not-found family, raised
both by path identifiers and by foreign keys carried in a request body, and the
authentication / authorization family. Every assertion pins the exact
identifier the PRD's catalogue pairs with the condition, together with the
error envelope the PRD fixes for every failed request.
"""

import pytest

from test_helpers import (
    ADMIN_USER_ID,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_agency_payload,
    register_agency,
    register_venue,
    set_clock,
    setup_assessed_asset,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["program_admin_headers"]
OFFICER = TEST_USERS["disposal_officer_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ─── The not-found family raised by path identifiers ──────────────────────

def test_unresolvable_path_identifier_reports_the_addressed_entitys_own_code(api):
    """PRD §2.11: "For any such path the server resolves identifiers strictly
    left to right and answers on the **first** identifier that does not
    resolve."
    PRD §2.11: "Each entity has its own not-found code: `ERR_AGENCY_NOT_FOUND`,
    `ERR_TURN_IN_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SCREENING_CYCLE_NOT_FOUND`, `ERR_SCREENING_REQUEST_NOT_FOUND`,
    `ERR_TRANSFER_ORDER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
    `ERR_AUCTION_LOT_NOT_FOUND`, `ERR_BIDDER_NOT_FOUND`,
    `ERR_SALE_INVOICE_NOT_FOUND` and `ERR_DISTRIBUTION_NOT_FOUND`, all
    answering with HTTP 404."
    PRD §2.12: "Every identifier in the path resolves, left to right —
    otherwise the matching 404 code from §2.11."

    Design: Corner/errors/err_path_id_not_found_family_is_entity_specific
    """
    set_clock()

    reads = [
        (
            "GET /agencies/{id}",
            lambda: api.get_agency(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AGENCY_NOT_FOUND,
        ),
        (
            "GET /turn-ins/{id}",
            lambda: api.get_turn_in(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_TURN_IN_NOT_FOUND,
        ),
        (
            "GET /assets/{id}",
            lambda: api.get_asset(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_ASSET_NOT_FOUND,
        ),
        (
            "GET /screening-cycles/{id}",
            lambda: api.get_screening_cycle(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_SCREENING_CYCLE_NOT_FOUND,
        ),
        (
            "GET /screening-requests/{id}",
            lambda: api.get_screening_request(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_SCREENING_REQUEST_NOT_FOUND,
        ),
        (
            "GET /transfer-orders/{id}",
            lambda: api.get_transfer_order(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_TRANSFER_ORDER_NOT_FOUND,
        ),
        (
            "GET /venues/{id}",
            lambda: api.get_venue(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_VENUE_NOT_FOUND,
        ),
        (
            "GET /auction-lots/{id}",
            lambda: api.get_auction_lot(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AUCTION_LOT_NOT_FOUND,
        ),
        (
            "GET /bidders/{id}",
            lambda: api.get_bidder(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_BIDDER_NOT_FOUND,
        ),
        (
            "GET /sale-invoices/{id}",
            lambda: api.get_sale_invoice(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_SALE_INVOICE_NOT_FOUND,
        ),
        (
            "GET /proceeds-distributions/{id}",
            lambda: api.get_proceeds_distribution(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND,
        ),
    ]

    for label, call, expected_error_id in reads:
        response = call()
        assert response.status_code == 404, (
            f"{label} addressed with an id matching no row must answer HTTP 404, "
            f"got {response.status_code}"
        )
        error = validate_error(response, expected_error_id)
        assert error["error_id"] == expected_error_id.value, (
            f"{label} must report {expected_error_id.value}, got {error['error_id']}"
        )

    _, meta = validate_paginated(api.list_agencies(ADMIN))
    assert meta["total_count"] == 0, (
        "eleven refused reads must not have created any row"
    )


def test_not_found_response_carries_the_pinned_error_envelope(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/err_path_id_not_found_family_is_entity_specific
    """
    set_clock()

    response = api.get_asset(NON_EXISTENT_UUID, ADMIN)
    assert response.status_code == 404, (
        f"an unknown asset id must answer HTTP 404, got {response.status_code}"
    )
    body = response.json()

    assert body["response_type"] == "error", (
        f"a failed request must carry response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the meta object of an error response holds only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert body["data"]["error_id"] == ApiErrorId.ERR_ASSET_NOT_FOUND.value, (
        f"error_id must be ERR_ASSET_NOT_FOUND, got {body['data']['error_id']!r}"
    )
    assert body["data"]["message"].strip(), (
        "an error response must carry a human-readable message alongside error_id"
    )


# ─── The not-found family raised by body foreign keys ─────────────────────

def test_unresolvable_body_reference_reports_the_referenced_entitys_code(api):
    """PRD §2.11: "Once every path identifier resolves, foreign keys carried in
    the request body are resolved next, in the order in which the fields are
    declared on the entity being created."
    PRD §2.11: "The same not-found codes apply."
    PRD §2.11: "Body-level foreign key resolution is performed by turn-in
    creation, asset creation, screening-cycle creation, screening-request
    filing, transfer-order issuance, auction-lot creation, bid placement and
    proceeds-distribution creation."
    PRD §2.12: "Every foreign key in the request body resolves, in entity
    field-declaration order — otherwise the matching 404 code."

    Design: Corner/errors/err_body_reference_not_found_family_per_referenced_entity
    """
    scenario = setup_assessed_asset(kind="furniture")
    asset = scenario["asset"]
    venue = register_venue()

    turn_in_attempt = api.create_turn_in(
        {
            "turning_in_agency_id": NON_EXISTENT_UUID,
            "custody_location": "Austin Yard 9",
        },
        ADMIN,
    )
    validate_error(turn_in_attempt, ApiErrorId.ERR_AGENCY_NOT_FOUND)

    cycle_attempt = api.create_screening_cycle(
        {
            "asset_id": NON_EXISTENT_UUID,
            "opens_at": "2026-08-03T00:00:00Z",
            "tier_window_days": 3,
        },
        OFFICER,
    )
    validate_error(cycle_attempt, ApiErrorId.ERR_ASSET_NOT_FOUND)

    # asset_id resolves and venue_id does not, so the venue column is isolated.
    lot_attempt = api.create_auction_lot(
        {
            "asset_id": asset["id"],
            "venue_id": NON_EXISTENT_UUID,
            "opens_at": "2026-08-04T00:00:00Z",
            "closes_at": "2026-08-05T00:00:00Z",
        },
        OFFICER,
    )
    validate_error(lot_attempt, ApiErrorId.ERR_VENUE_NOT_FOUND)

    # The unknown lot outranks the optimistic-concurrency comparison, which
    # would otherwise answer 412.
    distribution_attempt = api.create_proceeds_distribution(
        {
            "auction_lot_id": NON_EXISTENT_UUID,
            "basis": "ACCRUAL",
            "expected_auction_lot_version": 1,
        },
        FINANCE,
    )
    validate_error(distribution_attempt, ApiErrorId.ERR_AUCTION_LOT_NOT_FOUND)

    _, turn_in_meta = validate_paginated(api.list_turn_ins(ADMIN))
    assert turn_in_meta["total_count"] == 1, (
        "the refused turn-in creation must not have written a row; only the "
        f"pre-existing turn-in should remain, got {turn_in_meta['total_count']}"
    )
    _, cycle_meta = validate_paginated(api.list_screening_cycles(ADMIN))
    assert cycle_meta["total_count"] == 0, (
        f"no screening cycle may exist, got {cycle_meta['total_count']}"
    )
    _, lot_meta = validate_paginated(api.list_auction_lots(ADMIN))
    assert lot_meta["total_count"] == 0, (
        f"no auction lot may exist, got {lot_meta['total_count']}"
    )
    _, distribution_meta = validate_paginated(api.list_proceeds_distributions(FINANCE))
    assert distribution_meta["total_count"] == 0, (
        f"no proceeds distribution may exist, got {distribution_meta['total_count']}"
    )
    assert venue["status"] == "ACTIVE", (
        "the venue registered for this scenario stays ACTIVE and untouched"
    )


# ─── The authentication / authorization identifiers ───────────────────────

@pytest.mark.parametrize(
    "case, headers",
    [
        (
            "no X-User-Role header at all",
            {"X-User-ID": ADMIN_USER_ID, "Content-Type": "application/json"},
        ),
        (
            "an X-User-Role value outside the seven roles",
            build_user_headers(ADMIN_USER_ID, "SurplusCzar"),
        ),
        (
            "no X-User-ID header at all",
            {"X-User-Role": "ProgramAdmin", "Content-Type": "application/json"},
        ),
        (
            "an empty X-User-ID header",
            build_user_headers("", "ProgramAdmin"),
        ),
    ],
)
def test_missing_or_unrecognised_identity_headers_report_unauthenticated(
    api, case, headers
):
    """PRD §2.1: "A request whose `X-User-Role` header is missing, or whose
    value is not one of those seven, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD §2.1: "A request whose `X-User-ID` header is missing or empty is
    likewise rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/err_auth_envelope_unauthenticated_and_unauthorized
    """
    set_clock()
    agency = register_agency()

    response = api.get_agency(agency["id"], headers)
    assert response.status_code == 401, (
        f"a request sent with {case} must answer HTTP 401, got {response.status_code}"
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value, (
        f"a request sent with {case} must report ERR_UNAUTHENTICATED, "
        f"got {error['error_id']}"
    )

    _, meta = validate_paginated(api.list_agencies(ADMIN))
    assert meta["total_count"] == 1, (
        "the refused read must leave the single registered organization in place, "
        f"got {meta['total_count']} rows"
    )


def test_unresolvable_entity_backed_identity_outranks_the_role_list_check(api):
    """PRD §2.1: "When `X-User-Role` is `AgencyOfficer`, `X-User-ID` is the `id`
    of the acting `Agency`; the value must resolve to an existing `Agency` row,
    and a header that does not resolve is an `ERR_UNAUTHENTICATED` failure
    rather than a not-found."
    PRD §2.1: "When `X-User-Role` is `Bidder`, `X-User-ID` is the `id` of the
    acting `Bidder` row and must resolve to one; ownership checks compare
    `Bidder.id`, `Bid.bidder_id` and `SaleInvoice.bidder_id` to `X-User-ID`, and
    a mismatch is rejected with `ERR_FORBIDDEN_BIDDER_SCOPE` (HTTP 403)."
    PRD §2.12: "When several rules could reject the same request, the **first**
    rule violated in the order below determines the response, and no later rule
    is evaluated."
    PRD §2.12: "`X-User-ID` present, non-empty, and — for the entity-backed
    `AgencyOfficer` and `Bidder` roles — resolving to an existing row of the
    backing entity — otherwise `ERR_UNAUTHENTICATED` (401)."
    PRD §2.12: "The acting role appears in the called endpoint's authorised-role
    list — otherwise `ERR_UNAUTHORIZED` (403)."

    Design: Corner/errors/err_auth_envelope_unauthenticated_and_unauthorized
    """
    set_clock()
    register_agency()

    # An AgencyOfficer is not on the turn-in listing's role list, but its
    # unresolvable identity is answered first.
    officer_attempt = api.list_turn_ins(TEST_USERS["agency_officer_headers"])
    assert officer_attempt.status_code == 401, (
        "an AgencyOfficer whose X-User-ID resolves to no Agency row must be "
        f"answered 401 before the role list is consulted, got "
        f"{officer_attempt.status_code}"
    )
    validate_error(officer_attempt, ApiErrorId.ERR_UNAUTHENTICATED)

    # Likewise for a Bidder on an organisation-registration endpoint it is not
    # listed for: identity resolution precedes the role-list refusal.
    bidder_attempt = api.create_agency(
        create_agency_payload(agency_code="ROGUE-01"),
        TEST_USERS["bidder_headers"],
    )
    assert bidder_attempt.status_code == 401, (
        "a Bidder whose X-User-ID resolves to no Bidder row must be answered "
        f"401 rather than 403, got {bidder_attempt.status_code}"
    )
    validate_error(bidder_attempt, ApiErrorId.ERR_UNAUTHENTICATED)

    _, meta = validate_paginated(api.list_agencies(ADMIN))
    assert meta["total_count"] == 1, (
        "neither refused request may write a row; the single registered "
        f"organization must remain, got {meta['total_count']}"
    )


def test_authenticated_caller_outside_the_role_list_reports_unauthorized(api):
    """PRD §2.1: "Once the caller is authenticated, the role must appear in the
    authorised-role list of the endpoint being called, as tabulated in §4; a
    role calling an endpoint it is not listed for is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "A `ProgramAdmin` is the agency administrator: it maintains the
    participant registry, federal donee certifications, auction venues and
    bidder registrations, and reads everything, but it never appraises property,
    never certifies a clearance, never awards property and never posts money."

    Design: Corner/errors/err_auth_envelope_unauthenticated_and_unauthorized
    """
    set_clock()
    register_agency()

    response = api.create_agency(
        create_agency_payload(agency_code="ROGUE-02"), OFFICER
    )
    assert response.status_code == 403, (
        "a DisposalOfficer is not listed for organisation registration and must "
        f"be answered HTTP 403, got {response.status_code}"
    )
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        f"the refusal must report ERR_UNAUTHORIZED, got {error['error_id']}"
    )

    _, meta = validate_paginated(api.list_agencies(ADMIN))
    assert meta["total_count"] == 1, (
        "the refused registration must not have written a row, got "
        f"{meta['total_count']} organizations"
    )


def test_authorization_failure_carries_the_pinned_error_envelope(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/err_auth_envelope_unauthenticated_and_unauthorized
    """
    set_clock()

    response = api.create_agency(
        create_agency_payload(agency_code="ROGUE-03"), OFFICER
    )
    body = response.json()

    assert body["response_type"] == "error", (
        f"a refused request must carry response_type 'error', got {body['response_type']!r}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the meta object of an error response holds only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert body["data"]["error_id"] == ApiErrorId.ERR_UNAUTHORIZED.value, (
        f"error_id must be ERR_UNAUTHORIZED, got {body['data']['error_id']!r}"
    )
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), (
        "the message must be a non-empty human-readable explanation, got "
        f"{body['data'].get('message')!r}"
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
