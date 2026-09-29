"""Test support package for the Nutrient Trading & Watershed Load Allocation API.

Importing this package registers the error_id -> HTTP status mapping with the
shared response validators, so `validate_error` cross-checks statuses for free.
"""

from . import api_errors  # noqa: F401  (import registers the error status map)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient, canonical_instant  # noqa: F401

__all__ = [
    "ApiClient",
    "canonical_instant",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
