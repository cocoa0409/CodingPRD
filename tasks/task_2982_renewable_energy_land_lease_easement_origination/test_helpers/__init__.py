"""
Test infrastructure for the Renewable Land Origination API.

Importing this package registers the error-catalogue HTTP status map with the
generic validators, so any module that touches the helpers gets status
cross-checking on every rejection assertion for free.
"""

from . import api_errors  # noqa: F401  (import registers the status map)
from .api_client import LandOriginationApiClient
from .assertions import (
    as_cents,
    as_decimal2,
    assert_acres_equals,
    assert_cents_equals,
    assert_common_fields,
    assert_contains_id,
    assert_ascending_by_created_at,
    assert_excludes_id,
    assert_id_set,
    assert_ids_equal,
    assert_instant_equals,
    assert_is_date,
    assert_is_instant,
    assert_ledger_row_shape,
    assert_lease_dimensions,
    assert_null,
    assert_page_meta,
    assert_rate_equals,
    assert_score_equals,
    assert_status,
    assert_unchanged,
    assert_version_advanced,
    assert_version_is,
    normalize_instant,
)

__all__ = [
    "LandOriginationApiClient",
    "api_errors",
    "as_cents",
    "as_decimal2",
    "assert_acres_equals",
    "assert_cents_equals",
    "assert_common_fields",
    "assert_contains_id",
    "assert_ascending_by_created_at",
    "assert_excludes_id",
    "assert_id_set",
    "assert_ids_equal",
    "assert_instant_equals",
    "assert_is_date",
    "assert_is_instant",
    "assert_ledger_row_shape",
    "assert_lease_dimensions",
    "assert_null",
    "assert_page_meta",
    "assert_rate_equals",
    "assert_score_equals",
    "assert_status",
    "assert_unchanged",
    "assert_version_advanced",
    "assert_version_is",
    "normalize_instant",
]
