"""Test infrastructure for the municipal bond underwriting API.

Importing this package registers the PRD's error-id to HTTP-status map with the
shared framework, so ``validate_error`` can cross-check statuses everywhere.
"""

from . import api_errors, assertions, constants, factories, fixtures, types
from .api_client import PREFIX, ApiClient, api_client
from .api_errors import ERROR_HTTP_STATUS
from .constants import API_PREFIX, CLOCK_EPOCH
from .test_users import (
    BOND_COUNSEL_DRAFTER_HEADERS,
    BOND_COUNSEL_DRAFTER_ID,
    BOND_COUNSEL_REVIEWER_HEADERS,
    BOND_COUNSEL_REVIEWER_ID,
    COMPLIANCE_HEADERS,
    COMPLIANCE_OFFICER_ID,
    RATING_ANALYST_HEADERS,
    RATING_ANALYST_OTHER_HEADERS,
    RATING_ANALYST_OTHER_ID,
    RATING_ANALYST_PRIMARY_ID,
    make_advisor_headers,
    make_bond_counsel_headers,
    make_compliance_headers,
    make_headers,
    make_issuer_official_headers,
    make_rating_analyst_headers,
    make_underwriter_headers,
)
from .types import UserRole

__all__ = [
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "ApiClient",
    "api_client",
    "PREFIX",
    "API_PREFIX",
    "CLOCK_EPOCH",
    "ERROR_HTTP_STATUS",
    "UserRole",
    "BOND_COUNSEL_DRAFTER_HEADERS",
    "BOND_COUNSEL_DRAFTER_ID",
    "BOND_COUNSEL_REVIEWER_HEADERS",
    "BOND_COUNSEL_REVIEWER_ID",
    "COMPLIANCE_HEADERS",
    "COMPLIANCE_OFFICER_ID",
    "RATING_ANALYST_HEADERS",
    "RATING_ANALYST_OTHER_HEADERS",
    "RATING_ANALYST_OTHER_ID",
    "RATING_ANALYST_PRIMARY_ID",
    "make_advisor_headers",
    "make_bond_counsel_headers",
    "make_compliance_headers",
    "make_headers",
    "make_issuer_official_headers",
    "make_rating_analyst_headers",
    "make_underwriter_headers",
]
