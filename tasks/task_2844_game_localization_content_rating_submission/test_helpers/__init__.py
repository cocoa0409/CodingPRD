"""Shared test infrastructure for the Game Localization & Rating Submission API.

Modules:
    ``constants``   — enum value sets, reference tables and arithmetic literals
    ``api_errors``  — error codes and their HTTP statuses
    ``test_users``  — request headers for each role, including the talent agents
    ``types``       — typed response shapes for the twelve resources
    ``api_client``  — one method per endpoint
    ``assertions``  — domain assertions and derived-arithmetic mirrors
    ``factories``   — request payload builders
    ``fixtures``    — composite scenario builders and pytest fixtures
"""

from . import (  # noqa: F401
    api_client,
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    test_users,
    types,
)

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
