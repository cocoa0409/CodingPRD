"""
Departure-state guards on the licensing lifecycles.

This file pins where each lifecycle begins and what happens when a caller asks
for a transition the addressed row may not depart from: the states an
application and its minted licence open in, a second publication of a schedule
that is already effective, a submission against an approved application, a
second activation of a licence that is already covering the venue, any further
move on a terminated licence, findings on an audit case that was closed with no
action, and the one acceptance that legitimately advances a licence's accepted
report count.
"""

from test_helpers import (
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_DRAFT,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    BILLING_WRITTEN_OFF,
    CASE_STATUS_CLOSED_NO_ACTION,
    CLOSED_REASON_NO_GAP_FOUND,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    COVERAGE_TERMINATED,
    ERR_APPLICATION_STATE_INVALID,
    ERR_AUDIT_CASE_STATE_INVALID,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_LICENSE_STATE_INVALID,
    ERR_RATE_SCHEDULE_NOT_DRAFT,
    ERR_REPORT_STATE_INVALID,
    REPORT_DISPOSITION_ACCEPT,
    REPORT_STATUS_ACCEPTED,
    SCHEDULE_STATUS_EFFECTIVE,
    SCHEDULE_STATUS_SUPERSEDED,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    TERM_LENGTH_DAYS,
    USE_TYPE_LIVE,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_VOIDED,
    accept_for_review,
    admin_headers,
    application_row,
    approve_payload,
    assert_assessment,
    assert_count,
    assert_days_apart,
    assert_empty_list,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_pct,
    assert_venue_ledger,
    assert_version_advanced,
    assert_version_unchanged,
    assessments_of_license,
    auditor_headers,
    bar_grill_venue_payload,
    bmi_payload,
    case_row,
    close_case_payload,
    coverage_window_payload,
    given_approved_application,
    given_draft_application,
    given_draft_report,
    given_effective_schedule,
    given_licensed_venue,
    given_open_case,
    given_setlist_entry,
    given_society,
    given_venue,
    given_work,
    license_of_application,
    license_row,
    read_page,
    read_rows,
    renew_payload,
    report_review_payload,
    report_row,
    suspend_payload,
    terminate_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
    windows_of_license,
)

_TERM_START = "2026-09-01T00:00:00Z"
_PERIOD_END = "2026-10-01T00:00:00Z"


def test_lifecycle_application_and_license_start_in_declared_initial_states(api):
    """An application is filed in DRAFT with no review history, and the licence
    approval mints opens uncovered and unbilled with both fee-gap counters at
    zero and no successor anywhere.

    PRD §3.4: "A newly filed application is in `DRAFT` `status`, with
    `revision_round` at 0, `return_reason` and `decline_reason` at null, and both
    `assigned_license_type` and `provisional_annual_fee_cents` at null — those
    two are written only at approval."

    PRD §3.7: "And the predecessor's `renewal_issued_at` must still be null,
    otherwise `ERR_LICENSE_ALREADY_RENEWED`; a licence may be renewed once, and
    the successor that already exists is discoverable through its own
    `renewal_of_license_id`."

    Design: Corner/state_machines/corner_application_and_license_start_in_declared_initial_states
    """
    society = given_society(api, bmi_payload())
    given_effective_schedule(api, society["id"], "BAR_GRILL")
    venue = given_venue(api, bar_grill_venue_payload())

    filed = given_draft_application(api, venue, society["id"], _TERM_START)
    assert filed["status"] == APPLICATION_STATUS_DRAFT, (
        f"a newly filed application is DRAFT, got {filed['status']!r}"
    )
    assert_count(filed["revision_round"], 0, "revision_round")
    assert filed["return_reason"] is None, (
        f"a new filing carries no return reason, got {filed['return_reason']!r}"
    )
    assert filed["decline_reason"] is None, (
        f"a new filing carries no decline reason, got {filed['decline_reason']!r}"
    )
    assert filed["assigned_license_type"] is None, (
        "the licence type is assigned only at approval, got "
        f"{filed['assigned_license_type']!r}"
    )
    assert filed["provisional_annual_fee_cents"] is None, (
        "the provisional fee is computed only at approval, got "
        f"{filed['provisional_annual_fee_cents']!r}"
    )

    validate_success(
        api.submit_application(filed["id"], venue_operator_headers(venue["id"]))
    )
    accept_for_review(api, filed["id"])
    approved = validate_success(
        api.review_application(filed["id"], approve_payload(), admin_headers())
    )
    assert approved["status"] == APPLICATION_STATUS_APPROVED

    licence = license_of_application(api, filed["id"])
    assert_license_dimensions(licence, COVERAGE_PENDING_ACTIVATION, BILLING_UNBILLED)
    assert_money(
        licence["verified_fee_delta_cents"], 0, "verified_fee_delta_cents"
    )
    assert_count(licence["accepted_report_count"], 0, "accepted_report_count")
    assert licence["renewal_of_license_id"] is None, (
        f"a first term follows nothing, got {licence['renewal_of_license_id']!r}"
    )
    assert licence["renewal_issued_at"] is None, (
        f"no successor has been issued, got {licence['renewal_issued_at']!r}"
    )
    assert licence["suspension_reason"] is None, (
        f"a pending licence has never been suspended, got {licence['suspension_reason']!r}"
    )

    assert_instant_equals(licence["term_start"], _TERM_START, "term_start")
    assert_days_apart(
        licence["term_start"], licence["term_end"], TERM_LENGTH_DAYS, "annual term"
    )

    read_page(
        api.list_licenses(
            admin_headers(), {"renewal_of_license_id": licence["id"]}
        ),
        expected_total=0,
    )
    assert_empty_list(
        api.list_license_coverage_windows(licence["id"], admin_headers())
    )
    assert_empty_list(
        api.list_fee_assessments(admin_headers(), {"license_id": licence["id"]})
    )


