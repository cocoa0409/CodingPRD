"""Offers: negotiation cycle cap, 72h TTL boundary, terminal-state counters,
and the transaction re-list loop; plus CDA ladder cycling and gating."""
from test_helpers import (
    CA, MB, TA,
    CdaStatus, OfferStatus, TransactionStatus,
    assert_offer,
    create_offer, create_transaction_under_contract, create_cda,
    approve_cda_fully,
    get_success_data,
    set_clock,
    setup_office_with_active_agent, setup_pending_close_transaction,
    validate_error, validate_paginated, validate_success,
    make_agent_headers,
    api_client,
)


def _cycle(api, offer_id, agent, n):
    """Run n counter/reoffer cycles."""
    for _ in range(n):
        validate_success(api.counter_offer(offer_id, make_agent_headers(agent["id"])))
        validate_success(api.reoffer(offer_id, make_agent_headers(agent["id"])))


def test_offer_negotiation_cycle_capped_at_four_rounds(api):
    """PRD §3.5: "The cycle is capped: a re-offer attempted when `offer_round`
    is already 4 (so that the next round would begin round 5) is rejected with
    `ERR_NEGOTIATION_EXHAUSTED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_round_cap
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer = create_offer(office["id"], alice)
    assert offer["offer_round"] == 1
    assert offer["status"] == OfferStatus.OFFERED.value

    # Three full cycles land the offer back OFFERED at round 4.
    _cycle(api, offer["id"], alice, 3)
    current = validate_success(api.get_offer(offer["id"], make_agent_headers(alice["id"])))
    assert current["offer_round"] == 4
    assert current["status"] == OfferStatus.OFFERED.value

    # The fourth counter succeeds; the fourth reoffer (which would open
    # round 5) is rejected and the offer stays COUNTERED at round 4.
    validate_success(api.counter_offer(offer["id"], make_agent_headers(alice["id"])))
    resp = api.reoffer(offer["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_NEGOTIATION_EXHAUSTED")
    after = validate_success(api.get_offer(offer["id"], make_agent_headers(alice["id"])))
    assert after["status"] == OfferStatus.COUNTERED.value
    assert after["offer_round"] == 4


def test_offer_round_increments_only_on_reoffer(api):
    """PRD §3.5: "The listing office's agent counters the offer, moving it
    from `OFFERED` to `COUNTERED`. The buyer, through their agent, re-offers —
    moving the offer from `COUNTERED` back to `OFFERED` and incrementing
    `offer_round`."

    Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_round_cap
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer = create_offer(office["id"], alice)
    after_counter = validate_success(
        api.counter_offer(offer["id"], make_agent_headers(alice["id"])))
    assert after_counter["status"] == OfferStatus.COUNTERED.value
    assert after_counter["offer_round"] == 1, "counter alone must not advance the round"
    after_reoffer = validate_success(
        api.reoffer(offer["id"], make_agent_headers(alice["id"])))
    assert after_reoffer["status"] == OfferStatus.OFFERED.value
    assert after_reoffer["offer_round"] == 2


def test_offer_ttl_boundary_exactly_72_hours_expires(api):
    """PRD §3.5: "An offer left in `OFFERED` expires automatically when the
    logical clock reaches seventy-two hours after its last status change — a
    boundary-inclusive TTL: an offer whose last status change was exactly
    seventy-two hours ago is expired, while one second under is still alive.
    The expiry check runs on any read of the offer and on any attempt to
    accept it; an accept attempted after the TTL has elapsed is rejected with
    `ERR_OFFER_EXPIRED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/offer_ttl_72h_exact_boundary_expires
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer = create_offer(office["id"], alice)

    # 71:59:59 elapsed — still alive.
    set_clock("2026-09-12T23:59:59Z")
    read = validate_success(api.get_offer(offer["id"], make_agent_headers(alice["id"])))
    assert read["status"] == OfferStatus.OFFERED.value

    # Exactly 72:00:00 elapsed — expired; accept is rejected.
    set_clock("2026-09-13T00:00:00Z")
    resp = api.accept_offer(offer["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_OFFER_EXPIRED")
    after = validate_success(api.get_offer(offer["id"], make_agent_headers(alice["id"])))
    assert after["status"] == OfferStatus.EXPIRED.value


def test_offer_system_fields_ignore_client_supplied_round_and_status(api):
    """PRD §3.5: "The offer is born in `OFFERED` with `offer_round` set to 1."
    PRD §2.5: "`version` — an integer that starts at 1 and increments by 1 on
    every mutation, including mutations cascaded from a parent or a related
    entity."

    Design: Corner/entities/offer_system_fields_ignore_client_supplied_round_and_status
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer = create_offer(office["id"], alice, offer_round=7, status="ACCEPTED")
    assert offer["status"] == OfferStatus.OFFERED.value
    assert offer["offer_round"] == 1
    assert offer["version"] == 1


