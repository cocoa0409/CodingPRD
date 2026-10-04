"""RBAC and auth header enforcement (PRD §2.1, §4)."""
from test_helpers import (
    AD,
    ApiErrorId,
    anonymous_headers,
    create_property_payload,
    validate_error,
)


def test_adops_cannot_create_property(api):
    """PRD §2.1: "If the role is present but the endpoint is not open to
    that role per the matrix in §4, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /platform/properties is authorized for RightsManager only.

    Design: Corner/rbac/adops_cannot_create_property
    """
    resp = api.create_property(create_property_payload(), AD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or malformed, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_property(create_property_payload(), anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_viewer_default_tier_applied_when_omitted(api):
    """PRD §3.4: "A `Viewer` registers itself by supplying `email` (unique
    across viewers), `home_region` (a DMA region code), and optionally
    `subscription_tier` (one of `FREE`, `AD_SUPPORTED`, `PREMIUM`,
    defaulting to `AD_SUPPORTED` when omitted)."

    Design: Corner/entities/viewer_default_tier_applied_when_omitted
    """
    from test_helpers import PM, TEST_USERS, create_viewer_payload, validate_success

    resp = api.create_viewer(create_viewer_payload(), TEST_USERS["viewer_headers"])
    created = validate_success(resp, expected_status=201)
    fetched = validate_success(api.get_viewer(created["id"], PM))
    assert fetched["subscription_tier"] == "AD_SUPPORTED"


def test_computed_committed_units_starts_at_zero(api):
    """PRD §3.5: "The pool's `committed_units` counter is computed as the sum
    of units over all non-terminal reservations (those in `HELD` or
    `CONFIRMED`)."

    A freshly created pool has no reservations, so committed_units is 0 on
    both the create response and a follow-up read.

    Design: Corner/entities/computed_committed_units_ignores_input_override
    """
    from test_helpers import SO, create_pool

    pool = create_pool(total_units=10)
    assert pool["committed_units"] == 0
    from test_helpers import get_success_data
    fetched = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert fetched["committed_units"] == 0
