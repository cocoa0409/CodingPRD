"""
Test infrastructure for the Institutional Research and Federal Data Reporting API.

The package is layered so a test file can import exactly what it needs:

    constants   literal values the contract declares: roles, postures, metric keys,
                calendar anchors, thresholds and tolerance constants
    api_errors  the error identifier catalogue with its HTTP status map, registered
                with the framework's validator on import
    types       response shapes, including the definition row that carries neither
                updated_at nor version
    test_users  one distinct opaque operator identifier per role, plus the shared
                actor used to probe segregation of duties, and the header builders
    api_client  one named method per published endpoint, plus canonical_instant
    factories   request payload builders with the declared field types
    assertions  domain assertions: rounding, ledgers, conservation, ordering
    fixtures    five composable tiers of scenario setup
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import OMIT, ApiClient, canonical_instant
from .api_errors import (
    DUPLICATE_ERROR_IDS,
    HTTP_STATUS_CODES,
    NOT_FOUND_ERROR_IDS,
    ApiErrorId,
)
from .assertions import (
    assert_calendar_date,
    assert_cell,
    assert_cohort_conservation,
    assert_cohort_counts,
    assert_common_fields,
    assert_component_status,
    assert_controlled_rounding,
    assert_cycle_ledger,
    assert_cycle_posture,
    assert_divergence_is_difference_of_published_variants,
    assert_edit_check,
    assert_equals_number,
    assert_error_body_leaks_nothing,
    assert_immutable_definition_shape,
    assert_instant_before,
    assert_instant_equals,
    assert_instant_stamped,
    assert_integer_count,
    assert_json_number,
    assert_ledger_invariant,
    assert_metric_keys_ascending,
    assert_null,
    assert_one_decimal,
    assert_ordered_by,
    assert_publication_ledger,
    assert_rate_variants,
    assert_reconciliation,
    assert_reconciliation_fields_all_null,
    assert_request_counters,
    assert_restatement,
    assert_sequence_numbers_ascending,
    assert_two_decimals,
    assert_version,
    assert_version_bumped,
    cells_by_key,
    ids_of,
    round_half_up,
    rows_by_id,
)
from .test_users import (
    ANALYST_USER_ID,
    DIRECTOR_USER_ID,
    DISCLOSURE_USER_ID,
    REGISTRAR_USER_ID,
    SHARED_ACTOR_ID,
    STEWARD_USER_ID,
    headers_for_role,
    make_analyst_headers,
    make_director_headers,
    make_disclosure_headers,
    make_headers_missing_role,
    make_headers_missing_user_id,
    make_headers_unknown_role,
    make_headers_without_auth,
    make_registrar_headers,
    make_steward_headers,
)
