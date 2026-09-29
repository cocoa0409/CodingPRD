"""Test infrastructure for the Academic Program Review & Discontinuation API.

Importing this package registers the §5 error_id -> HTTP status mapping with the
framework's validator layer, so ``validate_error`` cross-checks the declared
status even when a call site does not name one.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient

__all__ = [
    "ApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
