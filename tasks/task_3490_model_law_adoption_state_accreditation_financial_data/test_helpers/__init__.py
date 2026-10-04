"""Barrel export: framework generics plus the PRD-specific helper layer.

Import discipline around the client: the ``api_client`` NAME in this package
always stays bound to the ``test_helpers.api_client`` SUBMODULE, never to an
instance — so ``import test_helpers.api_client as ac`` keeps working and the
module itself is callable like a client (``ac.create_state(...)`` delegates to a
shared instance). To grab the shared instance or class explicitly, use
``get_default_client()`` / ``ApiClient`` / ``create_api_client()``.
"""

# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

# PRD-specific submodules (bound as modules; api_client is NOT shadowed by an
# instance — its module doubles as the shared client via its __getattr__).
from . import api_client, api_errors, assertions, constants, factories, fixtures, test_users, types  # noqa: F401

from .api_client import ApiClient, create_api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES, PATH_ID_NOT_FOUND_CODES
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import Bundle  # noqa: F401
from .test_users import (
    SECOND_LEAD_HEADERS,
    TEST_USERS,
    THIRD_LEAD_HEADERS,
    headers_for_role,
    headers_with_unknown_role,
    headers_without_identity,
    make_actuary_headers,
    make_association_staff_headers,
    make_insurer_user_headers,
    make_producer_user_headers,
    make_review_team_lead_headers,
    make_state_regulator_headers,
)
from .fixtures import (  # noqa: F401
    add_response,
    advance_clock,
    cast_ballot,
    cast_ballots,
    certify_adoption,
    close_call,
    close_exposure_draft,
    create_act_in_balloting,
    create_active_standard,
    create_adopted_act,
    create_adoption,
    create_call,
    create_filing,
    create_insurer,
    create_license,
    create_model_act,
    create_producer,
    create_published_act,
    create_review,
    create_state,
    create_states,
    create_validated_filing,
    drive_state_to,
    finalize_review,
    insurer_version,
    issue_findings,
    issue_license,
    list_rbc_reports,
    list_responses,
    move_act_to_balloting,
    next_review_period,
    open_exposure_draft,
    read_insurer,
    read_model_act,
    read_producer,
    read_state,
    revoke_license,
    run_review,
    setup_call_with_responses,
    setup_certified_adoption,
    setup_filing_ready,
    setup_issued_license,
    setup_publish_cascade_ready,
    setup_validated_filing,
    state_version,
    submit_filing,
    validate_filing,
)


def get_default_client() -> ApiClient:
    """The shared client instance (same object the api_client module delegates to)."""
    return api_client.api_client
