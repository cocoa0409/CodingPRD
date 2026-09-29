"""Combinatorial formulas: several independent inputs combined non-linearly.

PRD 3.7 builds ``assessed_fine_cents`` from four independent inputs - the summed
``fine_cents_base`` of the findings, a tier multiplier read from the pinned
pre-cascade snapshot, a subject factor and an additive per-excess-point surcharge
- and then clamps the result into a statutory band before the fee is keyed on the
clamped figure alone.  PRD 2.7 / 3.5 pin the companion ordering rule: each
finding is rounded before the sum is taken, and the sum is rounded again.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    assert_cents,
    assert_fine_breakdown,
    assert_instants_equal,
    assert_points,
    create_establishment,
    create_violation_code,
    issue_citation,
    refresh_establishment,
    setup_finalized_inspection,
    setup_submitted_inspection,
    validate_success,
)


# --- Fine composition: tier, subject factor, surcharge, clamp, fee ------------
def _glow_salon_with_failing_finalized_inspection(api):
    """FSP-300 observed twice (40.00 points) and IMP-200 once (15.00 points).

    Neither finding is corrected on site, so no credit applies in either variant
    and PRD 3.5's bands resolve to FAIL on 55.00 points.  The establishment has
    never been finalized before, so PRD 3.7 hop two snapshots
    ``demerit_balance_before_finalize`` at 0.00.
    """
    foot_spa_code = create_violation_code(
        api,
        severity="CRITICAL",
        base_points=4.0,
        fine_cents_base=30000,
        category="FOOT_SPA",
        code="FSP-300",
    )
    implement_code = create_violation_code(
        api,
        severity="MAJOR",
        base_points=6.0,
        fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
        code="IMP-200",
    )
    establishment = create_establishment(
        api, station_capacity=4, establishment_type="SALON", county_code="NCA",
        legal_name="Glow Salon",
    )
    finalized = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[
            {"violation_code_id": foot_spa_code["id"], "observed_count": 2},
            {"violation_code_id": implement_code["id"], "observed_count": 1},
        ],
    )
    return {
        "establishment": establishment,
        "inspection": finalized["inspection"],
        "findings": finalized["findings"],
    }


def test_assessed_fine_combines_base_tier_subject_factor_and_excess_surcharge(api):
    """PRD 3.7: "The raw amount is the base multiplied by the demerit tier
    multiplier and then by the subject factor, that product rounded half up to
    whole cents, with the surcharge added afterwards", then clamped into the
    5000-250000 band, after which "the fee percentage is keyed on
    assessed_fine_cents alone".  Base 30000+12000 = 42000, tier 1.00 from a 0.00
    snapshot, subject factor 1.00 for an ESTABLISHMENT, surcharge
    400 * (55.00-30.00) = 10000, so assessed is 52000, the 8 percent band gives a
    4160 fee and 56160 is due.

    Design: Difficulty/combinatorial_formula/citation_fine_tier_subject_factor_and_excess_point_surcharge
    """
    built = _glow_salon_with_failing_finalized_inspection(api)
    inspection = built["inspection"]
    assert_points(inspection["final_adjusted_score"], 55.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL"
    assert_points(
        inspection["demerit_balance_before_finalize"],
        0.00,
        "demerit_balance_before_finalize",
    )

    citation = issue_citation(api, inspection["id"], subject_type="ESTABLISHMENT")
    assert citation["status"] == "ISSUED"
    assert_points(citation["demerit_tier_multiplier"], 1.00, "demerit_tier_multiplier")
    assert citation["max_finding_severity"] == "CRITICAL"
    assert_fine_breakdown(
        citation,
        assessed_fine_cents=52000,
        administrative_fee_cents=4160,
        total_due_cents=56160,
        outstanding_fine_cents=56160,
    )
    # Without the additive surcharge the assessed fine would have been 42000.
    assert citation["assessed_fine_cents"] != 42000
    assert_instants_equal(citation["issued_at"], "2026-08-01T00:00:00.000Z", "issued_at")
    assert_instants_equal(citation["due_at"], "2026-08-31T00:00:00.000Z", "due_at")
    assert_instants_equal(
        citation["contest_deadline_at"],
        "2026-08-21T00:00:00.000Z",
        "contest_deadline_at",
    )

    establishment = refresh_establishment(api, built["establishment"]["id"])
    assert_points(establishment["demerit_balance"], 55.00, "demerit_balance")
    assert_cents(
        establishment["outstanding_fine_total_cents"],
        56160,
        "outstanding_fine_total_cents",
    )
    assert establishment["open_critical_citation_count"] == 1
    assert establishment["compliance_posture"] == "RESTRICTED"


def test_tier_multiplier_reads_the_pre_cascade_snapshot_not_the_live_balance(api):
    """PRD 3.7: "The demerit tier multiplier is selected from the snapshot
    demerit_balance_before_finalize, not from the live balance ... 1.25 when the
    snapshot is at least 20.00 but below 50.00".  A first visit banks 25.00
    points; the second visit's own 30.00 points push the live balance to 55.00,
    which would key the 1.60 tier, yet the snapshot pinned by hop two is 25.00.
    Base 20000 * 1.25 * 1.00 = 25000 with a zero surcharge (the score equals the
    30.00 tolerance exactly), and 25000 sits on the 5 percent fee boundary, which
    PRD 3.7 makes inclusive.

    Design: Difficulty/combinatorial_formula/citation_fine_tier_subject_factor_and_excess_point_surcharge
    """
    establishment = create_establishment(api, station_capacity=4, county_code="NCA")
    first_code = create_violation_code(
        api, severity="MINOR", base_points=5.0, fine_cents_base=10000,
        category="SANITATION", code="SAN-120",
    )
    second_code = create_violation_code(
        api, severity="MAJOR", base_points=4.0, fine_cents_base=20000,
        category="DISINFECTION", code="DIS-210",
    )

    first = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[{"violation_code_id": first_code["id"], "observed_count": 5}],
        window_index=0,
    )
    assert_points(first["inspection"]["final_adjusted_score"], 25.00, "first score")
    assert_points(
        refresh_establishment(api, establishment["id"])["demerit_balance"],
        25.00,
        "demerit_balance after the first visit",
    )

    second = setup_finalized_inspection(
        api,
        establishment["id"],
        findings=[{"violation_code_id": second_code["id"], "observed_count": 3}],
        window_index=1,
    )
    assert_points(second["inspection"]["final_adjusted_score"], 30.00, "second score")
    assert_points(
        second["inspection"]["demerit_balance_before_finalize"],
        25.00,
        "demerit_balance_before_finalize",
    )
    assert_points(
        refresh_establishment(api, establishment["id"])["demerit_balance"],
        55.00,
        "live demerit_balance",
    )

    citation = issue_citation(api, second["inspection"]["id"])
    assert_points(citation["demerit_tier_multiplier"], 1.25, "demerit_tier_multiplier")
    assert_fine_breakdown(
        citation,
        assessed_fine_cents=25000,
        administrative_fee_cents=1250,
        total_due_cents=26250,
        outstanding_fine_cents=26250,
    )
    # The live 55.00 balance would have selected the 1.60 tier and 32000 cents.
    assert citation["assessed_fine_cents"] != 32000


# --- Rounding order: round each finding, then sum, then round -----------------
def _tidy_cuts_submitted_with_three_identical_odd_findings(api):
    """Three SAN-115 findings whose raw products land on a half-cent boundary.

    base_points 1.05 * SEVERITY_WEIGHT[MINOR] 1.0 * observed_count 1 *
    repeat_factor 1.0 gives 0.525 under the provisional 0.50 credit and 0.7875
    under the final 0.25 credit, so the per-finding rounding is observable.
    """
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=1.05,
        fine_cents_base=2500,
        category="SANITATION",
        code="SAN-115",
    )
    establishment = create_establishment(
        api, station_capacity=3, establishment_type="BARBERSHOP", county_code="NCB",
        legal_name="Tidy Cuts",
    )
    submitted = setup_submitted_inspection(
        api,
        establishment["id"],
        findings=[
            {"violation_code_id": code["id"], "observed_count": 1, "corrected_on_site": True}
            for _ in range(3)
        ],
    )
    return {
        "establishment": establishment,
        "inspection": submitted["inspection"],
        "findings": submitted["findings"],
    }


def _read_finding(api, finding_id):
    return validate_success(api.get_violation_finding(finding_id, BOARD_ADMIN_HEADERS))


def test_provisional_score_rounds_each_finding_to_two_places_before_summing(api):
    """PRD 2.7 / 3.5: "Inspection scoring rounds each finding's point value to two
    decimal places first, then sums the rounded values, then rounds the sum again
    ... summing unrounded products and rounding once at the end is explicitly not
    the rule".  Three raw 0.525 products therefore each round to 0.53 and sum to
    1.59, where the sum-then-round order would have produced 1.58.

    Design: Difficulty/combinatorial_formula/inspection_score_rounds_per_finding_before_summing
    """
    built = _tidy_cuts_submitted_with_three_identical_odd_findings(api)

    for finding in built["findings"]:
        scored = _read_finding(api, finding["id"])
        assert_points(scored["provisional_points"], 0.53, "provisional_points")

    provisional = built["inspection"]["provisional_adjusted_score"]
    assert_points(provisional, 1.59, "provisional_adjusted_score")
    assert abs(float(provisional) - 1.58) > 1e-9, (
        "1.58 is the sum-then-round answer, which PRD 2.7 explicitly rejects"
    )


def test_final_score_rounds_each_finding_before_summing_too(api):
    """PRD 2.7 / 3.5 apply the same order to the final variant, whose raw
    per-finding product is 1.05 * 1.0 * 1 * 1.0 * (1 - 0.25) = 0.7875: each
    finding rounds to 0.79 and the sum is 2.37, not the 2.36 that summing the
    unrounded products would give.  2.37 is not above 10.00, so PRD 3.5 bands the
    visit PASS and PRD 3.7 hop four promotes the facility to ACTIVE.

    Design: Difficulty/combinatorial_formula/inspection_score_rounds_per_finding_before_summing
    """
    built = _tidy_cuts_submitted_with_three_identical_odd_findings(api)

    finalized = validate_success(
        api.finalize_inspection(built["inspection"]["id"], BOARD_ADMIN_HEADERS)
    )
    for finding in built["findings"]:
        scored = _read_finding(api, finding["id"])
        assert_points(scored["final_points"], 0.79, "final_points")

    final_score = finalized["final_adjusted_score"]
    assert_points(final_score, 2.37, "final_adjusted_score")
    assert abs(float(final_score) - 2.36) > 1e-9, (
        "2.36 is the sum-then-round answer, which PRD 2.7 explicitly rejects"
    )
    assert finalized["final_outcome"] == "PASS"

    establishment = refresh_establishment(api, built["establishment"]["id"])
    assert_points(establishment["demerit_balance"], 2.37, "demerit_balance")
    assert establishment["license_status"] == "ACTIVE"
    assert establishment["compliance_posture"] == "CLEAR"
