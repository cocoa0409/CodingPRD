"""
The two multi-step ripples of the licensing contract, link by link.

The first half follows a rate-court-ordered schedule publication: the incumbent
schedule is superseded, the licence that followed it is re-pinned and re-rated, a
prorated true-up invoice is raised for the difference, and the venue's fee ledger
absorbs it.  The second half follows a setlist report submission: matching writes
the uncovered share, that share drives the venue's gap risk, the risk opens an
audit case and puts the venue on hold, and the hold pushes the venue's still
pending application back for revision.  Each test pins one link group so a break
localises to the link that broke.
"""

from test_helpers import (
    APPLICATION_STATUS_APPROVED,
    APPLICATION_STATUS_RETURNED_FOR_REVISION,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_KIND_RATE_CHANGE_TRUEUP,
    ASSESSMENT_STATUS_ISSUED,
    AUDIT_TRIGGER_GAP_RISK_ESCALATION,
    BILLING_INVOICED,
    CASE_STATUS_OPEN,
    COVERAGE_ACTIVE,
    DELINQUENCY_TOLERANCE_CENTS,
    RETURN_REASON_AUDIT_HOLD,
    SCHEDULE_STATUS_EFFECTIVE,
    SCHEDULE_STATUS_SUPERSEDED,
    USE_TYPE_LIVE,
    USE_TYPE_RECORDED,
    activate,
    admin_headers,
    application_row,
    ascap_payload,
    assert_assessment,
    assert_count,
    assert_license_dimensions,
    assert_money,
    assert_pct,
    assert_venue_ledger,
    assessments_of_license,
    bmi_payload,
    find_row,
    given_approved_application,
    given_draft_report,
    given_draft_schedule,
    given_effective_schedule,
    given_licensed_venue,
    given_setlist,
    given_societies,
    given_submitted_application,
    given_venue,
    given_work,
    license_of_application,
    license_row,
    move_clock,
    read_rows,
    report_row,
    sesac_payload,
    validate_success,
    venue_operator_headers,
    venue_row,
)

# ─── The rate-change world ────────────────────────────────────────────────
#
# The incumbent schedule prices the 180-occupancy MIXED bar and grill at 90017
# cents a year for a 4600 bp society (PRD §3.5, second occupancy tier, unadjusted
# schedule).  The successor schedule lifts the adjustment to 11500 bp, which
# scales the base and occupancy components but not the cover-revenue component,
# so the verified fee becomes 99216 cents.

_INITIAL_FEE_CENTS = 90017
_REVISED_FEE_CENTS = 99216

# The true-up is the 9199-cent rise prorated over the 335 whole days from
# 2026-10-01 to the term end of 2027-09-01, divided by 365 and rounded once.
_TRUEUP_CENTS = 8443
_LEDGER_TOTAL_CENTS = _INITIAL_FEE_CENTS + _TRUEUP_CENTS

_SUCCESSOR_ADJUSTMENT_BP = 11500
_SUCCESSOR_SCHEDULE_VERSION = 2
_SUCCESSOR_EFFECTIVE_FROM = "2026-09-15T00:00:00Z"
_RATE_COURT_ORDER_REF = "RC-2026-114"
_CLOCK_AT_PUBLICATION = "2026-10-01T00:00:00Z"

# ─── The setlist-gap world ────────────────────────────────────────────────
#
# Four performances weigh 500, 400, 120 and 1000 (whole minutes, part-minutes
# rounded up and capped at 10, times 100 for live and 40 for recorded).  Only the
# BMI performance is covered, so 1520 of the 2020 total weight is uncovered.

_UNCOVERED_SHARE_PCT = 75.25
_GAP_EXPOSURE_CENTS = 67738
_GAP_RISK_SCORE = 78.20

# Three distinct uncovered affiliations appear — ASCAP, SESAC and the entry the
# operator could not attribute at all.
_AFFILIATION_UNKNOWN = "UNKNOWN"

_ASCAP_TERM_START = "2026-10-01T00:00:00Z"


def _rate_change_world(api):
    """A venue on an ACTIVE licence, plus a draft successor schedule to publish.

    The logical clock is left at 2026-10-01, a month into the licence's term and
    past the successor schedule's own effective instant, so publication is
    permitted and the remaining term is 335 whole days.
    """
    world = given_licensed_venue(api)
    venue = world["venue"]
    successor = given_draft_schedule(
        api,
        world["society"]["id"],
        venue["venue_category"],
        _SUCCESSOR_EFFECTIVE_FROM,
        rate_court_order_ref=_RATE_COURT_ORDER_REF,
        adjustment_bp=_SUCCESSOR_ADJUSTMENT_BP,
    )
    move_clock(api, _CLOCK_AT_PUBLICATION)
    return {
        "venue": venue,
        "license": world["license"],
        "incumbent": world["schedule"],
        "successor": successor,
    }


