"""Grantee reporting obligations: windows, lateness, uniqueness (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_report,
    create_report_payload,
    get_grant,
    make_applicant_headers,
    set_clock_to,
    setup_active_grant,
    submit_report,
    validate_error,
    validate_success,
)


def test_report_final_before_end_date_returns_report_window_invalid(api):
    """PRD §3.9: "A FINAL report is accepted only once the logical clock has
    reached the grant's `end_date`, or when the grant has already reached
    COMPLETED or TERMINATED_EARLY (`ERR_REPORT_WINDOW_INVALID`)."
    PRD §3.9: "its `late` flag is set when that instant falls strictly after
    the applicable due date — the grant's `interim_report_due_date` for an
    INTERIM report, its `final_report_due_date` for a FINAL one; a submission
    landing exactly at the due instant is on time."

    At clock 2028-06-15 (grant ACTIVE, end 2028-07-01) the FINAL is rejected
    while an INTERIM at the same instant is accepted — the window rule is
    specific to FINAL.

    Design: Corner/state_machines/report_final_before_end_date_returns_report_window_invalid
    """
    bundle = setup_active_grant()
    applicant_headers = make_applicant_headers(bundle["applicant"]["id"])
    set_clock_to("2028-06-15T00:00:00Z")  # one month before end_date

    early_final = api.create_report(
        bundle["grant"]["id"],
        create_report_payload("FINAL", content="Too early"),
        applicant_headers,
    )
    validate_error(early_final, ApiErrorId.ERR_REPORT_WINDOW_INVALID)

    interim = api.create_report(
        bundle["grant"]["id"],
        create_report_payload("INTERIM", content="Midterm progress"),
        applicant_headers,
    )
    report = validate_success(interim, 201)
    assert_report(report)
    assert report["late"] is True, (
        "interim due 2028-01-01 (four months after start), submitted 2028-06-15"
    )

    grant = get_grant(bundle["grant"])
    assert grant["compliance_strikes"] == 1, "the late interim adds one strike"


def test_duplicate_interim_report_rejected(api):
    """PRD §3.9: "one report of each type may exist per grant
    (`ERR_DUPLICATE_REPORT`)"
    PRD §3.9: "A late first submission adds one to the grant's
    `compliance_strikes`, once; a resubmission never re-strikes, because
    `submitted_at` never moves."

    The first INTERIM (2027-12-15, due 2028-01-01) is on time; the second
    INTERIM is rejected.

    Design: Corner/state_machines/duplicate_interim_report_rejected
    """
    bundle = setup_active_grant()
    set_clock_to("2027-12-15T00:00:00Z")

    first = submit_report(
        bundle["grant"], bundle["applicant"], report_type="INTERIM",
        content="Midterm progress",
    )
    assert_report(first)
    assert first["late"] is False

    dup = api.create_report(
        bundle["grant"]["id"],
        create_report_payload("INTERIM", content="Second interim"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT)

    grant = get_grant(bundle["grant"])
    assert grant["compliance_strikes"] == 0


def test_report_lateness_boundaries(api):
    """PRD §3.9: "its `late` flag is set when that instant falls strictly
    after the applicable due date — the grant's `interim_report_due_date` for
    an INTERIM report, its `final_report_due_date` for a FINAL one; a
    submission landing exactly at the due instant is on time."
    PRD §3.9: "A late first submission adds one to the grant's
    `compliance_strikes`, once; a resubmission never re-strikes, because
    `submitted_at` never moves."

    INTERIM at 2028-01-15T10:00:00Z is strictly past its 2028-01-01 due date
    (strike 1); the FINAL submitted at exactly 2028-07-31T00:00:00Z — the
    final due instant, thirty days after end_date 2028-07-01 — is on time.

    Design: Corner/state_machines/report_lateness_boundaries
    """
    bundle = setup_active_grant()
    applicant_headers = make_applicant_headers(bundle["applicant"]["id"])

    set_clock_to("2028-01-15T10:00:00Z")
    interim = api.create_report(
        bundle["grant"]["id"],
        create_report_payload("INTERIM", content="Late midterm"),
        applicant_headers,
    )
    rep_i = validate_success(interim, 201)
    assert_report(rep_i)
    assert rep_i["late"] is True, "2028-01-15T10:00 is strictly after the due instant"

    set_clock_to("2028-07-31T00:00:00Z")  # exactly final_report_due_date
    final = api.create_report(
        bundle["grant"]["id"],
        create_report_payload("FINAL", content="Final at the deadline instant"),
        applicant_headers,
    )
    rep_f = validate_success(final, 201)
    assert_report(rep_f)
    assert rep_f["late"] is False, (
        "submission exactly at the due instant is on time (strictly-greater rule)"
    )

    grant = get_grant(bundle["grant"])
    assert grant["compliance_strikes"] == 1, (
        "only the late interim strikes; the on-time final adds none"
    )
