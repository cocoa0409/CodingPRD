"""Test infrastructure for the Pediatric PDN Authorization Staffing API."""

from prd_bench_local_runner.testing.validators import set_error_http_status_map

from .api_errors import ERROR_HTTP_STATUS

# Register the domain's error_id -> HTTP status mapping so that every
# validate_error call cross-checks the status code for free.
set_error_http_status_map(ERROR_HTTP_STATUS)

from . import api_errors, assertions, constants, factories, fixtures, test_users, types  # noqa: E402
from .api_client import ApiClient, canonicalize_instant, raw_json  # noqa: E402

__all__ = [
    "ApiClient",
    "canonicalize_instant",
    "raw_json",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "ERROR_HTTP_STATUS",
]
