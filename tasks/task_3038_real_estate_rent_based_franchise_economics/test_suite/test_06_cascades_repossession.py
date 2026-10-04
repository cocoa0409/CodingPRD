"""Repossession unwind cascade and default-declaration cascade."""
import test_helpers as th


def test_repossession_cascade_five_hops(api, admin_headers, finance_headers):
    """PRD §3.8: "Repossession moves the event `DECLARED → REPOSSESSED`, the
    sublease `DEFAULTED → REPOSSESSED`, and the store `SUSPENDED →
    REPOSSESSED`, where the store transition fans out into the full unwind
    cascade: the store's `ACTIVE` franchise agreement moves to `TERMINATED`;
    every one of the store's `OPEN` rent charges moves to `WAIVED`, every
    `OPEN` fund assessment moves to `WAIVED`, and every `ASSESSED` co-op
    assessment moves to `WAIVED`; every `PENDING` or `SUBMITTED` reinvestment
    obligation moves to `BREACHED`; and the operator moves to `TERMINATED` with
    `delinquency_balance_cents` recomputed — waived charges drop out of the
    delinquency sum."

    Design: Difficulty/transitive_cascade/repossession_cascade_five_hops
    """
    ctx = th.setup_repossessed_store()
    ids = {
        "event": ctx["default_event"]["id"],
        "sublease": ctx["sublease"]["id"],
        "store": ctx["store"]["id"],
        "agreement": ctx["agreement"]["id"],
        "charge": ctx["charges"][0]["id"],
        "obligation": ctx["obligation"]["id"],
        "coop_assessment": ctx["coop_assessment"]["id"],
        "operator": ctx["operator"]["id"],
    }

    assert th.validate_success(api.get_default_event(ids["event"], finance_headers))["status"] == "REPOSSESSED"
    assert th.validate_success(api.get_sublease(ids["sublease"], finance_headers))["status"] == "REPOSSESSED"
    assert th.validate_success(api.get_store(ids["store"], finance_headers))["status"] == "REPOSSESSED"
    assert th.validate_success(api.get_agreement(ids["agreement"], finance_headers))["status"] == "TERMINATED"
    assert th.validate_success(api.get_rent_charge(ids["charge"], finance_headers))["status"] == "WAIVED"
    assert th.validate_success(api.get_reinvestment_obligation(ids["obligation"], finance_headers))["status"] == "BREACHED"
    assert th.validate_success(api.get_coop_assessment(ids["coop_assessment"], finance_headers))["status"] == "WAIVED"
    operator = th.validate_success(api.get_operator(ids["operator"], finance_headers))
    assert operator["status"] == "TERMINATED"
    assert operator["delinquency_balance_cents"] == 0


def test_repossession_waives_open_fund_assessment_too(api, admin_headers, finance_headers):
    """PRD §3.8: "every one of the store's `OPEN` rent charges moves to
    `WAIVED`, every `OPEN` fund assessment moves to `WAIVED`, and every
    `ASSESSED` co-op assessment moves to `WAIVED`"
    PRD §3.8: "Each entity touched by the cascade has its own `version`
    incremented."

    Design: Difficulty/transitive_cascade/repossession_cascade_five_hops
    """
    ctx = th.setup_open_store()
    assessment = th.create_locked_sales_month(ctx["store"], ctx["operator"], "2026-09", 10_000_000)
    assert assessment["status"] == "OPEN"
    event = th.declare_store_default(ctx)
    th.validate_success(api.repossess_default(event["id"], admin_headers))

    waived = th.validate_success(api.get_fund_assessment(assessment["id"], finance_headers))
    assert waived["status"] == "WAIVED"
    store = th.validate_success(api.get_store(ctx["store"]["id"], finance_headers))
    assert store["status"] == "REPOSSESSED"


