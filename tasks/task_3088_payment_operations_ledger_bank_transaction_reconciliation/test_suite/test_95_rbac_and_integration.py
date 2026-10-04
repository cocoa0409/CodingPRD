"""Queue B (corner design), sections ``rbac`` and ``cross_cutting_complexity_layers``.

Role-model denials and shared operations, segregation of duties across a role
change, idempotency, filter-plus-pagination composition, OCC on the statement
import, and the derived effective velocity limit.
"""
import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    CONTROLLER,
    INITIATOR,
    INITIATOR_USER_ID,
    APPROVER_USER_ID,
    TEST_USERS,
    api_client,
    create_counterparty,
    create_manual_entry,
    create_order,
    create_statement_payload,
    get_success_data,
    headers_for,
    import_statement,
    ledger_scenario,
    list_payment_orders,
    mark_entry_settled,
    refresh_account,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS_APPROVER_HEADERS = TEST_USERS["payment_ops_approver_headers"]


# ─── RBAC ─────────────────────────────────────────────

def test_initiator_cannot_release_its_own_payment():
    """PRD §2.1: "the release endpoints do not list this role at all".
    PRD §3.5: "it is also why `PaymentInitiator` is absent from every release
    endpoint's authorized-role list — the draft's author simply has no standing to
    release it."

    Design: Corner/rbac/initiator_cannot_release_its_own_payment
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=3_300)

    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, INITIATOR)
    error = validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    assert res.status_code == 403
    assert error["error_id"] != "ERR_SELF_APPROVAL_FORBIDDEN"


def test_the_role_denial_leaves_the_order_awaiting_approval():
    """PRD §2.1: "a `PaymentOpsAnalyst` calling the very same endpoint never
    reaches the separateness check and fails at the role gate with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/initiator_cannot_release_its_own_payment
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=3_300)
    api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, INITIATOR)

    after = get_success_data(api_client.get_payment_order(order["id"], ANALYST))
    assert after["status"] == "PENDING_APPROVAL"


def test_approver_can_create_a_counterparty_through_a_shared_operation():
    """PRD §2.1: "Counterparties come next: a `PaymentInitiator`, a
    `PaymentApprover` or a `PlatformAdmin` supplies the owning
    `legal_entity_id`".
    PRD §4: POST /counterparties is authorized for "PaymentInitiator,
    PaymentApprover, PlatformAdmin".

    Design: Corner/rbac/approver_can_create_a_counterparty_through_a_shared_operation
    """
    scenario = ledger_scenario()
    res = api_client.create_counterparty(
        {"legal_entity_id": scenario["entity"]["id"],
         "display_name": "Harbour Freight", "external_ref": "HF-1"}, APPROVER)
    counterparty = validate_success(res, 201)
    assert counterparty["status"] == "ACTIVE"


def test_a_non_authorized_role_is_refused_on_the_shared_operation():
    """PRD §2.1: "If both headers are present and valid but the caller's role
    does not appear in the authorized-role list for the endpoint being invoked,
    the request is refused with `ERR_FORBIDDEN_FOR_ROLE`, reported with HTTP
    status 403."

    Design: Corner/rbac/approver_can_create_a_counterparty_through_a_shared_operation
    """
    scenario = ledger_scenario()
    res = api_client.create_counterparty(
        {"legal_entity_id": scenario["entity"]["id"],
         "display_name": "Iris Logistics", "external_ref": "IL-1"},
        OPS_APPROVER_HEADERS)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    assert res.status_code == 403


def test_the_denied_create_leaves_the_institution_with_only_its_counterparties():
    """PRD §2.1: "If both headers are present and valid but the caller's role
    does not appear in the authorized-role list for the endpoint being invoked,
    the request is refused with `ERR_FORBIDDEN_FOR_ROLE`, reported with HTTP
    status 403."

    Design: Corner/rbac/approver_can_create_a_counterparty_through_a_shared_operation
    """
    scenario = ledger_scenario()
    api_client.create_counterparty(
        {"legal_entity_id": scenario["entity"]["id"],
         "display_name": "Harbour Freight", "external_ref": "HF-1"}, APPROVER)
    api_client.create_counterparty(
        {"legal_entity_id": scenario["entity"]["id"],
         "display_name": "Iris Logistics", "external_ref": "IL-1"}, OPS_APPROVER_HEADERS)

    rows = get_success_data(api_client.list_counterparties(
        APPROVER, params={"legal_entity_id": scenario["entity"]["id"]}))
    assert len(rows) == 2, (
        f"expected the scenario counterparty plus the approver's, got {len(rows)}"
    )


