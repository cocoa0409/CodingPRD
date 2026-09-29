"""
Gap-risk arithmetic, the selectors that decide which row feeds a calculation,
and the roll-ups that hang off both.

The gap-risk score has a hard ceiling of 100.00 that a bad enough setlist would
otherwise overshoot, and exactly one report feeds it — a draft one never does.
Two selectors are pinned the same way: rate-schedule selection cannot see a
schedule still in draft, and repertoire matching ignores case and surrounding
whitespace while awarding a tie to the oldest registration. The remaining tests
pin the money that follows: the venue's four-column ledger across an issue and a
full payment, a rider fee rounded exactly once over whole covered days, the
coverage posture that counts only active licences, and the two licence types
whose assignment changes what is billed at all.
"""

from test_helpers import (
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_KIND_SEASONAL_RIDER,
    ASSESSMENT_STATUS_ISSUED,
    ASSESSMENT_STATUS_PAID,
    AUDIT_TRIGGER_GAP_RISK_ESCALATION,
    BILLING_INVOICED,
    BILLING_PAID,
    BILLING_UNBILLED,
    CASE_STATUS_OPEN,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    DEFAULT_ADJUSTMENT_BP,
    ERR_ASSESSMENT_NOT_ISSUED,
    EXEMPTION_EXEMPT,
    GAP_RISK_SCORE_CAP,
    POSTURE_PARTIALLY_COVERED,
    POSTURE_UNCOVERED,
    REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS,
    REPORT_STATUS_DRAFT,
    REPORT_STATUS_SUBMITTED,
    SCHEDULE_STATUS_DRAFT,
    SCHEDULE_STATUS_EFFECTIVE,
    SHARE_ASCAP_BP,
    SHARE_BMI_BP,
    TERM_LENGTH_DAYS,
    USE_TYPE_LIVE,
    WINDOW_KIND_ANNUAL_TERM,
    WINDOW_KIND_FESTIVAL_RIDER,
    WINDOW_KIND_SEASONAL_EVENT_RIDER,
    WINDOW_STATUS_ACTIVE,
    activate,
    admin_headers,
    ascap_payload,
    assert_assessment,
    assert_bp,
    assert_coverage,
    assert_count,
    assert_days_apart,
    assert_ledger_identity,
    assert_license_dimensions,
    assert_money,
    assert_not_money,
    assert_not_pct,
    assert_pct,
    assert_venue_ledger,
    assessments_of_license,
    assessments_of_venue,
    bar_grill_venue_payload,
    bgm_survey_fields,
    bmi_payload,
    cases_of_venue,
    find_row,
    fitness_studio_venue_payload,
    get_success_data,
    given_active_license,
    given_approved_application,
    given_coverage_window,
    given_draft_report,
    given_draft_schedule,
    given_effective_schedule,
    given_setlist,
    given_setlist_entry,
    given_societies,
    given_society,
    given_venue,
    given_work,
    gmr_payload,
    license_of_application,
    license_row,
    mid_concert_hall_venue_payload,
    move_clock,
    payment_payload,
    report_row,
    reset_clock,
    sesac_payload,
    setlist_entries_of,
    validate_error,
    validate_success,
    venue_operator_headers,
    venue_row,
    windows_of_license,
)

# The PRD names these enum values but ``test_helpers`` exposes no single-value
# constant for each, so they are spelled once here rather than inline.
_CATEGORY_BAR_GRILL = "BAR_GRILL"
_CATEGORY_CONCERT_HALL = "CONCERT_HALL"
_CATEGORY_FITNESS_STUDIO = "FITNESS_STUDIO"

_AFFILIATION_ASCAP = "ASCAP"
_AFFILIATION_BMI = "BMI"
_AFFILIATION_GMR = "GMR"
_AFFILIATION_SESAC = "SESAC"
_AFFILIATION_UNAFFILIATED = "UNAFFILIATED"
_AFFILIATION_UNKNOWN = "UNKNOWN"

# One second past the clock's start-up instant.  Advancing the logical clock by
# this much between two registrations is what gives the second row a strictly
# later ``created_at`` without moving any schedule, term or window boundary.
_SECOND_REGISTRATION_INSTANT = "2026-08-01T00:00:01Z"

_LICENSE_TYPE_BGM_EXEMPT = "BGM_EXEMPT"
_LICENSE_TYPE_BLANKET = "BLANKET"
_LICENSE_TYPE_PER_PROGRAM = "PER_PROGRAM"

# The verified annual fee of the 180-occupancy MIXED bar and grill against a
# default schedule and a 4600 bp society: second tier, so 78000 + 240 * 180 =
# 43200 and 4200000 * 135 / 10000 = 56700 give a subtotal of 177900; the MIXED
# 10000 bp plus 4 live nights at 250 bp scale that to 195690; and 4600 bp of
# 195690 is 90017.40, which rounds half up to 90017.
_BAR_GRILL_ANNUAL_FEE_CENTS = 90017


def _submit_report(api, report_id, venue_id):
    """Submit a draft performance report as the venue's own operator."""
    return get_success_data(
        api.submit_performance_report(report_id, venue_operator_headers(venue_id))
    )


