"""Shared test infrastructure for the Nitrogen Fertilizer Production API.

Importing this package registers the domain error catalogue with the shared
validators, so every ``validate_error`` call cross-checks the HTTP status that
PRD section 5 pins to the returned ``error_id``.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient
from .api_errors import HTTP_STATUS_CODES, NOT_FOUND_BY_FAMILY

__all__ = [
    "ApiClient",
    "HTTP_STATUS_CODES",
    "NOT_FOUND_BY_FAMILY",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
