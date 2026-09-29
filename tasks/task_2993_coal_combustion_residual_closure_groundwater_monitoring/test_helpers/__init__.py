"""Shared test infrastructure for the CCR Closure & Groundwater Monitoring API.

Importing this package registers the contract's error-identifier-to-HTTP-status
map with the shared validators, so ``validate_error`` cross-checks the status of
every refusal the suite asserts on.
"""

from . import api_errors  # noqa: F401  (import registers the error status map)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, canonical_instant  # noqa: F401
from .api_errors import ApiErrorId  # noqa: F401

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "api_errors",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
