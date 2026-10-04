"""Desk handoff: the identity ritual, its failure mode and desk saturation."""
import pytest

from test_helpers import validate_error, validate_success, ApiErrorId
from test_helpers import constants as C
from test_helpers import fixtures as X


def test_a_matching_token_verifies_and_collects_in_one_act(api):
    """PRD §3.10: "When the submitted `redemption_code` equals the purchase's
    `handoff_token`, and the desk's `status` is `OPEN`, and the desk's
    `handoffs_today` figure is still below its `daily_capacity` — and the purchase
    has not already recorded a failed handoff attempt — the verification
    succeeds: the purchase's `handoff_status` moves to `VERIFIED`, its
    `handoff_verified_at` is stamped with the instant of acceptance, its
    `logistics_status` moves to `COLLECTED`."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, desk_code, patron = X.setup_concierge_purchase(quantity=2)

    verified = X.create_handoff(purchase, desk_code, purchase["handoff_token"])

    assert verified["handoff_status"] == "VERIFIED"
    assert verified["logistics_status"] == "COLLECTED"
    assert verified["handoff_verified_at"] is not None
    assert verified["version"] > purchase["version"], \
        "the acceptance advances the purchase's version"


def test_a_wrong_token_is_a_permanently_recorded_failure(api):
    """PRD §3.10: "When the submitted `redemption_code` does not equal the
    purchase's `handoff_token`, the purchase's `handoff_status` moves to `FAILED`
    and its `handoff_failed_at` is stamped with the instant of the failed
    attempt."
    PRD §3.10: "A mismatch — including a presentation against a purchase that has
    already failed — is reported as `ERR_HANDOFF_TOKEN_INVALID` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, desk_code, patron = X.setup_concierge_purchase(quantity=2)

    response = api.create_handoff(
        {"purchase_id": purchase["id"], "desk_code": desk_code,
         "redemption_code": "000000", "idempotency_key": "failed-1"},
        X.DESK,
    )
    validate_error(response, ApiErrorId.ERR_HANDOFF_TOKEN_INVALID, expected_status=422)

    failed = X.get_purchase(purchase["id"])
    assert failed["handoff_status"] == "FAILED", (
        f"a wrong token records a failed attempt, got {failed['handoff_status']}"
    )
    assert failed["handoff_failed_at"] is not None
    assert failed["logistics_status"] == "AWAITING_HANDOFF", (
        "a failed presentation leaves the purchase visibly uncollected, got "
        f"{failed['logistics_status']}"
    )


def test_a_purchase_that_has_already_failed_can_never_be_verified(api):
    """PRD §3.10: "The attempt is also the only one the purchase gets: a purchase
    that has already recorded a failed handoff attempt can never be verified, and
    the invariant is enforced as a precondition rather than as a soft rule."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, desk_code, patron = X.setup_concierge_purchase(quantity=2)
    after_failure = X.setup_failed_handoff(purchase, desk_code)

    response = api.create_handoff(
        {"purchase_id": purchase["id"], "desk_code": desk_code,
         "redemption_code": purchase["handoff_token"],
         "idempotency_key": "retry-1"},
        X.DESK,
    )
    validate_error(response, ApiErrorId.ERR_HANDOFF_TOKEN_INVALID, expected_status=422)

    still_failed = X.get_purchase(purchase["id"])
    assert still_failed["handoff_status"] == "FAILED", \
        "the purchase must not become verifiable after a recorded failure"
    assert still_failed["handoff_verified_at"] is None
    assert after_failure["handoff_failed_at"] == still_failed["handoff_failed_at"], \
        "the failed attempt instant is not overwritten by the retry"


def test_reaching_daily_capacity_saturates_the_desk(api):
    """PRD §3.10: "The moment a verification takes the desk's `handoffs_today`
    figure to its `daily_capacity`, the desk's `status` moves from `OPEN` to
    `SATURATED` and its `version` advances."
    PRD §3.1: "a desk that is `SATURATED` or whose verified count has reached its
    daily capacity yields `ERR_DESK_CAPACITY_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, pending, desk_code = X.setup_saturated_desk(daily_capacity=1)

    pending = X.get_purchase(pending["id"])
    response = api.create_handoff(
        {"purchase_id": pending["id"], "desk_code": desk_code,
         "redemption_code": pending["handoff_token"],
         "idempotency_key": "saturated-1"},
        X.DESK,
    )
    validate_error(response, ApiErrorId.ERR_DESK_CAPACITY_REACHED, expected_status=409)

    unchanged = X.get_purchase(pending["id"])
    assert unchanged["handoff_status"] == "PENDING_CONCIERGE", (
        "a saturated desk rejects further handoffs for the remainder of its "
        f"epoch, got {unchanged['handoff_status']}"
    )


def test_a_desk_returns_to_open_only_when_a_new_epoch_resets_it(api):
    """PRD §3.10: "A saturated desk rejects further handoffs for the remainder of
    the current operational epoch."
    PRD §3.10: "The desk returns to `OPEN` only when an operational epoch opens a
    new day and resets the counter to zero, and that reset also advances the
    desk's `version`. A saturated desk is therefore a one-day condition, never a
    permanent one."

    Design: Difficulty/non_linear_state_machine/non_linear_ticket_purchase_parallel_state_dimensions
    """
    purchase, pending, desk_code = X.setup_saturated_desk(daily_capacity=1)

    sweep = X.ops_run("2026-09-12T09:30:00Z")

    assert sweep["desks_reset_count"] == 1, (
        f"the sweep resets the saturated desk for the new epoch, got {sweep['desks_reset_count']}"
    )
    verified = X.create_handoff(pending, desk_code, pending["handoff_token"])
    assert verified["handoff_status"] == "VERIFIED", (
        "the desk accepts handoffs again in the new epoch, got "
        f"{verified['handoff_status']}"
    )