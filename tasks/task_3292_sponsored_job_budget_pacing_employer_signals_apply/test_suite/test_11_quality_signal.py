"""Employer quality signal: tier selection and disposition mix.

The score is a tier drawn from the response rate plus a delta drawn from the
disposition mix, both computed over the same dispositioned population.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    make_employer_headers, set_clock, create_employer, create_seeker,
    create_posting, create_completed_application, create_answered_application,
    get_employer, build_quality_history,
    assert_employer, assert_employer_invariants,
    TIER_HIGH, TIER_MID, TIER_LOW,
)

ADMIN = TEST_USERS["admin_headers"]


def test_quality_score_uses_the_base_tier_for_a_thin_response_history(api):
    """PRD §3.7: "The first is a tier selected from the response rate, and its
    boundaries are inclusive at the bottom: a rate of at least 6,000 basis points
    earns the high tier of 100, a rate of at least 3,000 basis points but below
    6,000 earns the middle tier of 70, and anything lower earns the base tier of
    40."

    Design: Corner/calculations/quality_signal_low_tier_from_thin_response_history
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Thin Co", domain="thin.example")
    headers = make_employer_headers(employer["id"])
    seeker = create_seeker(full_name="Thin Seeker")
    posting = create_posting(employer, title="Thin Engineer")

    # One responded application out of four dispositioned => 2500 bps.
    create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    for _ in range(3):
        create_completed_application(posting, seeker, employer)
    # Re-read and close the three unanswered ones.
    data = validate_success(api_client.list_applications(
        ADMIN, params={"job_posting_id": posting["id"], "status": "COMPLETED"}), 200)
    for application in data:
        get_success_data(api_client.close_application(application["id"], headers))

    final = get_employer(employer["id"])
    assert_employer(final)
    assert final["response_rate_bps"] == 2500
    assert final["quality_score"] == TIER_LOW


def test_quality_score_rises_with_the_middle_tier(api):
    """PRD §3.7: "a rate of at least 3,000 basis points but below 6,000 earns the
    middle tier of 70".

    Design: Corner/calculations/quality_signal_low_tier_from_thin_response_history
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Mid Co", domain="mid.example")
    seeker = create_seeker(full_name="Mid Seeker")
    posting = create_posting(employer, title="Mid Engineer")

    # Two responded of four dispositioned => exactly 5000 bps.
    create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    for _ in range(2):
        create_completed_application(posting, seeker, employer)
    data = validate_success(api_client.list_applications(
        ADMIN, params={"job_posting_id": posting["id"], "status": "COMPLETED"}), 200)
    for application in data:
        get_success_data(api_client.close_application(
            application["id"], make_employer_headers(employer["id"])))

    final = get_employer(employer["id"])
    assert_employer(final)
    assert final["response_rate_bps"] == 5000
    assert final["quality_score"] == TIER_MID


def test_quality_score_keeps_the_high_tier_when_every_application_is_answered(api):
    """PRD §3.7: "a rate of at least 6,000 basis points earns the high tier of
    100".
    PRD §3.7: "The score starts at 100 for a brand-new employer, which is the
    highest possible tier, and the field can only be moved by disposition
    activity."

    Design: Corner/calculations/quality_signal_low_tier_from_thin_response_history
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="High Co", domain="high.example")
    seeker = create_seeker(full_name="High Seeker")
    posting = create_posting(employer, title="High Engineer")

    create_answered_application(posting, seeker, employer, disposition="REVIEWED")
    create_answered_application(posting, seeker, employer, disposition="HIRED")

    final = get_employer(employer["id"])
    assert_employer(final)
    assert final["response_rate_bps"] == 10000
    assert final["quality_score"] == TIER_HIGH


def test_quality_score_floor_holds_for_an_entirely_unanswered_history(api):
    """PRD §3.7: "when there are no dispositioned applications at all the rate is
    0, and an employer who never answers anything therefore sits at a response
    rate of 0 rather than being undefined."
    PRD §3.7: "The two parts are summed and the total is clamped into the closed
    interval from 0 to 100, which is the score."

    Design: Corner/calculations/quality_signal_low_tier_from_thin_response_history
    """
    set_clock("2026-09-01T00:00:00Z")
    employer = create_employer(legal_name="Floor Co", domain="floor.example")
    seeker = create_seeker(full_name="Floor Seeker")
    posting = create_posting(employer, title="Floor Engineer")

    for _ in range(4):
        create_completed_application(posting, seeker, employer)
    data = validate_success(api_client.list_applications(
        ADMIN, params={"job_posting_id": posting["id"], "status": "COMPLETED"}), 200)
    for application in data:
        get_success_data(api_client.close_application(
            application["id"], make_employer_headers(employer["id"])))

    final = get_employer(employer["id"])
    assert_employer_invariants(final)
    assert final["response_rate_bps"] == 0
    assert final["quality_score"] == TIER_LOW
    assert final["quality_score"] >= 0