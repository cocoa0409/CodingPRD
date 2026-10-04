"""Difficulty tests: dual_variant_calc — two sanctioned readings of one
calculation diverge on identical inputs (certification compliance score and
athlete funding points).
"""
import pytest

from test_helpers import (
    CLOCK_STARTUP_DEFAULT,
    add_verified_results,
    close_cycle,
    create_certification_cycle,
    create_funding_agreement,
    create_governing_body,
    issue_findings,
    move_cycle_to_remediation,
    open_cycle,
    parse_iso,
    read_governing_body,
    set_logical_clock,
    setup_certified_body,
    setup_eligible_athlete,
)

# Five verified results shared by both athletes in the funding test: at the
# 2027-03-01 anchor the trailing window includes the 2026-03-01 result at
# exactly 365 days (half weight) and excludes the 2026-02-28 result at 366.
FIVE_RESULTS = [
    {"event_name": "Winter Nationals", "event_grade": "A", "placing": 1,
     "event_date": "2027-02-01T00:00:00Z"},
    {"event_name": "Spring Open", "event_grade": "C", "placing": 2,
     "event_date": "2026-11-01T00:00:00Z"},
    {"event_name": "Summer Classic", "event_grade": "B", "placing": 3,
     "event_date": "2026-08-15T00:00:00Z"},
    {"event_name": "Early Meet", "event_grade": "C", "placing": 1,
     "event_date": "2026-03-01T00:00:00Z"},
    {"event_name": "Old Cup", "event_grade": "A", "placing": 2,
     "event_date": "2026-02-28T00:00:00Z"},
]


def test_certification_provisional_vs_final_score(api, committee_admin_headers):
    """PRD certification-cycle section: "The provisional score is a weighted
    blend of the three components: 0.40 times the governance component, plus
    0.35 times the athlete-representation component, plus 0.25 times the
    financial component, rounded half up to two decimal places."
    PRD certification-cycle section: "Closing a passed cycle out of remediation
    applies a remediation bonus before the final weighting: the single lowest
    of the three component scores is raised by 10 points, capped at 100, with
    ties for lowest broken by choosing the financial component first, then the
    athlete-representation component, then the governance component; the three
    components with that replacement are re-weighted by the same 0.40, 0.35,
    and 0.25 weights and rounded half up to two decimal places to produce
    `final_score`, and `remediation_applied` is set to true."
    PRD certification-cycle section: "A `CLOSED_PASSED` cycle moves an
    `APPLIED` body to `CERTIFIED` — stamping `certified_at` with the clock for
    the first such transition".

    Design: Difficulty/dual_variant_calc/certification_provisional_vs_final_score
    """
    body = create_governing_body(
        api=api,
        name="US Swim Federation",
        sport_code="SWIM",
        funding_budget_cents=5_000_000,
        sport_science_pool_hours=100,
    )
    cycle = create_certification_cycle(
        body["id"],
        api=api,
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-12-01T00:00:00Z",
    )
    open_cycle(cycle["id"], api=api)

    issued = issue_findings(cycle["id"], 80, 70, 60, api=api)
    # 0.40*80 + 0.35*70 + 0.25*60 = 32.0 + 24.5 + 15.0 = 71.5
    assert issued["provisional_score"] == pytest.approx(71.5, abs=1e-9), (
        f"provisional read must be 71.5, got {issued['provisional_score']!r}"
    )

    move_cycle_to_remediation(cycle["id"], api=api)
    closed = close_cycle(cycle["id"], "CLOSED_PASSED", api=api)

    # Remediation bonus: financial 60 -> 70; 0.40*80 + 0.35*70 + 0.25*70 = 74.0
    assert closed["status"] == "CLOSED_PASSED", (
        f"cycle must close CLOSED_PASSED, got {closed['status']!r}"
    )
    assert closed["final_score"] == pytest.approx(74.0, abs=1e-9), (
        f"final read must be 74.0, got {closed['final_score']!r}"
    )
    assert closed["remediation_applied"] is True
    assert closed["final_score"] != issued["provisional_score"], (
        "identical component scores, two sanctioned variants, different results"
    )

    body_after = read_governing_body(body["id"], api=api)
    assert body_after["status"] == "CERTIFIED", (
        f"body must cascade to CERTIFIED, got {body_after['status']!r}"
    )
    assert parse_iso(body_after["certified_at"]) == parse_iso(CLOCK_STARTUP_DEFAULT), (
        "certified_at must be stamped with the logical clock at close "
        f"(startup default {CLOCK_STARTUP_DEFAULT}), got {body_after['certified_at']!r}"
    )


