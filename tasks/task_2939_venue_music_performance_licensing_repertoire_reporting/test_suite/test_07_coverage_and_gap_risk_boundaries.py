"""
The two inclusive numeric boundaries of the licensing contract, hit dead-on.

The first is the venue's multi-society coverage roll-up: three societies whose
repertoire shares add up to exactly 9500 basis points let the full-coverage
threshold be landed on precisely rather than straddled, and suspending the
smallest of the three licences steps back off it again.  The second is the
venue's two-decimal repertoire gap-risk score against the 60.00 escalation
threshold: one report lands a hundredth below it and opens no audit case, while
a report differing only in a single performance's duration lands on 60.00
exactly and escalates.
"""

from test_helpers import (
    AUDIT_TRIGGER_GAP_RISK_ESCALATION,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    CASE_STATUS_OPEN,
    CLOCK_START_INSTANT,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    COVERAGE_SUSPENDED,
    POSTURE_FULLY_COVERED,
    POSTURE_PARTIALLY_COVERED,
    REPORT_STATUS_SUBMITTED,
    SUSPENSION_REASON_OPERATOR_REQUEST,
    USE_TYPE_LIVE,
    admin_headers,
    ascap_payload,
    assert_bp,
    assert_coverage,
    assert_count,
    assert_empty_list,
    assert_instant_equals,
    assert_license_dimensions,
    assert_money,
    assert_pct,
    assert_venue_ledger,
    bar_grill_venue_payload,
    bmi_payload,
    cases_of_venue,
    given_active_license,
    given_approved_application,
    given_draft_report,
    given_effective_schedule,
    given_setlist_entry,
    given_society,
    given_venue,
    given_work,
    license_of_application,
    license_row,
    report_row,
    sesac_payload,
    suspend_payload,
    validate_success,
    venue_operator_headers,
    venue_row,
)

# The bar and grill priced by every schedule these tests publish.
_VENUE_CATEGORY = "BAR_GRILL"
_SCHEDULE_FROM = "2026-01-01T00:00:00Z"

# Terms that begin at the logical clock's start-up instant, so the annual
# coverage window created by activation contains "now" and the licence really
# does count towards the venue's covered share.
_TERM_START = CLOCK_START_INSTANT

# The three verified annual fees for this venue, one per society share.
_FEE_BMI_CENTS = 90017
_FEE_ASCAP_CENTS = 86104
_FEE_SESAC_CENTS = 9785
_FEE_ALL_THREE_CENTS = _FEE_BMI_CENTS + _FEE_ASCAP_CENTS + _FEE_SESAC_CENTS

# Coverage sums either side of the inclusive full-coverage threshold.
_TWO_SOCIETY_SHARE_BP = 9000
_THREE_SOCIETY_SHARE_BP = 9500


def _build_two_covered_and_one_pending(api):
    """Three societies, three published schedules, one venue, three licences.

    BMI (4600 bp) and ASCAP (4400 bp) end up ``ACTIVE`` so the venue sits at
    9000 bp, and SESAC (500 bp) is left in ``PENDING_ACTIVATION`` so a single
    activation call is what carries the venue onto the threshold.  The venue row
    is re-read before every application filing because each preceding call
    advanced its revision counter.
    """
    bmi = given_society(api, bmi_payload())
    ascap = given_society(api, ascap_payload())
    sesac = given_society(api, sesac_payload())
    for society in (bmi, ascap, sesac):
        given_effective_schedule(
            api, society["id"], _VENUE_CATEGORY, _SCHEDULE_FROM
        )
    venue = given_venue(api, bar_grill_venue_payload())
    license_bmi = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _TERM_START
    )
    license_ascap = given_active_license(
        api, venue_row(api, venue["id"]), ascap["id"], _TERM_START
    )
    application_sesac = given_approved_application(
        api, venue_row(api, venue["id"]), sesac["id"], _TERM_START
    )
    license_sesac = license_of_application(api, application_sesac["id"])
    return {
        "bmi": bmi,
        "ascap": ascap,
        "sesac": sesac,
        "venue": venue,
        "license_bmi": license_bmi,
        "license_ascap": license_ascap,
        "license_sesac": license_sesac,
    }


def test_boundary_coverage_two_societies_sit_below_the_full_coverage_threshold(api):
    """Two ACTIVE licences put the venue at 9000 bp, and the pending third adds nothing.

    PRD §2.10: "Licences in `PENDING_ACTIVATION`, `SUSPENDED`, `EXPIRED` or
    `TERMINATED` contribute nothing at all."

    Design: Difficulty/boundary_precision_check/boundary_covered_share_bp_exactly_at_full_coverage_threshold
    """
    world = _build_two_covered_and_one_pending(api)

    venue = venue_row(api, world["venue"]["id"])
    assert_coverage(venue, _TWO_SOCIETY_SHARE_BP, POSTURE_PARTIALLY_COVERED)

    pending = license_row(api, world["license_sesac"]["id"])
    assert_license_dimensions(pending, COVERAGE_PENDING_ACTIVATION, BILLING_UNBILLED)
    assert_bp(
        validate_success(api.get_society(world["sesac"]["id"], admin_headers()))[
            "repertoire_share_bp"
        ],
        _THREE_SOCIETY_SHARE_BP - _TWO_SOCIETY_SHARE_BP,
        "SESAC repertoire_share_bp",
    )


