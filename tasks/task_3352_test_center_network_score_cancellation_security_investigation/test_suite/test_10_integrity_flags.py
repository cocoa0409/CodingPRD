"""Integrity screens: anomalous gain, response similarity, score variants."""
from test_helpers import (
    RAWS_PROVISIONAL_120,
    RAWS_PROVISIONAL_97,
    get_score_record,
    list_review_cases,
    setup_analyzed_session,
)


def _dual_variant_session(name):
    """A raws [33,21,40] prior 80; B raws [40,40,40] prior 100; analysis run.

    Session mean raw = 107.00, so A: provisional 97 -> scaled 91 (gain 11),
    B: provisional 120 -> scaled 127 (gain 27); neither flags.
    """
    specs = [
        {"section_raws": RAWS_PROVISIONAL_97, "prior_best_scaled_score": 80,
         "id_document_number": "PAAA"},
        {"section_raws": RAWS_PROVISIONAL_120, "prior_best_scaled_score": 100,
         "id_document_number": "NBBB", "id_document_type": "NATIONAL_ID",
         "id_document_expiry": "2028-01-01"},
    ]
    return setup_analyzed_session(specs, name=name, total_seats=10)


def test_provisional_differs_from_equated_variant(api):
    """PRD §3.5: "The provisional and equated variants genuinely diverge — a
    record with raw total 94 in a session whose mean raw is 107.00 finishes at
    91 rather than its provisional 97."

    Design: Difficulty/dual_variant_calc/score_scaling_provisional_vs_equated
    """
    ctx = _dual_variant_session("Center DV")
    record_a = get_score_record(ctx["score_records"][0]["id"])
    assert record_a["provisional_scaled_score"] == 97
    assert record_a["scaled_score"] == 91, (
        "97 + floor(0.5*(94-107.00)+0.5) = 97 - 6"
    )
    assert record_a["provisional_scaled_score"] != record_a["scaled_score"], (
        "the two variants produce different integers for identical raw input"
    )


def test_equated_variant_values_and_release(api):
    """PRD §3.5: "Records with no firing signal transition straight from
    `PENDING_ANALYSIS` to `RELEASED`, their `scaled_score` now final."
    PRD §3.5: "Third, each record's `scaled_score` is its provisional score
    plus the equating adjustment, where the adjustment is half of the
    difference between the record's own raw total and the session mean raw"

    Design: Difficulty/dual_variant_calc/score_scaling_provisional_vs_equated
    """
    ctx = _dual_variant_session("Center DV2")
    record_a = get_score_record(ctx["score_records"][0]["id"])
    record_b = get_score_record(ctx["score_records"][1]["id"])
    assert record_b["provisional_scaled_score"] == 120
    assert record_b["scaled_score"] == 127, "120 + floor(0.5*(120-107.00)+0.5)"
    assert record_a["status"] == "RELEASED"
    assert record_b["status"] == "RELEASED"


def _similarity_session(name):
    """A: raws [10,10,10], 34/40 matched, same-form adjacent, prior 23.
    B: raws [20,20,20], 33/40 matched, same-form adjacent, prior 68.

    Session mean raw = 45.00, so A equates to 23 (gain 0) and B to 68
    (gain 0): only the similarity signal can fire.
    """
    specs = [
        {"section_raws": [10, 10, 10], "prior_best_scaled_score": 23,
         "matched_responses_count": 34, "total_scored_items": 40,
         "same_form": True, "adjacent_seated": True, "id_document_number": "PSA1"},
        {"section_raws": [20, 20, 20], "prior_best_scaled_score": 68,
         "matched_responses_count": 33, "total_scored_items": 40,
         "same_form": True, "adjacent_seated": True, "id_document_number": "NSB1",
         "id_document_type": "NATIONAL_ID", "id_document_expiry": "2028-01-01"},
    ]
    return setup_analyzed_session(specs, name=name, total_seats=5)


