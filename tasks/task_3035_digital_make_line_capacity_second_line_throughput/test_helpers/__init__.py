"""Test infrastructure for the Digital Makeline Capacity API.

Re-exports the pieces test modules reach for most often: the endpoint client,
the error catalog, the domain assertions and the composite fixtures.
"""

from .api_client import ApiClient, api_client, canonical_instant
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_cents,
    assert_created_equals_updated,
    assert_envelope_meta,
    assert_instant,
    assert_instant_format,
    assert_int,
    assert_list_page,
    assert_mutable_common_fields,
)
from .test_users import (
    GENERAL_MANAGER_HEADERS,
    LINE_WORKER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    STORE_MANAGER_HEADERS,
    TEST_USERS,
    UNDECLARED_ROLE,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_general_manager_headers,
    make_line_worker_headers,
    make_marketplace_channel_headers,
    make_platform_admin_headers,
    make_store_manager_headers,
)
from . import constants, factories, fixtures

__all__ = [
    "ApiClient",
    "api_client",
    "canonical_instant",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "assert_cents",
    "assert_created_equals_updated",
    "assert_envelope_meta",
    "assert_instant",
    "assert_instant_format",
    "assert_int",
    "assert_list_page",
    "assert_mutable_common_fields",
    "TEST_USERS",
    "UNDECLARED_ROLE",
    "PLATFORM_ADMIN_HEADERS",
    "STORE_MANAGER_HEADERS",
    "GENERAL_MANAGER_HEADERS",
    "LINE_WORKER_HEADERS",
    "make_platform_admin_headers",
    "make_store_manager_headers",
    "make_general_manager_headers",
    "make_line_worker_headers",
    "make_marketplace_channel_headers",
    "headers_without_role",
    "headers_without_user_id",
    "headers_with_undeclared_role",
    "constants",
    "factories",
    "fixtures",
]
