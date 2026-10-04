"""Impact scoring (weighted roles, quorum gate) and both percentile variants
(raw within-section, normalized across the activity-code pool), including
tie-breaking and pool-wide reconciliation after a later release."""
from decimal import Decimal, ROUND_HALF_UP

import pytest

from test_helpers import (
    fixtures,
    factories,
    TEST_USERS,
    PRIMARY_WEIGHT,
    SECONDARY_WEIGHT,
)

_SRO = TEST_USERS["sro_headers"]


def _rhup(value, places: int) -> Decimal:
    """Round half up at the given decimal places (PRD rounding rule)."""
    return Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _percentile(rank: int, pool_size: int) -> float:
    """PRD §3.5 rank percentile: round_half_up(100 * (r - 0.5) / N, 1)."""
    return float(_rhup(Decimal(100) * (Decimal(rank) - Decimal("0.5")) / Decimal(pool_size), 1))


def _impact_score(scored_roles) -> int:
    """PRD §3.5: weighted mean of overall_impact_score (PRIMARY x2,
    SECONDARY x1), times ten, rounded half up to an integer."""
    weighted = sum(Decimal(score) * (PRIMARY_WEIGHT if role == "PRIMARY" else SECONDARY_WEIGHT)
                   for role, score in scored_roles)
    weights = sum(Decimal(PRIMARY_WEIGHT if role == "PRIMARY" else SECONDARY_WEIGHT)
                  for role, _ in scored_roles)
    return int(_rhup(weighted / weights * 10, 0))


def _normalized_ranks(impacts_by_app, section_of):
    """PRD §3.5 normalized variant: adjust each impact by (pool_mean -
    section_mean), sort ascending (ties: impact then creation order — the
    creation order here is the dict insertion order)."""
    sections = {}
    for app, sec in section_of.items():
        sections.setdefault(sec, []).append(impacts_by_app[app])
    section_mean = {s: _rhup(sum(map(Decimal, vals)) / len(vals), 1)
                    for s, vals in sections.items()}
    pool = list(impacts_by_app.values())
    pool_mean = _rhup(sum(map(Decimal, pool)) / len(pool), 1)
    adjusted = {app: Decimal(impacts_by_app[app]) - section_mean[section_of[app]] + pool_mean
                for app in impacts_by_app}
    return sorted(impacts_by_app, key=lambda a: (adjusted[a], impacts_by_app[a]))


def test_percentile_raw_vs_normalized_diverge_across_panels():
    """PRD §3.5: "The pool is every application of this study section in `SCORED` status, sorted by `impact_score` from lowest to highest; ties break by `approach_mean` lowest first, then `significance_mean` lowest first, then `innovation_mean` lowest first, and finally `created_at` earliest first — the resource `id` is never a tie-break."
    PRD §3.5: "The pool is every `SCORED` application — in any study section — whose announcement shares the same `activity_code` as the application being ranked."
    PRD §3.5: "Each application's adjusted score is its own `impact_score` minus the section mean of its own section plus the pool mean."

    Design: Difficulty/dual_variant_calc/percentile_raw_vs_normalized_diverge_across_panels
    """
    ctx = fixtures.make_review_context(indirect_cost_rate=0.5)
    sec_a = fixtures.make_study_section(name="Section A", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section B", meeting_date="2027-04-15T00:00:00Z")
    e_a1 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="A1")
    e_a2 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="A2")
    e_b1 = fixtures.add_reviewed_application(ctx, sec_b, convene=False, title="B1")
    # Impacts: a1 -> 20, a2 -> 40 (section A); b1 -> 50 (section B).
    fixtures.score_section(sec_a, [e_a1, e_a2], [
        [{"overall_impact_score": 2}, {"overall_impact_score": 2}],
        [{"overall_impact_score": 4}, {"overall_impact_score": 4}],
    ])
    fixtures.score_section(sec_b, [e_b1], [
        [{"overall_impact_score": 5}, {"overall_impact_score": 5}],
    ])

    a1 = fixtures.refresh_application(e_a1["application"]["id"])
    a2 = fixtures.refresh_application(e_a2["application"]["id"])
    b1 = fixtures.refresh_application(e_b1["application"]["id"])

    assert a1["impact_score"] == _impact_score([("PRIMARY", 2), ("SECONDARY", 2)]) == 20
    assert a2["impact_score"] == 40
    assert b1["impact_score"] == 50

    # Raw variant: within-section ranking only.
    assert a1["percentile_raw"] == _percentile(1, 2)   # 25.0
    assert a2["percentile_raw"] == _percentile(2, 2)   # 75.0
    assert b1["percentile_raw"] == _percentile(1, 1)   # 50.0

    # Normalized variant: one R01 pool of three; section means 30.0 and 50.0,
    # pool mean 36.7, so adjusted scores are a1 6.7, b1 36.7, a2 46.7 and the
    # variants disagree because section means differ.
    order = _normalized_ranks({"a1": 20, "a2": 40, "b1": 50},
                              {"a1": "A", "a2": "A", "b1": "B"})
    assert order == ["a1", "b1", "a2"]
    assert a1["percentile_normalized"] == _percentile(1, 3)   # 16.7
    assert b1["percentile_normalized"] == _percentile(2, 3)   # 50.0
    assert a2["percentile_normalized"] == _percentile(3, 3)   # 83.3
    assert a1["percentile_raw"] != a1["percentile_normalized"]


