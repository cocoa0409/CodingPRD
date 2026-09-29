"""Shared test infrastructure for the Packaging Machinery OEM service.

Importing this package registers the error-id to HTTP-status map with the
framework validators, so `validate_error` cross-checks the status of every
error assertion automatically.

Tests import everything they need from here:

    from test_helpers import (
        api_client, TEST_USERS, ApiErrorId, setup_active_contract, ...
    )
"""

from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401  (registers the status map)
from .constants import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .test_users import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
