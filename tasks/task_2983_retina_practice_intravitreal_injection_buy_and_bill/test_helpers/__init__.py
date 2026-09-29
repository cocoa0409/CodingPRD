"""
Shared test infrastructure for the retina buy-and-bill contract.

Layers, bottom up:

``constants``   named literals, role names and closed enum sets
``api_errors``  the error catalogue and its HTTP status map
``types``       documentation-grade TypedDicts for the entity representations
``api_client``  one method per endpoint, returning the raw response
``assertions``  envelope, system-field, money and conservation assertions
``test_users``  acting identities and the header builders that carry them
``factories``   request-payload factories
``fixtures``    composite state builders over the endpoints
"""

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_envelope_shape,
    assert_error_envelope,
    assert_fields_equal,
    assert_immutable_entity_fields,
    assert_instant_equals,
    assert_money_cents,
    assert_system_fields,
    assert_vial_conservation,
    assert_vial_counters,
    list_ids,
    validate_list,
    validate_unpaginated,
)
from .fixtures import BreadthWorld, DepthWorld, World
from .test_users import (
    ADMIN_USER_ID,
    BILLING_USER_ID,
    COMPLIANCE_USER_ID,
    COMPLIANCE_USER_ID_2,
    COMPLIANCE_USER_ID_3,
    TECH_USER_ID,
    TECH_USER_ID_ALT,
    TEST_USERS,
    UNKNOWN_ROLE_NAME,
    UNRESOLVABLE_IDENTITY,
    admin_headers,
    billing_headers,
    compliance_headers,
    headers_blanking,
    headers_for,
    headers_omitting,
    patient_headers,
    specialist_headers,
    tech_headers,
    with_role,
    with_user_id,
)

__all__ = [
    "ADMIN_USER_ID",
    "ApiClient",
    "ApiErrorId",
    "BILLING_USER_ID",
    "BreadthWorld",
    "COMPLIANCE_USER_ID",
    "COMPLIANCE_USER_ID_2",
    "COMPLIANCE_USER_ID_3",
    "DepthWorld",
    "HTTP_STATUS_CODES",
    "TECH_USER_ID",
    "TECH_USER_ID_ALT",
    "TEST_USERS",
    "UNKNOWN_ROLE_NAME",
    "UNRESOLVABLE_IDENTITY",
    "World",
    "admin_headers",
    "assert_envelope_shape",
    "assert_error_envelope",
    "assert_fields_equal",
    "assert_immutable_entity_fields",
    "assert_instant_equals",
    "assert_money_cents",
    "assert_system_fields",
    "assert_vial_conservation",
    "assert_vial_counters",
    "assertions",
    "billing_headers",
    "canonical_instant",
    "compliance_headers",
    "constants",
    "factories",
    "fixtures",
    "headers_blanking",
    "headers_for",
    "headers_omitting",
    "list_ids",
    "patient_headers",
    "specialist_headers",
    "tech_headers",
    "types",
    "validate_list",
    "validate_unpaginated",
    "with_role",
    "with_user_id",
]
