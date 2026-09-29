"""Test infrastructure for the rheumatology biologic-therapy coordination API.

Modules:
  * `types`      — the PRD's enumerations and resource shapes.
  * `api_errors` — the error catalogue and its HTTP status map.
  * `constants`  — thresholds, canonical reference data and instant helpers.
  * `api_client` — one method per endpoint in §4.
  * `test_users` — role headers and per-entity header builders.
  * `factories`  — payload builders for every write operation.
  * `assertions` — envelope, entity and conserved-ledger assertions.
  * `fixtures`   — phased composite setup helpers.
"""
from . import assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .test_users import TEST_USERS  # noqa: F401

__all__ = [
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    "TEST_USERS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
]