def test_segregation_of_duties_survives_a_role_change_on_the_same_identity():
    """PRD §2.1: "a `PaymentApprover` whose `X-User-ID` equals a payment order's
    `initiator_user_id` passes the role gate on approval and fails the later
    separateness check with `ERR_SELF_APPROVAL_FORBIDDEN`".

    Design: Corner/rbac/segregation_of_duties_survives_a_role_change_on_the_same_identity
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=125_000,
                         idempotency_key="idem-sod")
    # The order was drafted by the shared initiator identity; present that same
    # identity under the release role.
    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]},
        headers_for("PaymentApprover", INITIATOR_USER_ID))
    validate_error(res, "ERR_SELF_APPROVAL_FORBIDDEN")
    assert res.status_code == 403


def test_a_different_identity_in_the_same_role_releases_the_order():
    """PRD §3.5: "The separateness check requires that the `X-User-ID` of the
    approving operator differ from the order's `initiator_user_id`".

    Design: Corner/rbac/segregation_of_duties_survives_a_role_change_on_the_same_identity
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=125_000,
                         idempotency_key="idem-sod")
    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]},
        headers_for("PaymentApprover", APPROVER_USER_ID))
    approved = validate_success(res, 200)
    assert approved["approver_user_id"] == APPROVER_USER_ID


def test_the_separateness_rule_reads_the_order_not_the_session():
    """PRD §3.5: "The separateness check requires that the `X-User-ID` of the
    approving operator differ from the order's `initiator_user_id`".

    Design: Corner/rbac/segregation_of_duties_survives_a_role_change_on_the_same_identity
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=125_000,
                         idempotency_key="idem-sod")
    after = get_success_data(api_client.get_payment_order(order["id"], ANALYST))
    assert after["initiator_user_id"] == INITIATOR_USER_ID


# ─── Repeated create with the same idempotency key ─────

def test_repeating_an_idempotency_key_does_not_draft_a_second_order():
    """PRD §3.10: "A create that carries a key already used by a payment order
    for the same `legal_entity_id` in a status other than `CANCELLED` or
    `REJECTED` is refused with `ERR_DUPLICATE_PAYMENT` and HTTP 409, while a
    retried create that repeats a key whose prior order was cancelled or rejected
    proceeds."

    Design: Corner/cross_cutting_complexity_layers/repeated_create_with_the_same_idempotency_key_yields_one_order
    """
    scenario = ledger_scenario()
    payload = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 8_000,
        "idempotency_key": "idem-c29", "payable_to_name": "Delta Supply Co",
    }
    first = validate_success(api_client.create_payment_order(payload, INITIATOR), 201)

    retry = api_client.create_payment_order(payload, INITIATOR)
    assert retry.status_code >= 400, (
        "a key whose prior order is not CANCELLED or REJECTED must not draft a second order"
    )
    validate_error(retry, "ERR_DUPLICATE_PAYMENT")
    assert retry.status_code == 409

    rows = list_payment_orders(scenario["ledger"]["id"])
    assert len(rows) == 1, f"expected exactly one order row, got {len(rows)}"
    assert rows[0]["id"] == first["id"]


def test_a_different_key_produces_a_second_order():
    """PRD §3.10: "Two independent guards stop the same payment being drafted
    twice, and they have different scopes on purpose. The first is the caller's
    `idempotency_key`".

    Design: Corner/cross_cutting_complexity_layers/repeated_create_with_the_same_idempotency_key_yields_one_order
    """
    scenario = ledger_scenario()
    base = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 8_000,
        "payable_to_name": "Delta Supply Co",
    }
    first = validate_success(api_client.create_payment_order(
        {**base, "idempotency_key": "idem-c29"}, INITIATOR), 201)
    second = validate_success(api_client.create_payment_order(
        {**base, "idempotency_key": "idem-c29-b"}, INITIATOR), 201)
    assert second["id"] != first["id"]

    rows = list_payment_orders(scenario["ledger"]["id"])
    assert len(rows) == 2


# ─── Filters composed with pagination ─────────────────

def test_transaction_list_composes_filters_with_pagination():
    """PRD §3.6: "Filtering is available on the `ledger_id`, the
    `payment_order_id`, the `entry_type`, the `lifecycle_status` and the
    `settlement_status`".
    PRD §2.3: "`total_count` and `has_more` inside the `meta` object of the
    envelope."

    Design: Corner/cross_cutting_complexity_layers/transaction_list_composes_filters_with_pagination
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    settled_entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=900,
        value_effective_utc="2026-09-01T08:00:00Z")
    mark_entry_settled(settled_entry["id"])
    create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="CREDIT", amount_cents=700,
        value_effective_utc="2026-09-01T09:00:00Z")

    rows, meta = validate_paginated(api_client.list_transactions(
        CONTROLLER, params={"ledger_id": ledger_id, "settlement_status": "UNSETTLED",
                            "limit": 10, "offset": 0}))
    assert len(rows) == 1
    assert meta["total_count"] == 1, (
        f"total_count must report the filtered cardinality, got {meta['total_count']}"
    )