def test_default_declaration_cascade_two_hops(api, admin_headers, finance_headers):
    """PRD §3.7: "Declaration creates a **DefaultEvent** in `DECLARED` status
    whose `shortfall_cents` captures the store's delinquent open charges at the
    moment of declaration and whose `store_id` is copied from the sublease; the
    sublease moves `ACTIVE → DEFAULTED` and records the new event in
    `active_default_id`, while the store moves `OPEN → SUSPENDED`, which
    recomputes the operator's `stores_operated_count` (the store no longer
    counts as open) and `delinquency_balance_cents`."

    Design: Difficulty/transitive_cascade/default_declaration_cascade_two_hops
    """
    ctx = th.setup_open_store()
    operator_before = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator_before["stores_operated_count"] == 1

    event = th.declare_store_default(ctx)
    th.assert_default_event(event)
    assert event["status"] == "DECLARED"
    assert event["store_id"] == ctx["store"]["id"]

    sub = th.validate_success(api.get_sublease(ctx["sublease"]["id"], finance_headers))
    assert sub["status"] == "DEFAULTED"
    assert sub["active_default_id"] == event["id"]

    store = th.validate_success(api.get_store(ctx["store"]["id"], finance_headers))
    assert store["status"] == "SUSPENDED"

    operator_after = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator_after["stores_operated_count"] == 0
    assert operator_after["version"] > operator_before["version"]


def test_default_declaration_shortfall_captures_open_charges(api, admin_headers, finance_headers):
    """PRD §3.7: "Declaration creates a **DefaultEvent** in `DECLARED` status
    whose `shortfall_cents` captures the store's delinquent open charges at the
    moment of declaration and whose `store_id` is copied from the sublease; the
    sublease moves `ACTIVE → DEFAULTED` and records the new event in
    `active_default_id`, while the store moves `OPEN → SUSPENDED`, which
    recomputes the operator's `stores_operated_count` (the store no longer
    counts as open) and `delinquency_balance_cents`."
    PRD §3.5: "The `delinquency_balance_cents` on the operator is the sum of
    the unpaid amount over all of the operator's stores' `OPEN` rent charges
    plus their `OPEN` fund assessments."

    Design: Difficulty/transitive_cascade/default_declaration_cascade_two_hops
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    event = th.declare_store_default(ctx, cure_fee_cents=15_000)

    # One OPEN charge of 2,448,000 (escalated base binds, no sales).
    assert event["shortfall_cents"] == charge["selected_rent_cents"] == 2_448_000

    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["delinquency_balance_cents"] == 2_448_000
    assert operator["stores_operated_count"] == 0


def test_repossession_waive_conserves_store_charge_total(api, admin_headers, finance_headers):
    """PRD §3.8: "every one of the store's `OPEN` rent charges moves to
    `WAIVED`, every `OPEN` fund assessment moves to `WAIVED`, and every
    `ASSESSED` co-op assessment moves to `WAIVED`; every `PENDING` or
    `SUBMITTED` reinvestment obligation moves to `BREACHED`; and the operator
    moves to `TERMINATED` with `delinquency_balance_cents` recomputed — waived
    charges drop out of the delinquency sum."

    Design: Difficulty/compensating_invariant/repossession_waive_conserves_store_charge_total
    """
    ctx = th.setup_open_store()
    charge_a = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"],
                                   "2026", "2026-04-01", "2027-03-31")
    charge_b = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"],
                                   "2027", "2027-04-01", "2028-03-31")
    # 2,400,000 base (count 1 in window A -> 2,448,000); window B count 1
    # relative to the sublease start -> both escalate once.
    total_selected = charge_a["selected_rent_cents"] + charge_b["selected_rent_cents"]
    assert total_selected == 2_448_000 + 2_448_000

    operator_before = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator_before["delinquency_balance_cents"] == total_selected

    event = th.declare_store_default(ctx)
    th.validate_success(api.repossess_default(event["id"], admin_headers))

    waived_a = th.validate_success(api.get_rent_charge(charge_a["id"], finance_headers))
    waived_b = th.validate_success(api.get_rent_charge(charge_b["id"], finance_headers))
    assert waived_a["status"] == "WAIVED" and waived_b["status"] == "WAIVED"
    # The amounts themselves survive the waive — nothing is lost.
    assert waived_a["selected_rent_cents"] + waived_b["selected_rent_cents"] == total_selected

    operator_after = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator_after["delinquency_balance_cents"] == 0
    assert operator_after["status"] == "TERMINATED"


def test_repossession_waive_after_partial_payment_recomputes_delinquency(api, admin_headers, finance_headers):
    """PRD §3.8: "every one of the store's `OPEN` rent charges moves to
    `WAIVED`, every `OPEN` fund assessment moves to `WAIVED`, and every
    `ASSESSED` co-op assessment moves to `WAIVED`; every `PENDING` or
    `SUBMITTED` reinvestment obligation moves to `BREACHED`; and the operator
    moves to `TERMINATED` with `delinquency_balance_cents` recomputed — waived
    charges drop out of the delinquency sum."
    PRD §3.5: "each payment's `amount_cents` adds to `amount_paid_cents`, and
    when the cumulative payments fully cover the selected rent the charge moves
    `OPEN → PAID`, again recomputing `delinquency_balance_cents`."

    Design: Difficulty/compensating_invariant/repossession_waive_conserves_store_charge_total
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    full = charge["selected_rent_cents"]
    # Partial payment of 1,000,000: charge stays OPEN with a reduced remainder.
    th.validate_success(api.pay_rent_charge(charge["id"], {"amount_cents": 1_000_000}, finance_headers))
    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["delinquency_balance_cents"] == full - 1_000_000

    event = th.declare_store_default(ctx)
    th.validate_success(api.repossess_default(event["id"], admin_headers))

    waived = th.validate_success(api.get_rent_charge(charge["id"], finance_headers))
    assert waived["status"] == "WAIVED"
    # The paid portion is conserved on the charge; nothing is lost.
    assert waived["amount_paid_cents"] == 1_000_000
    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["delinquency_balance_cents"] == 0
    assert operator["status"] == "TERMINATED"


