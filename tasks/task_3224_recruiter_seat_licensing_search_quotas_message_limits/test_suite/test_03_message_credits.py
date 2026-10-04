"""Message credit pools: parallel message dimensions, credit accounting
identity, strike deltas, throttle cycle, and visibility gating."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TIER_LIMITS,
    ats_service_headers, recruiter_headers,
    create_candidate, send_message, record_response, get_message,
    get_credit_pool, setup_messaging, setup_assigned_seat, create_open_project,
    drain_credits,
)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/message_parallel_delivery_x_response_dimensions
# ---------------------------------------------------------------------------

def test_message_parallel_dimensions_delivery_then_response():
    """PRD section 3.5: "Every new `Message` starts with `delivery_status` of
    `PENDING` and `response_status` of `AWAITING`. Dispatch resolves
    immediately within the send call: if dispatch succeeds, the message moves
    to `delivery_status` of `SENT`"
    PRD section 3.5: "Once `SENT`, the message's `response_status` remains
    `AWAITING` until a response is recorded, the seat is suspended, or 30
    days elapse."
    PRD section 3.5: "`RESPONDED` moves the message to `response_status` of
    `RESPONDED`."

    Design: Difficulty/non_linear_state_machine/message_parallel_delivery_x_response_dimensions
    """
    ctx = setup_messaging(contract_number="C-MSG-1")
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    assert message["delivery_status"] == "SENT"
    assert message["response_status"] == "AWAITING"
    assert message["credit_consumed"] == 1

    updated = record_response(message["id"], "RESPONDED")
    assert updated["response_status"] == "RESPONDED"
    assert updated["delivery_status"] == "SENT"
    assert updated["credit_returned_flag"] is True


def test_message_delivery_dimension_unchanged_by_responses():
    """PRD section 3.5: "Every new `Message` starts with `delivery_status` of
    `PENDING` and `response_status` of `AWAITING`. Dispatch resolves
    immediately within the send call: if dispatch succeeds, the message moves
    to `delivery_status` of `SENT`"
    PRD section 3.5: "`NEGATIVE_RESPONSE` moves the message to
    `response_status` of `NEGATIVE_RESPONSE`, adds 1 to the pool's
    `spam_strike_count`, and returns no credit."

    Design: Difficulty/non_linear_state_machine/message_parallel_delivery_x_response_dimensions
    """
    ctx = setup_messaging(contract_number="C-MSG-1B")
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    assert message["delivery_status"] == "SENT"
    assert message["response_status"] == "AWAITING"

    updated = record_response(message["id"], "NEGATIVE_RESPONSE")
    assert updated["response_status"] == "NEGATIVE_RESPONSE"
    assert updated["delivery_status"] == "SENT"


# ---------------------------------------------------------------------------
# Corner/state_machines/record_response_twice_rejected
# ---------------------------------------------------------------------------

def test_record_response_twice_rejected():
    """PRD section 3.5: "The message must currently have `delivery_status` of
    `SENT` and `response_status` of `AWAITING`; otherwise the call is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/record_response_twice_rejected
    """
    ctx = setup_messaging(contract_number="C-SM-2")
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    record_response(message["id"], "RESPONDED")

    resp = api_client.record_response(message["id"], {"response_kind": "RESPONDED"},
                                      ats_service_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_record_response_credit_returned_exactly_once():
    """PRD section 3.5: "If the message's `credit_consumed` is 1 and its
    `credit_returned_flag` is false, the pool's `credits_returned` increments
    by 1 and `credit_returned_flag` flips to true — a credit is returned
    exactly once per message, and the no-credit case (`credit_consumed` 0,
    the open-to-work `ALL_MEMBERS` path) and the already-returned case are
    no-ops, protecting against double returns."

    Design: Corner/state_machines/record_response_twice_rejected
    """
    ctx = setup_messaging(contract_number="C-SM-2B")
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    record_response(message["id"], "RESPONDED")

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["credits_returned"] == 1

    resp = api_client.record_response(message["id"], {"response_kind": "RESPONDED"},
                                      ats_service_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    pool_after = get_credit_pool(ctx["seat"]["id"])
    assert pool_after["credits_returned"] == 1


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/credit_pool_accounting_identity_send_then_return
# ---------------------------------------------------------------------------

def test_credit_pool_identity_send_then_return():
    """PRD section 3.3: "`credits_available`, computed as `credits_granted`
    minus `credits_used` plus `credits_returned`, with a floor at zero."
    PRD section 3.5: "If the message's `credit_consumed` is 1 and its
    `credit_returned_flag` is false, the pool's `credits_returned` increments
    by 1 and `credit_returned_flag` flips to true"

    Design: Difficulty/compensating_invariant/credit_pool_accounting_identity_send_then_return
    """
    ctx = setup_messaging(contract_number="C-INV-1")
    seat_id = ctx["seat"]["id"]
    pool_before = get_credit_pool(seat_id)
    assert pool_before["credits_available"] == 100

    message = send_message(seat_id, ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    record_response(message["id"], "RESPONDED")

    pool = get_credit_pool(seat_id)
    assert pool["credits_granted"] == 100
    assert pool["credits_used"] == 1
    assert pool["credits_returned"] == 1
    assert pool["credits_available"] == 100
    assert pool["credits_granted"] == (
        pool["credits_used"] - pool["credits_returned"] + pool["credits_available"]
    )
    assert pool["credits_available"] == pool_before["credits_available"]


def test_credit_pool_send_without_response_leaves_credit_consumed():
    """PRD section 3.5: "Otherwise the pool's `credits_available` must be at
    least 1; if it is 0 the send is rejected with `ERR_NO_CREDITS_REMAINING`,
    and on success `credit_consumed` is 1 and the pool's `credits_used`
    increments by 1."
    PRD section 3.3: "`credits_available`, computed as `credits_granted`
    minus `credits_used` plus `credits_returned`, with a floor at zero."

    Design: Difficulty/compensating_invariant/credit_pool_accounting_identity_send_then_return
    """
    ctx = setup_messaging(contract_number="C-INV-1B")
    seat_id = ctx["seat"]["id"]
    message = send_message(seat_id, ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    assert message["credit_consumed"] == 1

    pool = get_credit_pool(seat_id)
    assert pool["credits_granted"] == 100
    assert pool["credits_used"] == 1
    assert pool["credits_returned"] == 0
    assert pool["credits_available"] == 99


# ---------------------------------------------------------------------------
# Corner/calculations/free_message_for_open_to_work_all_members
# ---------------------------------------------------------------------------

def test_free_message_for_open_to_work_all_members():
    """PRD section 3.5: "If the recipient's `open_to_work` is true and their
    `open_to_work_visibility` is `ALL_MEMBERS`, the message is sent without
    consuming a credit — the message's `credit_consumed` is 0."

    Design: Corner/calculations/free_message_for_open_to_work_all_members
    """
    ctx = setup_messaging(
        contract_number="C-CALC-1",
        privacy_setting="PRIVATE", open_to_work=True,
        open_to_work_visibility="ALL_MEMBERS",
    )
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    assert message["credit_consumed"] == 0
    assert message["delivery_status"] == "SENT"

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["credits_used"] == 0
    assert pool["credits_available"] == 100


def test_free_message_responded_returns_no_credit():
    """PRD section 3.5: "If the recipient's `open_to_work` is true and their
    `open_to_work_visibility` is `ALL_MEMBERS`, the message is sent without
    consuming a credit — the message's `credit_consumed` is 0."
    PRD section 3.5: "the no-credit case (`credit_consumed` 0, the
    open-to-work `ALL_MEMBERS` path) and the already-returned case are
    no-ops, protecting against double returns."

    Design: Corner/calculations/free_message_for_open_to_work_all_members
    """
    ctx = setup_messaging(
        contract_number="C-CALC-1B",
        privacy_setting="PRIVATE", open_to_work=True,
        open_to_work_visibility="ALL_MEMBERS",
    )
    message = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                           ctx["candidate"]["id"], ctx["project"]["id"])
    record_response(message["id"], "RESPONDED")

    updated = get_message(message["id"])
    assert updated["credit_returned_flag"] is False
    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["credits_used"] == 0
    assert pool["credits_returned"] == 0
    assert pool["credits_available"] == 100


# ---------------------------------------------------------------------------
# Corner/calculations/private_candidate_not_visible_blocks_send
# ---------------------------------------------------------------------------

def test_private_candidate_not_visible_blocks_send():
    """PRD section 3.4: "A candidate row is visible to a given recruiter
    search if and only if at least one of the following holds:
    - The candidate's `privacy_setting` is `PUBLIC`; or
    - The candidate's `privacy_setting` is `CONNECTIONS_ONLY` and the
      requesting seat's `assigned_recruiter_id`'s `manager_recruiter_id`
      chain — following the manager links upward from the seated recruiter —
      includes at least one recruiter whose `recruiter_status` is `ACTIVE`
      (this is the system's simplified "connection" proxy); or
    - The candidate's `open_to_work` is true and the candidate's
      `open_to_work_visibility` is either `ALL_MEMBERS` or
      `RECRUITERS_ONLY`."
    PRD section 3.5: "The recipient candidate must be visible to the sending
    recruiter under the §3.4 visibility rule; an invisible recipient is
    rejected with `ERR_CANDIDATE_NOT_VISIBLE`."

    Design: Corner/calculations/private_candidate_not_visible_blocks_send
    """
    ctx = setup_messaging(
        contract_number="C-CALC-2",
        privacy_setting="PRIVATE", open_to_work=False,
        open_to_work_visibility="NONE",
    )
    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "b"},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_VISIBLE)


def test_private_candidate_blocked_send_consumes_no_credit():
    """PRD section 3.5: "The recipient candidate must be visible to the
    sending recruiter under the §3.4 visibility rule; an invisible recipient
    is rejected with `ERR_CANDIDATE_NOT_VISIBLE`."
    PRD section 3.5: "Otherwise the pool's `credits_available` must be at
    least 1; if it is 0 the send is rejected with `ERR_NO_CREDITS_REMAINING`,
    and on success `credit_consumed` is 1 and the pool's `credits_used`
    increments by 1."

    Design: Corner/calculations/private_candidate_not_visible_blocks_send
    """
    ctx = setup_messaging(
        contract_number="C-CALC-2B",
        privacy_setting="PRIVATE", open_to_work=False,
        open_to_work_visibility="NONE",
    )
    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "b"},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_VISIBLE)

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["credits_used"] == 0
    assert pool["credits_available"] == 100


# ---------------------------------------------------------------------------
# Corner/calculations/negative_response_adds_one_strike_no_credit_return
# ---------------------------------------------------------------------------

def test_strike_deltas_per_response_kind():
    """PRD section 3.5: "`NEGATIVE_RESPONSE` moves the message to
    `response_status` of `NEGATIVE_RESPONSE`, adds 1 to the pool's
    `spam_strike_count`, and returns no credit."
    PRD section 3.5: "`REPORTED_AS_SPAM` moves the message to
    `response_status` of `REPORTED_AS_SPAM`, adds 2 to the pool's
    `spam_strike_count`, and returns no credit."
    PRD section 3.5: "When the recomputed count reaches or exceeds 3 and the
    pool is `OPEN`, the pool transitions to `THROTTLED`, and further message
    sends on the seat are rejected with `ERR_ANTISPAM_THROTTLED`."

    Design: Corner/calculations/negative_response_adds_one_strike_no_credit_return
    """
    ctx = setup_messaging(contract_number="C-CALC-3")
    m1 = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                      ctx["candidate"]["id"], ctx["project"]["id"], body="m1")
    m2 = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                      ctx["candidate"]["id"], ctx["project"]["id"], body="m2")

    record_response(m1["id"], "NEGATIVE_RESPONSE")
    record_response(m2["id"], "REPORTED_AS_SPAM")

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["spam_strike_count"] == 3
    assert pool["credits_returned"] == 0
    assert pool["pool_status"] == "THROTTLED"


def test_negative_response_below_threshold_keeps_pool_open():
    """PRD section 3.5: "`NEGATIVE_RESPONSE` moves the message to
    `response_status` of `NEGATIVE_RESPONSE`, adds 1 to the pool's
    `spam_strike_count`, and returns no credit."
    PRD section 3.5: "When the recomputed count reaches or exceeds 3 and the
    pool is `OPEN`, the pool transitions to `THROTTLED`, and further message
    sends on the seat are rejected with `ERR_ANTISPAM_THROTTLED`."

    Design: Corner/calculations/negative_response_adds_one_strike_no_credit_return
    """
    ctx = setup_messaging(contract_number="C-CALC-3B")
    m1 = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                      ctx["candidate"]["id"], ctx["project"]["id"], body="m1")
    record_response(m1["id"], "NEGATIVE_RESPONSE")

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["spam_strike_count"] == 1
    assert pool["pool_status"] == "OPEN"
    assert pool["credits_returned"] == 0


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/throttled_pool_reopens_on_positive_response
# ---------------------------------------------------------------------------

def test_throttled_pool_reopens_on_positive_response():
    """PRD section 3.5: "When the recomputed count falls below 3 and the pool
    is `THROTTLED`, the pool returns to `OPEN`."
    PRD section 3.5: "`RESPONDED` subtracts 1 only when the message was
    `SENT` while the pool was `OPEN` (that is, the message predates the
    current throttle episode) and the pool's `spam_strike_count` is currently
    greater than 0; otherwise `RESPONDED` contributes 0."

    Design: Corner/cross_cutting_layers/throttled_pool_reopens_on_positive_response
    """
    ctx = setup_messaging(contract_number="C-CCL-1")
    seat_id = ctx["seat"]["id"]
    m1 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m1")
    m2 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m2")
    m3 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m3")
    record_response(m1["id"], "NEGATIVE_RESPONSE")
    record_response(m2["id"], "REPORTED_AS_SPAM")

    pool = get_credit_pool(seat_id)
    assert pool["spam_strike_count"] == 3
    assert pool["pool_status"] == "THROTTLED"

    record_response(m3["id"], "RESPONDED")
    pool = get_credit_pool(seat_id)
    assert pool["spam_strike_count"] == 2
    assert pool["pool_status"] == "OPEN"


def test_throttled_pool_reopen_does_not_erase_strike_memory():
    """PRD section 3.5: "The throttle memory belongs to the pool — a positive
    response that drops the count below 3 does not consume the strike; the
    strike remains recorded on the pool."
    PRD section 3.5: "When the recomputed count falls below 3 and the pool is
    `THROTTLED`, the pool returns to `OPEN`."

    Design: Corner/cross_cutting_layers/throttled_pool_reopens_on_positive_response
    """
    ctx = setup_messaging(contract_number="C-CCL-1B")
    seat_id = ctx["seat"]["id"]
    m1 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m1")
    m2 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m2")
    m3 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m3")
    m4 = send_message(seat_id, ctx["recruiter"]["id"], ctx["candidate"]["id"],
                      ctx["project"]["id"], body="m4")
    record_response(m1["id"], "NEGATIVE_RESPONSE")
    record_response(m2["id"], "REPORTED_AS_SPAM")
    record_response(m3["id"], "RESPONDED")

    pool = get_credit_pool(seat_id)
    assert pool["pool_status"] == "OPEN"
    assert pool["spam_strike_count"] == 2

    # The two prior strikes remain: one more negative response re-throttles.
    record_response(m4["id"], "NEGATIVE_RESPONSE")
    pool = get_credit_pool(seat_id)
    assert pool["spam_strike_count"] == 3
    assert pool["pool_status"] == "THROTTLED"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/antispam_throttle_beats_no_credits
# ---------------------------------------------------------------------------

def _setup_throttled_and_drained_pool(contract_number):
    ctx = setup_messaging(product_tier="RECRUITER_LITE", contract_number=contract_number)
    credits = TIER_LIMITS["RECRUITER_LITE"]["monthly_credit_per_seat"]
    messages = drain_credits(ctx, credits, body_prefix="s")
    record_response(messages[0]["id"], "REPORTED_AS_SPAM")
    record_response(messages[1]["id"], "REPORTED_AS_SPAM")
    return ctx


def test_antispam_throttle_beats_no_credits():
    """PRD section 2.10: "Business rules then run in ascending priority:
    anti-spam throttle (priority 5, `ERR_ANTISPAM_THROTTLED`), ... no-credits
    (priority 11, `ERR_NO_CREDITS_REMAINING`)"
    PRD section 3.5: "The seat's current pool must not be `THROTTLED`; a send
    against a throttled pool is rejected with `ERR_ANTISPAM_THROTTLED`."

    Design: Difficulty/priority_pair_validation_conflict/antispam_throttle_beats_no_credits
    """
    ctx = _setup_throttled_and_drained_pool("C-PRI-1")
    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["credits_available"] == 0
    assert pool["pool_status"] == "THROTTLED"

    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "s31"},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANTISPAM_THROTTLED)


def test_throttled_send_rejected_even_with_credits_available():
    """PRD section 2.10: "Business rules then run in ascending priority:
    anti-spam throttle (priority 5, `ERR_ANTISPAM_THROTTLED`), ... no-credits
    (priority 11, `ERR_NO_CREDITS_REMAINING`)"
    PRD section 3.5: "The seat's current pool must not be `THROTTLED`; a send
    against a throttled pool is rejected with `ERR_ANTISPAM_THROTTLED`."

    Design: Difficulty/priority_pair_validation_conflict/antispam_throttle_beats_no_credits
    """
    ctx = setup_messaging(contract_number="C-PRI-1B")
    m1 = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                      ctx["candidate"]["id"], ctx["project"]["id"], body="m1")
    m2 = send_message(ctx["seat"]["id"], ctx["recruiter"]["id"],
                      ctx["candidate"]["id"], ctx["project"]["id"], body="m2")
    record_response(m1["id"], "REPORTED_AS_SPAM")
    record_response(m2["id"], "REPORTED_AS_SPAM")

    pool = get_credit_pool(ctx["seat"]["id"])
    assert pool["pool_status"] == "THROTTLED"
    assert pool["credits_available"] > 0

    resp = api_client.send_message(
        ctx["seat"]["id"],
        {"candidate_id": ctx["candidate"]["id"], "project_id": ctx["project"]["id"],
         "body": "m3"},
        recruiter_headers(ctx["recruiter"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ANTISPAM_THROTTLED)
