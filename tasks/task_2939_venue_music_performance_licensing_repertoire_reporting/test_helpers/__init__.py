"""
Shared test infrastructure for the Venue Music Licensing API.

Importing this package registers the error-id-to-HTTP-status catalogue with the
shared response validators, so ``validate_error`` cross-checks statuses without
any further setup.

The three envelope contracts every test relies on:

* ``validate_success(response)`` returns the envelope's ``data`` — it unwraps
  exactly once, so never index ``["data"]`` on its result.
* ``validate_paginated(response)`` takes only the response and returns
  ``(rows, meta)``; ``read_rows`` and ``read_page`` wrap it with a
  ``total_count`` check.
* Instants are compared through ``assert_instant_equals`` / ``canonical_instant``
  and never as raw strings.
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

from .api_client import LicensingApiClient
from .api_errors import *  # noqa: F401,F403
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_assessment,
    assert_bp,
    assert_count,
    assert_coverage,
    assert_date_equals,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_instant_in,
    assert_is_instant,
    assert_ledger_identity,
    assert_license_dimensions,
    assert_money,
    assert_not_money,
    assert_not_pct,
    assert_pct,
    assert_immutable_row,
    assert_venue_ledger,
    assert_version,
    assert_version_advanced,
    assert_version_unchanged,
    assert_versioned_row,
    canonical_instant,
    find_row,
    ids_of,
    read_page,
    read_rows,
    rows_matching,
    validate_unpaginated_list,
)
from .constants import *  # noqa: F401,F403
from .factories import (
    application_payload,
    approve_payload,
    ascap_payload,
    audit_case_payload,
    bar_grill_venue_payload,
    bgm_survey_fields,
    bmi_payload,
    clock_payload,
    close_case_payload,
    concert_hall_venue_payload,
    coverage_window_payload,
    fitness_studio_venue_payload,
    gmr_payload,
    matching_application_payload,
    mid_concert_hall_venue_payload,
    payment_payload,
    performance_report_payload,
    rate_schedule_payload,
    renew_payload,
    repertoire_work_payload,
    report_review_payload,
    review_payload,
    sesac_payload,
    setlist_entry_payload,
    setlist_family,
    settlement_offer_payload,
    society_payload,
    suspend_payload,
    terminate_payload,
    venue_payload,
)
from .fixtures import (
    accept_for_review,
    activate,
    api,
    application_row,
    approve,
    assessment_row,
    assessments_of_case,
    assessments_of_license,
    assessments_of_venue,
    case_row,
    cases_of_venue,
    given_active_license,
    given_approved_application,
    given_coverage_window,
    given_draft_application,
    given_draft_report,
    given_draft_schedule,
    given_effective_schedule,
    given_licensed_venue,
    given_open_case,
    given_setlist,
    given_setlist_entry,
    given_societies,
    given_society,
    given_submitted_application,
    given_venue,
    given_work,
    license_of_application,
    license_row,
    move_clock,
    report_row,
    reset_clock,
    setlist_entries_of,
    venue_row,
    windows_of_license,
)
from .test_users import (
    ADMIN_USER_ID,
    ADMIN_USER_ID_ALT,
    AUDITOR_USER_ID,
    AUDITOR_USER_ID_ALT,
    SETTLEMENT_USER_ID,
    SETTLEMENT_USER_ID_ALT,
    admin_headers,
    auditor_headers,
    headers_empty_role,
    headers_empty_user_id,
    headers_missing_role,
    headers_missing_user_id,
    headers_none,
    headers_unknown_role,
    headers_with_role,
    settlement_headers,
    venue_operator_headers,
)
from .types import (
    AuditCase,
    CoverageWindow,
    FeeAssessment,
    License,
    LicenseApplication,
    PerformanceReport,
    RateSchedule,
    RepertoireWork,
    Row,
    SetlistEntry,
    Society,
    Venue,
)
