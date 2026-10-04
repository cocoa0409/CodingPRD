"""State-machine cycles and cross-entity transition gates."""
import test_helpers as th


def test_sublease_default_cure_reinstate_cycle(api, admin_headers, finance_headers):
    """PRD §3.7: "Otherwise the escrow is debited by the full required amount,
    the shortfall is applied to the store's `OPEN` rent charges oldest first in
    `created_at` ascending order, marking each covered charge `PAID`, the event
    moves `DECLARED → CURED`, the sublease's `active_default_id` clears to null
    and the sublease moves `DEFAULTED → CURED`, and the store moves `SUSPENDED
    → OPEN` with the operator counters recomputed again."
    PRD §3.7: "A `CURED` sublease returns to normal standing when a
    `FranchisorAdmin` reinstates it, `CURED → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/sublease_default_cure_reinstate_cycle
    """
    # Default charge is 2,448,000 (escalated base, no sales); the cure
    # requires shortfall + cure_fee, so escrow must cover 2,448,000 + 15,000.
    ctx = th.setup_defaulted_store(escrow_cents=2_500_000, cure_fee_cents=15_000)
    sublease_id = ctx["sublease"]["id"]
    store_id = ctx["store"]["id"]
    operator_id = ctx["operator"]["id"]
    charge_id = ctx["charges"][0]["id"]
    event_id = ctx["default_event"]["id"]

    sub = th.validate_success(api.get_sublease(sublease_id, finance_headers))
    assert sub["status"] == "DEFAULTED"
    store = th.validate_success(api.get_store(store_id, finance_headers))
    assert store["status"] == "SUSPENDED"

    th.validate_success(api.cure_default(event_id, finance_headers))
    sub = th.validate_success(api.get_sublease(sublease_id, finance_headers))
    assert sub["status"] == "CURED"
    event = th.validate_success(api.get_default_event(event_id, finance_headers))
    assert event["status"] == "CURED"
    store = th.validate_success(api.get_store(store_id, finance_headers))
    assert store["status"] == "OPEN"

    th.validate_success(api.reinstate_sublease(sublease_id, admin_headers))
    sub = th.validate_success(api.get_sublease(sublease_id, finance_headers))
    assert sub["status"] == "ACTIVE"

    operator = th.validate_success(api.get_operator(operator_id, finance_headers))
    # 2,500,000 escrow - 2,448,000 shortfall - 15,000 cure fee
    assert operator["escrow_balance_cents"] == 37_000
    charge = th.validate_success(api.get_rent_charge(charge_id, finance_headers))
    assert charge["status"] == "PAID"


def test_sublease_can_redefault_after_reinstate(api, admin_headers, finance_headers):
    """PRD §3.7: "When an operator falls behind, a `FranchisorAdmin` declares
    default on the store's `ACTIVE` sublease, supplying a free-text `reason`
    (for example RENT_NONPAYMENT) and a non-negative administrative
    `cure_fee_cents`."
    PRD §3.7: "A `CURED` sublease returns to normal standing when a
    `FranchisorAdmin` reinstates it, `CURED → ACTIVE`."

    Design: Difficulty/non_linear_state_machine/sublease_default_cure_reinstate_cycle
    """
    ctx = th.setup_defaulted_store(escrow_cents=10_000_000, cure_fee_cents=15_000)
    sublease_id = ctx["sublease"]["id"]
    th.validate_success(api.cure_default(ctx["default_event"]["id"], finance_headers))
    th.validate_success(api.reinstate_sublease(sublease_id, admin_headers))
    sub = th.validate_success(api.get_sublease(sublease_id, finance_headers))
    assert sub["status"] == "ACTIVE"

    # The cycle is not one-shot: a second default on the re-activated sublease.
    second = th.validate_success(
        api.declare_default(sublease_id, th.declare_default_payload(reason="RENT_NONPAYMENT", cure_fee_cents=0),
                            admin_headers)
    )
    th.assert_default_event(second)
    assert second["status"] == "DECLARED"
    sub = th.validate_success(api.get_sublease(sublease_id, finance_headers))
    assert sub["status"] == "DEFAULTED"


def test_operator_suspend_reinstate_cycle_gated_by_grade(api, admin_headers, finance_headers):
    """PRD §3.2: "An `APPROVED` operator may be suspended (`APPROVED →
    SUSPENDED`) unconditionally. Reinstatement from `SUSPENDED` back to
    `APPROVED` requires that `capacity_grade` is not `FAILING` (else
    `ERR_CAPACITY_GRADE_FAILING`) and that `delinquency_balance_cents` is
    exactly 0 (else `ERR_OUTSTANDING_DELINQUENCY`)."

    Design: Difficulty/non_linear_state_machine/operator_suspend_reinstate_cycle_gated_by_grade
    """
    operator = th.create_strong_approved_operator(legal_name="Op Six LLC")
    op_id = operator["id"]

    suspended = th.validate_success(api.suspend_operator(op_id, admin_headers))
    assert suspended["status"] == "SUSPENDED"
    reinstated = th.validate_success(api.reinstate_operator(op_id, admin_headers))
    assert reinstated["status"] == "APPROVED"

    # The loop is not one-shot: the cycle repeats.
    suspended = th.validate_success(api.suspend_operator(op_id, admin_headers))
    assert suspended["status"] == "SUSPENDED"
    reinstated = th.validate_success(api.reinstate_operator(op_id, admin_headers))
    assert reinstated["status"] == "APPROVED"


