"""Queue B (corner design), section ``entities``.

Creation, retrieval, listing, defaults, computed fields, required fields and
type constraints on the resource model.
"""
import pytest

from test_helpers import (
    ADMIN,
    APPROVER,
    CONTROLLER,
    INITIATOR,
    UNKNOWN_ID,
    api_client,
    create_ledger,
    create_manual_entry,
    create_order,
    get_success_data,
    ledger_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ledger_create_returns_every_declared_field_and_opens_period_one():
    """PRD §3.1: "with `period_index` sitting at 1, `period_opened_utc` set to
    the ledger's own creation instant, `period_closed_through_index` sitting at
    0, and `status` at `OPEN`."
    PRD §3.1: "The response carries every derived balance initialised to zero —
    `pending_balance_cents`, `posted_balance_cents`, `delivered_fee_transfers_cents`
    and `undeliverable_cents` all begin at 0".

    Design: Corner/entities/ledger_create_returns_every_declared_field_and_opens_period_one
    """
    res = api_client.create_ledger({"name": "Primary Ledger", "currency": "USD"},
                                   ADMIN)
    ledger = validate_success(res, 201)
    assert ledger["period_index"] == 1
    assert ledger["period_closed_through_index"] == 0
    assert ledger["pending_balance_cents"] == 0
    assert ledger["posted_balance_cents"] == 0
    assert ledger["delivered_fee_transfers_cents"] == 0
    assert ledger["undeliverable_cents"] == 0
    assert ledger["status"] == "OPEN"
    assert isinstance(ledger["version"], int)
    assert ledger["created_at"] == ledger["period_opened_utc"], (
        "period_opened_utc is the ledger's own creation instant for the first period"
    )


def test_bank_account_get_round_trips_every_configuration_field():
    """PRD §3.1: "Bank accounts are registered next ... with the owning
    `legal_entity_id`, the holding bank's `institution_name`, a nine-digit
    `routing_number` passing the ABA mod-10 checksum, a four-digit
    `account_number_last4`, the `supported_rails` set and an optional
    `available_funds_cents`."

    Design: Corner/entities/bank_account_get_round_trips_every_configuration_field
    """
    scenario = ledger_scenario()
    fetched = get_success_data(
        api_client.get_bank_account(scenario["account"]["id"], CONTROLLER))
    assert fetched["supported_rails"] == ["ACH", "WIRE", "RTP"]
    assert fetched["available_funds_cents"] == 4_000_000
    assert fetched["routing_number"] == "021000021"
    assert fetched["account_number_last4"] == "4321"
    assert fetched["institution_name"] == "First Meridian"
    assert fetched["legal_entity_id"] == scenario["entity"]["id"]


def test_payment_orders_list_paginates_and_reports_total_count_and_has_more():
    """PRD §2.3: "List endpoints accept a `limit` and an `offset`. The `limit`
    parameter caps how many items a single response may carry; it defaults to 10,
    its minimum admissible value is 1 and its maximum is 100. The `offset`
    parameter states how many leading items to skip and defaults to 0."
    PRD §2.2: "total_count": 100 alongside "limit": 10.

    Design: Corner/entities/payment_orders_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = ledger_scenario()
    for amount in (2_000, 3_000, 4_000):
        create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=amount)

    page = validate_paginated(api_client.list_payment_orders(
        APPROVER, params={"ledger_id": scenario["ledger"]["id"], "limit": 2, "offset": 0}))
    rows, meta = page
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(api_client.list_payment_orders(
        APPROVER, params={"ledger_id": scenario["ledger"]["id"], "limit": 2, "offset": 2}))
    assert len(rows2) == 1
    assert meta2["has_more"] is False

    rows3, meta3 = validate_paginated(api_client.list_payment_orders(
        APPROVER, params={"ledger_id": scenario["ledger"]["id"]}))
    assert len(rows3) == 3
    assert meta3["limit"] == 10
    assert meta3["offset"] == 0


def test_counterparty_get_with_an_unknown_id_returns_counterparty_not_found():
    """PRD §2.10: "a missing counterparty as `ERR_COUNTERPARTY_NOT_FOUND`".
    PRD §2.10: "Each absent parent is reported as its own entity-specific
    not-found error rather than as a generic not-found, and every one of them
    carries HTTP status 404".

    Design: Corner/entities/counterparty_get_with_an_unknown_id_returns_counterparty_not_found
    """
    res = api_client.get_counterparty(UNKNOWN_ID, APPROVER)
    error = validate_error(res, "ERR_COUNTERPARTY_NOT_FOUND")
    assert res.status_code == 404
    assert error["error_id"] == "ERR_COUNTERPARTY_NOT_FOUND"
    body = res.json()
    assert body["response_type"] == "error"


def test_payment_order_create_without_idempotency_key_returns_invalid_request():
    """PRD §3.1: "the `idempotency_key` field is mandatory on every draft".
    PRD §2.10: "A malformed request — an unparseable body, a missing required
    field, a field of the wrong type, or a `return_reason` that is not one of
    `R01` through `R10` or `CHK_RETURNED` — is rejected with
    `ERR_INVALID_REQUEST` and HTTP 400."

    Design: Corner/entities/payment_order_create_without_idempotency_key_returns_invalid_request
    """
    scenario = ledger_scenario()
    payload = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 5_000,
        "payable_to_name": "Delta Supply Co",
    }
    res = api_client.create_payment_order(payload, INITIATOR)
    validate_error(res, "ERR_INVALID_REQUEST")
    assert res.status_code == 400

    rows, _ = validate_paginated(api_client.list_payment_orders(
        APPROVER, params={"ledger_id": scenario["ledger"]["id"]}))
    assert rows == [], "a rejected create must leave no order row"


def test_ledger_create_defaults_balances_and_counters_to_zero():
    """PRD §3.1: "with `period_index` sitting at 1 ... `period_closed_through_index`
    sitting at 0, and `status` at `OPEN`".
    PRD §2.4: "while `period_closed_through_index` starts at 0, where 0 means that
    no period has yet been closed at all."

    Design: Corner/entities/ledger_create_defaults_balances_and_counters_to_zero
    """
    ledger = create_ledger(name="Defaults Ledger", currency="EUR")
    assert ledger["period_index"] == 1
    assert ledger["period_closed_through_index"] == 0
    assert ledger["status"] == "OPEN"
    assert ledger["delivered_fee_transfers_cents"] == 0
    assert ledger["undeliverable_cents"] == 0
    assert ledger["period_opened_utc"] == ledger["created_at"]


def test_transaction_create_net_effect_cents_input_ignored():
    """PRD §3.6: "The signed effect of the row is carried by `net_effect_cents`,
    which is the negative of `amount_cents` when the direction is `DEBIT` and the
    positive of `amount_cents` when the direction is `CREDIT`."
    PRD §3.6: "Such an entry begins its life with `lifecycle_status` at `PENDING`
    and `settlement_status` at `UNSETTLED`".

    Design: Corner/entities/transaction_create_net_effect_cents_input_ignored
    """
    scenario = ledger_scenario()
    entry = create_manual_entry(
        scenario["ledger"]["id"], entry_type="ADJUSTMENT", direction="DEBIT",
        amount_cents=3_300, value_effective_utc="2026-09-01T09:00:00Z",
        net_effect_cents=999_999)

    assert entry["net_effect_cents"] == -3_300, (
        f"a client-supplied net_effect_cents must be ignored, got {entry['net_effect_cents']}"
    )
    assert entry["lifecycle_status"] == "PENDING"
    assert entry["settlement_status"] == "UNSETTLED"
    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == -3_300


def test_bank_account_create_with_a_seven_digit_routing_number_returns_invalid_request():
    """PRD §2.8: "a `routing_number` which must be exactly nine digits satisfying
    the ABA weighted mod-10 checksum, and `account_number_last4` which must be
    exactly four digits."

    Design: Corner/entities/bank_account_create_with_a_seven_digit_routing_number_returns_invalid_request
    """
    scenario = ledger_scenario()
    res = api_client.create_bank_account(
        {"legal_entity_id": scenario["entity"]["id"],
         "institution_name": "Bad Routing Bank", "routing_number": "1234567",
         "account_number_last4": "9999", "supported_rails": ["ACH"]}, CONTROLLER)
    validate_error(res, "ERR_INVALID_REQUEST")
    assert res.status_code == 400


def test_bank_account_create_with_a_failing_aba_checksum_is_refused():
    """PRD §2.8: "a `routing_number` which must be exactly nine digits satisfying
    the ABA weighted mod-10 checksum".

    Design: Corner/entities/bank_account_create_with_a_seven_digit_routing_number_returns_invalid_request
    """
    scenario = ledger_scenario()
    res = api_client.create_bank_account(
        {"legal_entity_id": scenario["entity"]["id"],
         "institution_name": "Bad Checksum Bank", "routing_number": "123456789",
         "account_number_last4": "9999", "supported_rails": ["ACH"]}, CONTROLLER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_bank_account_create_with_a_valid_routing_number_succeeds():
    """PRD §2.8: "a `routing_number` which must be exactly nine digits satisfying
    the ABA weighted mod-10 checksum".

    Design: Corner/entities/bank_account_create_with_a_seven_digit_routing_number_returns_invalid_request
    """
    scenario = ledger_scenario()
    res = api_client.create_bank_account(
        {"legal_entity_id": scenario["entity"]["id"],
         "institution_name": "Good Bank", "routing_number": "021000021",
         "account_number_last4": "1111", "supported_rails": ["ACH"]}, CONTROLLER)
    account = validate_success(res, 201)
    assert account["status"] == "OPEN"