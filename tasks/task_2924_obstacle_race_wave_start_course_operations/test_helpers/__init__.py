"""Shared test infrastructure for the Obstacle Course Race Operations API.

Importing this package registers the PRD §5 error-id → HTTP-status map with the
framework's validators, so `validate_error` can cross-check the status of every
refusal without each test naming it.
"""

from . import api_errors  # noqa: F401  (import registers the status map)

__all__ = ["api_errors"]