def test_the_unfiltered_list_reports_both_rows():
    """PRD §2.3: "List endpoints accept a `limit` and an `offset`."

    Design: Corner/cross_cutting_complexity_layers/transaction_list_composes_filters_with_pagination
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    settled_entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=900,
        value_effective_utc="2026-09-01T08:00:00Z")
    mark_entry_settled(settled_entry["id"])
    create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="CREDIT", amount_cents=700,
        value_effective_utc="2026-09-01T09:00:00Z")

    rows, meta = validate_paginated(api_client.list_transactions(
        CONTROLLER, params={"ledger_id": ledger_id}))
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_pagination_beyond_the_filtered_set_reports_no_more():
    """PRD §2.3: "Responses that are lists carry `limit`, `offset`, `total_count`
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/cross_cutting_complexity_layers/transaction_list_composes_filters_with_pagination
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    settled_entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=900,
        value_effective_utc="2026-09-01T08:00:00Z")
    mark_entry_settled(settled_entry["id"])

    rows, meta = validate_paginated(api_client.list_transactions(
        CONTROLLER, params={"ledger_id": ledger_id, "settlement_status": "SETTLED",
                            "limit": 1, "offset": 1}))
    assert rows == []
    assert meta["has_more"] is False


# ─── OCC on the statement import ─────────────────────

def test_statement_import_with_a_stale_account_version_returns_412():
    """PRD §2.7: "Importing a bank statement through the statement-import path
    requires `expected_bank_account_version` matching the current `version` of
    the `BankAccount` the statement belongs to; a writer whose view of that
    account's statement history has gone stale is rejected with
    `ERR_STALE_VERSION` and HTTP 412".

    Design: Corner/cross_cutting_complexity_layers/statement_import_with_a_stale_account_version_returns_412
    """
    scenario = ledger_scenario()
    stale_version = scenario["account_v"]
    get_success_data(import_statement(scenario, institution_ref="OCC-1",
                                      cycle_date="2026-09-01T08:00:00Z"),
                     expected_status=201)

    res = api_client.import_statement(
        create_statement_payload(scenario["account"]["id"], stale_version,
                                 institution_ref="OCC-2",
                                 cycle_date="2026-09-01T09:00:00Z"), ANALYST)
    validate_error(res, "ERR_STALE_VERSION")
    assert res.status_code == 412


def test_the_stale_import_leaves_the_statement_history_untouched():
    """PRD §2.7: "rather than being allowed to supersede a revision it has never
    seen".

    Design: Corner/cross_cutting_complexity_layers/statement_import_with_a_stale_account_version_returns_412
    """
    scenario = ledger_scenario()
    stale_version = scenario["account_v"]
    get_success_data(import_statement(scenario, institution_ref="OCC-1",
                                      cycle_date="2026-09-01T08:00:00Z"),
                     expected_status=201)
    api_client.import_statement(
        create_statement_payload(scenario["account"]["id"], stale_version,
                                 institution_ref="OCC-2",
                                 cycle_date="2026-09-01T09:00:00Z"), ANALYST)

    rows = get_success_data(api_client.list_statements(
        ANALYST, params={"bank_account_id": scenario["account"]["id"]}))
    assert len(rows) == 1