def test_reinstate_blocked_while_delinquency_outstanding(api, admin_headers, finance_headers):
    """PRD §3.2: "Reinstatement from `SUSPENDED` back to `APPROVED` requires
    that `capacity_grade` is not `FAILING` (else `ERR_CAPACITY_GRADE_FAILING`)
    and that `delinquency_balance_cents` is exactly 0 (else
    `ERR_OUTSTANDING_DELINQUENCY`)."

    Design: Difficulty/non_linear_state_machine/operator_suspend_reinstate_cycle_gated_by_grade
    """
    ctx = th.setup_open_store()
    # An OPEN rent charge makes the operator delinquent.
    th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    op_id = ctx["operator"]["id"]

    operator = th.validate_success(api.get_operator(op_id, finance_headers))
    assert operator["delinquency_balance_cents"] > 0

    th.validate_success(api.suspend_operator(op_id, admin_headers))
    resp = api.reinstate_operator(op_id, admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_OUTSTANDING_DELINQUENCY, expected_status=409)


def test_store_open_requires_sublease_active(api, admin_headers, finance_headers):
    """PRD §3.3: "Opening the store is the final step: a `FranchisorAdmin`
    opens a `SETUP` store only when the store has a `FranchiseAgreement` in
    `ACTIVE` status (else `ERR_AGREEMENT_NOT_ACTIVE`), a `Sublease` in `ACTIVE`
    status (else `ERR_SUBLEASE_NOT_ACTIVE`), and an operator in `APPROVED`
    status (else `ERR_OPERATOR_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/store_open_requires_agreement_and_sublease_active
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    th.activate_agreement(store, operator)
    # Sublease drafted but left PENDING.
    sub = th.get_success_data(
        api.create_sublease(th.create_sublease_payload(store["id"], operator["id"]), admin_headers)
    )
    assert sub["status"] == "PENDING"

    resp = api.open_store(store["id"], admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_SUBLEASE_NOT_ACTIVE, expected_status=409)
    store_after = th.validate_success(api.get_store(store["id"], finance_headers))
    assert store_after["status"] == "SETUP"


def test_store_open_requires_agreement_active(api, admin_headers, finance_headers):
    """PRD §3.3: "Opening the store is the final step: a `FranchisorAdmin`
    opens a `SETUP` store only when the store has a `FranchiseAgreement` in
    `ACTIVE` status (else `ERR_AGREEMENT_NOT_ACTIVE`), a `Sublease` in `ACTIVE`
    status (else `ERR_SUBLEASE_NOT_ACTIVE`), and an operator in `APPROVED`
    status (else `ERR_OPERATOR_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/store_open_requires_agreement_and_sublease_active
    """
    site = th.create_site()
    operator = th.create_strong_approved_operator()
    store = th.create_store_for(operator, site)
    # Agreement drafted but never submitted/paid: stays DRAFT.
    th.get_success_data(
        api.create_agreement(th.create_agreement_payload(store["id"], operator["id"]), admin_headers)
    )

    resp = api.open_store(store["id"], admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, expected_status=409)
    store_after = th.validate_success(api.get_store(store["id"], finance_headers))
    assert store_after["status"] == "SETUP"


def test_operator_approval_requires_submitted_capacity_review(api, admin_headers, finance_headers):
    """PRD §3.2: "A `FranchisorAdmin` approves a `CANDIDATE` operator only when
    a `SUBMITTED` capacity review exists for that operator whose grade is
    `STRONG` or `ADEQUATE`; otherwise approval is rejected with
    `ERR_CAPACITY_REVIEW_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/operator_approval_requires_submitted_capacity_review
    """
    op = th.create_operator(legal_name="Op Thirteen LLC")
    # Review created but left DRAFT (never submitted).
    review = th.get_success_data(
        api.create_capacity_review(th.create_capacity_review_payload(op["id"]), finance_headers)
    )
    assert review["status"] == "DRAFT"

    resp = api.approve_operator(op["id"], admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_CAPACITY_REVIEW_REQUIRED, expected_status=409)
    op_after = th.validate_success(api.get_operator(op["id"], finance_headers))
    assert op_after["status"] == "CANDIDATE"


def test_operator_approval_without_any_review_rejected(api, admin_headers, finance_headers):
    """PRD §3.2: "A `FranchisorAdmin` approves a `CANDIDATE` operator only when
    a `SUBMITTED` capacity review exists for that operator whose grade is
    `STRONG` or `ADEQUATE`; otherwise approval is rejected with
    `ERR_CAPACITY_REVIEW_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/operator_approval_requires_submitted_capacity_review
    """
    op = th.create_operator(legal_name="Op No Review LLC")
    resp = api.approve_operator(op["id"], admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_CAPACITY_REVIEW_REQUIRED, expected_status=409)
    op_after = th.validate_success(api.get_operator(op["id"], finance_headers))
    assert op_after["status"] == "CANDIDATE"