def test_calc_gap_risk_score_ceiling_holds_at_one_hundred(api):
    """A setlist bad enough to score 104 points is still reported as 100.00.

    Four equally weighted live performances, none of them covered and each
    naming a different affiliation, put the uncovered share at 100.00 percent
    and add four affiliation penalties: 80 points plus 24 is 104, and the
    published score is the ceiling of 100.00 rather than the raw sum. The
    escalation that follows lists only the three affiliations that are real
    societies holding repertoire.

    PRD §3.8: "Multiply the source report's `uncovered_share_pct` by 0.8, add 6
    points for each distinct uncovered affiliation, round the sum half up to two
    decimal places, and cap the result at 100.00 — the score never exceeds
    100.00 however bad the setlist."

    PRD §3.8: "It is created with `audit_trigger` `GAP_RISK_ESCALATION`, `status`
    `OPEN`, `lookback_start` equal to the submitted report's `period_start`,
    `lookback_end` equal to its `period_end`, and `society_ids` listing the `id`
    of every `Society` whose `repertoire_share_bp` is greater than 0 that appears
    as the `society_affiliation` of an uncovered entry of that report, ordered by
    the society's `created_at` ascending."

    PRD §3.8: "`gap_exposure_cents` puts money on the second figure: it is the
    owning licence's `annual_fee_cents` multiplied by `uncovered_share_pct` and
    divided by 100, rounded half up to whole cents."

    Design: Corner/calculations/corner_gap_risk_score_ceiling_holds_at_one_hundred
    """
    bmi, ascap, sesac, gmr = given_societies(
        api, bmi_payload(), ascap_payload(), sesac_payload(), gmr_payload()
    )
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)
    assert_money(
        licence["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )

    period_start = "2026-09-01T00:00:00Z"
    period_end = "2026-10-01T00:00:00Z"
    report = given_draft_report(
        api, licence["id"], venue["id"], period_start, period_end
    )
    # Four 60-second live performances weigh 100 each, so the total weight is
    # 400 and each uncovered entry carries a quarter of it.
    given_setlist(
        api,
        report["id"],
        venue["id"],
        [
            {
                "title": "Wandering Signal",
                "writer": "P. Larkin",
                "affiliation": _AFFILIATION_ASCAP,
                "when": "2026-09-04T21:00:00Z",
                "seconds": 60,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Second Wind",
                "writer": "R. Voss",
                "affiliation": _AFFILIATION_SESAC,
                "when": "2026-09-04T21:10:00Z",
                "seconds": 60,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Tallow Light",
                "writer": "M. Oyelaran",
                "affiliation": _AFFILIATION_GMR,
                "when": "2026-09-04T21:20:00Z",
                "seconds": 60,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "House Improvisation",
                "writer": "The House Band",
                "affiliation": _AFFILIATION_UNAFFILIATED,
                "when": "2026-09-04T21:30:00Z",
                "seconds": 60,
                "use_type": USE_TYPE_LIVE,
            },
        ],
    )

    submitted = _submit_report(api, report["id"], venue["id"])
    assert submitted["status"] == REPORT_STATUS_SUBMITTED, (
        f"expected a SUBMITTED report, got {submitted['status']!r}"
    )
    assert_count(submitted["reported_entry_count"], 4, "reported_entry_count")
    assert_count(submitted["matched_entry_count"], 0, "matched_entry_count")
    assert_count(submitted["uncovered_entry_count"], 4, "uncovered_entry_count")
    assert_pct(submitted["unmatched_share_pct"], 100.00, "unmatched_share_pct")
    assert_pct(submitted["uncovered_share_pct"], 100.00, "uncovered_share_pct")
    assert_money(
        submitted["gap_exposure_cents"],
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        "gap_exposure_cents",
    )

    exposed = venue_row(api, venue["id"])
    assert_pct(exposed["gap_risk_score"], GAP_RISK_SCORE_CAP, "gap_risk_score")
    assert_not_pct(exposed["gap_risk_score"], 104.00, "gap_risk_score")
    assert exposed["audit_hold"] is True, "a score of 100.00 escalates and holds"

    cases = cases_of_venue(api, venue["id"])
    assert len(cases) == 1, f"expected one audit case, got {len(cases)}"
    case = cases[0]
    assert case["audit_trigger"] == AUDIT_TRIGGER_GAP_RISK_ESCALATION, (
        f"expected a GAP_RISK_ESCALATION case, got {case['audit_trigger']!r}"
    )
    assert case["status"] == CASE_STATUS_OPEN, (
        f"expected an OPEN case, got {case['status']!r}"
    )
    # UNAFFILIATED is a fourth distinct affiliation for the score but names no
    # society, so it cannot appear among the case's societies.
    assert case["society_ids"] == [ascap["id"], sesac["id"], gmr["id"]], (
        "expected the three real societies in registration order"
    )


def test_calc_gap_risk_selector_ignores_draft_reports(api):
    """A draft report with an uncovered performance leaves the score untouched.

    The venue's only submitted report is fully covered, so its uncovered share
    is 0.00 percent. A second report covering the following month carries one
    unmatched and uncovered performance but is never submitted, and because only
    a submitted or accepted report may feed the score, the venue stays at 0.00
    and no case opens.

    PRD §3.8: "The candidates are the reports whose owning licence belongs to
    this venue and whose `status` is `SUBMITTED` or `ACCEPTED`; reports in
    `DRAFT` or `REJECTED` are excluded."

    PRD §3.8: "The three derived flags on the entry — `is_matched` at false,
    `matched_work_id` at null and `is_covered` at false — stay at their defaults
    until submission recomputes them."

    PRD §3.8: "A new report opens in `DRAFT` `status` with `reported_entry_count`,
    `matched_entry_count`, `uncovered_entry_count`, `unmatched_share_pct`,
    `uncovered_share_pct`, `gap_exposure_cents` and `review_round` all at 0 and
    `rejection_reason` at null."

    Design: Corner/calculations/corner_gap_risk_score_selector_ignores_draft_reports
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    given_work(api, bmi["id"], "Harbour Lights", "J. Okonjo")
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)

    covered_report = given_draft_report(
        api,
        licence["id"],
        venue["id"],
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    given_setlist_entry(
        api,
        covered_report["id"],
        venue["id"],
        "Harbour Lights",
        "J. Okonjo",
        _AFFILIATION_BMI,
        "2026-09-05T20:00:00Z",
        300,
        USE_TYPE_LIVE,
    )
    submitted = _submit_report(api, covered_report["id"], venue["id"])
    assert_count(submitted["matched_entry_count"], 1, "matched_entry_count")
    assert_count(submitted["uncovered_entry_count"], 0, "uncovered_entry_count")
    assert_pct(submitted["uncovered_share_pct"], 0.00, "uncovered_share_pct")

    draft_report = given_draft_report(
        api,
        licence["id"],
        venue["id"],
        "2026-10-01T00:00:00Z",
        "2026-11-01T00:00:00Z",
    )
    unlicensed_entry = given_setlist_entry(
        api,
        draft_report["id"],
        venue["id"],
        "Late Set Improvisation",
        "Unknown Writer",
        _AFFILIATION_UNKNOWN,
        "2026-10-15T22:00:00Z",
        600,
        USE_TYPE_LIVE,
    )
    assert unlicensed_entry["is_matched"] is False, (
        "an appended entry is not matched until the report is submitted"
    )
    assert unlicensed_entry["matched_work_id"] is None, (
        "an appended entry names no matched work until submission"
    )
    assert unlicensed_entry["is_covered"] is False, (
        "an appended entry is not coverage-tested until submission"
    )

    still_draft = report_row(api, draft_report["id"])
    assert still_draft["status"] == REPORT_STATUS_DRAFT, (
        f"expected a DRAFT report, got {still_draft['status']!r}"
    )
    assert_count(still_draft["reported_entry_count"], 1, "reported_entry_count")
    assert_count(still_draft["uncovered_entry_count"], 0, "uncovered_entry_count")
    assert_pct(still_draft["unmatched_share_pct"], 0.00, "unmatched_share_pct")
    assert_pct(still_draft["uncovered_share_pct"], 0.00, "uncovered_share_pct")
    assert_money(still_draft["gap_exposure_cents"], 0, "gap_exposure_cents")

    unmoved = venue_row(api, venue["id"])
    assert_pct(unmoved["gap_risk_score"], 0.00, "gap_risk_score")
    assert unmoved["audit_hold"] is False, "no case escalated, so no hold"
    assert cases_of_venue(api, venue["id"]) == [], (
        "a draft report cannot escalate an audit case"
    )


def test_calc_ledger_issue_then_full_payment(api):
    """Issuing and then fully paying one assessment moves cents between columns.

    Activation puts 90017 cents into both the lifetime total and the outstanding
    balance. Paying exactly the remainder moves the same 90017 cents out of
    outstanding and into settled, leaves the lifetime total alone, voids nothing,
    and takes the licence's billing dimension to paid. A further payment of a
    single cent is refused because the assessment is no longer issued, not
    because the amount exceeds the remainder.

    PRD §2.9: "`outstanding_balance_cents` is the sum, over that venue's
    assessments whose `status` is `ISSUED`, of `amount_cents` less
    `paid_amount_cents` on each such row."

    PRD §2.9: "`settled_amount_cents` is the sum of `paid_amount_cents` over
    *every* assessment of the venue, whatever its status — so a partial payment
    against a still-`ISSUED` row counts here the moment the cash lands."

    PRD §3.9: "**A payment for exactly the remainder** sets `paid_amount_cents`
    to the assessment's full `amount_cents`, moves `status` to the terminal
    `PAID`, and increments `version`."

    PRD §2.12: "Rules are evaluated **strictly in ascending priority order** and
    the **first** failing rule produces the error; later rules are never
    evaluated and their errors never surface."

    Design: Corner/calculations/corner_venue_ledger_aggregates_issue_then_full_payment
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)
    assert_money(
        licence["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )

    invoiced = venue_row(api, venue["id"])
    assert_venue_ledger(
        invoiced,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_ledger_identity(invoiced)
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
    )

    raised = assessments_of_license(api, licence["id"])
    assert len(raised) == 1, f"expected one assessment, got {len(raised)}"
    assessment = raised[0]
    assert_assessment(
        assessment,
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    paid = get_success_data(
        api.pay_assessment(
            assessment["id"],
            payment_payload(_BAR_GRILL_ANNUAL_FEE_CENTS),
            venue_operator_headers(venue["id"]),
        )
    )
    assert_assessment(
        paid,
        ASSESSMENT_KIND_INITIAL,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        ASSESSMENT_STATUS_PAID,
        paid=_BAR_GRILL_ANNUAL_FEE_CENTS,
    )

    settled = venue_row(api, venue["id"])
    assert_venue_ledger(
        settled,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
    )
    assert_ledger_identity(settled)
    assert_license_dimensions(
        license_row(api, licence["id"]), COVERAGE_ACTIVE, BILLING_PAID
    )

    validate_error(
        api.pay_assessment(
            assessment["id"],
            payment_payload(1),
            venue_operator_headers(venue["id"]),
        ),
        ERR_ASSESSMENT_NOT_ISSUED,
    )
    unchanged = venue_row(api, venue["id"])
    assert_venue_ledger(
        unchanged,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
        0,
        _BAR_GRILL_ANNUAL_FEE_CENTS,
    )


def test_calc_rider_fee_single_rounding_over_whole_days(api):
    """Each rider fee is rounded exactly once, at the very end of one expression.

    Three riders of 15, 7 and 3 covered days on a licence billing 90017 cents
    come out at 4994, 2331 and 999 cents: every one of them has a fractional
    part that only survives if the day fraction and the 13500-basis-point peak
    factor stay inside a single expression. The annual-term window that
    activation created still costs nothing, and the three rider assessments push
    the venue's outstanding balance to 98341 cents.

    PRD §3.6: "For a `SEASONAL_EVENT_RIDER` or a `FESTIVAL_RIDER`,
    `rider_fee_cents` is derived from the owning licence's `annual_fee_cents` as
    it stands **at the moment the rider is created**: multiply that
    `annual_fee_cents` by the window's `covered_day_count`, multiply by the
    seasonal peak factor of 13500 basis points, divide by the product of 365
    term-days and 10000, and round half up to whole cents — a **single** rounding
    step at the very end, with the day fraction and the peak factor combined
    inside one expression rather than rounded independently."

    PRD §3.6: "An `ANNUAL_TERM` window always has `rider_fee_cents` of 0."

    PRD §3.6: "`covered_day_count` is computed as the whole days from
    `window_start` up to `window_end`; because the interval is half-open, a
    window that ends exactly where the next begins contributes its days once and
    only once."

    PRD §3.6: "Creating a priced rider issues a `FeeAssessment` with
    `assessment_kind` `SEASONAL_RIDER` for exactly that `rider_fee_cents`, in
    `ISSUED` status with `paid_amount_cents` at 0 and `due_date` 30 days after
    the logical clock instant."

    Design: Corner/calculations/corner_seasonal_rider_fee_single_rounding_over_whole_days
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)
    assert_money(
        licence["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )

    # 90017 * 15 * 13500 / (365 * 10000) is 4994.09, which rounds to 4994.
    fifteen_days = given_coverage_window(
        api,
        licence["id"],
        "2026-12-20T00:00:00Z",
        "2027-01-04T00:00:00Z",
        WINDOW_KIND_SEASONAL_EVENT_RIDER,
    )
    assert_count(fifteen_days["covered_day_count"], 15, "covered_day_count")
    assert_days_apart(
        fifteen_days["window_start"], fifteen_days["window_end"], 15
    )
    assert_money(fifteen_days["rider_fee_cents"], 4994, "rider_fee_cents")

    # 90017 * 7 * 13500 / (365 * 10000) is 2330.57, which rounds to 2331.
    seven_days = given_coverage_window(
        api,
        licence["id"],
        "2027-01-04T00:00:00Z",
        "2027-01-11T00:00:00Z",
        WINDOW_KIND_FESTIVAL_RIDER,
    )
    assert_count(seven_days["covered_day_count"], 7, "covered_day_count")
    assert_money(seven_days["rider_fee_cents"], 2331, "rider_fee_cents")

    # 90017 * 3 * 13500 / (365 * 10000) is 998.82, which rounds to 999.
    three_days = given_coverage_window(
        api,
        licence["id"],
        "2027-02-01T00:00:00Z",
        "2027-02-04T00:00:00Z",
        WINDOW_KIND_SEASONAL_EVENT_RIDER,
    )
    assert_count(three_days["covered_day_count"], 3, "covered_day_count")
    assert_money(three_days["rider_fee_cents"], 999, "rider_fee_cents")

    annual = find_row(
        windows_of_license(api, licence["id"]), window_kind=WINDOW_KIND_ANNUAL_TERM
    )
    assert_count(annual["covered_day_count"], TERM_LENGTH_DAYS, "covered_day_count")
    assert_money(annual["rider_fee_cents"], 0, "rider_fee_cents")
    assert annual["status"] == WINDOW_STATUS_ACTIVE, (
        f"expected an ACTIVE annual window, got {annual['status']!r}"
    )

    billed = assessments_of_license(api, licence["id"])
    assert len(billed) == 4, f"expected four assessments, got {len(billed)}"
    rider_amounts = [
        row["amount_cents"]
        for row in billed
        if row["assessment_kind"] == ASSESSMENT_KIND_SEASONAL_RIDER
    ]
    assert rider_amounts == [4994, 2331, 999], (
        f"expected the three rider fees in creation order, got {rider_amounts}"
    )

    ledger = venue_row(api, venue["id"])
    total = _BAR_GRILL_ANNUAL_FEE_CENTS + 4994 + 2331 + 999
    assert_money(total, 98341, "expected total billed")
    assert_venue_ledger(ledger, total, 0, 0, total)
    assert_ledger_identity(ledger)


def test_calc_posture_counts_only_active_licenses(api):
    """A licence awaiting activation contributes nothing to coverage.

    While the minted licence still sits in pending activation the venue's
    covered share is 0 basis points and its posture is uncovered, and the
    society counts no licensed venue. Activation, which is also what creates the
    annual coverage window spanning the current instant, lifts the share to
    BMI's 4600 basis points and the posture to partially covered.

    PRD §2.10: "Precisely, `covered_share_bp` on a `Venue` is the sum of
    `repertoire_share_bp` over the **distinct** societies for which there exists
    a `License` whose `venue_id` is this venue, whose `society_id` is that
    society, whose `coverage_status` is `ACTIVE`, and which has at least one
    `CoverageWindow` in `ACTIVE` status whose half-open span from `window_start`
    up to but not including `window_end` contains the current logical clock
    instant."

    PRD §2.10: "Licences in `PENDING_ACTIVATION`, `SUSPENDED`, `EXPIRED` or
    `TERMINATED` contribute nothing at all."

    PRD §2.10: "`coverage_posture` is then read off that sum: `FULLY_COVERED`
    when `covered_share_bp` is at least 9500, `PARTIALLY_COVERED` when
    `covered_share_bp` is at least 1 and below 9500, and `UNCOVERED` when
    `covered_share_bp` is exactly 0."

    PRD §2.10: "Finally, each `Society` publishes `licensed_venue_count`: the
    number of distinct `Venue` rows holding at least one `License` for that
    society whose `coverage_status` is `ACTIVE`."

    Design: Corner/calculations/corner_coverage_posture_counts_only_active_licenses
    """
    bmi = given_society(api, bmi_payload())
    assert_bp(bmi["repertoire_share_bp"], SHARE_BMI_BP, "repertoire_share_bp")
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    application = given_approved_application(
        api, venue, bmi["id"], CLOCK_START_INSTANT
    )
    minted = license_of_application(api, application["id"])
    assert minted["coverage_status"] == COVERAGE_PENDING_ACTIVATION, (
        f"expected PENDING_ACTIVATION, got {minted['coverage_status']!r}"
    )
    assert windows_of_license(api, minted["id"]) == [], (
        "no coverage window exists before activation"
    )

    before = venue_row(api, venue["id"])
    assert_coverage(before, 0, POSTURE_UNCOVERED)
    society_before = validate_success(api.get_society(bmi["id"], admin_headers()))
    assert_count(society_before["licensed_venue_count"], 0, "licensed_venue_count")

    activated = activate(api, minted["id"])
    assert activated["coverage_status"] == COVERAGE_ACTIVE, (
        f"expected ACTIVE, got {activated['coverage_status']!r}"
    )

    after = venue_row(api, venue["id"])
    assert_coverage(after, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
    society_after = validate_success(api.get_society(bmi["id"], admin_headers()))
    assert_count(society_after["licensed_venue_count"], 1, "licensed_venue_count")

    windows = windows_of_license(api, minted["id"])
    assert len(windows) == 1, f"expected one coverage window, got {len(windows)}"
    assert windows[0]["window_kind"] == WINDOW_KIND_ANNUAL_TERM, (
        f"expected an ANNUAL_TERM window, got {windows[0]['window_kind']!r}"
    )
    assert windows[0]["status"] == WINDOW_STATUS_ACTIVE, (
        f"expected an ACTIVE window, got {windows[0]['status']!r}"
    )


def test_calc_schedule_selection_ignores_draft_schedules(api):
    """A newer schedule still in draft cannot price a licence.

    Two schedules exist for the same society and venue category: an effective
    one from January carrying the default 10000-basis-point adjustment, and a
    later, unpublished one carrying 11500. Selection sees only the effective row,
    so the fee is 90017 cents and not the 99216 cents the draft's adjustment
    would have produced, and the pinned-licence tally lands on the effective
    schedule alone.

    PRD §3.2: "The eligible candidates are `RateSchedule` rows whose
    `society_id` is the target society, whose `venue_category` equals the venue's
    `venue_category`, whose `status` is `EFFECTIVE`, and whose `effective_from`
    is at or before the current logical clock instant."

    PRD §3.2: "`DRAFT` and `SUPERSEDED` schedules are never eligible."

    PRD §3.4: "Finally, `pinned_license_count` on the winning schedule increases
    by 1."

    Design: Corner/calculations/corner_rate_schedule_selection_ignores_draft_schedules
    """
    bmi = given_society(api, bmi_payload())
    effective = given_effective_schedule(
        api, bmi["id"], _CATEGORY_BAR_GRILL, "2026-01-01T00:00:00Z"
    )
    assert effective["status"] == SCHEDULE_STATUS_EFFECTIVE, (
        f"expected an EFFECTIVE schedule, got {effective['status']!r}"
    )
    assert_bp(effective["adjustment_bp"], DEFAULT_ADJUSTMENT_BP, "adjustment_bp")

    unpublished = given_draft_schedule(
        api,
        bmi["id"],
        _CATEGORY_BAR_GRILL,
        "2026-03-01T00:00:00Z",
        adjustment_bp=11500,
    )
    assert unpublished["status"] == SCHEDULE_STATUS_DRAFT, (
        f"expected a DRAFT schedule, got {unpublished['status']!r}"
    )
    assert_bp(unpublished["adjustment_bp"], 11500, "adjustment_bp")

    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)

    assert licence["rate_schedule_id"] == effective["id"], (
        "the effective January schedule is the only eligible candidate"
    )
    assert_count(
        licence["pinned_schedule_version"],
        effective["schedule_version"],
        "pinned_schedule_version",
    )
    assert_money(
        licence["annual_fee_cents"], _BAR_GRILL_ANNUAL_FEE_CENTS, "annual_fee_cents"
    )
    # 11500 bp on the base and occupancy components would have given a subtotal
    # of 196080, a scaled 215688 and a 4600 bp slice of 99216.
    assert_not_money(licence["annual_fee_cents"], 99216, "annual_fee_cents")

    effective_after = validate_success(
        api.get_rate_schedule(effective["id"], admin_headers())
    )
    assert_count(effective_after["pinned_license_count"], 1, "pinned_license_count")
    assert effective_after["status"] == SCHEDULE_STATUS_EFFECTIVE, (
        "publication is not undone by pinning a licence"
    )

    unpublished_after = validate_success(
        api.get_rate_schedule(unpublished["id"], admin_headers())
    )
    assert_count(unpublished_after["pinned_license_count"], 0, "pinned_license_count")
    assert unpublished_after["status"] == SCHEDULE_STATUS_DRAFT, (
        "an unselected schedule stays in DRAFT"
    )


def test_calc_match_case_insensitive_oldest_registration_wins(api):
    """Matching ignores case and padding, and the earliest registration wins.

    Two societies register the identical title and writer, ASCAP first and BMI
    second. A performance reported as " blue horizon " by " a. reed " matches
    despite the capitalisation and the surrounding spaces, and it matches
    ASCAP's older registration even though BMI controls the larger repertoire
    share — registration order is consulted before share. Coverage is a separate
    question and is answered by the entry's own affiliation.

    PRD §3.8: "**Matching** looks for a registered work whose `title`, compared
    case-insensitively after trimming surrounding whitespace, equals the entry's
    `work_title`, and whose `writer_name`, compared the same way, equals the
    entry's `writer_name`."

    PRD §3.8: "Candidates are ranked by `created_at` ascending; ties are broken
    by the `repertoire_share_bp` of the work's registering society, descending,
    and then by that society's `society_code` in ascending lexicographic order."

    PRD §3.8: "Every `RepertoireWork` row is a candidate regardless of which
    society registered it."

    Design: Corner/calculations/corner_repertoire_match_is_case_insensitive_and_oldest_registration_wins
    """
    ascap, bmi = given_societies(api, ascap_payload(), bmi_payload())
    assert_bp(ascap["repertoire_share_bp"], SHARE_ASCAP_BP, "repertoire_share_bp")
    assert_bp(bmi["repertoire_share_bp"], SHARE_BMI_BP, "repertoire_share_bp")

    older = given_work(api, ascap["id"], "Blue Horizon", "A. Reed")
    # PRD §2.4: nothing reads the wall clock, so ``created_at`` is minted from
    # the logical clock instant.  The clock therefore has to move between the two
    # registrations for the second row to be genuinely newer than the first —
    # registered at one instant they would share a ``created_at``, the primary
    # "ranked by `created_at` ascending" key would tie, and the share tie-break
    # rather than registration order would decide.
    move_clock(api, _SECOND_REGISTRATION_INSTANT)
    newer = given_work(api, bmi["id"], "Blue Horizon", "A. Reed")
    reset_clock(api)

    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], CLOCK_START_INSTANT)

    report = given_draft_report(
        api,
        licence["id"],
        venue["id"],
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
    )
    appended = given_setlist_entry(
        api,
        report["id"],
        venue["id"],
        " blue horizon ",
        " a. reed ",
        _AFFILIATION_BMI,
        "2026-09-05T20:00:00Z",
        300,
        USE_TYPE_LIVE,
    )
    assert appended["is_matched"] is False, (
        "matching runs at submission, not at append"
    )

    submitted = _submit_report(api, report["id"], venue["id"])
    assert_count(submitted["reported_entry_count"], 1, "reported_entry_count")
    assert_count(submitted["matched_entry_count"], 1, "matched_entry_count")
    assert_count(submitted["uncovered_entry_count"], 0, "uncovered_entry_count")
    assert_pct(submitted["unmatched_share_pct"], 0.00, "unmatched_share_pct")
    assert_pct(submitted["uncovered_share_pct"], 0.00, "uncovered_share_pct")
    assert_money(submitted["gap_exposure_cents"], 0, "gap_exposure_cents")

    entries = setlist_entries_of(api, report["id"])
    assert len(entries) == 1, f"expected one setlist entry, got {len(entries)}"
    matched = entries[0]
    assert matched["is_matched"] is True, (
        "case and surrounding whitespace are set aside for the comparison"
    )
    assert matched["matched_work_id"] == older["id"], (
        "the earlier registration outranks the larger repertoire share"
    )
    assert matched["matched_work_id"] != newer["id"], (
        "the later registration must not win on its society's share"
    )
    assert matched["is_covered"] is True, (
        "the entry names BMI, which holds this venue's active licence"
    )
    assert matched["work_title"] == " blue horizon ", (
        "the reported title is stored as submitted; only the comparison trims"
    )


def test_calc_type_per_program_requires_category_and_nights(api):
    """A per-programme licence is granted only to the right category and cadence.

    Both venues ask for a per-programme licence. The concert hall with three
    weekly live nights satisfies every clause of that row and gets it, billing
    463761 cents from the fourth occupancy tier; the bar and grill fails the row
    on its category and on its four live nights and falls through to a blanket
    licence. Both licences still require reporting, because that flag turns on
    the licence type together with the venue's music use.

    PRD §3.4: "Otherwise, when `requested_license_type` is `PER_PROGRAM`, the
    venue's `venue_category` is `CONCERT_HALL` or `NIGHTCLUB`, and the venue's
    `weekly_live_performance_nights` is at most 3, `assigned_license_type`
    becomes `PER_PROGRAM`."

    PRD §3.4: "Otherwise `assigned_license_type` becomes `BLANKET`."

    PRD §3.4: "With the type assigned, approval computes
    `provisional_annual_fee_cents` on the application using the **provisional
    declared** variant of the annual-fee calculation in §3.5, sets the
    application's `status` to `APPROVED`, and increments its `version`. It then
    creates the `License` row: `coverage_status` `PENDING_ACTIVATION` and
    `billing_status` `UNBILLED`; `venue_id`, `society_id` and `application_id`
    copied from the application; `rate_schedule_id` and `pinned_schedule_version`
    taken from the winning schedule of rate-schedule selection; `license_type`
    equal to the freshly assigned `assigned_license_type`; `term_start` equal to
    `requested_term_start`; `term_end` exactly 365 days after `term_start`;
    `renewal_of_license_id` null; both `provisional_annual_fee_cents` and
    `annual_fee_cents` set to the provisional fee just computed;
    `verified_fee_delta_cents` at 0; `accepted_report_count` at 0;
    `renewal_issued_at` and `suspension_reason` at null; and `reporting_required`
    derived by its own rule — it is true exactly when the licence's
    `license_type` is `BLANKET` or `PER_PROGRAM` **and** the venue's
    `music_use_profile` is `LIVE_ONLY` or `MIXED`, and false otherwise."

    Design: Corner/calculations/corner_license_type_per_program_requires_category_and_nights
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_CONCERT_HALL)
    given_effective_schedule(api, bmi["id"], _CATEGORY_BAR_GRILL)

    hall = given_venue(api, mid_concert_hall_venue_payload())
    grill = given_venue(api, bar_grill_venue_payload())

    hall_application = given_approved_application(
        api,
        hall,
        bmi["id"],
        CLOCK_START_INSTANT,
        requested_license_type=_LICENSE_TYPE_PER_PROGRAM,
    )
    assert hall_application["assigned_license_type"] == _LICENSE_TYPE_PER_PROGRAM, (
        f"expected PER_PROGRAM, got {hall_application['assigned_license_type']!r}"
    )

    grill_application = given_approved_application(
        api,
        grill,
        bmi["id"],
        CLOCK_START_INSTANT,
        requested_license_type=_LICENSE_TYPE_PER_PROGRAM,
    )
    assert grill_application["assigned_license_type"] == _LICENSE_TYPE_BLANKET, (
        "a bar and grill running four live nights cannot hold a per-programme "
        f"licence, got {grill_application['assigned_license_type']!r}"
    )

    hall_license = activate(
        api, license_of_application(api, hall_application["id"])["id"]
    )
    assert hall_license["license_type"] == _LICENSE_TYPE_PER_PROGRAM, (
        f"expected a PER_PROGRAM licence, got {hall_license['license_type']!r}"
    )
    assert hall_license["reporting_required"] is True, (
        "a per-programme licence over a LIVE_ONLY venue must report"
    )
    # Fourth tier: 265000 + 385 * 800 = 308000 and 10000000 * 250 / 10000 =
    # 250000 give a subtotal of 823000; LIVE_ONLY at 11500 bp plus three live
    # nights at 250 bp scales that to 1008175; and 4600 bp of 1008175 is
    # 463760.50, which rounds half up to 463761.
    assert_money(hall_license["annual_fee_cents"], 463761, "annual_fee_cents")
    assert_not_money(hall_license["annual_fee_cents"], 463760, "annual_fee_cents")
    assert_money(hall_license["verified_fee_delta_cents"], 0, "verified_fee_delta_cents")
    assert_days_apart(
        hall_license["term_start"], hall_license["term_end"], TERM_LENGTH_DAYS
    )

    grill_license = license_of_application(api, grill_application["id"])
    assert grill_license["license_type"] == _LICENSE_TYPE_BLANKET, (
        f"expected a BLANKET licence, got {grill_license['license_type']!r}"
    )
    assert grill_license["reporting_required"] is True, (
        "a blanket licence over a MIXED venue must report too"
    )


def test_calc_type_bgm_exempt_zeroes_the_whole_fee(api):
    """An exempt venue's licence is activated for free and bills nothing at all.

    The exemption verdict makes the first row of the licence-type table match, so
    the operator's blanket request is overridden with an exempt licence, both fee
    fields are 0 cents, no assessment is raised, and the venue's four ledger
    totals stay at 0. Coverage is unaffected: the exempt licence is active and
    still carries BMI's 4600 basis points.

    PRD §3.4: "When the venue's `bgm_exemption_status` is `EXEMPT`,
    `assigned_license_type` becomes `BGM_EXEMPT`."

    PRD §3.5: "A licence whose `license_type` is `BGM_EXEMPT` has a fee of 0
    cents."

    PRD §3.4: "When `assigned_license_type` came out as `BGM_EXEMPT`, both
    `provisional_annual_fee_cents` and `annual_fee_cents` on the created licence
    are 0."

    PRD §3.6: "When `license_type` **is** `BGM_EXEMPT`, no assessment is created
    at all and `billing_status` stays `UNBILLED` — the exempt licence is
    activated for free."

    Design: Corner/calculations/corner_license_type_bgm_exempt_zeroes_the_whole_fee
    """
    bmi = given_society(api, bmi_payload())
    given_effective_schedule(api, bmi["id"], _CATEGORY_FITNESS_STUDIO)
    created = given_venue(
        api,
        fitness_studio_venue_payload("Pulse Fitness Studio", **bgm_survey_fields()),
    )
    exempt_venue = get_success_data(
        api.run_exemption_analysis(created["id"], admin_headers())
    )
    assert exempt_venue["bgm_exemption_status"] == EXEMPTION_EXEMPT, (
        f"expected EXEMPT, got {exempt_venue['bgm_exemption_status']!r}"
    )
    assert (
        exempt_venue["bgm_exemption_reason"] == REASON_WITHIN_SIZE_AND_SPEAKER_LIMITS
    ), "the survey sits inside every limit"

    application = given_approved_application(
        api, exempt_venue, bmi["id"], CLOCK_START_INSTANT
    )
    assert application["assigned_license_type"] == _LICENSE_TYPE_BGM_EXEMPT, (
        "the exemption verdict overrides the operator's blanket request, got "
        f"{application['assigned_license_type']!r}"
    )
    assert_money(
        application["provisional_annual_fee_cents"],
        0,
        "provisional_annual_fee_cents",
    )

    minted = license_of_application(api, application["id"])
    licence = activate(api, minted["id"])
    assert licence["license_type"] == _LICENSE_TYPE_BGM_EXEMPT, (
        f"expected a BGM_EXEMPT licence, got {licence['license_type']!r}"
    )
    assert_money(
        licence["provisional_annual_fee_cents"], 0, "provisional_annual_fee_cents"
    )
    assert_money(licence["annual_fee_cents"], 0, "annual_fee_cents")
    assert_money(licence["verified_fee_delta_cents"], 0, "verified_fee_delta_cents")
    assert licence["reporting_required"] is False, (
        "an exempt licence carries no reporting duty"
    )
    # Neither the schedule's floor nor the unclamped scaled amount may reappear:
    # 30000 cents at 4600 bp is 13800 and the unclamped 29520 is 13579.
    assert_not_money(licence["annual_fee_cents"], 13800, "annual_fee_cents")
    assert_not_money(licence["annual_fee_cents"], 13579, "annual_fee_cents")
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_UNBILLED)

    assert assessments_of_license(api, licence["id"]) == [], (
        "an exempt licence raises no assessment"
    )
    assert assessments_of_venue(api, created["id"]) == [], (
        "the venue's ledger sees no assessment either"
    )

    ledger = venue_row(api, created["id"])
    assert_venue_ledger(ledger, 0, 0, 0, 0)
    assert_ledger_identity(ledger)
    assert_coverage(ledger, SHARE_BMI_BP, POSTURE_PARTIALLY_COVERED)