def test_lifecycle_publish_already_effective_schedule_rejected(api):
    """Publication departs from DRAFT only, so publishing an effective schedule
    a second time is refused and leaves the schedule and its version untouched.

    PRD §3.2: "A `LicensingAdmin` publishes a schedule, taking its `status` from
    `DRAFT` to `EFFECTIVE`; the transition requires the schedule to still be in
    `DRAFT` — otherwise the request is rejected with
    `ERR_RATE_SCHEDULE_NOT_DRAFT` — and requires the logical clock instant to
    have reached `effective_from`, meaning `effective_from` is at or before the
    current logical clock instant."

    PRD §2.5: "`version` is an integer that starts at 1 on creation and increases
    by exactly 1 on every mutation of that row — including mutations the row's
    owner never requested, such as a recomputed derived field written by a
    cascade."

    Design: Corner/state_machines/corner_publish_already_effective_schedule_rejected
    """
    society = given_society(api, bmi_payload())
    published = given_effective_schedule(api, society["id"], "BAR_GRILL")
    assert published["status"] == SCHEDULE_STATUS_EFFECTIVE

    validate_error(
        api.publish_rate_schedule(published["id"], admin_headers()),
        ERR_RATE_SCHEDULE_NOT_DRAFT,
    )

    reread = validate_success(
        api.get_rate_schedule(published["id"], admin_headers())
    )
    assert reread["status"] == SCHEDULE_STATUS_EFFECTIVE, (
        f"the schedule must still be EFFECTIVE, got {reread['status']!r}"
    )
    assert_count(
        reread["schedule_version"], published["schedule_version"], "schedule_version"
    )
    assert_version_unchanged(reread, published, "rate schedule")

    assert_empty_list(
        api.list_rate_schedules(
            admin_headers(), {"status": SCHEDULE_STATUS_SUPERSEDED}
        )
    )


def test_lifecycle_submit_approved_application_rejected(api):
    """APPROVED is terminal for an application: submission, revision and
    withdrawal are all refused, and no second licence appears.

    PRD §3.4: "The three terminal states of an application are `APPROVED`,
    `DECLINED` and `WITHDRAWN`."

    PRD §3.4: "A revision attempted against a non-`DRAFT` application is rejected
    with `ERR_APPLICATION_STATE_INVALID`."

    PRD §3.4: "An application may be withdrawn by its operator (or by a
    `LicensingAdmin`) from `DRAFT`, from `SUBMITTED` or from
    `RETURNED_FOR_REVISION`, moving it to the terminal `WITHDRAWN` state with a
    `version` increment."

    Design: Corner/state_machines/corner_submit_approved_application_rejected
    """
    society = given_society(api, bmi_payload())
    given_effective_schedule(api, society["id"], "BAR_GRILL")
    venue = given_venue(api, bar_grill_venue_payload())
    approved = given_approved_application(api, venue, society["id"], _TERM_START)

    validate_error(
        api.submit_application(approved["id"], venue_operator_headers(venue["id"])),
        ERR_APPLICATION_STATE_INVALID,
    )

    after = application_row(api, approved["id"])
    assert after["status"] == APPLICATION_STATUS_APPROVED, (
        f"the application must still be APPROVED, got {after['status']!r}"
    )
    read_page(
        api.list_licenses(admin_headers(), {"application_id": approved["id"]}),
        expected_total=1,
    )

    validate_error(
        api.update_application(
            approved["id"], {"declared_seating": 150}, admin_headers()
        ),
        ERR_APPLICATION_STATE_INVALID,
    )
    validate_error(
        api.withdraw_application(approved["id"], admin_headers()),
        ERR_APPLICATION_STATE_INVALID,
    )

    still_approved = application_row(api, approved["id"])
    assert still_approved["status"] == APPLICATION_STATUS_APPROVED
    assert_version_unchanged(still_approved, after, "license application")


