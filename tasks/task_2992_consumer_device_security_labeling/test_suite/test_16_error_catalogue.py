"""The error catalogue's two systemic corners.

The authentication rung must fire for every shape of a missing identity, and
every entity-scoped read must report its own not-found identifier rather than a
single shared code.
"""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    make_headers,
    validate_error,
    validate_success,
)

# The three ways an identity can be missing: a blank principal, a role that is
# not one of the program's six, and a blank role.  Blank values travel as empty
# strings so the HTTP library transmits the header rather than rejecting it.
MISSING_IDENTITY_SHAPES = [
    ("", "Consumer"),
    ("ghost-1", "SuperAdministrator"),
    ("consumer-1", ""),
]

# One id per entity-scoped read, paired with that entity's own not-found code.
NOT_FOUND_READS = [
    (
        "00000000-0000-4000-8000-000000000001",
        api_client.get_program_tier,
        ApiErrorId.ERR_PROGRAM_CONFIG_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000002",
        api_client.get_manufacturer,
        ApiErrorId.ERR_MANUFACTURER_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000003",
        api_client.get_product,
        ApiErrorId.ERR_PRODUCT_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000004",
        api_client.get_test_engagement,
        ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000005",
        api_client.get_label_grant,
        ApiErrorId.ERR_GRANT_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000006",
        api_client.get_retailer,
        ApiErrorId.ERR_RETAILER_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000007",
        api_client.get_display_authorization,
        ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND,
    ),
    (
        "00000000-0000-4000-8000-000000000008",
        api_client.get_enforcement_case,
        ApiErrorId.ERR_CASE_NOT_FOUND,
    ),
]


class TestMissingIdentityShapes:
    """Every shape of a missing identity lands on the authentication rung."""

    def _tier(self):
        return validate_success(
            api_client.create_program_tier(factories.create_program_tier_payload(), ADMIN),
            201,
        )

    def test_blank_principal_unknown_role_and_blank_role_are_all_unauthenticated(self):
        """All three shapes report the same 401 identifier, never a 403.

        PRD: "If either header is absent, present but empty, or `X-User-Role` names something that is not one of the program's six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration."
        Design: Corner/errors/every_missing_identity_shape_returns_unauthenticated
        """
        fixtures.reset_clock()
        tier = self._tier()

        for user_id, role in MISSING_IDENTITY_SHAPES:
            response = api_client.get_program_tier(tier["id"], make_headers(user_id, role))
            validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
            assert response.status_code == 401, (
                f"identity shape ({user_id!r}, {role!r}) returned {response.status_code}"
            )

    def test_unauthenticated_rejection_leaks_no_program_tier_field(self):
        """The 401 body carries the error envelope only, never the guarded row.

        PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        Design: Corner/errors/every_missing_identity_shape_returns_unauthenticated
        """
        fixtures.reset_clock()
        tier = self._tier()

        for user_id, role in MISSING_IDENTITY_SHAPES:
            response = api_client.get_program_tier(tier["id"], make_headers(user_id, role))
            validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
            body = response.json()
            assert body["response_type"] == "error"
            assert sorted(body["data"].keys()) == ["error_id", "message"], sorted(
                body["data"].keys()
            )
            assert sorted(body["meta"].keys()) == [
                "api_request_id",
                "api_request_timestamp",
            ], sorted(body["meta"].keys())
            for leaked in ("tier_code", "label_validity_days", "min_overall_score"):
                assert leaked not in body["data"], f"{leaked} leaked through a 401"


class TestPerEntityNotFoundCodes:
    """Each entity-scoped read owns a distinct not-found identifier."""

    def test_every_entity_read_reports_its_own_not_found_code(self):
        """Eight reads against an empty database yield eight distinct 404 codes.

        PRD: "The reported code is the not-found code of whichever entity failed to resolve first — `ERR_PROGRAM_CONFIG_NOT_FOUND` for an unknown program tier or device category, `ERR_MANUFACTURER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CRITERION_NOT_FOUND`, `ERR_TEST_LAB_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND` or `ERR_REGISTRY_CODE_NOT_FOUND`."
        Design: Corner/errors/every_entity_read_has_its_own_not_found_error
        """
        fixtures.reset_clock()

        observed = []
        for entity_id, reader, expected in NOT_FOUND_READS:
            response = reader(entity_id, ADMIN)
            error = validate_error(response, expected.value)
            assert response.status_code == 404, (
                f"{expected.value} returned {response.status_code}"
            )
            assert isinstance(error["message"], str) and error["message"].strip()
            observed.append(error["error_id"])

        assert len(set(observed)) == len(NOT_FOUND_READS), (
            f"not-found codes collided: {observed}"
        )