def test_impact_score_weighted_roles_with_quorum_gate():
    """PRD §3.5: "Otherwise each submitted critique's `overall_impact_score` is weighted — a weight of two for a `PRIMARY` assignment, one for a `SECONDARY` assignment — and the weighted mean is the sum of each score multiplied by its weight, divided by the sum of the weights."
    PRD §3.5: "The `approach_mean`, `significance_mean`, and `innovation_mean` are the unweighted means of the corresponding criterion scores across the submitted critiques, each rounded half up to two decimal places."
    PRD §3.5: "An application with fewer than two submitted critiques becomes `UNSCORED` (a terminal state): its `impact_score`, criterion means, and both percentiles remain null."

    Design: Difficulty/combinatorial_formula/impact_score_weighted_roles_with_quorum_gate
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section G")
    e_a = fixtures.add_reviewed_application(ctx, section, convene=False, title="Gate A")
    e_b = fixtures.add_reviewed_application(ctx, section, convene=False, title="Gate B")
    fixtures.convene_section(section["id"])
    # App A: PRIMARY overall 2 (criteria 3) + SECONDARY overall 5 (criteria 7).
    fixtures.critique_panel(e_a["panel"], [
        {"overall_impact_score": 2, "significance_score": 3, "innovation_score": 3,
         "approach_score": 3, "investigator_score": 3, "environment_score": 3},
        {"overall_impact_score": 5, "significance_score": 7, "innovation_score": 7,
         "approach_score": 7, "investigator_score": 7, "environment_score": 7},
    ])
    # App B: only the PRIMARY critique is submitted; SECONDARY stays ACCEPTED,
    # so the quorum gate (fewer than two submitted critiques) fires.
    fixtures.critique_panel(e_b["panel"], [{"overall_impact_score": 4}, None])
    fixtures.release_scores(section["id"])

    app_a = fixtures.refresh_application(e_a["application"]["id"])
    assert app_a["status"] == "SCORED"
    assert app_a["impact_score"] == _impact_score([("PRIMARY", 2), ("SECONDARY", 5)]) == 30
    assert app_a["approach_mean"] == float(_rhup(Decimal(3 + 7) / 2, 2)) == 5.0

    app_b = fixtures.refresh_application(e_b["application"]["id"])
    assert app_b["status"] == "UNSCORED"
    assert app_b["impact_score"] is None
    assert app_b["percentile_raw"] is None


def test_percentile_tie_breaks_by_approach_mean():
    """PRD §3.5: "The pool is every application of this study section in `SCORED` status, sorted by `impact_score` from lowest to highest; ties break by `approach_mean` lowest first, then `significance_mean` lowest first, then `innovation_mean` lowest first, and finally `created_at` earliest first — the resource `id` is never a tie-break."
    PRD §3.5: "Each application takes a 1-based rank in this ordering, and its `percentile_raw` is one hundred multiplied by the rank minus one-half, divided by the pool size, rounded half up to one decimal place."

    Design: Corner/calculations/percentile_tie_breaks_by_approach_mean
    """
    ctx = fixtures.make_review_context()
    section = fixtures.make_study_section(name="Section TB")
    e_x = fixtures.add_reviewed_application(ctx, section, convene=False, title="Tie X")
    e_y = fixtures.add_reviewed_application(ctx, section, convene=False, title="Tie Y")
    # Both applications score impact 30; X has approach mean 2.0, Y has 5.0.
    fixtures.score_section(section, [e_x, e_y], [
        [{"overall_impact_score": 3, "approach_score": 2},
         {"overall_impact_score": 3, "approach_score": 2}],
        [{"overall_impact_score": 3, "approach_score": 5},
         {"overall_impact_score": 3, "approach_score": 5}],
    ])

    app_x = fixtures.refresh_application(e_x["application"]["id"])
    app_y = fixtures.refresh_application(e_y["application"]["id"])
    assert app_x["impact_score"] == 30 and app_y["impact_score"] == 30
    assert app_x["approach_mean"] == 2.0 and app_y["approach_mean"] == 5.0
    # Tied on impact: the lower approach_mean ranks first.
    assert app_x["percentile_raw"] == _percentile(1, 2)   # 25.0
    assert app_y["percentile_raw"] == _percentile(2, 2)   # 75.0


def test_normalized_percentile_reconciled_after_second_release():
    """PRD §3.5: "Because the normalized variant re-runs over the entire activity-code pool on every release, a later-releasing section rewrites the `percentile_normalized` values of applications scored by earlier sections; the two variants share inputs but rank differently whenever section means differ, and the normalized percentile is the metric that payline decisions use."

    Design: Corner/cross_cutting_layers/normalized_percentile_reconciled_after_second_release
    """
    ctx = fixtures.make_review_context()
    sec_a = fixtures.make_study_section(name="Section RA", meeting_date="2027-03-01T00:00:00Z")
    sec_b = fixtures.make_study_section(name="Section RB", meeting_date="2027-04-15T00:00:00Z")
    e_a1 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="RA1")
    e_a2 = fixtures.add_reviewed_application(ctx, sec_a, convene=False, title="RA2")
    e_b1 = fixtures.add_reviewed_application(ctx, sec_b, convene=False, title="RB1")
    # Convene both sections first, then submit every critique, so the two
    # releases differ only in pool membership at release time.
    fixtures.convene_section(sec_a["id"])
    fixtures.convene_section(sec_b["id"])
    fixtures.critique_panel(e_a1["panel"], [{"overall_impact_score": 2},
                                            {"overall_impact_score": 2}])
    fixtures.critique_panel(e_a2["panel"], [{"overall_impact_score": 4},
                                            {"overall_impact_score": 4}])
    fixtures.critique_panel(e_b1["panel"], [{"overall_impact_score": 5},
                                            {"overall_impact_score": 5}])

    fixtures.release_scores(sec_a["id"])
    mid = fixtures.refresh_application(e_a1["application"]["id"])
    # Only section A has scored applications: the R01 normalized pool is
    # {20, 40}, its mean equals the section mean, so adjusted scores equal the
    # raw impacts and a1 (20) ranks first of two.
    assert mid["percentile_normalized"] == _percentile(1, 2)   # 25.0
    assert mid["percentile_raw"] == _percentile(1, 2)          # 25.0

    fixtures.release_scores(sec_b["id"])
    end = fixtures.refresh_application(e_a1["application"]["id"])
    # The pool is now {20, 40, 50}: pool mean 36.7, section-A mean 30.0, so
    # a1's adjusted score is 6.7 and it still ranks first, now of three.
    assert end["percentile_normalized"] == _percentile(1, 3)   # 16.7
    assert end["percentile_raw"] == _percentile(1, 2) == 25.0, (
        "the raw percentile is section-local and must not be rewritten cross-panel"
    )
    assert end["impact_score"] == 20, (
        "reconciliation touches percentiles only, never the impact score"
    )