def test_boundary_coverage_exactly_9500_basis_points_is_fully_covered(api):
    """Activating the 500 bp licence lands the venue on 9500 bp, which is FULLY_COVERED.

    PRD §2.10: "The full-coverage boundary is inclusive — exactly 9500 basis
    points is `FULLY_COVERED`."

    Design: Difficulty/boundary_precision_check/boundary_covered_share_bp_exactly_at_full_coverage_threshold
    """
    world = _build_two_covered_and_one_pending(api)
    before = venue_row(api, world["venue"]["id"])
    assert_coverage(before, _TWO_SOCIETY_SHARE_BP, POSTURE_PARTIALLY_COVERED)

    activated = validate_success(
        api.activate_license(world["license_sesac"]["id"], admin_headers())
    )
    assert_license_dimensions(activated, COVERAGE_ACTIVE, BILLING_INVOICED)

    after = venue_row(api, world["venue"]["id"])
    assert_coverage(after, _THREE_SOCIETY_SHARE_BP, POSTURE_FULLY_COVERED)


def test_boundary_coverage_suspending_the_smallest_share_steps_back_off_the_threshold(api):
    """Withdrawing the 500 bp share drops 9500 back to 9000, proving the test is >= not >.

    PRD §3.7: "The venue's `covered_share_bp` and `coverage_posture` are
    recomputed — this society's share leaves the sum, because §2.10 counts only
    `ACTIVE` licences — the society's `licensed_venue_count` is recomputed, and
    `Venue.version` increments by 1."

    Design: Difficulty/boundary_precision_check/boundary_covered_share_bp_exactly_at_full_coverage_threshold
    """
    world = _build_two_covered_and_one_pending(api)
    validate_success(
        api.activate_license(world["license_sesac"]["id"], admin_headers())
    )
    assert_coverage(
        venue_row(api, world["venue"]["id"]),
        _THREE_SOCIETY_SHARE_BP,
        POSTURE_FULLY_COVERED,
    )

    suspended = validate_success(
        api.suspend_license(
            world["license_sesac"]["id"],
            suspend_payload(SUSPENSION_REASON_OPERATOR_REQUEST),
            admin_headers(),
        )
    )
    assert suspended["coverage_status"] == COVERAGE_SUSPENDED, (
        f"expected a SUSPENDED licence, got {suspended['coverage_status']!r}"
    )

    fallen_back = venue_row(api, world["venue"]["id"])
    assert_coverage(fallen_back, _TWO_SOCIETY_SHARE_BP, POSTURE_PARTIALLY_COVERED)
    assert_bp(
        validate_success(api.get_society(world["sesac"]["id"], admin_headers()))[
            "repertoire_share_bp"
        ],
        _THREE_SOCIETY_SHARE_BP - _TWO_SOCIETY_SHARE_BP,
        "SESAC repertoire_share_bp",
    )


