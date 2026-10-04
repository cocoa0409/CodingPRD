"""Reciprocal agreements (half-open windows, direction scopes) and reverse
offsets (matching, re-capped confirmation, expiry, empty pools)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_debt,
    add_payment,
    assert_reverse_offset_request,
    confirm_reverse_request,
    create_active_agreement,
    create_active_debt,
    create_active_policy,
    create_federal_creditor,
    create_payment_file,
    create_reciprocal_agreement_payload,
    create_reverse_offset_request_payload,
    create_reverse_request,
    create_state_creditor,
    evaluate_payment,
    execute_payment,
    make_creditor_analyst_headers,
    read_creditor,
    read_debt,
    refer_debt,
    register_eft_payee,
    set_logical_clock,
    setup_reverse_request,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["treasury_supervisor_headers"]
COORDINATOR = TEST_USERS["state_coordinator_headers"]


def test_reciprocal_agreement_half_open(api):
    """PRD §2.10: "The coverage window is half-open: `effective_from` is
    inclusive, `effective_until` is exclusive".
    PRD §2.10: "No two `ACTIVE` agreements for the same `state_code` may have
    half-open-overlapping windows with conflicting direction scopes.
    `BIDIRECTIONAL` conflicts with every scope, `FED_TO_STATE` conflicts with
    `FED_TO_STATE` and `BIDIRECTIONAL`, and `STATE_TO_FED` conflicts with
    `STATE_TO_FED` and `BIDIRECTIONAL`. A creation or activation that would
    produce such an overlap is rejected with `ERR_AGREEMENT_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/reciprocal_agreement_half_open
    """
    set_logical_clock()
    incumbent = create_active_agreement("TX", "FED_TO_STATE")
    assert incumbent["status"] == "ACTIVE"  # [2026-01-01, 2027-01-01)

    # Adjacent at the exclusive end: no overlap.
    resp_adjacent = api.create_reciprocal_agreement(
        create_reciprocal_agreement_payload(
            state_code="TX", direction="FED_TO_STATE",
            effective_from="2027-01-01T00:00:00Z",
            effective_until="2028-01-01T00:00:00Z",
        ),
        SUPERVISOR,
    )
    adjacent = validate_success(resp_adjacent, 201)
    activated = api.activate_reciprocal_agreement(adjacent["id"], SUPERVISOR)
    assert validate_success(activated)["status"] == "ACTIVE"

    # Overlapping the incumbent by one day conflicts.
    resp_overlap = api.create_reciprocal_agreement(
        create_reciprocal_agreement_payload(
            state_code="TX", direction="FED_TO_STATE",
            effective_from="2026-12-31T00:00:00Z",
            effective_until="2027-06-01T00:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(resp_overlap, ApiErrorId.ERR_AGREEMENT_OVERLAP)

    # Same window shape, disjoint direction scope: no conflict.
    resp_other_scope = api.create_reciprocal_agreement(
        create_reciprocal_agreement_payload(
            state_code="TX", direction="STATE_TO_FED",
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2027-06-01T00:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_success(resp_other_scope, 201)

    # BIDIRECTIONAL conflicts with every scope.
    resp_bidi = api.create_reciprocal_agreement(
        create_reciprocal_agreement_payload(
            state_code="TX", direction="BIDIRECTIONAL",
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2027-09-01T00:00:00Z",
        ),
        SUPERVISOR,
    )
    validate_error(resp_bidi, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_state_debt_activate_requires_agreement(api):
    """PRD §3.3: "a `STATE` creditor's debt activates only while an `ACTIVE`
    reciprocal agreement covers the creditor's `state_code` in the
    `FED_TO_STATE` or `BIDIRECTIONAL` scope at the current clock — otherwise
    `ERR_AGREEMENT_NOT_ACTIVE`."
    PRD §3.8: "Once `ACTIVE`, coverage runs until the logical clock reaches
    `effective_until`; there is no terminate operation, and beyond the window
    the agreement simply covers nothing, so state-debt activations and
    reverse-offset requests start failing their coverage gates."

    Design: Difficulty/cross_entity_state_dependency/state_debt_activate_requires_agreement
    """
    set_logical_clock()
    cred_or = create_state_creditor(
        "OR", creditor_code="OR-DOR", legal_name="Oregon Department of Revenue"
    )
    analyst = make_creditor_analyst_headers(cred_or["id"])
    debt = refer_debt(
        cred_or, debtor_tin="111-22-3333", debt_type="STATE_TAX",
        original_amount_cents=40000,
        notice_sent_at="2026-08-01T00:00:00Z", due_process_completed=True,
    )

    resp_none = api.activate_debt(debt["id"], analyst)
    validate_error(resp_none, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    create_active_agreement("OR", "FED_TO_STATE")
    activated = activate_debt(read_debt(debt["id"]), cred_or)
    assert activated["status"] == "ACTIVE"

    # At effective_until (exclusive) the agreement covers nothing.
    set_logical_clock("2027-01-01T00:00:00Z")
    debt_late = refer_debt(
        cred_or, debtor_tin="555-66-7777", debtor_name="Sam Poe",
        debt_type="STATE_TAX", original_amount_cents=40000,
        notice_sent_at="2026-11-15T00:00:00Z", due_process_completed=True,
    )
    resp_expired = api.activate_debt(debt_late["id"], analyst)
    validate_error(resp_expired, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)


def test_reverse_match_caps_at_requested_amount(api):
    """PRD §3.8: "Matching then runs the mirror-image waterfall on the federal
    side: `ACTIVE` debts of `FEDERAL` creditors whose `debtor_tin` equals the
    request's `payee_tin`, walked in the same
    `priority_rank`-then-`delinquent_since`-then-`created_at` order as §3.4,
    each taking the lesser of the remaining requested amount and its own
    `current_balance_cents`."
    PRD §3.8: "A non-empty result starts the request `MATCHED`".

    Design: Corner/calculations/reverse_match_caps_at_requested_amount
    """
    ns = setup_reverse_request(
        state_code="WA",
        direction="STATE_TO_FED",
        debt_specs=(
            (30000, "FEDERAL_TAX", "2026-01-10T00:00:00Z"),
            (40000, "FEDERAL_NONTAX", "2026-01-05T00:00:00Z"),
        ),
        payee_tin="111-22-3333",
        requested_amount_cents=50000,
    )
    request = ns["request"]
    assert_reverse_offset_request(request)
    assert request["status"] == "MATCHED"
    assert request["matched_total_cents"] == 50000

    debt_tax, debt_nontax = ns["debts"]
    matches = request["matches"]
    assert len(matches) == 2
    # Rank 20 (FEDERAL_TAX) is served first and consumed in full.
    assert matches[0]["debt_id"] == debt_tax["id"]
    assert matches[0]["matched_amount_cents"] == 30000
    # Rank 30 gets only what the request cap leaves.
    assert matches[1]["debt_id"] == debt_nontax["id"]
    assert matches[1]["matched_amount_cents"] == 20000

    # Matching alone must not move balances.
    assert read_debt(debt_tax["id"])["current_balance_cents"] == 30000
    assert read_debt(debt_nontax["id"])["current_balance_cents"] == 40000


def test_reverse_confirm_recaps_to_current_balance(api):
    """PRD §3.8: "Confirmation applies each match fresh: every matched amount is
    re-capped to the lesser of its `matched_amount_cents` and the debt's balance
    at confirmation time, the re-capped amount reduces that balance (reaching
    `PAID_IN_FULL` at zero), and the federal creditor's ledger is credited net
    of the §2.9 fee."
    PRD §3.8: "The request records what actually happened: `applied_total_cents`
    sums the applied amounts and `confirmed_at` stamps the clock."

    Design: Corner/endpoints/reverse_confirm_recaps_to_current_balance
    """
    set_logical_clock()
    create_active_agreement("WA", "STATE_TO_FED")
    creditor = create_federal_creditor()
    payee = register_eft_payee(tin="111-22-3333")
    create_active_policy("SALARY", "FULL")
    debt = create_active_debt(
        creditor, debt_type="FEDERAL_TAX", original_amount_cents=30000,
        delinquent_since="2026-01-10T00:00:00Z",
    )
    request = create_reverse_request("WA", "111-22-3333", 50000)
    assert request["status"] == "MATCHED"
    assert request["matched_total_cents"] == 30000

    # An ordinary offset shaves the debt to 20000 between match and confirm.
    payment_file = create_payment_file()
    payment = add_payment(payment_file, payee, 10000, "SALARY")
    payment = evaluate_payment(payment)
    execute_payment(payment)
    assert read_debt(debt["id"])["current_balance_cents"] == 20000

    confirmed = confirm_reverse_request(request)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["applied_total_cents"] == 20000  # re-capped to the balance

    debt_now = read_debt(debt["id"])
    assert debt_now["current_balance_cents"] == 0
    assert debt_now["status"] == "PAID_IN_FULL"
    # 9700 net (10000 less the 3% fee) + 19400 net (20000 less the 3% fee).
    assert read_creditor(creditor["id"])["remitted_net_total_cents"] == 29100


def test_reverse_request_confirm_expiry_boundary(api):
    """PRD §3.8: "A matched request lives ten days: `expires_at` is fixed at
    creation as exactly ten days after `created_at`. Confirming — the state
    certifying that it offset its own payment — moves `MATCHED` to `CONFIRMED`,
    but only while the logical clock is on or before `expires_at`; a late
    confirm flips the request to `EXPIRED` and fails with
    `ERR_REQUEST_EXPIRED`."
    PRD §3.8: "Confirming a request in any state other than `MATCHED` is
    `ERR_INVALID_STATE`."

    Design: Corner/endpoints/reverse_request_confirm_expiry_boundary
    """
    set_logical_clock()
    create_active_agreement("WA", "STATE_TO_FED")
    creditor = create_federal_creditor()
    create_active_debt(
        creditor, debtor_tin="111-22-3333", original_amount_cents=25000,
        delinquent_since="2026-01-10T00:00:00Z",
    )
    create_active_debt(
        creditor, debtor_tin="555-66-7777", debtor_name="Sam Poe",
        original_amount_cents=15000, delinquent_since="2026-01-10T00:00:00Z",
    )
    # Both created at 2026-09-01T00:00:00Z; both expire 2026-09-11T00:00:00Z.
    request_1 = create_reverse_request("WA", "111-22-3333", 30000)
    request_2 = create_reverse_request("WA", "555-66-7777", 10000)

    set_logical_clock("2026-09-11T00:00:00Z")  # exactly expires_at: allowed
    confirmed = confirm_reverse_request(request_1)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["applied_total_cents"] == 25000

    set_logical_clock("2026-09-11T00:00:01Z")  # one second past: expired
    resp_expired = api.confirm_reverse_offset_request(request_2["id"], COORDINATOR)
    validate_error(resp_expired, ApiErrorId.ERR_REQUEST_EXPIRED)

    # The failed confirm flipped the request to EXPIRED, which is terminal.
    resp_again = api.confirm_reverse_offset_request(request_2["id"], COORDINATOR)
    validate_error(resp_again, ApiErrorId.ERR_INVALID_STATE)


def test_reverse_request_no_match_empty_set(api):
    """PRD §3.8: "A non-empty result starts the request `MATCHED`; an empty one
    starts it `NO_MATCH` with a zero total, and `NO_MATCH` is terminal."

    Design: Corner/endpoints/reverse_request_no_match_empty_set
    """
    set_logical_clock()
    create_active_agreement("WA", "STATE_TO_FED")
    request = create_reverse_request("WA", "777-88-9999", 50000)
    assert_reverse_offset_request(request)
    assert request["status"] == "NO_MATCH"
    assert request["matched_total_cents"] == 0
    assert request["matches"] == []


def test_reverse_request_without_agreement_returns_no_reciprocal_agreement(api):
    """PRD §3.8: "The request is honored only while an `ACTIVE` agreement covers
    that state in the `STATE_TO_FED` or `BIDIRECTIONAL` scope at the current
    clock — otherwise `ERR_NO_RECIPROCAL_AGREEMENT`."

    Design: Corner/endpoints/reverse_request_without_agreement_returns_no_reciprocal_agreement
    """
    set_logical_clock()
    resp = api.create_reverse_offset_request(
        create_reverse_offset_request_payload(
            state_code="WA", payee_tin="111-22-3333",
            requested_amount_cents=50000,
        ),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_RECIPROCAL_AGREEMENT)
