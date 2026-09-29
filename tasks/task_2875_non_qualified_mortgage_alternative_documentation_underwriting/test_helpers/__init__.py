"""Test infrastructure for the non-QM alternative-documentation underwriting API.

Importing this package registers the PRD 5 error-to-HTTP-status map with the
framework validators, so ``validate_error`` checks the status code as well as the
error identifier.

Envelope contract (single decision for the whole suite): ``validate_success`` and
``get_success_data`` return the INNER ``data`` payload. Nothing indexes
``["data"]`` a second time.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
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

from . import api_errors, assertions, constants, factories, fixtures  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS, RULE_LADDER  # noqa: F401
from .assertions import (  # noqa: F401
    as_decimal,
    assert_codes_in_order,
    assert_common_fields,
    assert_created_at_ascending,
    assert_created_row,
    assert_decimal_equals,
    assert_fields,
    assert_ids_equal,
    assert_instant_equals,
    assert_is_null,
    assert_meta_pagination,
    assert_money,
    assert_pct_2dp,
    assert_pct_3dp,
    assert_ratio_4dp,
    assert_version,
    ids_of,
    quantize,
)
from .constants import (  # noqa: F401
    ALL_ROLES,
    DEFAULT_CLOCK_UTC,
    DEFAULT_INVESTOR_CODE,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
    ROLE_APPRAISAL_REVIEWER,
    ROLE_CHIEF_CREDIT_OFFICER,
    ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_OFFICER,
    ROLE_POST_CLOSE_AUDITOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SECURITIZATION_ANALYST,
    ROLE_UNDERWRITER,
    SEASONING_MATRIX,
)
from .test_users import (  # noqa: F401
    ADMIN,
    APPRAISAL_REVIEWER,
    CHIEF_CREDIT_OFFICER,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    TEST_USERS,
    UNDERWRITER,
    appraisal_reviewer,
    chief_credit_officer,
    credit_committee,
    headers_for,
    headers_with_blank_role,
    headers_with_blank_user,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user,
    loan_officer,
    post_close_auditor,
    program_admin,
    securitization_analyst,
    underwriter,
)
