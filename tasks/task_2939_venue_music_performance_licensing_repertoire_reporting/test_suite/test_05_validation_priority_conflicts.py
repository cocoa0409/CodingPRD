"""
Which rejection wins when two of the licensing contract's rules both refuse the
same call.

PRD §2.12 evaluates the rejection ladder strictly in ascending priority order
and lets the first failing rule produce the response, so a call that breaks two
rules is silent about the later one.  This file pins the two shadowing pairs the
contract calls out by name: a suspended licence shadowing a reporting-period
collision on a report submission, and a venue's audit hold shadowing its
unpaid balance on a licence renewal.  Each pair is exercised twice over — once
with both faults live, to see the higher-priority error and prove that nothing
was written, and once again after only the higher-priority fault has been
cleared, so the lower-priority rule finally answers on an otherwise identical
call.
"""

from test_helpers import (
    AUDIT_TRIGGER_ROUTINE,
    CASE_STATUS_CLOSED_NO_ACTION,
    CASE_STATUS_OPEN,
    CLOSED_REASON_NO_GAP_FOUND,
    COVERAGE_ACTIVE,
    COVERAGE_SUSPENDED,
    ERR_AUDIT_HOLD_ACTIVE,
    ERR_LICENSE_NOT_ACTIVE,
    ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL,
    ERR_REPORT_PERIOD_OVERLAP,
    REJECTION_REASON_INCOMPLETE_SETLIST,
    RENEWAL_OUTSTANDING_LIMIT_CENTS,
    REPORT_DISPOSITION_REJECT,
    REPORT_STATUS_DRAFT,
    REPORT_STATUS_REJECTED,
    SUSPENSION_REASON_AUDIT_FINDINGS,
    USE_TYPE_LIVE,
    admin_headers,
    assert_empty_list,
    assert_money,
    assert_version_unchanged,
    auditor_headers,
    close_case_payload,
    concert_hall_venue_payload,
    get_success_data,
    given_draft_report,
    given_licensed_venue,
    given_open_case,
    given_setlist_entry,
    license_row,
    read_rows,
    renew_payload,
    report_review_payload,
    report_row,
    suspend_payload,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
)

# The concert-hall survey lands in the fourth occupancy tier, so its verified
# annual fee for a 4600 bp society on a default schedule is 1335461 cents — far
# above the 100000-cent renewal outstanding limit of PRD §2.9.
CONCERT_HALL_ANNUAL_FEE_CENTS = 1335461


def _two_reports_sharing_a_period_on_a_suspended_license(api):
    """Drive one bar and grill to a suspended licence carrying two DRAFT reports
    over one and the same reporting period.

    Reaching that pair of faults needs the report cycle: report B is submitted
    and rejected, which takes its period out of the collision set so report C
    may be opened over exactly the same month; appending one performance to B
    reopens B into ``DRAFT``, and only then is the licence suspended.  The
    returned dict carries the venue id, the licence id and both report rows.
    """
    world = given_licensed_venue(api)
    venue_id = world["venue"]["id"]
    license_id = world["license"]["id"]
    society_code = world["society"]["society_code"]

    report_b = given_draft_report(api, license_id, venue_id)
    get_success_data(
        api.submit_performance_report(
            report_b["id"], venue_operator_headers(venue_id)
        )
    )
    rejected = get_success_data(
        api.review_performance_report(
            report_b["id"],
            report_review_payload(
                REPORT_DISPOSITION_REJECT, REJECTION_REASON_INCOMPLETE_SETLIST
            ),
            auditor_headers(),
        )
    )
    assert rejected["status"] == REPORT_STATUS_REJECTED, (
        f"the rejected report should sit in REJECTED, got {rejected['status']!r}"
    )

    report_c = given_draft_report(api, license_id, venue_id)

    given_setlist_entry(
        api,
        report_b["id"],
        venue_id,
        "Blue Horizon",
        "A. Reed",
        society_code,
        "2026-09-10T20:00:00Z",
        300,
        USE_TYPE_LIVE,
    )
    reopened = report_row(api, report_b["id"])
    assert reopened["status"] == REPORT_STATUS_DRAFT, (
        "appending a performance must reopen the rejected report into DRAFT, "
        f"got {reopened['status']!r}"
    )

    suspended = get_success_data(
        api.suspend_license(
            license_id,
            suspend_payload(SUSPENSION_REASON_AUDIT_FINDINGS),
            admin_headers(),
        )
    )
    assert suspended["coverage_status"] == COVERAGE_SUSPENDED, (
        f"the licence should be SUSPENDED, got {suspended['coverage_status']!r}"
    )

    return {
        "venue_id": venue_id,
        "license_id": license_id,
        "report_b": report_b,
        "report_c": report_c,
    }


