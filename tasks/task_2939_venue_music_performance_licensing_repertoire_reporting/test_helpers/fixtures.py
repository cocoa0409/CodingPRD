"""
Pytest fixtures and composite setup builders.

Every test runs against a server whose state has been wiped, so **nothing is
seeded**: each test creates, through the API's own declared endpoints, every
society, schedule, venue, application, licence, report and case it needs.  The
``given_*`` builders below are that creation work, factored out so a test body
reads as the one thing it is actually about.

Each builder returns the row it created (already unwrapped from the envelope),
so a caller can read an ``id`` or a ``version`` straight off it.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import LicensingApiClient
from .assertions import read_rows
from .constants import (
    APPLICATION_STATUS_APPROVED,
    AUDIT_TRIGGER_ROUTINE,
    CLOCK_START_INSTANT,
    DISPOSITION_ACCEPT_FOR_REVIEW,
    DISPOSITION_APPROVE,
)
from .factories import (
    approve_payload,
    audit_case_payload,
    bar_grill_venue_payload,
    bmi_payload,
    clock_payload,
    coverage_window_payload,
    matching_application_payload,
    performance_report_payload,
    rate_schedule_payload,
    repertoire_work_payload,
    review_payload,
    setlist_entry_payload,
)
from .test_users import (
    admin_headers,
    auditor_headers,
    venue_operator_headers,
)

Row = Dict[str, Any]


@pytest.fixture
def api() -> LicensingApiClient:
    """A client pointed at the server under test for this one test."""
    return LicensingApiClient()


# ─── The logical clock (PRD §2.4) ─────────────────────────────────────────


def move_clock(api: LicensingApiClient, instant: str) -> None:
    """Replace the server-held logical clock instant.

    Moving the clock "writes no row and mutates no state on its own"; a test
    that wants a term to expire or a schedule to become selectable must still
    make the corresponding business call afterwards.
    """
    get_success_data(api.set_clock(clock_payload(instant)))


def reset_clock(api: LicensingApiClient) -> None:
    """Return the logical clock to its start-up instant."""
    move_clock(api, CLOCK_START_INSTANT)


# ─── Societies and repertoire ─────────────────────────────────────────────


def given_society(api: LicensingApiClient, payload: Optional[Row] = None) -> Row:
    """Register one performing-rights society; defaults to BMI at 4600 bp."""
    body = payload if payload is not None else bmi_payload()
    return get_success_data(api.create_society(body, admin_headers()))


def given_societies(api: LicensingApiClient, *payloads: Row) -> List[Row]:
    """Register several societies in the order given."""
    return [given_society(api, payload) for payload in payloads]


def given_work(
    api: LicensingApiClient,
    society_id: str,
    title: str,
    writer_name: str,
    iswc: Optional[str] = None,
) -> Row:
    """Register one repertoire work against one society."""
    return get_success_data(
        api.create_repertoire_work(
            repertoire_work_payload(society_id, title, writer_name, iswc),
            admin_headers(),
        )
    )


# ─── Rate schedules ───────────────────────────────────────────────────────


def given_draft_schedule(
    api: LicensingApiClient,
    society_id: str,
    venue_category: str,
    effective_from: str = "2026-01-01T00:00:00Z",
    **overrides: Any,
) -> Row:
    """Create a rate schedule and leave it in DRAFT."""
    return get_success_data(
        api.create_rate_schedule(
            rate_schedule_payload(
                society_id, venue_category, effective_from, **overrides
            ),
            admin_headers(),
        )
    )


def given_effective_schedule(
    api: LicensingApiClient,
    society_id: str,
    venue_category: str,
    effective_from: str = "2026-01-01T00:00:00Z",
    **overrides: Any,
) -> Row:
    """Create a rate schedule and publish it so selection can reach it."""
    draft = given_draft_schedule(
        api, society_id, venue_category, effective_from, **overrides
    )
    return get_success_data(api.publish_rate_schedule(draft["id"], admin_headers()))


# ─── Venues ───────────────────────────────────────────────────────────────


def given_venue(api: LicensingApiClient, payload: Optional[Row] = None) -> Row:
    """Create one venue; defaults to the 180-occupancy MIXED bar and grill."""
    body = payload if payload is not None else bar_grill_venue_payload()
    return get_success_data(api.create_venue(body, admin_headers()))


def venue_row(api: LicensingApiClient, venue_id: str) -> Row:
    """Re-read one venue, for the ledger and coverage roll-ups it carries."""
    return validate_success(api.get_venue(venue_id, admin_headers()))


# ─── Applications ─────────────────────────────────────────────────────────


def given_draft_application(
    api: LicensingApiClient,
    venue: Row,
    society_id: str,
    requested_term_start: str = "2026-09-01T00:00:00Z",
    payload: Optional[Row] = None,
    **overrides: Any,
) -> Row:
    """File an application as the venue's own operator, leaving it in DRAFT.

    ``expected_venue_version`` is read off the venue row handed in, so a caller
    that has just mutated the venue must re-read it first.
    """
    body = (
        payload
        if payload is not None
        else matching_application_payload(
            venue, society_id, requested_term_start, **overrides
        )
    )
    return get_success_data(
        api.create_application(body, venue_operator_headers(venue["id"]))
    )


def given_submitted_application(
    api: LicensingApiClient,
    venue: Row,
    society_id: str,
    requested_term_start: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Row:
    """File an application and submit it, leaving it in SUBMITTED."""
    application = given_draft_application(
        api, venue, society_id, requested_term_start, **overrides
    )
    return get_success_data(
        api.submit_application(
            application["id"], venue_operator_headers(venue["id"])
        )
    )


def accept_for_review(api: LicensingApiClient, application_id: str) -> Row:
    """Take a submitted application into UNDER_REVIEW."""
    return get_success_data(
        api.review_application(
            application_id,
            review_payload(DISPOSITION_ACCEPT_FOR_REVIEW),
            admin_headers(),
        )
    )


def approve(api: LicensingApiClient, application_id: str) -> Row:
    """Approve an application under review, minting its licence."""
    return get_success_data(
        api.review_application(application_id, approve_payload(), admin_headers())
    )


def given_approved_application(
    api: LicensingApiClient,
    venue: Row,
    society_id: str,
    requested_term_start: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Row:
    """Drive one application all the way from DRAFT to APPROVED."""
    application = given_submitted_application(
        api, venue, society_id, requested_term_start, **overrides
    )
    accept_for_review(api, application["id"])
    approved = approve(api, application["id"])
    assert approved["status"] == APPLICATION_STATUS_APPROVED, (
        f"expected an APPROVED application, got {approved['status']!r}"
    )
    return approved


def application_row(api: LicensingApiClient, application_id: str) -> Row:
    """Re-read one application."""
    return validate_success(api.get_application(application_id, admin_headers()))


# ─── Licences ─────────────────────────────────────────────────────────────


def license_of_application(api: LicensingApiClient, application_id: str) -> Row:
    """The single licence an approval minted for one application.

    Approval does not return the licence, so it is found by filtering the
    licence list on ``application_id``; asserting there is exactly one row is
    part of the contract being checked.
    """
    rows = read_rows(
        api.list_licenses(admin_headers(), {"application_id": application_id}),
        expected_total=1,
    )
    return rows[0]


def license_row(api: LicensingApiClient, license_id: str) -> Row:
    """Re-read one licence, for its two independent state dimensions."""
    return validate_success(api.get_license(license_id, admin_headers()))


def activate(api: LicensingApiClient, license_id: str) -> Row:
    """Activate a licence, fixing its verified fee and billing it."""
    return get_success_data(api.activate_license(license_id, admin_headers()))


def given_active_license(
    api: LicensingApiClient,
    venue: Row,
    society_id: str,
    requested_term_start: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Row:
    """Drive one venue and society pair to a single ACTIVE licence."""
    application = given_approved_application(
        api, venue, society_id, requested_term_start, **overrides
    )
    minted = license_of_application(api, application["id"])
    return activate(api, minted["id"])


def given_licensed_venue(
    api: LicensingApiClient,
    venue_payload_row: Optional[Row] = None,
    society_payload_row: Optional[Row] = None,
    venue_category: str = "BAR_GRILL",
    requested_term_start: str = "2026-09-01T00:00:00Z",
    schedule_effective_from: str = "2026-01-01T00:00:00Z",
    **schedule_overrides: Any,
) -> Dict[str, Row]:
    """The whole happy path in one call: society, schedule, venue, ACTIVE licence.

    Returns a dict of the four rows under the keys ``society``, ``schedule``,
    ``venue`` and ``license``, plus the freshly re-read ``venue`` so its ledger
    already reflects the initial assessment.
    """
    society = given_society(api, society_payload_row)
    schedule = given_effective_schedule(
        api,
        society["id"],
        venue_category,
        schedule_effective_from,
        **schedule_overrides
    )
    venue = given_venue(api, venue_payload_row)
    licence = given_active_license(
        api, venue, society["id"], requested_term_start
    )
    return {
        "society": society,
        "schedule": schedule,
        "venue": venue_row(api, venue["id"]),
        "created_venue": venue,
        "license": licence,
    }


def given_coverage_window(
    api: LicensingApiClient,
    license_id: str,
    window_start: str,
    window_end: str,
    window_kind: str,
    headers: Optional[Dict[str, str]] = None,
) -> Row:
    """Add one rider coverage window to an active licence."""
    return get_success_data(
        api.create_coverage_window(
            license_id,
            coverage_window_payload(window_start, window_end, window_kind),
            headers if headers is not None else admin_headers(),
        )
    )


# ─── Reports and setlists ─────────────────────────────────────────────────


def given_draft_report(
    api: LicensingApiClient,
    license_id: str,
    venue_id: str,
    period_start: str = "2026-09-01T00:00:00Z",
    period_end: str = "2026-10-01T00:00:00Z",
) -> Row:
    """Open a DRAFT performance report over one reporting period."""
    return get_success_data(
        api.create_performance_report(
            performance_report_payload(license_id, period_start, period_end),
            venue_operator_headers(venue_id),
        )
    )


def given_setlist_entry(
    api: LicensingApiClient,
    report_id: str,
    venue_id: str,
    title: str,
    writer: str,
    affiliation: str,
    when: str,
    seconds: int,
    use_type: str = "LIVE",
) -> Row:
    """Append one performance to a draft report's setlist."""
    return get_success_data(
        api.create_setlist_entry(
            report_id,
            setlist_entry_payload(title, writer, affiliation, when, seconds, use_type),
            venue_operator_headers(venue_id),
        )
    )


