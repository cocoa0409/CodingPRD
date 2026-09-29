"""Test infrastructure for the Public Safety Radio Interoperability API.

Importing this package registers the PRD Section 5 error/HTTP-status map with
the runner's validators, so `validate_error(response, ERR_X)` checks the status
code without every call site restating it.
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from .api_client import ApiClient, canonical_instant, instants_equal

__all__ = ["ApiClient", "canonical_instant", "instants_equal", "api_errors"]