def _publish(api, rate_schedule_id):
    """Publish one draft schedule as the society-side administrator."""
    return validate_success(
        api.publish_rate_schedule(rate_schedule_id, admin_headers())
    )


def _schedule_row(api, rate_schedule_id):
    """Re-read one rate schedule and its recomputed pinned-licence count."""
    return validate_success(api.get_rate_schedule(rate_schedule_id, admin_headers()))


def _setlist_gap_world(api):
    """A venue with one covered society, a pending application and a draft report.

    BMI licenses the venue for the whole reported period; ASCAP has only a
    submitted application, SESAC nothing at all, and one performance carries no
    attribution — so three quarters of the reported weight is uncovered.
    """
    bmi, ascap, sesac = given_societies(
        api, bmi_payload(), ascap_payload(), sesac_payload()
    )
    venue = given_venue(api)
    given_effective_schedule(api, bmi["id"], venue["venue_category"])
    covered_application = given_approved_application(api, venue, bmi["id"])
    licence = activate(
        api, license_of_application(api, covered_application["id"])["id"]
    )
    pending_application = given_submitted_application(
        api, venue_row(api, venue["id"]), ascap["id"], _ASCAP_TERM_START
    )
    given_work(api, bmi["id"], "Blue Horizon", "A. Reed")
    given_work(api, ascap["id"], "Midnight Freight", "J. Vance")
    given_work(api, sesac["id"], "Neon Sermon", "K. Ito")
    report = given_draft_report(api, licence["id"], venue["id"])
    given_setlist(
        api,
        report["id"],
        venue["id"],
        [
            {
                "title": "Blue Horizon",
                "writer": "A. Reed",
                "affiliation": bmi["society_code"],
                "when": "2026-09-05T20:00:00Z",
                "seconds": 300,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Midnight Freight",
                "writer": "J. Vance",
                "affiliation": ascap["society_code"],
                "when": "2026-09-05T20:30:00Z",
                "seconds": 240,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Neon Sermon",
                "writer": "K. Ito",
                "affiliation": sesac["society_code"],
                "when": "2026-09-05T21:00:00Z",
                "seconds": 180,
                "use_type": USE_TYPE_RECORDED,
            },
            {
                "title": "Unknown Jam",
                "writer": "Unknown",
                "affiliation": _AFFILIATION_UNKNOWN,
                "when": "2026-09-05T21:30:00Z",
                "seconds": 600,
                "use_type": USE_TYPE_LIVE,
            },
        ],
    )
    return {
        "venue": venue,
        "license": licence,
        "report": report,
        "covered_application": covered_application,
        "pending_application": pending_application,
    }


def _submit_report(api, report_id, venue_id):
    """Submit one draft report as the venue's own operator."""
    return validate_success(
        api.submit_performance_report(report_id, venue_operator_headers(venue_id))
    )


def test_cascade_rate_publication_supersedes_the_incumbent_and_repins_the_license(api):
    """Publishing the successor schedule supersedes the incumbent and re-pins its licence.

    The newly published schedule takes the next schedule version for the society
    and venue category pair, the schedule it displaces leaves the effective state,
    and the active licence that followed the displaced schedule now points at the
    successor — which is also where the two pinned-licence counts end up.

    PRD §3.2: "Its identity is resolved exactly: the candidate set is the
    `RateSchedule` rows whose `status` is `EFFECTIVE` for the same `society_id`
    and `venue_category`, ranked by `effective_from` descending, then
    `schedule_version` descending, with `created_at` descending as the tie-break;
    the top-ranked row moves from `EFFECTIVE` to `SUPERSEDED` and its `version`
    increments by 1."

    PRD §3.2: "Once the dust settles, `pinned_license_count` is recomputed on both
    the newly effective schedule and the superseded one, each counting the
    `License` rows whose `rate_schedule_id` equals that schedule's `id`."

    Design: Difficulty/transitive_cascade/cascade_a_rate_publish_supersede_repin_trueup_ledger
    """
    world = _rate_change_world(api)

    published = _publish(api, world["successor"]["id"])

    assert published["status"] == SCHEDULE_STATUS_EFFECTIVE, (
        f"the published schedule must be effective, got {published['status']!r}"
    )
    assert_count(
        published["schedule_version"],
        _SUCCESSOR_SCHEDULE_VERSION,
        "schedule_version",
    )

    incumbent = _schedule_row(api, world["incumbent"]["id"])
    assert incumbent["status"] == SCHEDULE_STATUS_SUPERSEDED, (
        "the displaced schedule must be superseded, "
        f"got {incumbent['status']!r}"
    )
    assert_count(incumbent["pinned_license_count"], 0, "pinned_license_count")

    successor = _schedule_row(api, world["successor"]["id"])
    assert_count(successor["pinned_license_count"], 1, "pinned_license_count")

    licence = license_row(api, world["license"]["id"])
    assert licence["rate_schedule_id"] == world["successor"]["id"], (
        "the active licence must follow the newly effective schedule, "
        f"but it is pinned to {licence['rate_schedule_id']!r}"
    )
    assert_count(
        licence["pinned_schedule_version"],
        _SUCCESSOR_SCHEDULE_VERSION,
        "pinned_schedule_version",
    )


