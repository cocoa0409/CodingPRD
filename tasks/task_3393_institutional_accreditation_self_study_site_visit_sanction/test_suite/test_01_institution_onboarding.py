"""Institution onboarding, response envelope, directory listing, and auth gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_institution,
    create_institution,
    institution_payload,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import DUES_CANONICAL_800_A_B


def test_institution_onboarding_applies_computed_defaults(api, admin_headers):
    """PRD section 3.1: "A new institution begins with `accreditation_status` `PROSPECTIVE` and `sanction_status` `NONE`, with `distance_delivery_approved` false, `locations_count` at 1, no candidacy pathway or timestamps — `candidacy_pathway`, `candidacy_started_at`, and `candidacy_expires_at` all null — no `accredited_since` or `last_reaffirmed_at`, and no CFI history, so `latest_cfi_value` and `latest_cfi_band` are null until the first indicator evaluation."
    PRD section 3.1: "At creation the system also initializes `dues_paid_cents` equal to `current_annual_dues_cents`, so a freshly onboarded institution starts with zero arrears."

    Design: Corner/entities/institution_create_applies_computed_defaults
    """
    set_logical_clock()
    response = api.create_institution(institution_payload(), admin_headers)
    data = validate_success(response, 201)
    assert_institution(data)
    assert data["accreditation_status"] == "PROSPECTIVE"
    assert data["sanction_status"] == "NONE"
    assert data["version"] == 1
    assert data["current_annual_dues_cents"] == DUES_CANONICAL_800_A_B
    assert data["dues_paid_cents"] == DUES_CANONICAL_800_A_B
    assert data["outstanding_dues_cents"] == 0
    assert data["distance_delivery_approved"] is False
    assert data["locations_count"] == 1
    assert data["candidacy_pathway"] is None
    assert data["latest_cfi_value"] is None
    assert data["latest_cfi_band"] is None


def test_response_envelope_success_and_error_shape(api, admin_headers, staff_headers):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD section 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD section 2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    set_logical_clock()
    create_response = api.create_institution(
        institution_payload(legal_name="Envelope College", legal_status="PUBLIC",
                            fte_enrollment=100, degree_levels_offered=["ASSOCIATE"]),
        admin_headers,
    )
    data = validate_success(create_response, 201)
    body = create_response.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert data["legal_name"] == "Envelope College"

    error_response = api.get_institution(NON_EXISTENT_UUID, staff_headers)
    validate_error(error_response, ApiErrorId.ERR_INSTITUTION_NOT_FOUND)
    error_body = error_response.json()
    assert error_body["response_type"] == "error"
    assert isinstance(error_body["data"]["message"], str)
    assert error_body["data"]["message"].strip()


def test_institution_directory_paginates_with_total_count(api, admin_headers, staff_headers):
    """PRD section 2.3: "`limit` caps the number of items returned; when omitted it defaults to 10, and any supplied value must be at least 1 and at most 100. `offset` skips that many items from the front of the result set and defaults to 0."
    PRD section 2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/institutions_list_paginates_with_total_count_and_has_more
    """
    set_logical_clock()
    create_institution(legal_name="Alpha College", legal_status="PRIVATE_NONPROFIT",
                       state_code="IA", fte_enrollment=100, degree_levels_offered=["ASSOCIATE"])
    create_institution(legal_name="Beta University", legal_status="PUBLIC",
                       state_code="MN", fte_enrollment=200, degree_levels_offered=["BACCALAUREATE"])
    create_institution(legal_name="Gamma Institute", legal_status="PRIVATE_FORPROFIT",
                       state_code="MO", fte_enrollment=300, degree_levels_offered=["DOCTORAL"])

    page1, meta1 = validate_paginated(
        api.list_institutions(staff_headers, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_institutions(staff_headers, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2


def test_institution_get_unknown_id_returns_not_found(api, staff_headers):
    """PRD section 2.8: "The global order is: (1) authentication of the two headers, failing as `ERR_UNAUTHENTICATED`; (2) role permission and entity-backed ownership, failing as `ERR_UNAUTHORIZED_ROLE`; (3) existence of every identifier in the path, validated left to right, where the first unresolved identifier produces the not-found code belonging to its own path root — one of `ERR_INSTITUTION_NOT_FOUND`, `ERR_ELIGIBILITY_APPLICATION_NOT_FOUND`, `ERR_REVIEW_CYCLE_NOT_FOUND`, `ERR_ASSURANCE_ARGUMENT_NOT_FOUND`, `ERR_EVIDENCE_ITEM_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_REVIEW_TEAM_NOT_FOUND`, `ERR_TEAM_ASSIGNMENT_NOT_FOUND`, `ERR_DECISION_PANEL_NOT_FOUND`, `ERR_ACTION_OUTCOME_NOT_FOUND`, `ERR_SUBSTANTIVE_CHANGE_NOT_FOUND`, or `ERR_INDICATOR_REPORT_NOT_FOUND`, each an HTTP 404; (4) state-machine checks — whether the target resource stands in a state that permits the requested transition, failing as `ERR_INVALID_STATE` — together with the creation guards on review cycles (`ERR_CYCLE_ALREADY_OPEN`) and substantive-change requests (`ERR_INSTITUTION_NOT_ACCREDITED`); and finally (5) the business rules of the endpoint — safety, constraint, temporal, referential, and fiscal checks — each named where it applies in §3."

    Design: Corner/entities/institution_get_not_found_returns_404
    """
    set_logical_clock()
    response = api.get_institution(NON_EXISTENT_UUID, staff_headers)
    validate_error(response, ApiErrorId.ERR_INSTITUTION_NOT_FOUND)
    assert response.json()["response_type"] == "error"


def test_request_without_auth_headers_is_unauthenticated(api, staff_headers):
    """PRD section 2.1: "A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    set_logical_clock()
    response = api.create_institution(
        institution_payload(legal_name="No Headers College", legal_status="PUBLIC",
                            fte_enrollment=100, degree_levels_offered=["ASSOCIATE"]),
        None,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)

    _page, meta = validate_paginated(api.list_institutions(staff_headers))
    assert meta["total_count"] == 0
