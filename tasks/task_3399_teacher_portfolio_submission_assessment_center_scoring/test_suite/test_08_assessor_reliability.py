"""Assessor reliability index: the exact and adjacent agreement variants over the
trailing 10-read window, and the exact-floor auto-suspension."""
import pytest

from test_helpers import (
    SCORING_ADMIN,
    AssessorStatus,
    IRR_WINDOW,
    assert_assessor,
    create_active_assessor,
    create_default_benchmark,
    create_eligible_candidate,
    create_open_cycle,
    create_portfolio_submission_in_state,
    cycle_component,
    score_portfolio_with_read_pair,
    validate_success,
)


def _ten_read_reliability_scenario(api):
    """Build the ten-finalized-live-reads scenario for assessor AX.

    Cycle components: K1 (ASSESSMENT 0.10) + C1..C10 (PORTFOLIO 0.09), weights
    summing to exactly 1.000. Candidate (district D-100) is ELIGIBLE; AX (D-900)
    and AY (D-901) are ACTIVE. On every Ci the read pair is (AX, AY): AX scores
    3.00 everywhere; AY scores 3.00 on C1..C5 and 3.50 on C6..C10. Finals are
    therefore 3.00 five times and 3.25 five times — |3.00 - 3.50| == 0.50 stays
    inside the 0.50 divergence tolerance, so every attempt resolves by agreement.
    AX's own score equals the final on exactly 5 of 10 reads and sits within
    0.25 of the final on all 10.
    """
    components = [cycle_component("K1", "ASSESSMENT", 0.10)] + [
        cycle_component(f"C{i}", "PORTFOLIO", 0.09) for i in range(1, 11)
    ]
    cycle = create_open_cycle(components=components)
    candidate = create_eligible_candidate()
    benchmark = create_default_benchmark()
    ax = create_active_assessor(benchmark["id"], home_district_code="D-900")
    ay = create_active_assessor(benchmark["id"], home_district_code="D-901")

    for i in range(1, 11):
        submission = create_portfolio_submission_in_state(
            cycle["id"], candidate, f"C{i}", state="SCORING"
        )
        ay_score = 3.00 if i <= 5 else 3.50
        score_portfolio_with_read_pair(submission["id"], ax, ay, 3.00, ay_score)

    return {"ax": ax, "ay": ay}


def test_exact_agreement_variant_below_floor_auto_suspends(api):
    """PRD §3.5: "When a finalization pushes `scored_read_count` to at least 10
    while the recomputed `exact_agreement_rate` falls below 0.70, the assessor is
    auto-suspended from `ACTIVE` to `SUSPENDED` — an exact rate of exactly 0.70
    does not suspend."
    PRD §3.5: "Once 10 such reads exist, two rates are computed to 2 decimal
    places: `exact_agreement_rate`, the fraction of the window whose own score
    equals the submission's `final_score` exactly, and `adjacent_agreement_rate`,
    the fraction within 0.25 of it".

    AX's exact variant lands at 5/10 == 0.50, below the 0.70 floor.

    Design: Difficulty/dual_variant_calc/assessor_reliability_exact_vs_adjacent_rates
    """
    scenario = _ten_read_reliability_scenario(api)

    record = validate_success(api.get_assessor(scenario["ax"]["id"], SCORING_ADMIN))

    assert_assessor(record)
    assert record["scored_read_count"] == IRR_WINDOW == 10
    assert record["exact_agreement_rate"] == pytest.approx(0.50)
    assert record["status"] == AssessorStatus.SUSPENDED.value


def test_adjacent_agreement_variant_rates_same_reads_differently(api):
    """PRD §3.5: "Once 10 such reads exist, two rates are computed to 2 decimal
    places: `exact_agreement_rate`, the fraction of the window whose own score
    equals the submission's `final_score` exactly, and `adjacent_agreement_rate`,
    the fraction within 0.25 of it — the adjacent band means the same read set
    always yields an adjacent rate at least as high as the exact rate, and
    strictly higher whenever any read sits exactly 0.25 off."

    Over the SAME ten reads the adjacent variant rates AX at 10/10 == 1.00
    (every miss is exactly 0.25 off), while the exact variant reads 0.50 — the
    variant choice flips the reliability verdict on identical data.

    Design: Difficulty/dual_variant_calc/assessor_reliability_exact_vs_adjacent_rates
    """
    scenario = _ten_read_reliability_scenario(api)

    record = validate_success(api.get_assessor(scenario["ax"]["id"], SCORING_ADMIN))

    assert_assessor(record)
    assert record["scored_read_count"] == 10
    assert record["exact_agreement_rate"] == pytest.approx(0.50)
    assert record["adjacent_agreement_rate"] == pytest.approx(1.00)
    assert record["adjacent_agreement_rate"] > record["exact_agreement_rate"]