def test_lifecycle_activate_twice_second_call_rejected(api):
    """Activation is not repeatable: the second call on an already-covering
    licence is refused and mints no second annual assessment, no second annual
    window and no further ledger movement.

    PRD §3.6: "A licence created by approval sits in `PENDING_ACTIVATION` and
    covers nothing at all until a `LicensingAdmin` activates it, moving
    `coverage_status` to `ACTIVE`."

    PRD §2.12: "**Departure state.** The addressed row sits in a state the
    requested transition may depart from: a `LicenseApplication` is `DRAFT` for a
    field revision and `DRAFT` or `RETURNED_FOR_REVISION` for submission, and
    `SUBMITTED` or `UNDER_REVIEW` for review; a `RateSchedule` is `DRAFT` for
    publication; a `License` is `PENDING_ACTIVATION` for activation, `ACTIVE` for
    suspension, `SUSPENDED` for reinstatement, `ACTIVE` or `SUSPENDED` for
    termination, and `ACTIVE` or `EXPIRED` for renewal; a `PerformanceReport` is
    `DRAFT` or `REJECTED` for setlist-entry creation, `DRAFT` for submission and
    `SUBMITTED` for review; an `AuditCase` is `OPEN` for findings and for closing,
    `FINDINGS_ISSUED` or `DISPUTED` for a settlement offer, and
    `SETTLEMENT_PROPOSED` for a dispute or an acceptance; a `FeeAssessment` is
    `ISSUED` for a payment."

    Design: Corner/state_machines/corner_activate_twice_second_call_rejected
    """
    world = given_licensed_venue(api)
    licence = world["license"]
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_INVOICED)

    validate_error(
        api.activate_license(licence["id"], admin_headers()),
        ERR_LICENSE_STATE_INVALID,
    )

    after = license_row(api, licence["id"])
    assert_license_dimensions(after, COVERAGE_ACTIVE, BILLING_INVOICED)
    assert_version_unchanged(after, licence, "license")

    assessments = assessments_of_license(api, licence["id"])
    assert len(assessments) == 1, (
        f"activation bills once, found {len(assessments)} assessments"
    )
    assert_assessment(
        assessments[0], ASSESSMENT_KIND_INITIAL, 90017, ASSESSMENT_STATUS_ISSUED
    )

    windows = windows_of_license(api, licence["id"])
    assert len(windows) == 1, (
        f"activation opens one annual window, found {len(windows)}"
    )
    assert windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM, (
        f"the sole window is the annual term, got {windows[0]['window_kind']!r}"
    )

    assert_money(
        venue_row(api, world["venue"]["id"])["outstanding_balance_cents"],
        90017,
        "outstanding_balance_cents",
    )


