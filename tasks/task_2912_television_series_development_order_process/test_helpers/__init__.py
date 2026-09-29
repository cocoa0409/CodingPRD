"""Test infrastructure for the television series development order process API.

Re-exports the framework primitives alongside this domain's client, error catalogue,
constants, payload factories, assertions, identity builders and composite fixtures so
a test module needs a single import.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import assertions, constants, factories, fixtures
from .api_client import ApiClient, canonical_instant
from .api_errors import ERROR_HTTP_STATUS
from .types import PIPELINE_STAGES, Headers, JsonDict, ScenarioContext

__all__ = [
    # Framework primitives
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # Domain infrastructure
    "ApiClient",
    "canonical_instant",
    "ERROR_HTTP_STATUS",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "ScenarioContext",
    "PIPELINE_STAGES",
    "Headers",
    "JsonDict",
]
