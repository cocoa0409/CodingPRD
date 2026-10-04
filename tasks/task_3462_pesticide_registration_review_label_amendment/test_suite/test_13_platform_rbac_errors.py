"""Platform-wide contracts: operator-context and role authorization, the
validation pipeline's priority order, fixed reference sets, specific vs generic
404s, duplicate-tolerance uniqueness, and pagination (PRD §2.1–§2.9, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_active_ingredient,
    create_product,
    create_tolerance,
    list_product_tolerances,
    make_application_decision_payload,
    make_certification_renewal_payload,
    make_product_payload,
    make_tolerance_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]
ASSESSOR = TEST_USERS["assessor_1_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]
CERT_AUTHORITY = TEST_USERS["certification_authority_headers"]


def test_missing_x_user_role_header_returns_400(api):
    """PRD §2.1: "A request missing either header, or carrying a role outside this
    set of six, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/validations/missing_x_user_role_header_returns_400
    """
    ai = create_active_ingredient()
    payload = make_product_payload(ai["id"], product_name="Nominex G")
    # X-User-ID present, X-User-Role omitted entirely.
    resp = api_client.create_product(payload, {"X-User-ID": "reg-alice"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    _, meta = validate_paginated(api_client.list_products(REVIEWER))
    assert meta["total_count"] == 0


def test_wrong_role_product_create_returns_403(api):
    """PRD §2.1: "A request whose role is not among the roles an operation
    authorizes is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §4: "| POST | `/pesticide-registry/products` | Create a product shell |
    RegistrantRepresentative |"

    Design: Corner/rbac/wrong_role_product_create_returns_403
    """
    ai = create_active_ingredient()
    payload = make_product_payload(ai["id"], product_name="Nominex G")
    resp = api_client.create_product(payload, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    _, meta = validate_paginated(api_client.list_products(REVIEWER))
    assert meta["total_count"] == 0


def test_get_endpoints_accept_every_declared_role(api):
    """PRD §2.1: "Six roles are recognized, spelled exactly as follows:
    `SystemAdministrator`, `RegistrantRepresentative`, `RegistrationReviewer`,
    `RiskAssessor`, `StateLeadAgency`, and `CertificationAuthority`."
    PRD §4: "| GET | `/pesticide-registry/active-ingredients` | List active
    ingredients | All roles |"

    Design: Corner/rbac/get_endpoints_accept_every_declared_role
    """
    create_active_ingredient()
    for headers in (ADMIN, REGISTRANT, REVIEWER, ASSESSOR, STATE_AGENCY,
                    CERT_AUTHORITY):
        rows, meta = validate_paginated(api_client.list_active_ingredients(headers))
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert api_client.list_active_ingredients(headers).json()[
            "response_type"] == "array"


def test_product_get_unknown_id_returns_product_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve produces the 404 for
    its own resource type: `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_APPLICATION_NOT_FOUND` for an application,
    `ERR_STATE_REGISTRATION_NOT_FOUND` for a state registration, and the generic
    `ERR_NOT_FOUND` for every other resource type."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/errors/product_get_unknown_id_returns_product_not_found
    """
    resp = api_client.get_product(NON_EXISTENT_UUID, REVIEWER)
    error_data = validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"]
    assert isinstance(error_data["message"], str) and error_data["message"]


def test_state_registration_get_unknown_id_returns_specific_404(api):
    """PRD §2.9: "the first identifier that does not resolve produces the 404 for
    its own resource type: `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_APPLICATION_NOT_FOUND` for an application,
    `ERR_STATE_REGISTRATION_NOT_FOUND` for a state registration, and the generic
    `ERR_NOT_FOUND` for every other resource type."

    Design: Corner/errors/state_registration_get_unknown_id_returns_specific_404
    """
    resp = api_client.get_state_registration(NON_EXISTENT_UUID, STATE_AGENCY)
    validate_error(resp, ApiErrorId.ERR_STATE_REGISTRATION_NOT_FOUND)