def test_repossession_cascade_visible_in_same_response(api, admin_headers, finance_headers):
    """PRD §2.10: "State changes propagate across entity boundaries
    automatically, without a client request on the affected resource. When a
    store completes repossession, its agreement, sublease, open charges, open
    assessments, and pending obligations are all resolved in one cascade, and
    its operator is terminated; each affected entity has its own `updated_at`
    refreshed and its own `version` incremented."
    PRD §2.10: "Recomputed aggregate fields on the `Operator` —
    `stores_operated_count` and `delinquency_balance_cents` — are refreshed
    whenever an underlying store status or charge status changes, and these
    recomputations are immediate: the system's consistency model is
    synchronous, never deferred."

    Design: Corner/consistency_model/repossession_cascade_visible_in_same_response
    """
    ctx = th.setup_open_store()
    charge = th.post_rent_charge(ctx["store"]["id"], ctx["sublease"]["id"])
    event = th.declare_store_default(ctx)

    resp = api.repossess_default(event["id"], admin_headers)
    th.validate_success(resp)

    store = th.validate_success(api.get_store(ctx["store"]["id"], finance_headers))
    assert store["status"] == "REPOSSESSED"
    operator = th.validate_success(api.get_operator(ctx["operator"]["id"], finance_headers))
    assert operator["status"] == "TERMINATED"
    waived = th.validate_success(api.get_rent_charge(charge["id"], finance_headers))
    assert waived["status"] == "WAIVED"


def test_repossess_on_cured_default_returns_invalid_state(api, admin_headers, finance_headers):
    """PRD §3.8: "When a default cannot be cured, a `FranchisorAdmin`
    repossesses the store behind the `DECLARED` event (an event in any other
    state is rejected with `ERR_DEFAULT_NOT_DECLARED`)."

    Design: Corner/state_machines/repossess_on_cured_default_returns_invalid_state
    """
    ctx = th.setup_defaulted_store(escrow_cents=5_000_000, cure_fee_cents=15_000)
    event_id = ctx["default_event"]["id"]
    th.validate_success(api.cure_default(event_id, finance_headers))

    resp = api.repossess_default(event_id, admin_headers)
    th.validate_error(resp, th.ApiErrorId.ERR_DEFAULT_NOT_DECLARED, expected_status=409)
    event = th.validate_success(api.get_default_event(event_id, finance_headers))
    assert event["status"] == "CURED"
