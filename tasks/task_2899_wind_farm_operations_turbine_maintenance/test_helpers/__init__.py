"""Test infrastructure for the wind farm operations and turbine maintenance API.

Importing this package registers the domain's error identifier to HTTP status
mapping with the shared envelope validators.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import WindOpsApiClient

__all__ = [
    "WindOpsApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
