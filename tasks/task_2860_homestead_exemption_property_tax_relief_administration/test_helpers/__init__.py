"""Shared test infrastructure for the Homestead Exemption & Property Tax Relief API.

Layers:
  constants.py   — domain constants pinned by the PRD (clock, bps, rates, enums)
  types.py       — small structural aliases used across the helpers
  api_errors.py  — the error catalogue and its error_id -> HTTP status mapping
  api_client.py  — one method per PRD endpoint
  factories.py   — request-payload builders with PRD-legal defaults
  assertions.py  — domain assertions over entity bodies
  test_users.py  — per-role auth headers, including the entity-backed Taxpayer
  fixtures.py    — composite state builders (programmes, parcels, grants, appeals)

Importing the package registers the error_id -> HTTP status map with the
framework validators, so ``validate_error`` cross-checks the status code of every
rejection without the test having to repeat it.
"""

from . import api_errors  # noqa: F401  (registers the error status map)
from . import assertions, constants, factories, fixtures
from .api_client import ApiClient, canonical_instant
from .test_users import (
    ADMIN,
    ANALYST,
    ANALYST_2,
    CLERK,
    CLERK_2,
    HEARING_CLERK,
    HEARING_OFFICER,
    HEARING_OFFICER_2,
    INVESTIGATOR,
    INVESTIGATOR_2,
    RECOVERY,
    RECOVERY_2,
    REVIEWER,
    REVIEWER_2,
    TEST_USERS,
    make_headers,
    make_taxpayer_headers,
)

api_client = ApiClient()

__all__ = [
    "ApiClient",
    "api_client",
    "canonical_instant",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "TEST_USERS",
    "ADMIN",
    "ANALYST",
    "ANALYST_2",
    "CLERK",
    "CLERK_2",
    "REVIEWER",
    "REVIEWER_2",
    "INVESTIGATOR",
    "INVESTIGATOR_2",
    "RECOVERY",
    "RECOVERY_2",
    "HEARING_CLERK",
    "HEARING_OFFICER",
    "HEARING_OFFICER_2",
    "make_headers",
    "make_taxpayer_headers",
]
