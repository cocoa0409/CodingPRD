"""Registration, listing, envelope, and existence probes.

Covers issuer/underwriter registration defaults, engagement list filters and
pagination, typed 404s, required-field rejection, multi-engagement
coexistence, authentication-header enforcement, and pagination bounds
(PRD sections 2.1, 2.2, 2.3, 2.5, 2.9 and 3.1).
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN_HEADERS,
    NO_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    CLOCK_START_ISO,
    create_engagement_solicited,
    create_engagement_unsolicited,
    create_issuer,
    create_underwriter,
    engagement_payload,
    issuer_payload,
    make_issuer_headers,
    make_underwriter_headers,
    underwriter_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_issuer_create_returns_defaults_and_system_fields(api):
    """PRD section 3.1: "A new issuer starts with a `credit_balance_cents` of 0
    and a `delinquent_flag` of false."
    PRD section 2.4: "Before any operator input, the clock stands at exactly
    2026-09-01T00:00:00Z" and every recorded timestamp reads this clock.
    PRD section 4: "Operations that create a new, stand-alone resource —
    registering an issuer or an underwriter, opening an engagement, drafting a
    criteria version, scheduling a committee session, casting a ballot, filing
    an appeal, pricing a bond sale — answer `201 Created`."

    Design: Corner/entities/issuer_create_returns_defaults_and_system_fields
    """
    resp = api.create_issuer(issuer_payload(), headers=ADMIN_HEADERS)
    data = validate_success(resp, 201)
    assert data["legal_name"] == "City of Example"
    assert data["state_code"] == "CA"
    assert data["fiscal_year_end"] == "06-30"
    assert data["version"] == 1, "a freshly created resource is version 1"
    assert data["credit_balance_cents"] == 0
    assert data["delinquent_flag"] is False
    assert _instant(data["created_at"]) == _instant(CLOCK_START_ISO), (
        "created_at must read the logical clock, not wall-clock time"
    )


def test_underwriter_create_then_get_round_trips(api):
    """PRD section 3.1: "Registering an underwriter records the `firm_name`
    and the municipal `license_number`."

    Design: Corner/entities/underwriter_create_then_get_round_trips
    """
    created = create_underwriter(api)
    resp = api.get_underwriter(
        created["id"], headers=make_underwriter_headers(created["id"])
    )
    data = validate_success(resp, 200)
    assert data["firm_name"] == "Meridian Capital Markets"
    assert data["license_number"] == "MW-4481"
    assert data["version"] == 1
    assert _instant(data["created_at"]) == _instant(CLOCK_START_ISO)


def test_engagements_list_filters_and_paginates(api):
    """PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the envelope's `meta` object."
    PRD section 2.3: "Beyond pagination, list endpoints accept optional
    equality filters on the resource's own fields — `state_code` on issuers;
    `issuer_id`, `underwriter_id`, `status`, and `credit_type` on engagements".

    Design: Corner/entities/engagements_list_filters_and_paginates
    """
    issuer_a = create_issuer(api, legal_name="City of Example")
    issuer_b = create_issuer(api, legal_name="County of Example")
    eng_a1 = create_engagement_solicited(api, issuer_a)
    eng_a2 = create_engagement_solicited(api, issuer_a)
    create_engagement_solicited(api, issuer_b)

    page1, meta1 = validate_paginated(
        api.list_engagements(
            headers=ADMIN_HEADERS,
            params={"issuer_id": issuer_a["id"], "limit": 1, "offset": 0},
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2, "total_count counts the filtered set"
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_engagements(
            headers=ADMIN_HEADERS,
            params={"issuer_id": issuer_a["id"], "limit": 1, "offset": 1},
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    assert page1[0]["issuer_id"] == issuer_a["id"]
    assert page2[0]["issuer_id"] == issuer_a["id"]
    assert {page1[0]["id"], page2[0]["id"]} == {eng_a1["id"], eng_a2["id"]}, (
        "the two pages together cover exactly issuer A's two engagements"
    )


def test_issuer_get_unknown_id_returns_not_found(api):
    """PRD section 2.9: "The request is rejected with a 404 the moment an
    identifier fails to resolve, before any later segment is examined: an
    unknown issuer yields `ERR_ISSUER_NOT_FOUND`".

    Design: Corner/entities/issuer_get_unknown_id_returns_not_found
    """
    resp = api.get_issuer(NON_EXISTENT_UUID, headers=ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert "meta" in body and "api_request_id" in body["meta"]


def test_engagement_create_missing_credit_type_rejected(api):
    """PRD section 2.10: "Fourth, request well-formedness: required fields
    present, enum values in range, `end_at` after `start_at`,
    `par_amount_cents` positive, `maturity_years` within 1 to 30, and
    `withdraw_reason` present exactly when the rating action is `WITHDRAW`,
    failing as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/engagement_create_missing_credit_type_rejected
    """
    issuer = create_issuer(api)
    payload = engagement_payload(issuer["id"])
    payload.pop("credit_type")
    resp = api.create_engagement(
        payload, headers=make_issuer_headers(issuer["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(
        api.list_engagements(
            headers=ADMIN_HEADERS, params={"issuer_id": issuer["id"]}
        )
    )
    assert data == [] and meta["total_count"] == 0, (
        "a rejected creation persists nothing"
    )


def test_concurrent_engagements_same_credit_type_coexist(api):
    """PRD section 3.1: "Multiple concurrent engagements per issuer, whether
    of the same or of different credit types, are permitted, modeling issuers
    that rate with multiple agencies."

    Design: Corner/validations/concurrent_engagements_same_credit_type_coexist
    """
    issuer = create_issuer(api)
    eng1 = create_engagement_solicited(api, issuer)
    eng2 = create_engagement_solicited(api, issuer)
    eng3 = create_engagement_unsolicited(api, issuer)

    data, meta = validate_paginated(
        api.list_engagements(
            headers=ADMIN_HEADERS, params={"issuer_id": issuer["id"]}
        )
    )
    assert meta["total_count"] == 3
    by_id = {row["id"]: row for row in data}
    assert by_id[eng1["id"]]["status"] == "REQUESTED"
    assert by_id[eng2["id"]]["status"] == "REQUESTED"
    assert by_id[eng3["id"]]["status"] == "INFORMATION_GATHERING"


def test_missing_auth_headers_rejected(api):
    """PRD section 2.1: "A request missing either header, or carrying a role
    the system does not declare, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_rejected
    """
    resp = api.list_issuers(headers=NO_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_invalid_pagination_params_rejected(api):
    """PRD section 2.3: "A `limit` outside the 1-to-100 range or a negative
    `offset` is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400)."

    Design: Corner/errors/invalid_pagination_params_rejected
    """
    issuer = create_issuer(api)
    create_engagement_solicited(api, issuer)
    resp = api.list_engagements(headers=ADMIN_HEADERS, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)


def test_unknown_resource_ids_return_typed_404s(api):
    """PRD section 2.9: "The request is rejected with a 404 the moment an
    identifier fails to resolve, before any later segment is examined: an
    unknown issuer yields `ERR_ISSUER_NOT_FOUND`, an unknown underwriter
    `ERR_UNDERWRITER_NOT_FOUND`, an unknown engagement
    `ERR_ENGAGEMENT_NOT_FOUND`, an unknown criteria version
    `ERR_CRITERIA_VERSION_NOT_FOUND`, an unknown committee session
    `ERR_SESSION_NOT_FOUND`, an unknown rating `ERR_RATING_NOT_FOUND`, an
    unknown appeal `ERR_APPEAL_NOT_FOUND`, an unknown disclosure obligation
    `ERR_OBLIGATION_NOT_FOUND`, an unknown bond sale `ERR_BOND_SALE_NOT_FOUND`,
    and an unknown review item `ERR_REVIEW_ITEM_NOT_FOUND`."

    Design: Corner/errors/unknown_resource_ids_return_typed_404s
    """
    cases = [
        (lambda: api.get_underwriter(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_UNDERWRITER_NOT_FOUND),
        (lambda: api.get_engagement(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
        (lambda: api.get_criteria_version(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_CRITERIA_VERSION_NOT_FOUND),
        (lambda: api.get_session(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_SESSION_NOT_FOUND),
        (lambda: api.get_rating(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_RATING_NOT_FOUND),
        (lambda: api.get_appeal(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_APPEAL_NOT_FOUND),
        (lambda: api.get_obligation(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_OBLIGATION_NOT_FOUND),
        (lambda: api.get_bond_sale(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_BOND_SALE_NOT_FOUND),
        (lambda: api.get_review_item(NON_EXISTENT_UUID, headers=ADMIN_HEADERS),
         ApiErrorId.ERR_REVIEW_ITEM_NOT_FOUND),
    ]
    for call, error_id in cases:
        validate_error(call(), error_id)
