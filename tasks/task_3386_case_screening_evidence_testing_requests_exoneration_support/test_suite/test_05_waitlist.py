"""Waitlist selection: priority-score ranking, the created_at tie-break, the
expedited variant's effect on the winner, and the empty-pool rejection."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_jurisdiction,
    get_intake_request,
    setup_waitlisted_request,
    validate_error,
    validate_ok,
)

DECIDER = TEST_USERS["managing_attorney_headers"]


def test_waitlist_tie_break_uses_created_at_not_id(api):
    """PRD section 3.2: "the system considers every request in `WAITLISTED`
    status, ranks them by `waitlist_priority_score` descending, breaks ties by
    `created_at` ascending, and returns the chosen request to `SCREENING` for
    a fresh recommendation cycle."
    PRD section 3.2: "The `id` never participates in the ranking or the
    tie-break."
    PRD section 3.2: "If no request is waitlisted, the activation is rejected
    with `ERR_WAITLIST_EMPTY` (HTTP 409) and nothing changes."

    Design: Corner/calculations/waitlist_tie_break_uses_created_at_not_id
    """
    jurisdiction = create_jurisdiction(state_code="SC", name="South Carolina")
    client = create_client(full_name="Al Poe", inmate_number="SC-1")
    factors = {
        "conviction_date": "2010-01-01T00:00:00Z",
        "claim_strength": "MODERATE",
        "evidence_potential": "UNCERTAIN",
        "years_served": 30,
        "health_urgency": "NONE",
    }
    first_created = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={**factors, "conviction_summary": "Tie A"},
    )["intake"]
    second_created = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={**factors, "conviction_summary": "Tie B"},
    )["intake"]
    # Identical factors freeze identical scores (23.38 + 9.63 + 18.50 + 0.00).
    assert first_created["waitlist_priority_score"] == pytest.approx(51.51, abs=1e-9)
    assert second_created["waitlist_priority_score"] == pytest.approx(51.51, abs=1e-9)

    winner1 = validate_ok(api.activate_waitlist_next(DECIDER))
    assert winner1["id"] == first_created["id"], (
        "the earlier-created request wins the created_at tie-break"
    )
    assert winner1["status"] == "SCREENING"
    winner2 = validate_ok(api.activate_waitlist_next(DECIDER))
    assert winner2["id"] == second_created["id"]

    assert get_intake_request(first_created["id"])["status"] == "SCREENING"
    assert get_intake_request(second_created["id"])["status"] == "SCREENING"
    resp = api.activate_waitlist_next(DECIDER)
    validate_error(resp, ApiErrorId.ERR_WAITLIST_EMPTY)


def test_waitlist_variant_selection_flips_the_winner(api):
    """PRD section 3.2: "At decide time the server freezes
    `waitlist_priority_score` on the request: the `screening_score_expedited`
    value when the request's `expedited_review` flag is true, the
    `screening_score_standard` value otherwise."
    PRD section 3.2: "ranks them by `waitlist_priority_score` descending".

    Design: Corner/calculations/waitlist_variant_selection_flips_the_winner
    """
    jurisdiction = create_jurisdiction(state_code="ND", name="North Dakota")
    client = create_client(full_name="Cy Wren", inmate_number="ND-1")
    older_plain = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={"conviction_summary": "Variant X"},
    )["intake"]
    newer_expedited = setup_waitlisted_request(
        jurisdiction_id=jurisdiction["id"],
        client_id=client["id"],
        intake_overrides={"conviction_summary": "Variant Y", "expedited_review": True},
    )["intake"]
    # Identical anchor factors: STANDARD 66.55 vs EXPEDITED 71.07.
    assert older_plain["waitlist_priority_score"] == pytest.approx(66.55, abs=1e-9)
    assert newer_expedited["waitlist_priority_score"] == pytest.approx(71.07, abs=1e-9)

    winner = validate_ok(api.activate_waitlist_next(DECIDER))
    assert winner["id"] == newer_expedited["id"], (
        "the expedited variant's higher frozen score beats the older request; "
        "a STANDARD-scored Y would have tied at 66.55 and lost the created_at "
        "tie-break to X"
    )


def test_waitlist_activate_with_empty_pool_rejected(api):
    """PRD section 3.2: "If no request is waitlisted, the activation is
    rejected with `ERR_WAITLIST_EMPTY` (HTTP 409) and nothing changes."

    Design: Corner/validations/waitlist_activate_with_empty_pool_rejected
    """
    resp = api.activate_waitlist_next(DECIDER)
    validate_error(resp, ApiErrorId.ERR_WAITLIST_EMPTY)