def test_similarity_at_threshold_flags(api):
    """PRD §3.5: "The two gates interact non-linearly: 34 matches out of 40
    items for a same-form adjacent pair yields 0.85 and flags, 33 of 40 yields
    0.825 and does not, and 34 of 40 for a non-adjacent pair yields 0.595 and
    does not."
    PRD §3.5: "A record with at least one firing signal transitions to
    `UNDER_REVIEW` — still receiving its final `scaled_score` — and the run
    opens a `ScoreReviewCase` for it in `OPENED` status, with
    `flagged_by_analyst_id` set to the running analyst's identifier and
    `trigger_reason` chosen by priority when several signals fire at once:
    `CONTENT_EXPOSURE` outranks `ANOMALOUS_GAIN`, which outranks
    `RESPONSE_SIMILARITY`."

    Design: Difficulty/combinatorial_formula/similarity_weighted_nonlinear_threshold
    """
    ctx = _similarity_session("Center SM")
    run = ctx["run_output"]
    assert run["processed_count"] == 2
    assert run["flagged_count"] == 1
    assert run["released_count"] == 1
    record_a = get_score_record(ctx["score_records"][0]["id"])
    assert record_a["scaled_score"] == 23, "30 + floor(0.5*(30-45.00)+0.5)"
    assert record_a["status"] == "UNDER_REVIEW", (
        "34/40 * 1.0 * 1.0 = 0.85 >= 0.85 and 34 >= 20"
    )
    case = list_review_cases(ctx["registrations"][0]["id"])[0]
    assert case["trigger_reason"] == "RESPONSE_SIMILARITY"
    assert case["status"] == "OPENED"


def test_similarity_below_threshold_releases(api):
    """PRD §3.5: "The two gates interact non-linearly: 34 matches out of 40
    items for a same-form adjacent pair yields 0.85 and flags, 33 of 40 yields
    0.825 and does not, and 34 of 40 for a non-adjacent pair yields 0.595 and
    does not."
    PRD §3.5: "Records with no firing signal transition straight from
    `PENDING_ANALYSIS` to `RELEASED`, their `scaled_score` now final."

    Design: Difficulty/combinatorial_formula/similarity_weighted_nonlinear_threshold
    """
    ctx = _similarity_session("Center SM2")
    record_b = get_score_record(ctx["score_records"][1]["id"])
    assert record_b["scaled_score"] == 68, "60 + floor(0.5*(60-45.00)+0.5)"
    assert record_b["status"] == "RELEASED", "33/40 = 0.825 < 0.85"
    assert list_review_cases(ctx["registrations"][1]["id"]) == [], (
        "no case opened for a clean record"
    )


def _gain_boundary_session(name):
    """A: raws [33,21,40] prior 61 -> equated 91 -> gain exactly 30.
    B: raws [40,40,40] prior 98 -> equated 127 -> gain exactly 29."""
    specs = [
        {"section_raws": RAWS_PROVISIONAL_97, "prior_best_scaled_score": 61,
         "id_document_number": "PGA1"},
        {"section_raws": RAWS_PROVISIONAL_120, "prior_best_scaled_score": 98,
         "id_document_number": "NGB1", "id_document_type": "NATIONAL_ID",
         "id_document_expiry": "2028-01-01"},
    ]
    return setup_analyzed_session(specs, name=name, total_seats=10)


def test_gain_exactly_30_flags(api):
    """PRD §3.5: "The anomalous-gain check subtracts `prior_best_scaled_score`
    from the new `scaled_score` and flags the record when the gain is at least
    30 — a gain of exactly 30 flags, while 29 does not."

    Design: Difficulty/boundary_precision_check/gain_threshold_exact_30_flags
    """
    ctx = _gain_boundary_session("Center GT")
    record_a = get_score_record(ctx["score_records"][0]["id"])
    assert record_a["scaled_score"] == 91
    assert record_a["scaled_score"] - 61 == 30
    assert record_a["status"] == "UNDER_REVIEW", "gain >= 30 flags"
    case = list_review_cases(ctx["registrations"][0]["id"])[0]
    assert case["trigger_reason"] == "ANOMALOUS_GAIN"
    run = ctx["run_output"]
    assert run["processed_count"] == 2
    assert run["flagged_count"] == 1
    assert run["released_count"] == 1


def test_gain_29_does_not_flag(api):
    """PRD §3.5: "The anomalous-gain check subtracts `prior_best_scaled_score`
    from the new `scaled_score` and flags the record when the gain is at least
    30 — a gain of exactly 30 flags, while 29 does not."
    PRD §3.5: "Records with no firing signal transition straight from
    `PENDING_ANALYSIS` to `RELEASED`, their `scaled_score` now final."

    Design: Difficulty/boundary_precision_check/gain_threshold_exact_30_flags
    """
    ctx = _gain_boundary_session("Center GT2")
    record_b = get_score_record(ctx["score_records"][1]["id"])
    assert record_b["scaled_score"] == 127
    assert record_b["scaled_score"] - 98 == 29
    assert record_b["status"] == "RELEASED", "gain 29 < 30 does not flag"
    assert list_review_cases(ctx["registrations"][1]["id"]) == []
