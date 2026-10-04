"""Dual-failure requests: the ordered ladder decides which error the caller sees."""
from test_helpers import (
    ApiErrorId,
    LATE_WINDOW_CLOCK_UTC,
    PRE_RELEASE_CLOCK_UTC,
    SPECIALIST,
    api_client,
    get_score,
    host_headers,
    open_case,
    set_clock,
    setup_aggregated_score,
    setup_fee_pending_registration,
    transition_registration,
    validate_error,
)


def _attempt_registration_transition(registration, school, to_status, extra=None):
    payload = {"to_status": to_status}
    if extra:
        payload.update(extra)
    return api_client.transition_exam_registration(
        registration["id"], payload, host_headers(school)
    )


# --------------------------------------------------------------------------
# rank 7 (ERR_INVALID_STATE) outranks rank 24 (ERR_LATE_FEE_UNPAID)
# --------------------------------------------------------------------------

def test_state_failure_outranks_the_unpaid_late_fee_on_a_cancelled_registration():
    """PRD §2.6: "Every request is evaluated against an ordered ladder of twenty-nine ranks, and the first failing rank wins: a request that violates two rules simultaneously returns the error belonging to the lower-numbered rank, never the other one."
    PRD §2.6: "| 7 | The entity's current status admits the requested `to_status` | `ERR_INVALID_STATE` | 409 |"
    PRD §2.6: "| 24 | A registration only reaches `CONFIRMED` when `fees_paid_cents` is at least `late_fee_cents` | `ERR_LATE_FEE_UNPAID` | 402 |"

    Design: Difficulty/priority_pair_validation_conflict/state_precedence_over_fiscal_on_confirm_replay
    """
    bundle = setup_fee_pending_registration(clock=LATE_WINDOW_CLOCK_UTC)
    registration = bundle["registration"]
    assert registration["late_fee_cents"] == 4000
    assert registration["fees_paid_cents"] == 0

    cancelled = transition_registration(registration, "CANCELLED", school=bundle["school"])
    assert cancelled["status"] == "CANCELLED"

    response = _attempt_registration_transition(cancelled, bundle["school"], "CONFIRMED")
    error = validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] != ApiErrorId.ERR_LATE_FEE_UNPAID
    assert response.status_code == 409, (
        f"rank 7 wins, so the answer is 409 and never 402; got {response.status_code}"
    )


def test_unpaid_late_fee_alone_returns_payment_required():
    """PRD §3.3: "The forward move to `CONFIRMED` requires `fees_paid_cents` to be at least `late_fee_cents`, and a registration whose late fee is still unpaid is refused with `ERR_LATE_FEE_UNPAID`"
    PRD §2.6: "| 24 | A registration only reaches `CONFIRMED` when `fees_paid_cents` is at least `late_fee_cents` | `ERR_LATE_FEE_UNPAID` | 402 |"

    Design: Difficulty/priority_pair_validation_conflict/state_precedence_over_fiscal_on_confirm_replay
    """
    bundle = setup_fee_pending_registration(clock=LATE_WINDOW_CLOCK_UTC)
    registration = bundle["registration"]

    response = _attempt_registration_transition(registration, bundle["school"], "CONFIRMED")
    validate_error(response, ApiErrorId.ERR_LATE_FEE_UNPAID)
    assert response.status_code == 402, (
        f"the fiscal refusal is a 402, not a state error; got {response.status_code}"
    )


# --------------------------------------------------------------------------
# rank 19 (ERR_RELEASE_BLOCKED) outranks rank 20 (ERR_SCORE_RELEASE_TOO_EARLY)
# --------------------------------------------------------------------------

def test_release_block_outranks_the_release_window_on_a_dual_failure():
    """PRD §2.6: "| 19 | Score release requires `release_blocked` to be false; an open or investigating case blocks it | `ERR_RELEASE_BLOCKED` | 409 |"
    PRD §2.6: "| 20 | A score is only `RELEASED` at or after its release-open instant | `ERR_SCORE_RELEASE_TOO_EARLY` | 422 |"
    PRD §2.6: "Every request is evaluated against an ordered ladder of twenty-nine ranks, and the first failing rank wins"

    Design: Difficulty/priority_pair_validation_conflict/referential_precedence_over_temporal_on_release
    """
    bundle = setup_aggregated_score()
    set_clock(PRE_RELEASE_CLOCK_UTC)
    open_case(bundle["registration"], bundle["school"], "UNAUTHORIZED_DEVICE")

    score = get_score(bundle["score"]["id"])
    assert score["release_blocked"] is True

    response = api_client.transition_exam_score(
        score["id"],
        {"to_status": "RELEASED", "expected_exam_score_version": score["version"]},
        SPECIALIST,
    )
    error = validate_error(response, ApiErrorId.ERR_RELEASE_BLOCKED)
    assert error["error_id"] != ApiErrorId.ERR_SCORE_RELEASE_TOO_EARLY
    assert response.status_code == 409, (
        f"rank 19 wins, so the answer is 409 and never 422; got {response.status_code}"
    )


def test_release_before_the_release_open_instant_alone_returns_too_early():
    """PRD §3.8: "A release attempted before the gate opens is refused with `ERR_SCORE_RELEASE_TOO_EARLY`."
    PRD §2.6: "| 20 | A score is only `RELEASED` at or after its release-open instant | `ERR_SCORE_RELEASE_TOO_EARLY` | 422 |"

    Design: Difficulty/priority_pair_validation_conflict/referential_precedence_over_temporal_on_release
    """
    bundle = setup_aggregated_score()
    set_clock(PRE_RELEASE_CLOCK_UTC)
    score = get_score(bundle["score"]["id"])
    assert score["release_blocked"] is False

    response = api_client.transition_exam_score(
        score["id"],
        {"to_status": "RELEASED", "expected_exam_score_version": score["version"]},
        SPECIALIST,
    )
    validate_error(response, ApiErrorId.ERR_SCORE_RELEASE_TOO_EARLY)
    assert response.status_code == 422, (
        f"the temporal refusal is a 422, not a state error; got {response.status_code}"
    )
