"""Shared test infrastructure for the Global Payroll Aggregation API.

Import surface for the suite:

  * `api_client` — the module-level `ApiClient` instance every test drives;
  * `TEST_USERS` — the role-keyed header dictionaries;
  * `make_provider_user_headers(provider_id)` — the per-provider identity;
  * `constants`, `api_errors` — PRD enum members and error identifiers;
  * `factories` — request-payload builders with the PRD's type discipline;
  * `fixtures` — composite setup chains built purely from PRD endpoints;
  * `assertions` — domain post-condition assertions.

Helpers return the inner `data` object of the response envelope, so no caller
ever needs to index `["data"]` again.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_errors import *  # noqa: F401,F403
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADMIN_USER_ID,
    AUDITOR_HEADERS,
    AUDITOR_USER_ID,
    CONTROLLER_2_HEADERS,
    CONTROLLER_2_USER_ID,
    CONTROLLER_HEADERS,
    CONTROLLER_USER_ID,
    OPS_2_HEADERS,
    OPS_2_USER_ID,
    OPS_HEADERS,
    OPS_USER_ID,
    PLATFORM_ADMIN_HEADERS,
    TEST_USERS,
    TREASURY_APPROVER_HEADERS,
    TREASURY_APPROVER_USER_ID,
    TREASURY_RELEASER_HEADERS,
    TREASURY_RELEASER_USER_ID,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
    make_headers,
    make_provider_user_headers,
)
from .types import (  # noqa: F401
    APPEND_ONLY_FIELDS,
    COMMON_FIELDS,
    Headers,
    Json,
)

# Imported last so that `api_client` names the shared client instance rather than
# the module that defines it.
from .api_client import ApiClient, api_client  # noqa: F401