def test_counter_rejected_offer_is_invalid_state(api):
    """PRD §3.5: "An offer can be rejected from either `OFFERED` or
    `COUNTERED` (moving to `REJECTED`), and withdrawn from `COUNTERED` (moving
    to `WITHDRAWN`)."

    Design: Corner/state_machines/offer_counter_from_terminal_rejected_returns_invalid_state
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer = create_offer(office["id"], alice)
    validate_success(api.reject_offer(offer["id"], make_agent_headers(alice["id"])))

    resp = api.counter_offer(offer["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_INVALID_STATE")
    after = validate_success(api.get_offer(offer["id"], make_agent_headers(alice["id"])))
    assert after["status"] == OfferStatus.REJECTED.value
    assert after["offer_round"] == 1


def test_cda_reject_cycles_ladder_back_to_rung_zero(api):
    """PRD §3.6: "A `REJECT` at any rung resets `current_rung` to 0 — the
    ladder cycles back to compliance review rather than terminating, and the
    CDA stays in `IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/cda_review_ladder_reject_cycles_to_rung_zero
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    # Walk to rung 2, then REJECT.
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA))
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA))
    after_reject = validate_success(
        api.review_cda(cda["id"], {"verdict": "REJECT"}, MB))
    assert after_reject["status"] == CdaStatus.IN_REVIEW.value
    assert after_reject["current_rung"] == 0

    # The ladder really reset: a rung-1 review now is a rung mismatch.
    mismatch = api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA)
    validate_error(mismatch, "ERR_REVIEW_RUNG_MISMATCH")

    # A second clean walk reaches APPROVED — the loop is productive.
    approve_cda_fully(cda["id"])
    final = validate_success(api.get_cda(cda["id"], MB))
    assert final["status"] == CdaStatus.APPROVED.value


def test_cda_reject_keeps_status_in_review_not_terminated(api):
    """PRD §3.6: "A `REJECT` at any rung resets `current_rung` to 0 — the
    ladder cycles back to compliance review rather than terminating, and the
    CDA stays in `IN_REVIEW`."

    Design: Difficulty/non_linear_state_machine/cda_review_ladder_reject_cycles_to_rung_zero
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    after = validate_success(api.review_cda(cda["id"], {"verdict": "REJECT"}, CA))
    assert after["status"] == CdaStatus.IN_REVIEW.value
    assert after["current_rung"] == 0


def test_request_close_blocked_until_cda_approved(api):
    """PRD §3.6: "The CDA is the gate on closing. A request to advance a
    transaction from `UNDER_CONTRACT` to `PENDING_CLOSE` is rejected with
    `ERR_CDA_NOT_APPROVED` (HTTP 409) when no `APPROVED` CDA exists for the
    deal."

    Design: Difficulty/cross_entity_state_dependency/request_close_gated_by_cda_approval
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    # Only rung 0 approved — still IN_REVIEW.
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, CA))

    resp = api.request_close(txn["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_CDA_NOT_APPROVED")
    txn_now = validate_success(api.get_transaction(txn["id"], MB))
    assert txn_now["status"] == TransactionStatus.UNDER_CONTRACT.value

    # After the ladder completes, the identical request succeeds.
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, TA))
    validate_success(api.review_cda(cda["id"], {"verdict": "APPROVE"}, MB))
    ok = validate_success(api.request_close(txn["id"], make_agent_headers(alice["id"])))
    assert ok["status"] == TransactionStatus.PENDING_CLOSE.value


def test_request_close_succeeds_with_approved_cda_and_active_agent(api):
    """PRD §3.6: "An `APPROVE` at rung 2 completes the ladder: the CDA's
    `status` becomes `APPROVED`, and from that moment the parent transaction
    may advance to `PENDING_CLOSE`."

    Design: Difficulty/cross_entity_state_dependency/request_close_gated_by_cda_approval
    """
    ctx = setup_pending_close_transaction()
    assert ctx["txn"]["status"] == TransactionStatus.PENDING_CLOSE.value
    cda = validate_success(api.get_cda(ctx["cda"]["id"], MB))
    assert cda["status"] == CdaStatus.APPROVED.value


def test_second_cda_on_same_transaction_rejected(api):
    """PRD §3.6: "Only one live CDA may exist per transaction: if a CDA in
    `DRAFT`, `IN_REVIEW`, or `APPROVED` already exists for the transaction,
    the create is rejected with `ERR_CDA_EXISTS` (HTTP 409)."

    Design: Corner/state_machines/second_cda_on_same_transaction_rejected
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    create_cda(txn["id"])
    resp = api.create_cda(txn["id"],
                          {"review_ladder": ["COMPLIANCE_REVIEW", "TRUST_REVIEW",
                                             "BROKER_SIGNOFF"]}, MB)
    validate_error(resp, "ERR_CDA_EXISTS")
    rows, _ = validate_paginated(api.list_transaction_cdas(txn["id"], MB))
    assert len(rows) == 1


def test_fell_through_relist_recontract_cycle_supersedes_cda(api):
    """PRD §3.5: "From `UNDER_CONTRACT`, the agent may mark the deal as fallen
    through (`FELL_THROUGH`); from `FELL_THROUGH`, the agent may re-list it
    (`RELISTED`); from `RELISTED`, the agent may put it back under contract
    (`UNDER_CONTRACT`)."
    PRD §3.6: "If the parent transaction is marked fallen through while the
    CDA is `IN_REVIEW`, the CDA is automatically moved to `SUPERSEDED`."

    Design: Corner/state_machines/fell_through_relist_recontract_cycle
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    v_before = txn["version"]

    fell = validate_success(api.mark_fell_through(txn["id"], make_agent_headers(alice["id"])))
    assert fell["status"] == TransactionStatus.FELL_THROUGH.value
    cda_now = validate_success(api.get_cda(cda["id"], MB))
    assert cda_now["status"] == CdaStatus.SUPERSEDED.value
    assert fell["version"] > v_before

    relisted = validate_success(api.relist_transaction(txn["id"], make_agent_headers(alice["id"])))
    assert relisted["status"] == TransactionStatus.RELISTED.value
    assert relisted["version"] > fell["version"]

    recontracted = validate_success(
        api.recontract_transaction(txn["id"], make_agent_headers(alice["id"])))
    assert recontracted["status"] == TransactionStatus.UNDER_CONTRACT.value
    assert recontracted["version"] > relisted["version"]


def test_request_close_requires_active_listing_agent(api):
    """PRD §3.6: "The same transition also requires the listing agent to be in
    `ACTIVE` status; if the listing agent has entered `TERMINATION_PENDING`
    (or any other non-active state), the request is rejected with
    `ERR_AGENT_NOT_ACTIVE` (HTTP 409) — a cross-entity dependency from the
    transaction to the listing agent."

    Design: Corner/state_machines/request_close_requires_active_listing_agent
    """
    office, schedule, alice = setup_office_with_active_agent("2026-09-10T00:00:00Z")
    offer, txn = create_transaction_under_contract(office["id"], alice)
    cda = create_cda(txn["id"])
    approve_cda_fully(cda["id"])
    validate_success(api.terminate_agent(alice["id"], make_agent_headers(alice["id"])))

    resp = api.request_close(txn["id"], make_agent_headers(alice["id"]))
    validate_error(resp, "ERR_AGENT_NOT_ACTIVE")
    txn_now = validate_success(api.get_transaction(txn["id"], MB))
    assert txn_now["status"] == TransactionStatus.UNDER_CONTRACT.value
