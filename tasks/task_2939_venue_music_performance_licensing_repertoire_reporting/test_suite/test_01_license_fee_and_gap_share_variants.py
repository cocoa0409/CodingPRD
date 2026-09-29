"""
The two-variant derivations of the licensing contract.

Almost every number in this system is derived twice.  The annual licence fee is
computed once from the operator's self-declaration when the application is
approved, and again from the society's verified venue survey when the licence is
activated, with the difference retained on the licence.  The repertoire gap is
measured twice over one identical setlist: once by asking whether a performed
work is registered at all, and once by asking whether any active licence of the
venue actually covers the society the venue attributed it to.  This file pins
both pairs, including the figures that make the two members of each pair
disagree.
"""

from test_helpers import (
    APPLICATION_STATUS_APPROVED,
    ASSESSMENT_KIND_INITIAL,
    ASSESSMENT_STATUS_ISSUED,
    BILLING_INVOICED,
    BILLING_UNBILLED,
    COVERAGE_ACTIVE,
    COVERAGE_PENDING_ACTIVATION,
    LICENSE_TYPES,
    MUSIC_USE_PROFILES,
    REPORT_STATUS_SUBMITTED,
    USE_TYPE_LIVE,
    USE_TYPE_RECORDED,
    VENUE_CATEGORIES,
    accept_for_review,
    activate,
    admin_headers,
    application_payload,
    application_row,
    approve,
    ascap_payload,
    assert_assessment,
    assert_count,
    assert_license_dimensions,
    assert_money,
    assert_not_pct,
    assert_pct,
    bar_grill_venue_payload,
    bmi_payload,
    find_row,
    get_success_data,
    given_active_license,
    given_draft_application,
    given_draft_report,
    given_effective_schedule,
    given_societies,
    given_society,
    given_setlist,
    given_venue,
    given_work,
    license_of_application,
    license_row,
    read_rows,
    report_row,
    sesac_payload,
    setlist_entries_of,
    venue_operator_headers,
    venue_row,
)

# Enum values the PRD declares but the shared constants expose only as tuples.
_LICENSE_TYPE_BLANKET = "BLANKET"
_BAR_GRILL = "BAR_GRILL"
_RECORDED_ONLY = "RECORDED_ONLY"
_AFFILIATION_BMI = "BMI"
_AFFILIATION_ASCAP = "ASCAP"
_AFFILIATION_SESAC = "SESAC"
_AFFILIATION_UNKNOWN = "UNKNOWN"

assert _LICENSE_TYPE_BLANKET in LICENSE_TYPES
assert _BAR_GRILL in VENUE_CATEGORIES
assert _RECORDED_ONLY in MUSIC_USE_PROFILES

_TERM_START = "2026-09-01T00:00:00Z"

# The declaration the operator files: 90 seats and 90 standing places put the
# billable occupancy in the first tier, against a verified survey of 120 seats
# and 180 standing places which lands in the second.
_DECLARED_SEATING = 90
_DECLARED_STANDING = 90
_DECLARED_COVER_REVENUE_CENTS = 1000000
_DECLARED_LIVE_NIGHTS = 1

_PROVISIONAL_FEE_CENTS = 26121
_VERIFIED_FEE_CENTS = 90017
_VERIFIED_FEE_DELTA_CENTS = 63896


