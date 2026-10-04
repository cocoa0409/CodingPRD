"""Suspension/reinstatement cycles and the cross-entity ACTIVE gates.

Covers PRD §3.7 (suspend/reinstate with classification sub-states), §3.3
(submit gates), §2.8 (state-before-temporal pipeline order), and §3.6 (claim
filing blocked only for classification/exit states).
Instances:
Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_with_classification,
Difficulty/cross_entity_state_dependency/order_submit_blocked_when_agreement_suspended,
Difficulty/priority_pair_validation_conflict/order_submit_state_gate_beats_lead_time,
Corner/validations/claim_blocked_only_for_classification_suspension.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_item,
    create_claim_payload,
    create_order,
    create_stale_claim,
    get_agreement,
    get_distributor,
    list_orders,
    make_distributor_headers,
    order_line,
    reinstate_agreement,
    set_clock,
    setup_active_cash_agreement,
    setup_delivered_order,
    submit_order,
    validate_error,
)
from test_helpers.fixtures import suspend_agreement  # not re-exported by the barrel

_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def _find_order(distributor_id: str, order_id: str) -> dict:
    matches = [o for o in list_orders(distributor_id) if o["id"] == order_id]
    assert len(matches) == 1, f"order {order_id} not found"
    return matches[0]


def test_agreement_suspend_reinstate_full_cycle(api):
    """PRD §3.7: "Suspending with `SERVICE_DEFAULT` moves the agreement to
    `SUSPENDED_SERVICE`, stamps `suspension_reason` accordingly, and cancels
    forward demand..."
    PRD §3.7: "From `SUSPENDED_SERVICE`, either a `RouteOpsManager` or a
    `CompanyAdmin` reinstates with the `resolution` omitted, returning the
    agreement to `ACTIVE` and clearing `suspension_reason` to null."
    PRD §3.7: "`CONFIRMED_IC` reaffirms independent-contractor status: the
    agreement returns to `ACTIVE`, `suspension_reason` clears to null, and the
    distributor's `classification_status` returns to `INDEPENDENT_CONTRACTOR`
    with a `version` bump."

    Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_with_classification
    """
    ctx = setup_active_cash_agreement()
    agr_id = ctx["agreement"]["id"]
    dist_id = ctx["distributor"]["id"]

    suspended = suspend_agreement(agr_id, "SERVICE_DEFAULT")
    assert suspended["status"] == "SUSPENDED_SERVICE"
    assert suspended["suspension_reason"] == "SERVICE_DEFAULT"

    reinstated = reinstate_agreement(agr_id)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None

    suspended2 = suspend_agreement(agr_id, "CLASSIFICATION_DISPUTE")
    assert suspended2["status"] == "SUSPENDED_CLASSIFICATION"
    assert suspended2["suspension_reason"] == "CLASSIFICATION_DISPUTE"
    assert get_distributor(dist_id)["classification_status"] == "DISPUTED"

    reinstated2 = reinstate_agreement(
        agr_id, resolution="CONFIRMED_IC", as_company_admin=True
    )
    assert reinstated2["status"] == "ACTIVE"
    assert reinstated2["suspension_reason"] is None
    assert get_distributor(dist_id)["classification_status"] == (
        "INDEPENDENT_CONTRACTOR"
    )
    assert reinstated2["version"] == 6, (
        "create 1, activate 2, suspend 3, reinstate 4, suspend 5, reinstate 6"
    )


def test_classification_suspension_marks_distributor_disputed(api):
    """PRD §3.7: "Suspending with `CLASSIFICATION_DISPUTE` moves the agreement
    to `SUSPENDED_CLASSIFICATION`, additionally flips the distributor's
    `classification_status` to `DISPUTED` with a `version` bump, and fires the
    same cancellation cascade."

    Design: Difficulty/non_linear_state_machine/agreement_suspend_reinstate_cycle_with_classification
    """
    ctx = setup_active_cash_agreement()
    agr_id = ctx["agreement"]["id"]
    dist_id = ctx["distributor"]["id"]

    suspended = suspend_agreement(agr_id, "CLASSIFICATION_DISPUTE")
    assert suspended["status"] == "SUSPENDED_CLASSIFICATION"
    assert suspended["suspension_reason"] == "CLASSIFICATION_DISPUTE"
    assert get_distributor(dist_id)["classification_status"] == "DISPUTED"

    reinstated = reinstate_agreement(
        agr_id, resolution="CONFIRMED_IC", as_company_admin=True
    )
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] is None
    assert get_distributor(dist_id)["classification_status"] == (
        "INDEPENDENT_CONTRACTOR"
    )


def test_order_submit_blocked_when_agreement_suspended(api):
    """PRD §3.3: "Submission converts the forecast into a firm order (`DRAFT →
    SUBMITTED`, stamping `submitted_on` from the logical clock), and this is
    where the firm gates bite: the distributor must hold an `ACTIVE` agreement
    (`ERR_AGREEMENT_NOT_ACTIVE` otherwise)..."

    Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_agreement_suspended
    """
    ctx = setup_active_cash_agreement()
    order = create_order(
        ctx["distributor"], "2026-09-05", [order_line("WHT-24", 5)]
    )
    suspend_agreement(ctx["agreement"]["id"], "SERVICE_DEFAULT")
    resp = api_client.submit_order(
        order["id"], make_distributor_headers(ctx["distributor"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert _find_order(ctx["distributor"]["id"], order["id"])["status"] == "DRAFT"


def test_order_submit_succeeds_after_reinstate(api):
    """PRD §3.3: "the distributor must hold an `ACTIVE` agreement
    (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the `delivery_date` must fall at
    least two days after the current logical date (`ERR_ORDER_LEAD_TIME`
    otherwise), and the catalog sku check re-runs (`ERR_SKU_UNKNOWN`)."
    PRD §3.7: "From `SUSPENDED_SERVICE`, either a `RouteOpsManager` or a
    `CompanyAdmin` reinstates with the `resolution` omitted, returning the
    agreement to `ACTIVE` and clearing `suspension_reason` to null."

    Design: Difficulty/cross_entity_state_dependency/order_submit_blocked_when_agreement_suspended
    """
    ctx = setup_active_cash_agreement()
    order = create_order(
        ctx["distributor"], "2026-09-05", [order_line("WHT-24", 5)]
    )
    suspend_agreement(ctx["agreement"]["id"], "SERVICE_DEFAULT")
    resp = api_client.submit_order(
        order["id"], make_distributor_headers(ctx["distributor"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    reinstate_agreement(ctx["agreement"]["id"])
    submitted = submit_order(order)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_on"] is not None


def test_submit_state_gate_beats_lead_time(api):
    """PRD §2.8: "Seventh, state preconditions (`ERR_INVALID_STATE_TRANSITION`,
    `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_TERRITORY_NOT_LISTED`,
    `ERR_PRODUCTION_DAY_LOCKED`, `ERR_CLAIM_NOT_REVIEWABLE`,
    `ERR_FINANCING_NOT_DISBURSED`, `ERR_FINANCING_PLAN_EXISTS`)."
    PRD §2.8: "Tenth, temporal windows (`ERR_ORDER_LEAD_TIME`,
    `ERR_CLAIM_NOT_STALE_YET`, `ERR_CLAIM_WINDOW_EXPIRED`)."
    PRD §3.3: "the distributor must hold an `ACTIVE` agreement
    (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the `delivery_date` must fall at
    least two days after the current logical date (`ERR_ORDER_LEAD_TIME`
    otherwise), and the catalog sku check re-runs (`ERR_SKU_UNKNOWN`)."

    Design: Difficulty/priority_pair_validation_conflict/order_submit_state_gate_beats_lead_time
    """
    ctx = setup_active_cash_agreement()
    suspend_agreement(ctx["agreement"]["id"], "SERVICE_DEFAULT")
    order = create_order(
        ctx["distributor"], "2026-09-02", [order_line("WHT-24", 5)]
    )
    resp = api_client.submit_order(
        order["id"], make_distributor_headers(ctx["distributor"]["id"])
    )
    error = validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert error["error_id"] != "ERR_ORDER_LEAD_TIME", (
        "state gate (seventh) outranks the temporal window (tenth)"
    )
    assert _find_order(ctx["distributor"]["id"], order["id"])["status"] == "DRAFT"


def test_submit_short_lead_time_rejected_when_agreement_active(api):
    """PRD §3.3: "the `delivery_date` must fall at least two days after the
    current logical date (`ERR_ORDER_LEAD_TIME` otherwise)..."
    PRD §2.8: "Tenth, temporal windows (`ERR_ORDER_LEAD_TIME`,
    `ERR_CLAIM_NOT_STALE_YET`, `ERR_CLAIM_WINDOW_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/order_submit_state_gate_beats_lead_time
    """
    ctx = setup_active_cash_agreement()
    order = create_order(
        ctx["distributor"], "2026-09-02", [order_line("WHT-24", 5)]
    )
    resp = api_client.submit_order(
        order["id"], make_distributor_headers(ctx["distributor"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_LEAD_TIME)
    assert _find_order(ctx["distributor"]["id"], order["id"])["status"] == "DRAFT"


def test_claim_blocked_only_for_classification_suspension(api):
    """PRD §3.6: "Filing is blocked only while the distributor's agreement is
    `SUSPENDED_CLASSIFICATION`, `EXITING`, or `EXITED`; in those states the
    attempt is rejected with `ERR_AGREEMENT_NOT_ACTIVE`."

    Design: Corner/validations/claim_blocked_only_for_classification_suspension
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(ctx, "2026-09-04", [order_line("WHT-24", 5)])
    set_clock("2026-09-10T09:00:00Z")

    suspend_agreement(ctx["agreement"]["id"], "SERVICE_DEFAULT")
    claim = create_stale_claim(
        ctx["distributor"],
        [claim_item("WHT-24", "2026-09-04", 1, "2026-09-10")],
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_credit_cents"] == 192, (
        "stale-credit rights survive a service suspension"
    )

    reinstate_agreement(ctx["agreement"]["id"])
    suspend_agreement(ctx["agreement"]["id"], "CLASSIFICATION_DISPUTE")
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("WHT-24", "2026-09-04", 1, "2026-09-10")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
    assert get_distributor(ctx["distributor"]["id"])["classification_status"] == (
        "DISPUTED"
    )
    assert get_agreement(ctx["agreement"]["id"])["status"] == (
        "SUSPENDED_CLASSIFICATION"
    )
