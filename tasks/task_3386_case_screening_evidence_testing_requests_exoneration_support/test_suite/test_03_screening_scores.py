"""Screening priority scores: the STANDARD and EXPEDITED weight profiles, the
per-factor rounding order, and variant selection for the waitlist freeze."""
import pytest

from test_helpers import (
    ANCHOR_SCORE_EXPEDITED,
    ANCHOR_SCORE_STANDARD,
    create_client,
    create_jurisdiction,
    setup_intake_pipeline,
    setup_waitlisted_request,
)


def _two_identical_factor_waitlisted_requests():
    """Two requests with identical assessment factors (the PRD's worked
    anchor inputs), one plain and one expedited, both decided WAITLISTED."""
    jurisdiction = create_jurisdiction(state_code="AZ", name="Arizona")
    client = create_client(full_name="Maria Sol", inmate_number="AZ-0099")
    plain = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={"conviction_summary": "Request one"},
    )["intake"]
    expedited = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={"conviction_summary": "Request two", "expedited_review": True},
    )["intake"]
    assert plain["expedited_review"] is False
    assert expedited["expedited_review"] is True
    return plain, expedited


def test_screening_standard_and_expedited_scores_stored_at_recommend(api):
    """PRD section 3.1: "For illustration, a request rated `STRONG`,
    `LIKELY_STORED`, 7 years served, and `CRITICAL` yields a time factor of
    23.33 and, under STANDARD, the products 34.00, 17.88, 4.32, and 10.35 — a
    `screening_score_standard` of 66.55; the identical inputs under EXPEDITED
    produce 71.07 as the `screening_score_expedited`."

    Design: Difficulty/dual_variant_calc/screening_standard_vs_expedited_score
    """
    plain, _ = _two_identical_factor_waitlisted_requests()
    assert plain["screening_score_standard"] == pytest.approx(66.55, abs=1e-9)
    assert plain["screening_score_expedited"] == pytest.approx(71.07, abs=1e-9)
    assert plain["screening_score_standard"] == ANCHOR_SCORE_STANDARD
    assert plain["screening_score_expedited"] == ANCHOR_SCORE_EXPEDITED


def test_waitlist_freeze_selects_variant_by_expedited_flag(api):
    """PRD section 3.2: "At decide time the server freezes
    `waitlist_priority_score` on the request: the `screening_score_expedited`
    value when the request's `expedited_review` flag is true, the
    `screening_score_standard` value otherwise."
    PRD section 3.1: "Both variants are always computed and stored at
    recommendation time, regardless of the `expedited_review` flag."

    Design: Difficulty/dual_variant_calc/screening_standard_vs_expedited_score
    """
    plain, expedited = _two_identical_factor_waitlisted_requests()
    # Identical factors -> identical stored score pair on both requests...
    assert expedited["screening_score_standard"] == pytest.approx(66.55, abs=1e-9)
    assert expedited["screening_score_expedited"] == pytest.approx(71.07, abs=1e-9)
    # ...but the frozen waitlist score follows the per-request flag.
    assert plain["waitlist_priority_score"] == pytest.approx(66.55, abs=1e-9)
    assert expedited["waitlist_priority_score"] == pytest.approx(71.07, abs=1e-9)
    assert plain["waitlist_priority_score"] != expedited["waitlist_priority_score"]


def test_screening_score_standard_per_factor_rounding(api):
    """PRD section 2.10: "Screening scores are carried to exactly 2 decimal
    places using round-half-up, and the rounding order is pinned: each weighted
    factor product is rounded to 2 decimals first, and the score is the plain
    sum of those four rounded products with no final re-rounding."
    PRD section 3.1: "the products 34.00, 17.88, 4.32, and 10.35 — a
    `screening_score_standard` of 66.55".

    Design: Difficulty/combinatorial_formula/screening_per_factor_rounding_order
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "GA", "name": "Georgia"},
        recommendation="WAITLIST",
    )
    # Sum-then-round of the unrounded products would give 66.54; the pinned
    # per-factor-first order gives exactly 66.55.
    assert ctx["intake"]["screening_score_standard"] == pytest.approx(66.55, abs=1e-9)


def test_screening_score_both_variants_computed_regardless_of_flag(api):
    """PRD section 3.1: "Both variants are always computed and stored at
    recommendation time, regardless of the `expedited_review` flag."
    PRD section 3.1: "the identical inputs under EXPEDITED produce 71.07 as the
    `screening_score_expedited`."

    Design: Difficulty/combinatorial_formula/screening_per_factor_rounding_order
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "GA", "name": "Georgia"},
        intake_overrides={"expedited_review": True},
        recommendation="WAITLIST",
    )
    intake = ctx["intake"]
    assert intake["expedited_review"] is True
    assert intake["screening_score_standard"] == pytest.approx(66.55, abs=1e-9)
    assert intake["screening_score_expedited"] == pytest.approx(71.07, abs=1e-9)
    assert intake["screening_score_standard"] != intake["screening_score_expedited"]