def test_the_import_succeeds_with_the_freshly_read_account_version():
    """PRD §2.7: "Importing a bank statement through the statement-import path
    requires `expected_bank_account_version` matching the current `version` of
    the `BankAccount` the statement belongs to".

    Design: Corner/cross_cutting_complexity_layers/statement_import_with_a_stale_account_version_returns_412
    """
    scenario = ledger_scenario()
    get_success_data(import_statement(scenario, institution_ref="OCC-1",
                                      cycle_date="2026-09-01T08:00:00Z"),
                     expected_status=201)
    refresh_account(scenario)

    res = api_client.import_statement(
        create_statement_payload(scenario["account"]["id"], scenario["account_v"],
                                 institution_ref="OCC-2",
                                 cycle_date="2026-09-01T09:00:00Z"), ANALYST)
    statement = validate_success(res, 201)
    assert statement["status"] == "IMPORTED"


# ─── Effective velocity limit fallback ───────────────

def test_effective_velocity_limit_falls_back_to_the_institution_default():
    """PRD §3.5: "The effective limit for an order is the counterparty's own
    `velocity_limit_cents` when that field is not null, and otherwise it is the
    counterparty's legal entity's `default_velocity_limit_cents`; where the
    platform supplies a fallback it is 5000000 cents."

    Design: Corner/cross_cutting_complexity_layers/effective_velocity_limit_falls_back_to_the_institution_default
    """
    scenario = ledger_scenario()
    inheriting = create_counterparty(
        scenario["entity"]["id"], display_name="Inherit Co", external_ref="IC-1")
    fetched = get_success_data(api_client.get_counterparty(inheriting["id"], APPROVER))
    assert fetched["velocity_limit_cents"] is None
    assert scenario["entity"]["default_velocity_limit_cents"] == 5_000_000


def test_an_order_below_the_default_is_admitted_and_one_at_it_is_refused():
    """PRD §3.5: "An order is admitted only when its `amount_cents` is strictly
    less than that effective limit, so an order whose amount exactly equals the
    limit is refused with `ERR_VELOCITY_LIMIT_EXCEEDED` and HTTP 409 while an
    order one cent below the limit is admitted".

    Design: Corner/cross_cutting_complexity_layers/effective_velocity_limit_falls_back_to_the_institution_default
    """
    scenario = ledger_scenario(account_overrides={"supported_rails": ["WIRE"]})
    inheriting = create_counterparty(
        scenario["entity"]["id"], display_name="Inherit Co", external_ref="IC-1")
    scenario["counterparty"] = inheriting

    admitted = create_order(scenario, rail="WIRE", direction="CREDIT",
                            amount_cents=4_999_999)
    assert admitted["status"] == "PENDING_APPROVAL"

    res = api_client.create_payment_order({
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": inheriting["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "WIRE", "direction": "CREDIT", "amount_cents": 5_000_000,
        "idempotency_key": "idem-default-at-limit", "payable_to_name": "Inherit Co",
    }, INITIATOR)
    validate_error(res, "ERR_VELOCITY_LIMIT_EXCEEDED")


def test_the_counterpartys_own_limit_still_overrides_the_default():
    """PRD §3.5: "The effective limit for an order is the counterparty's own
    `velocity_limit_cents` when that field is not null".

    Design: Corner/cross_cutting_complexity_layers/effective_velocity_limit_falls_back_to_the_institution_default
    """
    scenario = ledger_scenario(account_overrides={"supported_rails": ["WIRE"]})
    limited = create_counterparty(
        scenario["entity"]["id"], display_name="Limited Co", external_ref="LC-1",
        velocity_limit_cents=3_000_000)
    scenario["counterparty"] = limited

    res = api_client.create_payment_order({
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": limited["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "WIRE", "direction": "CREDIT", "amount_cents": 3_500_000,
        "idempotency_key": "idem-own-limit", "payable_to_name": "Limited Co",
    }, INITIATOR)
    validate_error(res, "ERR_VELOCITY_LIMIT_EXCEEDED")