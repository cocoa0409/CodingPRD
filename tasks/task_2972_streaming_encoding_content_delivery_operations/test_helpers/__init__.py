"""Test infrastructure for the Streaming Encoding & Delivery Operations API.

Importing this package registers the PRD §5 error identifier to HTTP status
mapping with the shared validators, so `validate_error` cross-checks statuses
even when a test names only the identifier.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient, canonical_instant, instants_equal, parse_instant

__all__ = [
    "ApiClient",
    "api_errors",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "instants_equal",
    "parse_instant",
    "test_users",
    "types",
]