def test_funding_trailing_vs_season_points(api, committee_admin_headers):
    """PRD results/points section: "`TRAILING_365` anchors on the current
    logical clock and includes each verified result whose age — clock minus
    `event_date` — is at least 0 days and at most 365 days. A recency weight
    applies per result: full weight for results aged at most 180 days, and
    half weight — a multiplier of 0.5 — for results aged 181 through 365
    days."
    PRD results/points section: "`CALENDAR_SEASON` includes each verified
    result whose `event_date` falls from January 1 of the current logical
    clock's calendar year through the clock itself, with no recency decay: the
    points are the plain sum of the included results' `base_points`, rounded
    half up to two decimal places."
    PRD results/points section: "Both values live on the agreement as
    `trailing_points` and `season_points`".
    PRD results/points section: "the operative value fixes the funding `tier`
    against inclusive thresholds: `TIER_A` at 100 points or more, `TIER_B` at
    60 or more, `TIER_C` at 30 or more, and `NONE` below 30 — a value exactly
    on a threshold qualifies for that tier. The tier fixes
    `monthly_stipend_cents`: 300000 cents monthly for `TIER_A`, 200000 for
    `TIER_B`, 100000 for `TIER_C`, and 0 for `NONE`."

    Design: Difficulty/dual_variant_calc/funding_trailing_vs_season_points
    """
    body = setup_certified_body(
        api=api,
        name="US Rowing",
        sport_code="ROWI",
        funding_budget_cents=8_000_000,
        sport_science_pool_hours=100,
    )
    athlete_p = setup_eligible_athlete(
        body["id"], api=api, full_name="Pat Lane", date_of_birth="1998-05-05"
    )
    add_verified_results(athlete_p["id"], FIVE_RESULTS, api=api)
    athlete_q = setup_eligible_athlete(
        body["id"], api=api, full_name="Quinn Lake", date_of_birth="1999-01-01"
    )
    add_verified_results(athlete_q["id"], FIVE_RESULTS, api=api)

    # Anchor the window at 2027-03-01 BEFORE the offers are created.
    set_logical_clock("2027-03-01T00:00:00Z", api=api)

    agreement_p = create_funding_agreement(
        athlete_p["id"],
        api=api,
        coverage_start="2027-03-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        points_method="TRAILING_365",
    )
    agreement_q = create_funding_agreement(
        athlete_q["id"],
        api=api,
        coverage_start="2027-03-01T00:00:00Z",
        coverage_end="2027-08-01T00:00:00Z",
        points_method="CALENDAR_SEASON",
    )

    # Trailing (both athletes, identical histories): 60.0 (1st/A, 28d, full)
    # + 32.0 (2nd/C, 120d, full) + 16.25 (3rd/B, 198d, half) + 20.0 (1st/C,
    # exactly 365d, included at half) = 128.25; the 2026-02-28 result is 366
    # days old and excluded.
    assert agreement_p["trailing_points"] == pytest.approx(128.25, abs=1e-9), (
        f"P trailing must be 128.25, got {agreement_p['trailing_points']!r}"
    )
    assert agreement_q["trailing_points"] == pytest.approx(128.25, abs=1e-9), (
        "both variants are stored on every agreement; "
        f"Q trailing must be 128.25, got {agreement_q['trailing_points']!r}"
    )
    # Season at the 2027-03-01 anchor: only the 2027-02-01 result falls in
    # calendar year 2027 -> 60.0.
    assert agreement_q["season_points"] == pytest.approx(60.0, abs=1e-9), (
        f"Q season must be 60.0, got {agreement_q['season_points']!r}"
    )

    # Operative values diverge: P is TIER_A/300000, Q is TIER_B/200000.
    assert agreement_p["tier"] == "TIER_A"
    assert agreement_p["monthly_stipend_cents"] == 300000
    assert agreement_q["tier"] == "TIER_B"
    assert agreement_q["monthly_stipend_cents"] == 200000
    assert agreement_p["monthly_stipend_cents"] != agreement_q["monthly_stipend_cents"], (
        "identical result sets, divergent operative outputs under the two "
        "sanctioned windowing methods"
    )
