"""Authentication and authorization gates (PRD §2.1, §2.8 tiers 1-2)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_geo_zone_payload,
    validate_error,
)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "If either header is missing, if `X-User-ID` is empty, or if
    `X-User-Role` is not one of the declared roles, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    res = api.list_programs(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_geo_zone_create_forbidden_role(api, comp_analyst_headers):
    """PRD §2.1: "Every endpoint declares the roles permitted to call it; an
    authenticated caller whose role is not listed for the endpoint is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /comp/geo-zones lists only CompAdmin.

    Design: Corner/validations/geo_zone_create_forbidden_role
    """
    res = api.create_geo_zone(
        create_geo_zone_payload(zone_code="US-NAT", name="US National",
                                differential_ratio=1.000000),
        comp_analyst_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)
