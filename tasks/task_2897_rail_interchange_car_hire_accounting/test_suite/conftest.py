"""Shared pytest wiring for the rail interchange car hire accounting suite.

The harness relaunches the API server with an empty database before every
individual test, so there is no session-scoped state here: each test builds the
railroads, junctions, rate books, cars and events it needs from scratch through
the endpoints the specification declares.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import ApiClient, ERROR_HTTP_STATUS  # noqa: E402
from test_helpers.api_errors import set_error_http_status_map  # noqa: E402

set_error_http_status_map(ERROR_HTTP_STATUS)


def _base_url() -> str:
    return (
        os.environ.get("_PRD_BENCH_API_URL")
        or os.environ.get("API_BASE_URL")
        or "http://localhost:10000"
    )


@pytest.fixture()
def api() -> ApiClient:
    """A transport client pointed at the freshly restarted server."""
    return ApiClient(_base_url())