def _understated_declaration_case(api):
    """A BMI licence for a bar and grill whose operator under-declared the venue.

    Returns the society, the venue as created, the APPROVED application and the
    freshly minted licence, which is still in PENDING_ACTIVATION so a caller can
    observe the provisional figures before activation overwrites them.
    """
    society = given_society(api, bmi_payload())
    given_effective_schedule(api, society["id"], _BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    application = given_draft_application(
        api,
        venue,
        society["id"],
        payload=application_payload(
            venue["id"],
            society["id"],
            _LICENSE_TYPE_BLANKET,
            _DECLARED_SEATING,
            _DECLARED_STANDING,
            _DECLARED_COVER_REVENUE_CENTS,
            _DECLARED_LIVE_NIGHTS,
            _RECORDED_ONLY,
            _TERM_START,
            expected_venue_version=venue["version"],
        ),
    )
    get_success_data(
        api.submit_application(
            application["id"], venue_operator_headers(venue["id"])
        )
    )
    accept_for_review(api, application["id"])
    approved = approve(api, application["id"])
    assert approved["status"] == APPLICATION_STATUS_APPROVED
    return {
        "society": society,
        "venue": venue,
        "application": approved,
        "license": license_of_application(api, approved["id"]),
    }


def _bmi_only_setlist_case(api):
    """A bar and grill licensed by BMI alone, reporting a four-work setlist.

    Three of the four performed works are registered — one to BMI, one to ASCAP
    and one to SESAC — and the fourth is registered nowhere, so the matching
    question and the coverage question have deliberately different answers.
    """
    bmi, ascap, sesac = given_societies(
        api, bmi_payload(), ascap_payload(), sesac_payload()
    )
    given_effective_schedule(api, bmi["id"], _BAR_GRILL)
    venue = given_venue(api, bar_grill_venue_payload())
    licence = given_active_license(api, venue, bmi["id"], _TERM_START)
    works = {
        "Blue Horizon": given_work(api, bmi["id"], "Blue Horizon", "A. Reed"),
        "Midnight Freight": given_work(
            api, ascap["id"], "Midnight Freight", "J. Vance"
        ),
        "Neon Sermon": given_work(api, sesac["id"], "Neon Sermon", "K. Ito"),
    }
    report = given_draft_report(api, licence["id"], venue["id"])
    given_setlist(
        api,
        report["id"],
        venue["id"],
        [
            {
                "title": "Blue Horizon",
                "writer": "A. Reed",
                "affiliation": _AFFILIATION_BMI,
                "when": "2026-09-05T20:00:00Z",
                "seconds": 300,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Midnight Freight",
                "writer": "J. Vance",
                "affiliation": _AFFILIATION_ASCAP,
                "when": "2026-09-05T20:30:00Z",
                "seconds": 240,
                "use_type": USE_TYPE_LIVE,
            },
            {
                "title": "Neon Sermon",
                "writer": "K. Ito",
                "affiliation": _AFFILIATION_SESAC,
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
    submitted = get_success_data(
        api.submit_performance_report(
            report["id"], venue_operator_headers(venue["id"])
        )
    )
    assert submitted["status"] == REPORT_STATUS_SUBMITTED
    return {
        "venue": venue,
        "license": licence,
        "works": works,
        "report": report_row(api, report["id"]),
    }


def test_fee_variant_provisional_fee_from_the_operator_declaration(api):
    """Approval prices the licence from the operator's own declared figures.

    Ninety seats and ninety standing places give a billable occupancy of 90,
    which with a RECORDED_ONLY profile, one live night and 1000000 cents of
    declared cover revenue prices the whole repertoire at 56784 cents; BMI's
    4600 basis points of that is 26121 cents, and the same figure is stamped on
    the application and on the licence approval mints.

    PRD §3.5: "The **provisional declared** variant reads the operator's
    self-declaration: the seating figure is `declared_seating`, the standing
    figure is `declared_standing`, the cover revenue is
    `declared_cover_revenue_cents`, the live-night count is
    `declared_live_nights`, and the use profile is
    `declared_music_use_profile`."

    PRD §3.5: "It runs exactly once, when a `LicensingAdmin` approves an
    application, and it writes `provisional_annual_fee_cents` on both the
    `LicenseApplication` and the newly created `License`."

    Design: Difficulty/dual_variant_calc/license_fee_provisional_declared_versus_final_verified
    """
    case = _understated_declaration_case(api)

    assert_money(
        case["application"]["provisional_annual_fee_cents"],
        _PROVISIONAL_FEE_CENTS,
        "application provisional_annual_fee_cents",
    )
    persisted = application_row(api, case["application"]["id"])
    assert_money(
        persisted["provisional_annual_fee_cents"],
        _PROVISIONAL_FEE_CENTS,
        "re-read application provisional_annual_fee_cents",
    )
    assert_money(
        case["license"]["provisional_annual_fee_cents"],
        _PROVISIONAL_FEE_CENTS,
        "licence provisional_annual_fee_cents",
    )
    assert_license_dimensions(
        case["license"], COVERAGE_PENDING_ACTIVATION, BILLING_UNBILLED
    )


def test_fee_variant_activation_reprices_from_the_verified_survey(api):
    """Activation re-prices the licence from the society's verified survey.

    The survey's 180 standing places beat its 120 seats, so the billable
    occupancy moves into the second tier; with a MIXED profile, four live nights
    and 4200000 cents of verified cover revenue the whole-repertoire price is
    195690 cents and BMI's share of it is 90017 cents. The gap against the
    26121-cent declaration is retained on the licence.

    PRD §3.6: "First, it re-rates: `annual_fee_cents` is recomputed under the
    **final verified** variant against the currently pinned schedule,
    `verified_fee_delta_cents` is set to that recomputed figure less
    `provisional_annual_fee_cents`, and the licence's `version` increments by
    1."

    PRD §3.5: "The billable occupancy is the **larger** of the seating figure
    and the standing figure — never their sum."

    Design: Difficulty/dual_variant_calc/license_fee_provisional_declared_versus_final_verified
    """
    case = _understated_declaration_case(api)

    activate(api, case["license"]["id"])
    licence = license_row(api, case["license"]["id"])

    assert_money(
        licence["annual_fee_cents"], _VERIFIED_FEE_CENTS, "annual_fee_cents"
    )
    assert_money(
        licence["provisional_annual_fee_cents"],
        _PROVISIONAL_FEE_CENTS,
        "provisional_annual_fee_cents",
    )
    assert_money(
        licence["verified_fee_delta_cents"],
        _VERIFIED_FEE_DELTA_CENTS,
        "verified_fee_delta_cents",
    )
    assert_license_dimensions(licence, COVERAGE_ACTIVE, BILLING_INVOICED)


def test_fee_variant_initial_assessment_bills_the_verified_figure(api):
    """The venue is billed the verified fee, not the declared one.

    Activation raises exactly one INITIAL assessment for the freshly computed
    90017 cents with nothing yet paid against it, and both the venue's lifetime
    and outstanding totals move by that same amount — the 26121-cent
    declaration is never billed.

    PRD §3.6: "When `license_type` is anything other than `BGM_EXEMPT`, a
    `FeeAssessment` is issued with `venue_id` copied from the licence,
    `license_id` set to the licence, `audit_case_id` null, `amount_cents` equal
    to the freshly computed `annual_fee_cents`, `paid_amount_cents` at 0,
    `status` `ISSUED`, and `due_date` set to the logical clock instant of
    issuance plus 30 days."

    PRD §3.6: "Fourth, it recomputes the venue: `lifetime_assessed_cents` and
    `outstanding_balance_cents` each increase by the created assessment's
    `amount_cents`, `covered_share_bp` and `coverage_posture` are recomputed per
    §2.10, and `Venue.version` increments by 1."

    Design: Difficulty/dual_variant_calc/license_fee_provisional_declared_versus_final_verified
    """
    case = _understated_declaration_case(api)

    activate(api, case["license"]["id"])

    billed = read_rows(
        api.list_fee_assessments(
            admin_headers(), {"license_id": case["license"]["id"]}
        ),
        expected_total=1,
    )
    assert_assessment(
        billed[0],
        ASSESSMENT_KIND_INITIAL,
        _VERIFIED_FEE_CENTS,
        ASSESSMENT_STATUS_ISSUED,
        paid=0,
    )

    venue = venue_row(api, case["venue"]["id"])
    assert_money(
        venue["outstanding_balance_cents"],
        _VERIFIED_FEE_CENTS,
        "outstanding_balance_cents",
    )
    assert_money(
        venue["lifetime_assessed_cents"],
        _VERIFIED_FEE_CENTS,
        "lifetime_assessed_cents",
    )


def test_gap_variant_unmatched_share_weighs_only_the_unregistered_work(api):
    """The matched-share measure asks only whether the work is registered.

    Three of the four performances name a registered work, whichever society
    registered it, so only the unregistered "Unknown Jam" is flagged. Its ten
    minutes of live playing weigh 1000 of the setlist's 2020 total weight, which
    is 49.50 percent once rounded to two places.

    PRD §3.8: "`reported_entry_count` is the number of attached entries;
    `matched_entry_count` is the number of attached entries whose `is_matched`
    came out true; `uncovered_entry_count` is the number whose `is_covered` came
    out false."

    PRD §3.8: "`unmatched_share_pct` flags the entries whose `is_matched` is
    false — the performances for which no registered work exists at all."

    Design: Difficulty/dual_variant_calc/repertoire_gap_share_title_match_versus_affiliation_coverage
    """
    case = _bmi_only_setlist_case(api)
    report = case["report"]

    assert_count(report["reported_entry_count"], 4, "reported_entry_count")
    assert_count(report["matched_entry_count"], 3, "matched_entry_count")
    assert_pct(report["unmatched_share_pct"], 49.50, "unmatched_share_pct")


def test_gap_variant_uncovered_share_diverges_from_the_unmatched_share(api):
    """The coverage measure asks which society licenses the venue, and differs.

    A BMI-only licence covers only the BMI performance, so the ASCAP work, the
    SESAC work and the unattributed jam are all uncovered: 1520 of the 2020
    total weight, or 75.25 percent — a different figure from the 49.50 percent
    the same setlist yields on the matching question. The licence's 90017-cent
    annual fee puts 67738 cents of money on that share.

    PRD §3.8: "A registered-but-unlicensed work is flagged here and not by the
    matched-share measure, which is precisely why the two percentages differ for
    identical setlist data."

    PRD §3.8: "`gap_exposure_cents` puts money on the second figure: it is the
    owning licence's `annual_fee_cents` multiplied by `uncovered_share_pct` and
    divided by 100, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/repertoire_gap_share_title_match_versus_affiliation_coverage
    """
    case = _bmi_only_setlist_case(api)
    report = case["report"]

    assert_count(report["uncovered_entry_count"], 3, "uncovered_entry_count")
    assert_pct(report["uncovered_share_pct"], 75.25, "uncovered_share_pct")
    assert_not_pct(
        report["uncovered_share_pct"],
        report["unmatched_share_pct"],
        "uncovered_share_pct",
    )
    assert_money(report["gap_exposure_cents"], 67738, "gap_exposure_cents")


def test_gap_variant_entry_flags_split_matching_from_coverage(api):
    """One entry can be matched and still uncovered; another is neither.

    "Midnight Freight" is registered, so it carries the winning work's id on its
    match verdict, yet the venue holds no ASCAP licence and the entry is
    therefore not covered. "Unknown Jam" is registered nowhere, so it has no
    matched work at all and an UNKNOWN affiliation can never be covered.

    PRD §3.8: "**Coverage-testing** is a separate question: an entry's
    `is_covered` becomes true only when its `society_affiliation` names a
    `Society` for which this venue holds a `License` with `coverage_status`
    `ACTIVE` that also has an `ACTIVE` `CoverageWindow` whose half-open span
    contains the entry's `performance_datetime`."

    PRD §3.8: "On a hit, the entry's `is_matched` becomes true and
    `matched_work_id` becomes the winning work's `id`; when no candidate
    qualifies, `is_matched` stays false and `matched_work_id` stays null."

    Design: Difficulty/dual_variant_calc/repertoire_gap_share_title_match_versus_affiliation_coverage
    """
    case = _bmi_only_setlist_case(api)
    entries = setlist_entries_of(api, case["report"]["id"])
    assert_count(len(entries), 4, "attached setlist entries")

    freight = find_row(entries, work_title="Midnight Freight")
    assert freight["is_matched"] is True, (
        "a registered work must be matched however its society is affiliated"
    )
    assert freight["matched_work_id"] == case["works"]["Midnight Freight"]["id"], (
        "the match must name the ASCAP-registered work that was found"
    )
    assert freight["is_covered"] is False, (
        "a BMI-only licence covers no ASCAP-affiliated performance"
    )

    jam = find_row(entries, work_title="Unknown Jam")
    assert jam["is_matched"] is False, (
        "an unregistered work has no registry candidate to match"
    )
    assert jam["matched_work_id"] is None, (
        "an unmatched entry must leave matched_work_id null"
    )
    assert jam["is_covered"] is False, (
        "an UNKNOWN affiliation is never covered"
    )
