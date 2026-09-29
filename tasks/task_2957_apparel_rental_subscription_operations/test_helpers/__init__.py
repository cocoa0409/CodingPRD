"""Test infrastructure for the Apparel Rental Subscription Operations API suite.

Importing this package registers the error-identifier to HTTP-status contract
with the shared validators, so ``validate_error`` cross-checks statuses for
every test in the suite.
"""

from test_helpers import api_errors  # noqa: F401  (registers the status map)

__all__ = [
    "api_client",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
