"""
Test infrastructure for the HVAC Filter Subscription & Resident Benefit
Package API.

Modules:
  constants   — roles, enum members, clock default, policy numbers
  types       — TypedDict shapes for every entity
  api_errors  — the error catalog and its HTTP status mapping
  api_client  — one method per endpoint
  assertions  — domain assertion helpers
  test_users  — role identities and the entity-backed header builders
  factories   — request payload factories
  fixtures    — composite setup builders
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

from .api_client import ApiClient  # noqa: F401
