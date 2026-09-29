"""Shared test infrastructure for the store-operations compliance suite.

Importing this package registers the error-identifier to HTTP-status mapping the
validators need, so a test module only has to import the names it uses.
"""

from . import assertions, constants, factories, fixtures, types
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    BOOTSTRAP_MANAGER_HEADERS,
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    SECOND_COMPLIANCE_HEADERS,
    TEST_USERS,
    headers_for,
    make_care_headers,
    make_compliance_headers,
    make_dispatcher_headers,
    make_driver_headers,
    make_manager_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "BOOTSTRAP_MANAGER_HEADERS",
    "CARE_HEADERS",
    "COMPLIANCE_HEADERS",
    "DISPATCHER_HEADERS",
    "HTTP_STATUS_CODES",
    "SECOND_COMPLIANCE_HEADERS",
    "TEST_USERS",
    "api_client",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "headers_for",
    "make_care_headers",
    "make_compliance_headers",
    "make_dispatcher_headers",
    "make_driver_headers",
    "make_manager_headers",
    "types",
]
