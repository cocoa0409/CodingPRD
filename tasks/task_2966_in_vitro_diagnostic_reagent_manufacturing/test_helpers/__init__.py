"""Shared test infrastructure for the IVD reagent manufacturing API.

Submodules:
    ``types``       — role and enumeration symbols, plus resource shapes.
    ``api_errors``  — the error identifier catalogue and its HTTP status map.
    ``constants``   — numeric thresholds, defaults and clock/instant helpers.
    ``api_client``  — one client method per endpoint.
    ``test_users``  — pre-built role headers with distinct operator identities.
    ``factories``   — payload builders, input fields only.
    ``assertions``  — resource-shape assertions and invariant checkers.
    ``fixtures``    — composite setup chains built from documented endpoints.

At the top level, ``api_client`` is the shared client **instance** the conftest
hands to every test.
"""
from . import api_errors, assertions, constants, factories, fixtures
from . import test_users, types
from .api_client import ApiClient
from .api_client import api_client as api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import TEST_USERS

__all__ = [
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
]
