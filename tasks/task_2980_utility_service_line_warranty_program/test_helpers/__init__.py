"""Shared test infrastructure for the Utility Service Line Warranty Program API.

Importing this package registers the PRD §5 error-to-status map with the shared
validators, so ``validate_error`` cross-checks the HTTP status of every refusal
even when a test names only the ``error_id``.
"""

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, canonical_instant  # noqa: F401

__all__ = [
    "ApiClient",
    "api_errors",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
