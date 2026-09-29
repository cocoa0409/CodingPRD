"""Test helper package for the Academic Integrity Case Adjudication API.

Layout:
  types.py       domain enums and entity TypedDicts
  constants.py   PRD thresholds and the canonical fixture literals
  api_errors.py  the 72 error ids and their HTTP statuses
  api_client.py  one method per endpoint + instant canonicalisation
  assertions.py  envelope, list and per-entity assertions
  factories.py   request-payload builders (input fields only)
  test_users.py  acting-identity headers for the six roles
  fixtures.py    composite setup helpers built from PRD endpoints only
"""
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant, instants_equal
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    TEST_USERS,
    headers_for,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_with_whitespace_role,
    headers_with_whitespace_user_id,
    headers_without_role,
    headers_without_user_id,
    make_chair_headers,
    make_dean_headers,
    make_officer_headers,
    make_registrar_headers,
    make_reporter_headers,
    make_student_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "api_client",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "headers_for",
    "headers_with_empty_role",
    "headers_with_empty_user_id",
    "headers_with_whitespace_role",
    "headers_with_whitespace_user_id",
    "headers_without_role",
    "headers_without_user_id",
    "instants_equal",
    "make_chair_headers",
    "make_dean_headers",
    "make_officer_headers",
    "make_registrar_headers",
    "make_reporter_headers",
    "make_student_headers",
    "types",
]
