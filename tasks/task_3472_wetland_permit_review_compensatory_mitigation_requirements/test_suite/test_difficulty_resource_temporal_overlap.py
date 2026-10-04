"""Difficulty queue — temporal overlap rules (PRD §3.1, §3.8).

Point-in-window membership for one live determination per site (inclusive
of the expiration day), and zero-gap contiguity across sibling monitoring
coverage intervals.
"""
from test_helpers import (
    ApiErrorId,
    JdStatus,
    ReportStatus,
    assert_iso_instants_equal,
    create_applicant,
    create_jd,
    create_site,
    issue_jd,
    iso_add_days,
    make_applicant_headers,
    review_report,
    set_clock,
    setup_issued_permit,
    submit_monitoring_report_payload,
    submit_report,
    validate_error,
    validate_success,
)


def test_jd_issuance_blocked_by_live_validity_window(api, district_engineer_headers):
    """PRD §3.1: "Issuance is the `DistrictEngineer`'s act and is guarded by
    the one-live-determination rule: no other determination for the same site
    may already be `ISSUED` with an `expiration_date` still at or beyond the
    current clock, otherwise the issuance is rejected with
    `ERR_ACTIVE_JD_EXISTS` (HTTP 409)."
    PRD §2.5: "An `ISSUED` determination whose `expiration_date` is before
    the current clock is simply treated as expired at validation time — it
    fails a submission check with `ERR_JD_EXPIRED`, and it no longer blocks
    issuance of a new determination for the same site."

    jd1 issues at the 2026-09-01 startup clock (expiration 2031-08-31); a
    second determination for the same site cannot issue while the window
    covers the clock — including exactly on the expiration day — and issues
    cleanly the day after.

    Design: Difficulty/resource_temporal_overlap/jd_issuance_blocked_by_live_validity_window
    """
    applicant = create_applicant()
    site = create_site(applicant, resource_types_present=["FORESTED_WETLAND"])
    jd1 = issue_jd(create_jd(site, rationale="First delineation"))
    assert_iso_instants_equal(
        jd1["expiration_date"], "2031-08-31T00:00:00Z",
        label="expiration_date = issued 2026-09-01 + 1825 days",
    )
    jd2 = create_jd(site, rationale="Renewal delineation")

    resp = api.issue_jd(jd2["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_JD_EXISTS)

    # The window is closed at its right end: blocked at clock == expiration.
    set_clock(jd1["expiration_date"])
    resp = api.issue_jd(jd2["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_JD_EXISTS)

    set_clock(iso_add_days(jd1["expiration_date"], 1))
    jd2 = validate_success(api.issue_jd(jd2["id"], district_engineer_headers))
    assert jd2["status"] == JdStatus.ISSUED.value
    assert_iso_instants_equal(
        jd2["issued_date"], "2031-09-01T00:00:00Z",
        label="second determination issues one day after the first expired",
    )


def test_monitoring_coverage_requires_zero_gap_contiguity(api):
    """PRD §3.8: "the first report's `coverage_start` must equal the permit's
    `issue_date`, and each later report's `coverage_start` must equal the
    `coverage_end` most recently submitted — in `SUBMITTED` or `ACCEPTED`
    status — for the preceding period index. No gaps and no overlaps are
    tolerated between sibling reports; a break in that zero-gap chain is
    `ERR_COVERAGE_INTERVAL_CONFLICT` (HTTP 409)."

    With report 1 covering [issue, issue+365 days] and ACCEPTED, report 2
    rejects a start one day inside report 1 (overlap) and a start one day
    after report 1's end (gap); only exact adjacency submits.

    Design: Difficulty/resource_temporal_overlap/monitoring_coverage_requires_zero_gap_contiguity
    """
    ctx = setup_issued_permit()
    permit, applicant, reports = ctx["permit"], ctx["applicant"], ctx["reports"]
    issue = permit["issue_date"]
    rep1, rep2 = reports[0], reports[1]

    rep1 = submit_report(rep1, permit, applicant)  # [issue, issue+365 days]
    rep1 = review_report(rep1)  # ACCEPTED
    headers = make_applicant_headers(applicant["id"])

    # Overlap: start one day before report 1's coverage_end.
    resp = api.submit_monitoring_report(
        rep2["id"],
        submit_monitoring_report_payload(
            iso_add_days(issue, 364), iso_add_days(issue, 729),
            findings_text="Overlapping coverage",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_INTERVAL_CONFLICT)

    # Gap: start one day after report 1's coverage_end.
    resp = api.submit_monitoring_report(
        rep2["id"],
        submit_monitoring_report_payload(
            iso_add_days(issue, 366), iso_add_days(issue, 731),
            findings_text="Gapped coverage",
        ),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_INTERVAL_CONFLICT)

    # Exact adjacency: coverage_start == report 1's coverage_end.
    rep2 = submit_report(
        rep2, permit, applicant,
        coverage_start=iso_add_days(issue, 365),
        coverage_end=iso_add_days(issue, 730),
        findings_text="Exactly adjacent coverage",
    )
    assert rep2["status"] == ReportStatus.SUBMITTED.value
