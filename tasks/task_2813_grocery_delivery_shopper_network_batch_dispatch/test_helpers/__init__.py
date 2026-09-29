"""Test infrastructure for the Grocery Delivery Shopper Network & Batch Dispatch API.

Importing this package registers the error_id -> HTTP status map with the
framework validators, so validate_error() cross-checks statuses everywhere.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import (
    ApiClient,
    canonical_instant,
    normalize_timestamp,
    shift_hours,
    shift_minutes,
)
from .api_errors import ERROR_HTTP_STATUS
from .test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_admin_headers,
    make_customer_headers,
    make_retailer_manager_headers,
    make_shopper_headers,
    make_support_headers,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "ADMIN_HEADERS",
    "SUPPORT_HEADERS",
    "api_errors",
    "assertions",
    "canonical_instant",
    "constants",
    "factories",
    "fixtures",
    "make_admin_headers",
    "make_customer_headers",
    "make_retailer_manager_headers",
    "make_shopper_headers",
    "make_support_headers",
    "normalize_timestamp",
    "shift_hours",
    "shift_minutes",
    "test_users",
    "types",
]
