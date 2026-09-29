"""Test infrastructure for the reverse-logistics returns-processing center API.

Importing this package registers the error_id -> HTTP status mapping with the
framework validators.
"""

from . import api_errors, constants, factories, fixtures, test_users  # noqa: F401
from .api_client import ApiClient  # noqa: F401

__all__ = [
    "ApiClient",
    "api_errors",
    "constants",
    "factories",
    "fixtures",
    "test_users",
]