def given_setlist(
    api: LicensingApiClient,
    report_id: str,
    venue_id: str,
    entries: Sequence[Dict[str, Any]],
) -> List[Row]:
    """Append a whole setlist, in the order given, to a draft report."""
    created: List[Row] = []
    for entry in entries:
        created.append(
            given_setlist_entry(
                api,
                report_id,
                venue_id,
                entry["title"],
                entry["writer"],
                entry["affiliation"],
                entry["when"],
                entry["seconds"],
                entry.get("use_type", "LIVE"),
            )
        )
    return created


def report_row(api: LicensingApiClient, report_id: str) -> Row:
    """Re-read one performance report and its computed gap figures."""
    return validate_success(api.get_performance_report(report_id, admin_headers()))


def setlist_entries_of(api: LicensingApiClient, report_id: str) -> List[Row]:
    """Every setlist entry of one report, oldest first."""
    return read_rows(api.list_report_setlist_entries(report_id, admin_headers()))


# ─── Audit cases and assessments ──────────────────────────────────────────


def given_open_case(
    api: LicensingApiClient,
    venue_id: str,
    society_ids: Sequence[str],
    lookback_start: str = "2025-01-01T00:00:00Z",
    lookback_end: str = "2026-07-01T00:00:00Z",
    audit_trigger: str = AUDIT_TRIGGER_ROUTINE,
    user_id: Optional[str] = None,
) -> Row:
    """Open an audit case over a lookback interval against a set of societies."""
    headers = auditor_headers() if user_id is None else auditor_headers(user_id)
    return get_success_data(
        api.create_audit_case(
            audit_case_payload(
                venue_id, audit_trigger, lookback_start, lookback_end, society_ids
            ),
            headers,
        )
    )