def test_lifecycle_terminate_terminated_license_rejected(api):
    """TERMINATED is the terminal exit on the coverage dimension: a second
    termination, a suspension, a reinstatement, a renewal and a new coverage
    window are all refused, the voided window is not re-voided, and the ledger
    stands still.

    PRD §3.7: "Termination is the terminal exit on the coverage dimension,
    available from `ACTIVE` and from `SUSPENDED`, and it carries a compensating
    switch."

    PRD §3.7: "When `void_unpaid_assessments` is true, every `FeeAssessment` of
    this licence whose `status` is `ISSUED` moves to `VOIDED` with its
    `paid_amount_cents` left exactly as it was, the licence's `billing_status`
    becomes the terminal `WRITTEN_OFF`, the venue's `outstanding_balance_cents`
    decreases by the total of `amount_cents` less `paid_amount_cents` summed over
    those voided assessments, and the venue's `voided_amount_cents` increases by
    that same total."

    PRD §2.12: "**Licence is active.** The addressed `License` has
    `coverage_status` equal to `ACTIVE` — otherwise `ERR_LICENSE_NOT_ACTIVE`
    (409). Applies to `POST /licensing/performance-reports`,
    `POST /licensing/performance-reports/{report_id}/submit` and
    `POST /licensing/licenses/{license_id}/coverage-windows`."

    Design: Corner/state_machines/corner_terminate_terminated_license_rejected
    """
    world = given_licensed_venue(api)
    licence = world["license"]
    venue_id = world["venue"]["id"]

    terminated = validate_success(
        api.terminate_license(
            licence["id"], terminate_payload(True), admin_headers()
        )
    )
    assert_license_dimensions(terminated, COVERAGE_TERMINATED, BILLING_WRITTEN_OFF)
    assert_venue_ledger(venue_row(api, venue_id), 0, 0, 90017, 90017)

    voided_window = windows_of_license(api, licence["id"])[0]
    assert voided_window["status"] == WINDOW_STATUS_VOIDED, (
        f"termination voids the annual window, got {voided_window['status']!r}"
    )

    validate_error(
        api.terminate_license(
            licence["id"], terminate_payload(False), admin_headers()
        ),
        ERR_LICENSE_STATE_INVALID,
    )

    after = license_row(api, licence["id"])
    assert_license_dimensions(after, COVERAGE_TERMINATED, BILLING_WRITTEN_OFF)
    assert_version_unchanged(after, terminated, "license")

    validate_error(
        api.suspend_license(
            licence["id"],
            suspend_payload(SUSPENSION_REASON_OPERATOR_REQUEST),
            admin_headers(),
        ),
        ERR_LICENSE_STATE_INVALID,
    )
    validate_error(
        api.reinstate_license(licence["id"], admin_headers()),
        ERR_LICENSE_STATE_INVALID,
    )
    validate_error(
        api.renew_license(
            licence["id"],
            renew_payload(licence["term_end"], after["version"]),
            admin_headers(),
        ),
        ERR_LICENSE_STATE_INVALID,
    )
    validate_error(
        api.create_coverage_window(
            licence["id"],
            coverage_window_payload(
                "2026-10-01T00:00:00Z",
                "2026-11-01T00:00:00Z",
                WINDOW_KIND_SEASONAL_EVENT_RIDER,
            ),
            admin_headers(),
        ),
        ERR_LICENSE_NOT_ACTIVE,
    )

    windows = windows_of_license(api, licence["id"])
    assert len(windows) == 1, (
        f"no rider window was added to a terminated licence, found {len(windows)}"
    )
    assert_version_unchanged(windows[0], voided_window, "coverage window")
    assert_venue_ledger(venue_row(api, venue_id), 0, 0, 90017, 90017)


def test_lifecycle_findings_on_closed_audit_case_rejected(api):
    """A case closed with no action is finished: findings on it are refused, no
    back-licence bill appears, and the venue leaves the hold behind with an empty
    ledger.

    PRD §3.9: "An auditor who finds nothing worth pursuing closes the case, moving
    it from `OPEN` to the terminal `CLOSED_NO_ACTION` with a supplied
    `closed_reason` of either `NO_GAP_FOUND` or `WITHIN_TOLERANCE` and a `version`
    increment."

    PRD §3.9: "The venue's `audit_hold` is then recomputed and becomes false when
    no other `AuditCase` of that venue remains in `OPEN`, `FINDINGS_ISSUED`,
    `SETTLEMENT_PROPOSED` or `DISPUTED`; `Venue.version` increments by 1."

    PRD §3.9: "Issuing findings records `findings_issued_by_user_id` as the acting
    `X-User-ID`, moves `status` to `FINDINGS_ISSUED` and increments `version`."

    Design: Corner/state_machines/corner_findings_on_closed_audit_case_rejected
    """
    society = given_society(api, bmi_payload())
    venue = given_venue(api, bar_grill_venue_payload())
    case = given_open_case(api, venue["id"], [society["id"]])

    closed = validate_success(
        api.close_audit_case(
            case["id"],
            close_case_payload(CLOSED_REASON_NO_GAP_FOUND),
            auditor_headers(),
        )
    )
    assert closed["status"] == CASE_STATUS_CLOSED_NO_ACTION, (
        f"a no-action closure is terminal, got {closed['status']!r}"
    )

    validate_error(
        api.issue_findings(case["id"], auditor_headers()),
        ERR_AUDIT_CASE_STATE_INVALID,
    )

    after = case_row(api, case["id"])
    assert after["status"] == CASE_STATUS_CLOSED_NO_ACTION, (
        f"the case must still be closed, got {after['status']!r}"
    )
    assert after["closed_reason"] == CLOSED_REASON_NO_GAP_FOUND, (
        f"the recorded closure reason must survive, got {after['closed_reason']!r}"
    )
    assert after["findings_issued_by_user_id"] is None, (
        "no auditor is recorded as having issued findings, got "
        f"{after['findings_issued_by_user_id']!r}"
    )
    assert_version_unchanged(after, closed, "audit case")

    assert_empty_list(
        api.list_fee_assessments(admin_headers(), {"venue_id": venue["id"]})
    )

    reread_venue = venue_row(api, venue["id"])
    assert reread_venue["audit_hold"] is False, (
        f"the closure lifted the hold, got audit_hold {reread_venue['audit_hold']!r}"
    )
    assert_money(
        reread_venue["outstanding_balance_cents"], 0, "outstanding_balance_cents"
    )