def test_certification_renew_unknown_id_returns_generic_not_found(api):
    """PRD §2.9: "the first identifier that does not resolve produces the 404 for
    its own resource type: `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_APPLICATION_NOT_FOUND` for an application,
    `ERR_STATE_REGISTRATION_NOT_FOUND` for a state registration, and the generic
    `ERR_NOT_FOUND` for every other resource type."

    Design: Corner/errors/certification_renew_unknown_id_returns_generic_not_found
    """
    resp = api_client.renew_certification(
        NON_EXISTENT_UUID, make_certification_renewal_payload("2028-01-01T00:00:00Z"),
        CERT_AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_tolerance_create_unknown_commodity_returns_422(api):
    """PRD §2.9: "The dietary model knows exactly five commodities — `CORN`,
    `SOYBEAN`, `WHEAT`, `APPLE`, and `COTTON` — and any `commodity_code` outside
    this set is rejected with `ERR_UNKNOWN_COMMODITY` (HTTP 422)."

    Design: Corner/errors/tolerance_create_unknown_commodity_returns_422
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"], product_name="Nominex 15G")
    resp = api_client.create_tolerance(
        make_tolerance_payload(product["id"], "QUINOA", 0.05), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_UNKNOWN_COMMODITY)
    assert list_product_tolerances(product["id"]) == []


def test_duplicate_tolerance_same_commodity_rejected(api):
    """PRD §3.4: "At most one tolerance in `PROPOSED` or `ESTABLISHED` may exist
    for a given product-and-commodity pair; a colliding proposal is rejected with
    `ERR_DUPLICATE_TOLERANCE` (HTTP 409)."

    Design: Corner/validations/duplicate_tolerance_same_commodity_rejected
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"], product_name="Nominex 15G")
    create_tolerance(product["id"], REGISTRANT, commodity_code="CORN",
                     tolerance_ppm=0.05)

    resp = api_client.create_tolerance(
        make_tolerance_payload(product["id"], "CORN", 0.1), REGISTRANT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TOLERANCE)
    assert len(list_product_tolerances(product["id"])) == 1


def test_nonexistent_application_decision_returns_404_before_state(api):
    """PRD §2.8: "4. **Existence** — path identifiers resolve left to right, then
    body-supplied foreign keys resolve; the first miss produces the
    resource-appropriate 404 (§2.9)."
    PRD §2.9: "Where a path nests one resource beneath another, identifiers are
    validated in a strict left-to-right order, and the first identifier that does
    not resolve produces the 404 for its own resource type:
    `ERR_PRODUCT_NOT_FOUND` for a product, `ERR_APPLICATION_NOT_FOUND` for an
    application, `ERR_STATE_REGISTRATION_NOT_FOUND` for a state registration, and
    the generic `ERR_NOT_FOUND` for every other resource type."

    Design: Corner/validations/nonexistent_application_decision_returns_404_before_state
    """
    resp = api_client.decide_application(
        NON_EXISTENT_UUID,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REVIEWER,
    )
    error_data = validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"]


def test_wrong_role_with_nonexistent_id_returns_403_before_404(api):
    """PRD §2.8: "The stages are evaluated in the order below, and a failure at
    any stage short-circuits all later stages"
    PRD §2.8: "2. **Role authorization** — the role must be listed for the
    endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, HTTP 403)."
    PRD §4: "| POST |
    `/pesticide-registry/registration-applications/{id}/review-decisions` |
    Reviewer decision: APPROVE, DENY, or DEFICIENCY | RegistrationReviewer |"

    Design: Corner/validations/wrong_role_with_nonexistent_id_returns_403_before_404
    """
    resp = api_client.decide_application(
        NON_EXISTENT_UUID,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REGISTRANT,
    )
    # Authorization (stage 2) fires ahead of existence (stage 4): the caller
    # never learns whether the id exists.
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_active_ingredients_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of
    100. The `offset` parameter specifies how many items to skip and defaults to
    0."
    PRD §2.3: "List responses include four pagination fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/active_ingredients_list_paginates_with_total_count_and_has_more
    """
    create_active_ingredient(common_name="nominex", cas_number="100-00-1",
                           tox_category="III", reference_dose_mg_kg_day=0.05,
                           aquatic_lc50_ppm=100.0)
    create_active_ingredient(common_name="toximax", cas_number="200-00-2",
                           tox_category="I", reference_dose_mg_kg_day=0.02,
                           aquatic_lc50_ppm=10.0)
    create_active_ingredient(common_name="herbex", cas_number="300-00-3",
                           tox_category="IV", reference_dose_mg_kg_day=0.1,
                           aquatic_lc50_ppm=50.0)

    page1, meta1 = validate_paginated(
        api_client.list_active_ingredients(REVIEWER, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_active_ingredients(REVIEWER, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    all_rows, meta_all = validate_paginated(
        api_client.list_active_ingredients(REVIEWER))
    assert len(all_rows) == 3  # default limit 10, offset 0
    assert meta_all["total_count"] == 3
    assert meta_all["has_more"] is False