def case_row(api: LicensingApiClient, audit_case_id: str) -> Row:
    """Re-read one audit case and its whole exposure waterfall."""
    return validate_success(api.get_audit_case(audit_case_id, admin_headers()))


def assessments_of_license(api: LicensingApiClient, license_id: str) -> List[Row]:
    """Every fee assessment raised against one licence, oldest first."""
    return read_rows(
        api.list_fee_assessments(admin_headers(), {"license_id": license_id})
    )


def assessments_of_case(api: LicensingApiClient, audit_case_id: str) -> List[Row]:
    """Every fee assessment raised against one audit case, oldest first."""
    return read_rows(
        api.list_fee_assessments(admin_headers(), {"audit_case_id": audit_case_id})
    )


def assessments_of_venue(api: LicensingApiClient, venue_id: str) -> List[Row]:
    """Every fee assessment on one venue's ledger, oldest first."""
    return read_rows(
        api.list_fee_assessments(admin_headers(), {"venue_id": venue_id})
    )


def assessment_row(api: LicensingApiClient, assessment_id: str) -> Row:
    """Re-read one fee assessment."""
    return validate_success(
        api.get_fee_assessment(assessment_id, admin_headers())
    )


def cases_of_venue(api: LicensingApiClient, venue_id: str) -> List[Row]:
    """Every audit case opened on one venue, oldest first."""
    return read_rows(api.list_audit_cases(admin_headers(), {"venue_id": venue_id}))


def windows_of_license(api: LicensingApiClient, license_id: str) -> List[Row]:
    """Every coverage window of one licence, oldest first."""
    return read_rows(api.list_license_coverage_windows(license_id, admin_headers()))


APPROVE_DISPOSITION = DISPOSITION_APPROVE
