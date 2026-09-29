"""Test infrastructure for the Residential Solar Portfolio Servicing API.

Importing this package registers the error identifier to HTTP status mapping of
PRD §5 with the framework validators, so ``validate_error`` cross-checks status
codes without every test restating them.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from . import assertions, constants, factories, test_users, types  # noqa: F401
from .api_client import ApiClient  # noqa: F401

__all__ = [
    "ApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "test_users",
    "types",
]