def test_lifecycle_report_review_accept_increments_accepted_report_count(api):
    """Accepting a submitted report is terminal for the report and moves the
    owning licence's accepted-report counter from zero to one in the same call.

    PRD §3.8: "An acceptance moves the report to the terminal `ACCEPTED`,
    increments its `version`, increases the owning licence's
    `accepted_report_count` by 1 with a `version` increment on the licence, and
    recomputes the venue's `gap_risk_score` from the most recent reportable
    report."

    PRD §3.8: "**Coverage-testing** is a separate question: an entry's
    `is_covered` becomes true only when its `society_affiliation` names a
    `Society` for which this venue holds a `License` with `coverage_status`
    `ACTIVE` that also has an `ACTIVE` `CoverageWindow` whose half-open span
    contains the entry's `performance_datetime`."

    Design: Corner/state_machines/corner_report_review_accept_increments_accepted_report_count
    """
    world = given_licensed_venue(api)
    licence = world["license"]
    venue_id = world["venue"]["id"]
    given_work(api, world["society"]["id"], "Blue Horizon", "A. Reed")

    report = given_draft_report(api, licence["id"], venue_id, _TERM_START, _PERIOD_END)
    given_setlist_entry(
        api,
        report["id"],
        venue_id,
        "Blue Horizon",
        "A. Reed",
        "BMI",
        "2026-09-05T20:00:00Z",
        300,
        USE_TYPE_LIVE,
    )
    validate_success(
        api.submit_performance_report(report["id"], venue_operator_headers(venue_id))
    )

    before = license_row(api, licence["id"])
    assert_count(before["accepted_report_count"], 0, "accepted_report_count")

    accepted = validate_success(
        api.review_performance_report(
            report["id"],
            report_review_payload(REPORT_DISPOSITION_ACCEPT),
            auditor_headers(),
        )
    )
    assert accepted["status"] == REPORT_STATUS_ACCEPTED, (
        f"an acceptance is terminal for the report, got {accepted['status']!r}"
    )
    assert accepted["rejection_reason"] is None, (
        f"an accepted report carries no rejection reason, got {accepted['rejection_reason']!r}"
    )
    assert_count(accepted["review_round"], 0, "review_round")

    after = license_row(api, licence["id"])
    assert_count(after["accepted_report_count"], 1, "accepted_report_count")
    assert_version_advanced(after, before, 1, "license")

    entries = read_rows(
        api.list_report_setlist_entries(report["id"], admin_headers()),
        expected_total=1,
    )
    assert entries[0]["is_matched"] is True, (
        f"the registered work matches, got is_matched {entries[0]['is_matched']!r}"
    )
    assert entries[0]["is_covered"] is True, (
        f"the annual window covers the performance, got is_covered {entries[0]['is_covered']!r}"
    )

    reread_report = report_row(api, report["id"])
    assert_pct(reread_report["uncovered_share_pct"], 0.00, "uncovered_share_pct")
    assert_money(reread_report["gap_exposure_cents"], 0, "gap_exposure_cents")

    reread_venue = venue_row(api, venue_id)
    assert_pct(reread_venue["gap_risk_score"], 0.00, "gap_risk_score")
    assert reread_venue["audit_hold"] is False, (
        f"a fully covered setlist opens no case, got audit_hold {reread_venue['audit_hold']!r}"
    )

    validate_error(
        api.review_performance_report(
            report["id"],
            report_review_payload(REPORT_DISPOSITION_ACCEPT),
            auditor_headers(),
        ),
        ERR_REPORT_STATE_INVALID,
    )
