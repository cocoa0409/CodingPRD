"""Barrel export: framework generics + PRD-specific infrastructure.

Regional News Operations API (regional-news-ops) test helpers.
Everything a test module needs is re-exported from here.
"""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .api_client import api_client, ApiClient
from .constants import *
from .factories import *
from .assertions import *
from .test_users import TEST_USERS, make_subscriber_headers
from .fixtures import *
from .fixtures_market import *
from .fixtures_delivery import *
from .fixtures_edition import *
from .fixtures_subscriber import *
from .fixtures_newsroom import *
from .fixtures_scenarios import *

# ─── Convenience aliases ─────────────────────────────────────────────
# Tests address the client as `api` and read rows by their PRD entity names.
api = api_client
get_print_market = get_market
get_print_route = get_route
get_print_site = get_site


def create_print_site_response(hub_id, **overrides):
    """Create a print site and return the raw Response (for error paths)."""
    from .factories import create_print_site_payload
    return api_client.create_print_site(
        hub_id, create_print_site_payload(**overrides), TEST_USERS["print_ops_headers"])


def create_market_response(region_id, **overrides):
    """Create a print market and return the raw Response (for error paths)."""
    from .factories import create_print_market_payload
    return api_client.create_print_market(
        region_id, create_print_market_payload(**overrides),
        TEST_USERS["print_ops_headers"])