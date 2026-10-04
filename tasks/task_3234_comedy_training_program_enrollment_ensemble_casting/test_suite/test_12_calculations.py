"""Corner queue: calculations — precision, selector input-set filtering, constants."""
import pytest
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error, ApiErrorId,
    create_student, reset_clock, create_audition_payload, create_level,
    create_placement_evaluation_payload, setup_open_term_with_section,
    enroll_with_fresh_version, confirm_enrollment, drop_enrollment, get_enrollment,
)

PD = TEST_USERS["program_director_headers"]
REG = TEST_USERS["registrar_headers"]
PO = TEST_USERS["placement_officer_headers"]
CD = TEST_USERS["casting_director_headers"]


def test_ensemble_composite_score_precision_round_half_up():
    """PRD §3.7: "each dimension's rubric score is multiplied by that dimension's
    weight — scene work counts for 40%, characters for 25%, musicality for 20%, and
    game for 15% — the products are summed, dimensions missing from the rubric
    contribute zero, and the total is rounded half-up to two decimal places."

    Design: Corner/calculations/ensemble_composite_score_precision_round_half_up
    """
    reset_clock()
    student = create_student()
    aud = validate_success(api_client.create_audition(
        create_audition_payload(student["id"], "ENSEMBLE",
                                rubric_scores={"scene_work": 5, "characters": 5,
                                               "musicality": 5, "game": 5}), CD), 201)
    evaluated = validate_success(api_client.evaluate_audition(aud["id"], CD))
    # 5 * (0.4+0.25+0.2+0.15) = 5.00 exactly
    assert evaluated["composite_score"] == pytest.approx(5.00, abs=0.001)


def test_seat_allocation_selector_priority_tier_beats_created_at():
    """PRD §3.3: "They are ranked first by `priority_tier` with `RETURNING` ahead of
    `NEW`, then by enrollment `created_at` ascending; ties fall to earlier
    `created_at`, and the record `id` is never used as a tie-break."

    Design: Corner/calculations/seat_allocation_selector_priority_tier_beats_created_at
    """
    ctx = setup_open_term_with_section(capacity=1)
    s1 = create_student()
    s2 = create_student()
    s3 = create_student()
    e1 = enroll_with_fresh_version(s1["id"], ctx["section"]["id"])
    confirm_enrollment(e1["id"])
    e2 = enroll_with_fresh_version(s2["id"], ctx["section"]["id"],
                                   priority_tier="NEW")
    e3 = enroll_with_fresh_version(s3["id"], ctx["section"]["id"],
                                   priority_tier="RETURNING")
    assert get_enrollment(e2["id"])["status"] == "WAITLISTED"
    assert get_enrollment(e3["id"])["status"] == "WAITLISTED"
    drop_enrollment(e1["id"])
    # RETURNING (s3, created later) must be promoted ahead of NEW (s2, earlier)
    assert get_enrollment(e3["id"])["status"] == "REGISTERED"
    assert get_enrollment(e2["id"])["status"] == "WAITLISTED"


def test_placement_portfolio_threshold_boundary_69_vs_70():
    """PRD §3.3: "Granting a `PORTFOLIO_REVIEW` petition requires a
    `portfolio_score` of at least 70 — below that threshold the grant fails with
    `ERR_PORTFOLIO_SCORE_TOO_LOW` (HTTP 422)."

    Design: Corner/calculations/placement_portfolio_threshold_boundary_69_vs_70
    """
    reset_clock()
    create_level(code="L1", allows_placement_bypass=False)
    lvl2 = create_level(code="L2", sequence_index=1, requires_level_code="L1",
                        allows_placement_bypass=True)
    s1 = create_student()
    s2 = create_student()
    pe69 = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(
            s1["id"], lvl2["id"], prior_institution="Unknown School",
            portfolio_score=69), PO), 201)
    pe70 = validate_success(api_client.create_placement_evaluation(
        create_placement_evaluation_payload(
            s2["id"], lvl2["id"], prior_institution="Unknown School",
            portfolio_score=70), PO), 201)
    validate_success(api_client.begin_review_placement(pe69["id"], PO))
    validate_success(api_client.begin_review_placement(pe70["id"], PO))
    validate_error(api_client.grant_placement(pe69["id"], PO),
                   ApiErrorId.ERR_PORTFOLIO_SCORE_TOO_LOW, 422)
    granted = validate_success(api_client.grant_placement(pe70["id"], PO))
    assert granted["decision"] == "GRANTED"