def test_boundary_coverage_three_apportioned_fees_stay_inside_the_delinquency_tolerance(api):
    """The three society slices of one clamped amount, and the ledger they build.

    PRD §3.5: "Only now is the society's `repertoire_share_bp` applied: the
    clamped amount is multiplied by `repertoire_share_bp`, divided by 10000, and
    rounded half up to whole cents."

    PRD §2.9: "A venue is treated as **delinquent** when
    `outstanding_balance_cents` is strictly greater than a delinquency tolerance
    of 250000 cents — that is, when it owes more than two thousand five hundred
    dollars; owing exactly 250000 cents is *not* delinquent."

    Design: Difficulty/boundary_precision_check/boundary_covered_share_bp_exactly_at_full_coverage_threshold
    """
    world = _build_two_covered_and_one_pending(api)
    validate_success(
        api.activate_license(world["license_sesac"]["id"], admin_headers())
    )

    assert_money(
        license_row(api, world["license_bmi"]["id"])["annual_fee_cents"],
        _FEE_BMI_CENTS,
        "BMI annual_fee_cents",
    )
    assert_money(
        license_row(api, world["license_ascap"]["id"])["annual_fee_cents"],
        _FEE_ASCAP_CENTS,
        "ASCAP annual_fee_cents",
    )
    assert_money(
        license_row(api, world["license_sesac"]["id"])["annual_fee_cents"],
        _FEE_SESAC_CENTS,
        "SESAC annual_fee_cents",
    )

    venue = venue_row(api, world["venue"]["id"])
    assert_venue_ledger(venue, _FEE_ALL_THREE_CENTS, 0, 0, _FEE_ALL_THREE_CENTS)
    for key in ("license_bmi", "license_ascap", "license_sesac"):
        assert_license_dimensions(
            license_row(api, world[key]["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
        )


# ─── The gap-risk escalation threshold ────────────────────────────────────

# Only BMI licenses this venue, so every ASCAP-attributed performance is
# uncovered while every title remains a registered work.
_GAP_TERM_START = "2026-09-01T00:00:00Z"
_PERIOD_A = ("2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z")
_PERIOD_B = ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")

# Four performances shared by both reports: two covered BMI works weighing
# 1000 and 300, then two uncovered ASCAP works weighing 1000 each.
_SHARED_SETLIST = (
    ("Blue Horizon", "A. Reed", "BMI", 600),
    ("Harbour Lights", "A. Reed", "BMI", 180),
    ("Midnight Freight", "J. Vance", "ASCAP", 600),
    ("Copper Wire", "J. Vance", "ASCAP", 600),
)
_TAIL_TITLE = "Slow Fuse"
_TAIL_WRITER = "M. Ortiz"

# Report A: the fifth performance runs 360 seconds, weighing 600, so the
# uncovered weight is 2600 of 3900.
_TAIL_SECONDS_A = 360
_UNCOVERED_SHARE_A_PCT = 66.67
_GAP_EXPOSURE_A_CENTS = 60014
_GAP_RISK_SCORE_A = 59.34

# Report B: the same performance runs 420 seconds, weighing 700, so the
# uncovered weight is 2700 of 4000.
_TAIL_SECONDS_B = 420
_UNCOVERED_SHARE_B_PCT = 67.50
_GAP_EXPOSURE_B_CENTS = 60761
_GAP_RISK_SCORE_B = 60.00

_UNCOVERED_ENTRY_COUNT = 3


def _build_gap_risk_venue(api):
    """One BMI-licensed bar and grill whose whole reported repertoire is registered.

    ASCAP exists as a society and registers three of the five works, but holds
    no licence on this venue, which is what separates the matching question from
    the coverage question in the two share percentages.
    """
    bmi = given_society(api, bmi_payload())
    ascap = given_society(api, ascap_payload())
    given_effective_schedule(api, bmi["id"], _VENUE_CATEGORY, _SCHEDULE_FROM)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(
        api, venue_row(api, venue["id"]), bmi["id"], _GAP_TERM_START
    )
    for title, writer, affiliation, _seconds in _SHARED_SETLIST:
        society_id = bmi["id"] if affiliation == "BMI" else ascap["id"]
        given_work(api, society_id, title, writer)
    given_work(api, ascap["id"], _TAIL_TITLE, _TAIL_WRITER)
    return {"bmi": bmi, "ascap": ascap, "venue": venue, "license": licence}


def _fill_and_submit_report(api, world, period, day, tail_seconds):
    """Open a report over ``period``, append the five performances, submit it."""
    venue_id = world["venue"]["id"]
    report = given_draft_report(
        api, world["license"]["id"], venue_id, period[0], period[1]
    )
    minute = 0
    for title, writer, affiliation, seconds in _SHARED_SETLIST:
        given_setlist_entry(
            api,
            report["id"],
            venue_id,
            title,
            writer,
            affiliation,
            f"{day}T20:{minute:02d}:00Z",
            seconds,
            USE_TYPE_LIVE,
        )
        minute += 15
    given_setlist_entry(
        api,
        report["id"],
        venue_id,
        _TAIL_TITLE,
        _TAIL_WRITER,
        "ASCAP",
        f"{day}T21:00:00Z",
        tail_seconds,
        USE_TYPE_LIVE,
    )
    submitted = validate_success(
        api.submit_performance_report(report["id"], venue_operator_headers(venue_id))
    )
    assert submitted["status"] == REPORT_STATUS_SUBMITTED, (
        f"expected a SUBMITTED report, got {submitted['status']!r}"
    )
    return report


def test_boundary_gap_risk_registered_but_unlicensed_repertoire_is_uncovered_not_unmatched(api):
    """Every title is registered, so only the coverage share moves off zero.

    PRD §3.8: "`unmatched_share_pct` flags the entries whose `is_matched` is
    false — the performances for which no registered work exists at all."

    PRD §3.8: "`gap_exposure_cents` puts money on the second figure: it is the
    owning licence's `annual_fee_cents` multiplied by `uncovered_share_pct` and
    divided by 100, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/boundary_gap_risk_score_at_escalation_threshold
    """
    world = _build_gap_risk_venue(api)
    report = _fill_and_submit_report(
        api, world, _PERIOD_A, "2026-09-05", _TAIL_SECONDS_A
    )

    read = report_row(api, report["id"])
    assert_pct(read["unmatched_share_pct"], 0.00, "unmatched_share_pct")
    assert_pct(read["uncovered_share_pct"], _UNCOVERED_SHARE_A_PCT, "uncovered_share_pct")
    assert_count(read["uncovered_entry_count"], _UNCOVERED_ENTRY_COUNT, "uncovered_entry_count")
    assert_count(read["reported_entry_count"], len(_SHARED_SETLIST) + 1, "reported_entry_count")
    assert_money(read["gap_exposure_cents"], _GAP_EXPOSURE_A_CENTS, "gap_exposure_cents")


def test_boundary_gap_risk_score_one_hundredth_below_the_threshold_opens_no_case(api):
    """59.34 is under 60.00, so no audit case is opened and no hold is placed.

    PRD §3.8: "Multiply the source report's `uncovered_share_pct` by 0.8, add 6
    points for each distinct uncovered affiliation, round the sum half up to two
    decimal places, and cap the result at 100.00 — the score never exceeds 100.00
    however bad the setlist."

    PRD §3.8: "When the recomputed score is below 60.00, no case is created and
    Link 4 does not run at all."

    Design: Difficulty/boundary_precision_check/boundary_gap_risk_score_at_escalation_threshold
    """
    world = _build_gap_risk_venue(api)
    _fill_and_submit_report(api, world, _PERIOD_A, "2026-09-05", _TAIL_SECONDS_A)

    venue = venue_row(api, world["venue"]["id"])
    assert_pct(venue["gap_risk_score"], _GAP_RISK_SCORE_A, "gap_risk_score")
    assert venue["audit_hold"] is False, (
        "a sub-threshold gap risk score must leave audit_hold false"
    )
    assert_empty_list(
        api.list_audit_cases(admin_headers(), {"venue_id": world["venue"]["id"]})
    )


def test_boundary_gap_risk_score_exactly_sixty_escalates_into_an_audit_case(api):
    """One extra minute of uncovered music lands the score on 60.00, which escalates.

    PRD §3.8: "Because the recomputed `gap_risk_score` has reached the escalation
    threshold of 60.00 — the comparison is *at least* 60.00, so a score of
    exactly 60.00 escalates — the system opens an `AuditCase` on that venue by
    itself."

    PRD §3.8: "It is created with `audit_trigger` `GAP_RISK_ESCALATION`, `status`
    `OPEN`, `lookback_start` equal to the submitted report's `period_start`,
    `lookback_end` equal to its `period_end`, and `society_ids` listing the `id`
    of every `Society` whose `repertoire_share_bp` is greater than 0 that appears
    as the `society_affiliation` of an uncovered entry of that report, ordered by
    the society's `created_at` ascending."

    Design: Difficulty/boundary_precision_check/boundary_gap_risk_score_at_escalation_threshold
    """
    world = _build_gap_risk_venue(api)
    _fill_and_submit_report(api, world, _PERIOD_A, "2026-09-05", _TAIL_SECONDS_A)
    report_b = _fill_and_submit_report(
        api, world, _PERIOD_B, "2026-10-05", _TAIL_SECONDS_B
    )

    read_b = report_row(api, report_b["id"])
    assert_pct(read_b["uncovered_share_pct"], _UNCOVERED_SHARE_B_PCT, "uncovered_share_pct")
    assert_money(read_b["gap_exposure_cents"], _GAP_EXPOSURE_B_CENTS, "gap_exposure_cents")

    venue = venue_row(api, world["venue"]["id"])
    assert_pct(venue["gap_risk_score"], _GAP_RISK_SCORE_B, "gap_risk_score")
    assert venue["audit_hold"] is True, (
        "reaching the escalation threshold must set audit_hold true"
    )

    cases = cases_of_venue(api, world["venue"]["id"])
    assert len(cases) == 1, f"expected exactly one audit case, got {len(cases)}"
    case = cases[0]
    assert case["audit_trigger"] == AUDIT_TRIGGER_GAP_RISK_ESCALATION, (
        f"audit_trigger: expected GAP_RISK_ESCALATION, got {case['audit_trigger']!r}"
    )
    assert case["status"] == CASE_STATUS_OPEN, (
        f"a self-opened case starts OPEN, got {case['status']!r}"
    )
    assert case["society_ids"] == [world["ascap"]["id"]], (
        "only the uncovered affiliation's society belongs in scope, got "
        f"{case['society_ids']!r}"
    )
    assert_instant_equals(case["lookback_start"], _PERIOD_B[0], "lookback_start")
    assert_instant_equals(case["lookback_end"], _PERIOD_B[1], "lookback_end")
