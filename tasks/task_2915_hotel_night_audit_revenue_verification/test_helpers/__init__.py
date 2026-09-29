"""Test infrastructure for the hotel night-audit revenue verification API.

Importing this package registers the error id to HTTP status mapping with the
framework validators, so `validate_error` cross-checks the status line for free.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import OMIT, NightAuditApiClient
from .api_errors import ERROR_HTTP_STATUS

__all__ = [
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "NightAuditApiClient",
    "OMIT",
    "ERROR_HTTP_STATUS",
]