def test_priority_report_submit_answers_with_the_license_state_failure(api):
    """A submission refused both because its licence is suspended and because a
    sibling report already holds the period reports only the licence-state fault.

    PRD §2.12: "First, a report submission on a licence that is `SUSPENDED`
    *and* whose reporting period also overlaps an existing `SUBMITTED` report
    fails at rule 7 with `ERR_LICENSE_NOT_ACTIVE`, never at rule 12 with
    `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_on_report_submit
    """
    world = _two_reports_sharing_a_period_on_a_suspended_license(api)

    refused = api.submit_performance_report(
        world["report_b"]["id"], venue_operator_headers(world["venue_id"])
    )
    validate_error(refused, ERR_LICENSE_NOT_ACTIVE)


def test_priority_report_refused_submit_leaves_both_periods_in_draft(api):
    """The refused submission writes nothing: both reports keep their DRAFT
    status and neither revision counter moves.

    PRD §2.5: "`version` is an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row — including mutations
    the row's owner never requested, such as a recomputed derived field written
    by a cascade."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_on_report_submit
    """
    world = _two_reports_sharing_a_period_on_a_suspended_license(api)
    before_b = report_row(api, world["report_b"]["id"])
    before_c = report_row(api, world["report_c"]["id"])

    refused = api.submit_performance_report(
        world["report_b"]["id"], venue_operator_headers(world["venue_id"])
    )
    validate_error(refused, ERR_LICENSE_NOT_ACTIVE)

    after_b = report_row(api, world["report_b"]["id"])
    after_c = report_row(api, world["report_c"]["id"])
    assert after_b["status"] == REPORT_STATUS_DRAFT, (
        f"the refused report must stay DRAFT, got {after_b['status']!r}"
    )
    assert after_c["status"] == REPORT_STATUS_DRAFT, (
        f"the sibling report must stay DRAFT, got {after_c['status']!r}"
    )
    assert_version_unchanged(after_b, before_b, "refused report")
    assert_version_unchanged(after_c, before_c, "sibling report")


def test_priority_report_reinstatement_exposes_the_period_overlap(api):
    """Reinstating the licence and changing nothing else lets the same
    submission fall through to the reporting-period collision.

    PRD §2.12: "The report's half-open period does not overlap the period of any
    other report on the same `license_id` whose `status` is `DRAFT`, `SUBMITTED`
    or `ACCEPTED`; a period beginning exactly where an existing one ends does not
    overlap; `REJECTED` reports are excluded from the overlap set, so a rejected
    period may be re-reported — otherwise `ERR_REPORT_PERIOD_OVERLAP` (409)."

    Design: Difficulty/priority_pair_validation_conflict/conflict_state_beats_temporal_on_report_submit
    """
    world = _two_reports_sharing_a_period_on_a_suspended_license(api)
    operator = venue_operator_headers(world["venue_id"])

    first_attempt = api.submit_performance_report(world["report_b"]["id"], operator)
    validate_error(first_attempt, ERR_LICENSE_NOT_ACTIVE)

    reinstated = get_success_data(
        api.reinstate_license(world["license_id"], admin_headers())
    )
    assert reinstated["coverage_status"] == COVERAGE_ACTIVE, (
        f"reinstatement must restore ACTIVE, got {reinstated['coverage_status']!r}"
    )

    second_attempt = api.submit_performance_report(world["report_b"]["id"], operator)
    validate_error(second_attempt, ERR_REPORT_PERIOD_OVERLAP)

    still_draft = report_row(api, world["report_b"]["id"])
    assert still_draft["status"] == REPORT_STATUS_DRAFT, (
        f"the twice-refused report must stay DRAFT, got {still_draft['status']!r}"
    )


def _renewal_blocked_by_both_the_hold_and_the_balance(api):
    """Drive one concert hall to an ACTIVE licence whose renewal breaks two gates.

    The activation invoice for the fourth-tier survey leaves the venue owing far
    more than the renewal outstanding limit, and a routine audit case opened over
    the same venue puts it under an audit hold at the same time.  The returned
    dict carries the venue id, the society id, the freshly re-read predecessor
    licence row and the open case row.
    """
    world = given_licensed_venue(
        api,
        concert_hall_venue_payload(),
        venue_category="CONCERT_HALL",
        requested_term_start="2026-08-01T00:00:00Z",
    )
    venue_id = world["venue"]["id"]
    society_id = world["society"]["id"]
    predecessor = license_row(api, world["license"]["id"])

    assert_money(
        world["venue"]["outstanding_balance_cents"],
        CONCERT_HALL_ANNUAL_FEE_CENTS,
        "outstanding_balance_cents",
    )
    assert (
        world["venue"]["outstanding_balance_cents"] > RENEWAL_OUTSTANDING_LIMIT_CENTS
    ), "the activation invoice must leave the venue above the renewal limit"

    case = given_open_case(
        api,
        venue_id,
        [society_id],
        "2025-01-01T00:00:00Z",
        "2026-05-01T00:00:00Z",
        AUDIT_TRIGGER_ROUTINE,
    )
    assert case["status"] == CASE_STATUS_OPEN, (
        f"a freshly opened case should be OPEN, got {case['status']!r}"
    )
    held = venue_row(api, venue_id)
    assert held["audit_hold"] is True, (
        "opening a case must put the venue under an audit hold"
    )

    return {
        "venue_id": venue_id,
        "society_id": society_id,
        "predecessor": predecessor,
        "case": case,
    }