def test_cascade_rate_repinning_re_rates_the_license_and_raises_the_true_up(api):
    """Re-pinning re-rates the licence and bills the prorated difference.

    The lifted schedule adjustment scales the base and occupancy components but
    not the cover-revenue component, so the verified annual fee rises from 90017
    to 99216 cents; the 9199-cent rise, prorated across the 335 whole days left in
    the term, becomes a single true-up invoice of 8443 cents alongside the
    original activation invoice.

    PRD §3.2: "Because a re-pinned licence's `annual_fee_cents` rose, a prorated
    `FeeAssessment` is raised against it with `assessment_kind`
    `RATE_CHANGE_TRUEUP` and `status` `ISSUED`."

    PRD §3.2: "Otherwise count the whole days remaining in the term, that is the
    whole days from the current logical clock instant up to the licence's
    `term_end`, multiply the fee difference by that day count, divide by 365, and
    round half up to whole cents in a single rounding step at the end."

    Design: Difficulty/transitive_cascade/cascade_a_rate_publish_supersede_repin_trueup_ledger
    """
    world = _rate_change_world(api)
    assert_money(
        world["license"]["annual_fee_cents"], _INITIAL_FEE_CENTS, "annual_fee_cents"
    )

    _publish(api, world["successor"]["id"])

    licence = license_row(api, world["license"]["id"])
    assert_money(licence["annual_fee_cents"], _REVISED_FEE_CENTS, "annual_fee_cents")

    raised = assessments_of_license(api, world["license"]["id"])
    assert len(raised) == 2, (
        "the licence must carry its activation invoice and one true-up, "
        f"but {len(raised)} assessments exist"
    )
    assert_assessment(
        find_row(raised, assessment_kind=ASSESSMENT_KIND_INITIAL),
        ASSESSMENT_KIND_INITIAL,
        _INITIAL_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )
    assert_assessment(
        find_row(raised, assessment_kind=ASSESSMENT_KIND_RATE_CHANGE_TRUEUP),
        ASSESSMENT_KIND_RATE_CHANGE_TRUEUP,
        _TRUEUP_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )


def test_cascade_rate_true_up_rolls_into_the_venue_ledger_without_delinquency(api):
    """The true-up invoice lands on the venue ledger and stops short of delinquency.

    Both running totals the new invoice touches rise by its amount, leaving the
    venue owing 98460 cents in total; because that is inside the delinquency
    tolerance the licence's billing dimension stays merely invoiced.

    PRD §3.2: "Because a new `ISSUED` assessment exists, the owning venue's
    `lifetime_assessed_cents` and `outstanding_balance_cents` each increase by the
    assessment's `amount_cents` and `Venue.version` increments by 1."

    PRD §2.9: "A venue is treated as **delinquent** when
    `outstanding_balance_cents` is strictly greater than a delinquency tolerance
    of 250000 cents — that is, when it owes more than two thousand five hundred
    dollars; owing exactly 250000 cents is *not* delinquent."

    Design: Difficulty/transitive_cascade/cascade_a_rate_publish_supersede_repin_trueup_ledger
    """
    world = _rate_change_world(api)

    _publish(api, world["successor"]["id"])

    venue = venue_row(api, world["venue"]["id"])
    assert_venue_ledger(venue, _LEDGER_TOTAL_CENTS, 0, 0, _LEDGER_TOTAL_CENTS)
    assert _LEDGER_TOTAL_CENTS <= DELINQUENCY_TOLERANCE_CENTS, (
        "this world is built so the true-up stays inside the delinquency "
        "tolerance; the expected balance must not exceed it"
    )
    assert_license_dimensions(
        license_row(api, world["license"]["id"]), COVERAGE_ACTIVE, BILLING_INVOICED
    )


