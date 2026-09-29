"""Test infrastructure for the Newsroom Standards & Corrections API.

Importing this package registers the PRD §5 error-id-to-HTTP-status map with
the shared validators, so ``validate_error`` cross-checks the status code of
every error response without each test having to repeat it.
"""

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from . import assertions
from . import constants
from . import factories
from . import fixtures
from . import types
from .api_client import ApiClient, api_client
from .api_errors import ERROR_HTTP_STATUS
from .test_users import (
    ALTERNATE_PUBLIC_EDITOR_USER_ID,
    BOOTSTRAP_EXEC_USER_ID,
    PUBLIC_EDITOR_USER_ID,
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_bootstrap_exec_headers,
    make_executive_editor_headers,
    make_legal_counsel_headers,
    make_public_editor_headers,
    make_reporter_headers,
    make_standards_editor_headers,
)

__all__ = [
    "ALTERNATE_PUBLIC_EDITOR_USER_ID",
    "ApiClient",
    "BOOTSTRAP_EXEC_USER_ID",
    "ERROR_HTTP_STATUS",
    "PUBLIC_EDITOR_USER_ID",
    "TEST_USERS",
    "api_client",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "headers_without_role",
    "headers_without_user_id",
    "make_bootstrap_exec_headers",
    "make_executive_editor_headers",
    "make_legal_counsel_headers",
    "make_public_editor_headers",
    "make_reporter_headers",
    "make_standards_editor_headers",
    "types",
]
