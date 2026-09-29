"""Test infrastructure for the public access television studio operations API.

Importing this package registers the PRD's error-identifier-to-HTTP-status map
with the shared response validators, so ``validate_error`` can check the status
of every refusal without each test restating it.
"""

from . import api_errors  # noqa: F401  (imported for its status-map registration)
from .api_client import StudioApiClient
from .test_users import (
    ADMIN_HEADERS,
    ADMIN2_HEADERS,
    FACILITIES_HEADERS,
    FACILITIES2_HEADERS,
    FINANCE_HEADERS,
    FINANCE2_HEADERS,
    REVIEWER_HEADERS,
    REVIEWER2_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    make_producer_headers,
)

__all__ = [
    "StudioApiClient",
    "ADMIN_HEADERS",
    "ADMIN2_HEADERS",
    "FACILITIES_HEADERS",
    "FACILITIES2_HEADERS",
    "FINANCE_HEADERS",
    "FINANCE2_HEADERS",
    "REVIEWER_HEADERS",
    "REVIEWER2_HEADERS",
    "SCHEDULER_HEADERS",
    "TRAINER_HEADERS",
    "make_producer_headers",
]
