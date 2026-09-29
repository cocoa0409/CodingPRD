"""Test infrastructure for the crime-laboratory case-management API.

Re-exports the client, the error catalogue, the payload factories, the domain
assertions, the caller identities and the shared constants so a test module can
import everything it needs from one place.
"""

from .api_client import LabApiClient, OMIT, canonical_instant
from .api_errors import ERROR_HTTP_STATUS, NOT_FOUND_BY_ENTITY
from . import api_errors
from . import assertions
from . import constants
from . import factories
from . import test_users

__all__ = [
    "LabApiClient",
    "OMIT",
    "canonical_instant",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_BY_ENTITY",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "test_users",
]
