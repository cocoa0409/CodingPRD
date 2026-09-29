"""
Test helpers for the Reentry Employment Services API compliance suite.

Layout:
  constants.py   — every enum value, threshold and worked figure from the PRD
  api_errors.py  — error identifiers and their HTTP statuses
  types.py       — TypedDict shapes for payloads and responses
  api_client.py  — one method per endpoint, plus instant canonicalisation
  test_users.py  — pre-built caller identities per role
  assertions.py  — envelope, common-field, money and list-shape assertions
  factories.py   — payload builders with PRD-valid defaults
  fixtures.py    — pytest fixtures that build multi-step preconditions

Importing this package registers the error-id to HTTP-status mapping with the
shared response validators.
"""

from . import api_errors  # noqa: F401  (registers the error/status mapping)
from .api_client import ApiClient, canonical_instant, canonical_instants
from .assertions import (
    assert_common_fields,
    assert_created_at_stable,
    assert_ids_in_order,
    assert_instant_equals,
    assert_int_field,
    assert_money_cents,
    assert_nullable_rate,
    assert_one_decimal_place,
    assert_page_ids,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    validate_unpaginated,
)
from .test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    NO_AUTH,
    PROGRAM_DIRECTOR,
    PROGRAM_DIRECTOR_2,
    SUPERVISION_OFFICER,
    SUPERVISION_OFFICER_2,
    headers_for_role,
    headers_with_empty_user_id,
    headers_without_user_id,
    participant_headers,
)

__all__ = [
    "ApiClient",
    "canonical_instant",
    "canonical_instants",
    "assert_common_fields",
    "assert_created_at_stable",
    "assert_ids_in_order",
    "assert_instant_equals",
    "assert_int_field",
    "assert_money_cents",
    "assert_nullable_rate",
    "assert_one_decimal_place",
    "assert_page_ids",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    "validate_unpaginated",
    "CASE_MANAGER",
    "EMPLOYER_LIAISON",
    "FUNDER_ANALYST",
    "NO_AUTH",
    "PROGRAM_DIRECTOR",
    "PROGRAM_DIRECTOR_2",
    "SUPERVISION_OFFICER",
    "SUPERVISION_OFFICER_2",
    "headers_for_role",
    "headers_with_empty_user_id",
    "headers_without_user_id",
    "participant_headers",
]
