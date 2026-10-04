"""Refund claims: filing gates, review/decide chain, segregation of duties,
claim and appeal windows, and the restitution ledger decomposition."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appeal_claim,
    assert_refund_conservation,
    create_decision_payload,
    create_refund_claim_payload,
    decide_claim,
    execute_payment,
    file_refund_claim,
    make_refund_officer_headers,
    read_refund_claim,
    set_logical_clock,
    setup_applied_offset,
    setup_claim_under_review,
    setup_denied_claim,
    setup_evaluated_payment,
    setup_paid_claim,
    validate_error,
    validate_paginated,
    validate_success,
    review_claim,
)

OPERATOR = TEST_USERS["treasury_operator_headers"]
OFFICER = TEST_USERS["refund_officer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_refund_claim_requires_offset_applied(api):
    """PRD §3.6: "The payload names the `offset_id` — an unknown id is
    `ERR_OFFSET_NOT_FOUND`, and an offset not in `APPLIED` status is
    `ERR_OFFSET_NOT_APPLIED`".

    Design: Difficulty/cross_entity_state_dependency/refund_claim_requires_offset_applied
    """
    ns = setup_evaluated_payment()  # offset still PROPOSED
    offset = ns["offsets"][0]

    resp = api.create_refund_claim(
        create_refund_claim_payload(offset["id"], 30000), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_OFFSET_NOT_APPLIED)
    rows, _ = validate_paginated(
        api.list_refund_claims(AUDITOR, params={"offset_id": offset["id"]})
    )
    assert rows == []

    execute_payment(ns["payment"])  # PROPOSED -> APPLIED
    claim = file_refund_claim(offset, 30000)
    assert claim["status"] == "FILED"


def test_refund_decide_from_filed_returns_invalid_state(api):
    """PRD §3.6: "Deciding takes a `decision` of approve or deny and is allowed
    only from `UNDER_REVIEW`."
    PRD §2.8 (tier 7): "The attempted transition is defined for the resource's
    current state — terminal states included — and OCC version equality holds
    where §2.7 applies — otherwise `ERR_INVALID_STATE`,
    `ERR_PAYMENT_NOT_EXECUTABLE`, `ERR_OFFSET_NOT_APPLIED`, or
    `ERR_APPEAL_LIMIT_REACHED` (409), or `ERR_STALE_VERSION` (412)."

    Design: Corner/state_machines/refund_decide_from_filed_returns_invalid_state
    """
    ns = setup_applied_offset()
    claim = file_refund_claim(ns["offset"], 10000, "AMOUNT_INCORRECT")
    assert claim["status"] == "FILED"

    resp = api.decide_refund_claim(
        claim["id"], create_decision_payload("APPROVE"), OFFICER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    claim_now = read_refund_claim(claim["id"])
    assert claim_now["status"] == "FILED"
    assert claim_now.get("refund_amount_cents") is None


def test_claim_window_vs_amount(api):
    """PRD §2.8: "Every request is validated against an ordered cascade of
    eleven tiers, and the first failing tier produces the response, masking
    anything later."
    PRD §2.8 (tier 9): "Claim, appeal, request-expiry, and window-overlap rules
    — otherwise `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_APPEAL_WINDOW_EXPIRED`,
    `ERR_REQUEST_EXPIRED`, `ERR_AGREEMENT_OVERLAP`, or `ERR_DNP_WINDOW_OVERLAP`
    (409)."
    PRD §2.8 (tier 11): "Claim and remittance ceilings — otherwise
    `ERR_REFUND_EXCEEDS_OFFSET`, `ERR_COLLECT_EXCEEDS_BALANCE`, or
    `ERR_COLLECT_AMOUNT_ZERO` (422)."

    Design: Difficulty/priority_pair_validation_conflict/claim_window_vs_amount
    """
    ns = setup_applied_offset(
        file_overrides={"settlement_date": "2027-12-31T00:00:00Z"}
    )
    # 181 days after the offset's applied_at: past the 180-day window, and the
    # claimed amount also exceeds the offset. The temporal tier fires first.
    set_logical_clock("2027-03-01T00:00:00Z")
    resp = api.create_refund_claim(
        create_refund_claim_payload(ns["offset"]["id"], 30001), OPERATOR
    )
    err = validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)
    assert err["error_id"] != "ERR_REFUND_EXCEEDS_OFFSET"

    rows, _ = validate_paginated(
        api.list_refund_claims(AUDITOR, params={"offset_id": ns["offset"]["id"]})
    )
    assert rows == []


def test_claim_at_exactly_180_days_succeeds(api):
    """PRD §3.6: "Timeliness is enforced at filing: the claim must be filed
    within 180 days of the offset's `applied_at`, and a later filing is
    `ERR_CLAIM_WINDOW_EXPIRED`."

    Design: Corner/validations/claim_at_exactly_180_days_succeeds
    """
    ns = setup_applied_offset(
        file_overrides={"settlement_date": "2027-12-31T00:00:00Z"}
    )
    # applied_at == 2026-09-01T00:00:00Z; day 180 is 2027-02-28 — inside.
    set_logical_clock("2027-02-28T00:00:00Z")
    claim = file_refund_claim(ns["offset"], 30000)
    assert claim["status"] == "FILED"
    assert claim["appeal_count"] == 0


def test_refund_amount_over_offset_returns_422(api):
    """PRD §3.6: "a `claimed_amount_cents` strictly greater than zero and no
    more than the offset's `offset_amount_cents`, with any excess rejected as
    `ERR_REFUND_EXCEEDS_OFFSET` (422)".

    Design: Corner/validations/refund_amount_over_offset_returns_422
    """
    ns = setup_applied_offset()
    set_logical_clock("2026-09-10T00:00:00Z")  # 9 days in: window still open
    resp = api.create_refund_claim(
        create_refund_claim_payload(ns["offset"]["id"], 30001, "AMOUNT_INCORRECT"),
        OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_OFFSET)
    rows, _ = validate_paginated(
        api.list_refund_claims(AUDITOR, params={"offset_id": ns["offset"]["id"]})
    )
    assert rows == []


def test_segregation_of_duties_blocks_executor_as_decider(api):
    """PRD §3.6: "the deciding officer's `X-User-ID` must differ from the
    `executed_by_user_id` recorded on the payment behind the claimed offset,
    otherwise `ERR_SEGREGATION_OF_DUTIES` — the officer who decides a claim must
    never be the operator who executed the offset."

    Design: Corner/validations/segregation_of_duties_blocks_executor_as_decider
    """
    ns = setup_claim_under_review()  # executed by "op-1", reviewed by "ro-1"

    resp_blocked = api.decide_refund_claim(
        ns["claim"]["id"],
        create_decision_payload("APPROVE"),
        make_refund_officer_headers("op-1"),  # same id as the executor
    )
    validate_error(resp_blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resp_ok = api.decide_refund_claim(
        ns["claim"]["id"],
        create_decision_payload("DENY"),
        make_refund_officer_headers("ro-2"),
    )
    assert validate_success(resp_ok)["status"] == "DENIED"


def test_appeal_after_30_days_returns_expired(api):
    """PRD §3.6: "the logical clock must be within thirty days of `decided_at`,
    with a later appeal rejected as `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/validations/appeal_after_30_days_returns_expired
    """
    ns = setup_denied_claim()  # decided_at == default clock 2026-09-01
    set_logical_clock("2026-10-06T00:00:00Z")  # 35 days after the decision
    resp = api.appeal_refund_claim(ns["claim"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
    claim_now = read_refund_claim(ns["claim"]["id"])
    assert claim_now["status"] == "DENIED"
    assert claim_now["appeal_count"] == 0


def test_second_appeal_returns_limit_reached(api):
    """PRD §3.6: "A denied claimant gets exactly one appeal, filed by a
    `TreasuryOperator` (`DENIED` → `APPEALED`): the claim's `appeal_count` must
    still be 0 — a second appeal is `ERR_APPEAL_LIMIT_REACHED`".
    PRD §3.6: "Appealing increments `appeal_count`, and a fresh review returns
    the claim to `UNDER_REVIEW` for a second decision under the same
    segregation-of-duties rule."

    Design: Corner/validations/second_appeal_returns_limit_reached
    """
    ns = setup_denied_claim()

    appealed = appeal_claim(ns["claim"])
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1

    decide_claim(review_claim(appealed), "DENY")
    resp = api.appeal_refund_claim(ns["claim"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED)
    assert read_refund_claim(ns["claim"]["id"])["status"] == "DENIED"


def test_remittance_ledger_refund_clawback(api):
    """PRD §3.6: "`clawback_cents` — the lesser of the claimed amount and the
    offset's `net_remittance_cents` — is debited from the creditor's
    `remitted_net_total_cents`."
    PRD §3.6: "`treasury_absorbed_cents` is the remainder, the withheld fee that
    Treasury absorbs, so the refund always conserves: the refunded amount is
    exactly the clawback plus the absorbed portion."
    PRD §3.6: "The debt behind the offset moves to `RETURNED` — whether it was
    still `ACTIVE` or already `PAID_IN_FULL` — its `returned_count` increments,
    and its balance is deliberately not restored".

    Design: Difficulty/compensating_invariant/remittance_ledger_refund_clawback
    """
    ns = setup_paid_claim()  # full 30000 claim approved by ro-1 (executor op-1)

    claim = ns["claim"]
    assert claim["status"] == "PAID"
    assert claim["refund_amount_cents"] == 30000
    assert claim["clawback_cents"] == 29100  # min(30000, net remittance 29100)
    assert claim["treasury_absorbed_cents"] == 900
    assert_refund_conservation(claim)

    # The ledger returns to its pre-offset value; Treasury absorbed the fee.
    assert ns["creditor"]["remitted_net_total_cents"] == 0
    assert ns["offset"]["status"] == "REFUNDED"
    assert ns["debt"]["status"] == "RETURNED"
