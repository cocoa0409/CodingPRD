"""
Test infrastructure for the Design System Governance API.

Modules:
- constants:   role names, enum members, weights and thresholds from the PRD
- api_errors:  the error catalogue and its HTTP status mapping
- types:       payload and row type aliases
- test_users:  identity header builders for the five roles
- api_client:  one method per endpoint, plus instant canonicalisation
- factories:   request-payload builders
- assertions:  domain assertions over already-unwrapped rows
- fixtures:    composite scenario builders that assemble preconditions
"""

from . import api_errors  # noqa: F401  - registers the error status map on import