def test_cascade_report_submission_writes_the_uncovered_share_and_its_exposure(api):
    """Submitting the setlist quantifies the repertoire nobody licenses.

    Only the BMI performance falls under an active licence with a live window, so
    the ASCAP, SESAC and unattributed performances carry 1520 of the report's 2020
    weight — 75.25 per cent — and that share puts 67738 cents of the licence's
    annual fee at risk.

    PRD §3.8: "`uncovered_share_pct` flags the entries whose `is_covered` is false
    — the performances that no active licence of this venue covers."

    PRD §3.8: "`gap_exposure_cents` puts money on the second figure: it is the
    owning licence's `annual_fee_cents` multiplied by `uncovered_share_pct` and
    divided by 100, rounded half up to whole cents."

    Design: Difficulty/transitive_cascade/cascade_b_report_submit_gap_escalation_returns_pending_application
    """
    world = _setlist_gap_world(api)

    _submit_report(api, world["report"]["id"], world["venue"]["id"])

    report = report_row(api, world["report"]["id"])
    assert_pct(report["uncovered_share_pct"], _UNCOVERED_SHARE_PCT, "uncovered_share_pct")
    assert_money(report["gap_exposure_cents"], _GAP_EXPOSURE_CENTS, "gap_exposure_cents")


def test_cascade_report_uncovered_share_escalates_into_an_open_audit_case(api):
    """The uncovered share drives the venue's gap risk over the escalation threshold.

    Four fifths of the 75.25 per cent uncovered share plus six points for each of
    the three distinct uncovered affiliations scores the venue at 78.20, which is
    past the escalation threshold, so the system opens the audit case itself and
    puts the venue on hold.

    PRD §3.8: "Multiply the source report's `uncovered_share_pct` by 0.8, add 6
    points for each distinct uncovered affiliation, round the sum half up to two
    decimal places, and cap the result at 100.00 — the score never exceeds 100.00
    however bad the setlist."

    PRD §3.8: "Because the recomputed `gap_risk_score` has reached the escalation
    threshold of 60.00 — the comparison is *at least* 60.00, so a score of exactly
    60.00 escalates — the system opens an `AuditCase` on that venue by itself."

    Design: Difficulty/transitive_cascade/cascade_b_report_submit_gap_escalation_returns_pending_application
    """
    world = _setlist_gap_world(api)

    _submit_report(api, world["report"]["id"], world["venue"]["id"])

    venue = venue_row(api, world["venue"]["id"])
    assert_pct(venue["gap_risk_score"], _GAP_RISK_SCORE, "gap_risk_score")
    assert venue["audit_hold"] is True, (
        f"the escalation must put the venue on audit hold, got {venue['audit_hold']!r}"
    )

    cases = read_rows(
        api.list_audit_cases(admin_headers(), {"venue_id": world["venue"]["id"]}),
        expected_total=1,
    )
    assert cases[0]["audit_trigger"] == AUDIT_TRIGGER_GAP_RISK_ESCALATION, (
        "the self-opened case must record the escalation as its trigger, "
        f"got {cases[0]['audit_trigger']!r}"
    )
    assert cases[0]["status"] == CASE_STATUS_OPEN, (
        f"the self-opened case must be open, got {cases[0]['status']!r}"
    )


def test_cascade_report_audit_hold_returns_the_pending_application_for_revision(api):
    """The new audit hold pushes the venue's still pending application back.

    The ASCAP application was sitting in submitted state with no revisions behind
    it, so the hold returns it for revision with the hold recorded as the reason
    and its first revision round counted; the BMI application that already reached
    a terminal state is left exactly as it was.

    PRD §3.8: "Because `audit_hold` just became true, every `LicenseApplication`
    of that venue whose `status` is `SUBMITTED` or `UNDER_REVIEW` is pushed back:
    it moves to `RETURNED_FOR_REVISION` with `return_reason` `AUDIT_HOLD` and
    `revision_round` incremented by 1, unless its `revision_round` already equals
    the maximum of 3 revision rounds, in which case it moves to `DECLINED` with
    `decline_reason` `REVISION_LIMIT_EXCEEDED` instead."

    Design: Difficulty/transitive_cascade/cascade_b_report_submit_gap_escalation_returns_pending_application
    """
    world = _setlist_gap_world(api)

    _submit_report(api, world["report"]["id"], world["venue"]["id"])

    pending = application_row(api, world["pending_application"]["id"])
    assert pending["status"] == APPLICATION_STATUS_RETURNED_FOR_REVISION, (
        "the pending application must be returned for revision, "
        f"got {pending['status']!r}"
    )
    assert pending["return_reason"] == RETURN_REASON_AUDIT_HOLD, (
        "the return must be attributed to the audit hold, "
        f"got {pending['return_reason']!r}"
    )
    assert_count(pending["revision_round"], 1, "revision_round")

    terminal = application_row(api, world["covered_application"]["id"])
    assert terminal["status"] == APPLICATION_STATUS_APPROVED, (
        "an application that already reached a terminal state must be untouched, "
        f"but it reads {terminal['status']!r}"
    )
    assert_count(terminal["revision_round"], 0, "revision_round")