def test_priority_renewal_answers_with_the_audit_hold_failure(api):
    """A renewal refused both by the venue's audit hold and by its unpaid balance
    reports only the hold.

    PRD §2.12: "Second, a renewal on a venue that both carries `audit_hold` true
    *and* owes more than 100000 cents fails at rule 9 with
    `ERR_AUDIT_HOLD_ACTIVE`, never at rule 20 with
    `ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL`; rule 20 is reachable only when
    `audit_hold` is false."

    Design: Difficulty/priority_pair_validation_conflict/conflict_safety_beats_fiscal_on_license_renew
    """
    world = _renewal_blocked_by_both_the_hold_and_the_balance(api)
    predecessor = world["predecessor"]

    refused = api.renew_license(
        predecessor["id"],
        renew_payload(
            predecessor["term_end"],
            expected_license_version=predecessor["version"],
        ),
        admin_headers(),
    )
    validate_error(refused, ERR_AUDIT_HOLD_ACTIVE)


def test_priority_renewal_refused_by_the_hold_mints_no_successor(api):
    """The refused renewal creates nothing: the predecessor is still unrenewed and
    no successor points back at it.

    PRD §3.7: "And the predecessor's `renewal_issued_at` must still be null,
    otherwise `ERR_LICENSE_ALREADY_RENEWED`; a licence may be renewed once, and
    the successor that already exists is discoverable through its own
    `renewal_of_license_id`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_safety_beats_fiscal_on_license_renew
    """
    world = _renewal_blocked_by_both_the_hold_and_the_balance(api)
    predecessor = world["predecessor"]

    refused = api.renew_license(
        predecessor["id"],
        renew_payload(
            predecessor["term_end"],
            expected_license_version=predecessor["version"],
        ),
        admin_headers(),
    )
    validate_error(refused, ERR_AUDIT_HOLD_ACTIVE)

    after = license_row(api, predecessor["id"])
    assert after["renewal_issued_at"] is None, (
        "a refused renewal must leave renewal_issued_at null, got "
        f"{after['renewal_issued_at']!r}"
    )
    assert_version_unchanged(after, predecessor, "predecessor licence")
    assert_empty_list(
        api.list_licenses(
            admin_headers(), {"renewal_of_license_id": predecessor["id"]}
        )
    )
    read_rows(
        api.list_licenses(
            admin_headers(),
            {"venue_id": world["venue_id"], "society_id": world["society_id"]},
        ),
        expected_total=1,
    )


def test_priority_renewal_closing_the_case_exposes_the_balance_gate(api):
    """Closing the audit case with no action clears the hold and nothing else, so
    the identical renewal then reports the unpaid balance.

    PRD §2.12: "The venue's `outstanding_balance_cents` is at most 100000 cents
    — otherwise `ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/conflict_safety_beats_fiscal_on_license_renew
    """
    world = _renewal_blocked_by_both_the_hold_and_the_balance(api)
    predecessor = world["predecessor"]
    body = renew_payload(
        predecessor["term_end"], expected_license_version=predecessor["version"]
    )

    first_attempt = api.renew_license(predecessor["id"], body, admin_headers())
    validate_error(first_attempt, ERR_AUDIT_HOLD_ACTIVE)

    closed = validate_success(
        api.close_audit_case(
            world["case"]["id"],
            close_case_payload(CLOSED_REASON_NO_GAP_FOUND),
            auditor_headers(),
        )
    )
    assert closed["status"] == CASE_STATUS_CLOSED_NO_ACTION, (
        f"a no-action closure should be CLOSED_NO_ACTION, got {closed['status']!r}"
    )
    released = venue_row(api, world["venue_id"])
    assert released["audit_hold"] is False, (
        "closing the only open case must lift the audit hold"
    )
    assert_money(
        released["outstanding_balance_cents"],
        CONCERT_HALL_ANNUAL_FEE_CENTS,
        "outstanding_balance_cents",
    )

    second_attempt = api.renew_license(predecessor["id"], body, admin_headers())
    validate_error(second_attempt, ERR_OUTSTANDING_BALANCE_BLOCKS_RENEWAL)

    after = license_row(api, predecessor["id"])
    assert_version_unchanged(after, predecessor, "predecessor licence")
