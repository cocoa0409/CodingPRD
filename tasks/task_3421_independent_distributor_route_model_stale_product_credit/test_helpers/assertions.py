"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §2.9, §3).

Field-presence and type assertions only; value equality belongs in tests.
Nullable fields are asserted as (present and either None or the right type) so
pre-transition states (null computed fields) pass.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStanding,
    AgreementStatus,
    CancelledReason,
    ClaimStatus,
    ClassificationStatus,
    DenialReason,
    DistributorStatus,
    FinancingPlanStatus,
    FinancierType,
    OrderStatus,
    ProductionDayStatus,
    SuspensionReason,
    TerritoryStatus,
    TransferMode,
    TransferStatus,
    WEEKDAY_VALUES,
)

_ENUM_VALUES = lambda enum_cls: [e.value for e in enum_cls]  # noqa: E731


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}: created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}: updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be an integer >= 1"
    )


def _assert_optional_timestamp(data: dict, field: str, label: str):
    value = data.get(field)
    assert field in data, f"{label}: {field} key must be present (null allowed)"
    if value is not None:
        assert isinstance(value, str), f"{label}: {field} must be a string or null"


def _assert_optional_int(data: dict, field: str, label: str):
    value = data.get(field)
    assert field in data, f"{label}: {field} key must be present (null allowed)"
    if value is not None:
        assert isinstance(value, int), f"{label}: {field} must be an integer or null"


def assert_bakery(data: dict):
    _assert_common_fields(data, "Bakery")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["daily_capacity_units"], int)
    assert data["daily_capacity_units"] >= 1
    catalog = data["product_catalog"]
    assert isinstance(catalog, list) and len(catalog) > 0
    skus = []
    for entry in catalog:
        assert isinstance(entry["sku"], str) and len(entry["sku"]) > 0
        assert isinstance(entry["display_name"], str)
        assert isinstance(entry["shelf_life_days"], int)
        assert entry["shelf_life_days"] >= 1
        assert isinstance(entry["list_price_cents"], int)
        assert entry["list_price_cents"] >= 1
        skus.append(entry["sku"])
    assert len(skus) == len(set(skus)), "catalog skus must be unique"


def assert_territory(data: dict):
    _assert_common_fields(data, "Territory")
    assert isinstance(data["area_code"], str) and len(data["area_code"]) > 0
    assert isinstance(data["list_price_cents"], int)
    assert data["list_price_cents"] >= 1
    assert data["status"] in _ENUM_VALUES(TerritoryStatus)


def assert_distributor(data: dict):
    _assert_common_fields(data, "Distributor")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 1
    assert data["status"] in _ENUM_VALUES(DistributorStatus)
    assert data["classification_status"] in _ENUM_VALUES(ClassificationStatus)
    assert data["account_standing"] in _ENUM_VALUES(AccountStanding)
    assert isinstance(data["trade_balance_cents"], int)


def assert_route_agreement(data: dict):
    _assert_common_fields(data, "RouteAgreement")
    for fk in ("territory_id", "distributor_id", "bakery_id"):
        assert isinstance(data[fk], str) and len(data[fk]) > 0
    assert isinstance(data["purchase_price_cents"], int)
    assert data["purchase_price_cents"] >= 1
    assert isinstance(data["financed_amount_cents"], int)
    assert 0 <= data["financed_amount_cents"] <= data["purchase_price_cents"]
    assert isinstance(data["discount_pct"], (int, float))
    assert 0 < data["discount_pct"] < 1
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in _ENUM_VALUES(AgreementStatus)
    assert data["suspension_reason"] is None or data["suspension_reason"] in (
        _ENUM_VALUES(SuspensionReason)
    )
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    _assert_optional_timestamp(data, "activated_on", "RouteAgreement")
    _assert_optional_timestamp(data, "exited_on", "RouteAgreement")


def assert_financing_plan(data: dict):
    _assert_common_fields(data, "FinancingPlan")
    assert isinstance(data["agreement_id"], str) and len(data["agreement_id"]) > 0
    assert data["financier_type"] in _ENUM_VALUES(FinancierType)
    if data["financier_type"] == FinancierType.EXTERNAL_LENDER.value:
        assert isinstance(data["lender_name"], str) and len(data["lender_name"]) > 0
    assert isinstance(data["principal_cents"], int)
    assert data["principal_cents"] >= 1
    assert isinstance(data["annual_interest_rate"], (int, float))
    assert 0 < data["annual_interest_rate"] < 1
    assert isinstance(data["term_weeks"], int) and data["term_weeks"] >= 1
    _assert_optional_int(data, "weekly_payment_cents", "FinancingPlan")
    _assert_optional_int(data, "outstanding_principal_cents", "FinancingPlan")
    _assert_optional_timestamp(data, "disburse_date", "FinancingPlan")
    assert isinstance(data["total_paid_cents"], int)
    assert data["total_paid_cents"] >= 0
    assert data["status"] in _ENUM_VALUES(FinancingPlanStatus)


def assert_retail_account(data: dict):
    _assert_common_fields(data, "RetailAccount")
    assert isinstance(data["distributor_id"], str) and len(data["distributor_id"]) > 0
    assert isinstance(data["store_name"], str) and len(data["store_name"]) > 0
    weekdays = data["delivery_weekdays"]
    assert isinstance(weekdays, list) and len(weekdays) > 0
    for day in weekdays:
        assert day in WEEKDAY_VALUES
    score = data["compliance_score"]
    assert score is None or (isinstance(score, int) and 0 <= score <= 100)
    last_audit = data["last_audit_on"]
    assert last_audit is None or isinstance(last_audit, str)
    log = data["audit_log"]
    assert isinstance(log, list)
    for entry in log:
        assert isinstance(entry["audit_date"], str)
        for component in ("shelf_stock_score", "rotation_score", "display_score"):
            assert isinstance(entry[component], int)
            assert 0 <= entry[component] <= 100
        assert isinstance(entry["composite_score"], int)
        assert isinstance(entry["is_violation"], bool)


def assert_production_day(data: dict):
    _assert_common_fields(data, "ProductionDay")
    assert isinstance(data["bakery_id"], str) and len(data["bakery_id"]) > 0
    assert isinstance(data["date"], str) and len(data["date"]) > 0
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert isinstance(data["forecast_units"], int) and data["forecast_units"] >= 0
    assert data["status"] in _ENUM_VALUES(ProductionDayStatus)


def _assert_order_lines(lines, label: str):
    assert isinstance(lines, list) and len(lines) > 0
    for line in lines:
        assert isinstance(line["sku"], str) and len(line["sku"]) > 0
        assert isinstance(line["qty"], int) and line["qty"] >= 1, (
            f"{label}: qty must be >= 1"
        )


def assert_daily_order(data: dict):
    _assert_common_fields(data, "DailyOrder")
    assert isinstance(data["distributor_id"], str) and len(data["distributor_id"]) > 0
    assert isinstance(data["delivery_date"], str)
    _assert_order_lines(data["lines"], "DailyOrder")
    assert isinstance(data["units_total"], int) and data["units_total"] >= 1
    assert data["units_total"] == sum(line["qty"] for line in data["lines"])
    assert data["status"] in _ENUM_VALUES(OrderStatus)
    _assert_optional_timestamp(data, "submitted_on", "DailyOrder")
    if data.get("delivered_lines") is not None:
        _assert_order_lines(data["delivered_lines"], "DailyOrder.delivered_lines")
    _assert_optional_int(data, "total_charge_cents", "DailyOrder")
    if data.get("verified_lines") is not None:
        _assert_order_lines(data["verified_lines"], "DailyOrder.verified_lines")
    assert isinstance(data["shortage_credit_cents"], int)
    assert data["shortage_credit_cents"] >= 0
    assert data["cancelled_reason"] is None or data["cancelled_reason"] in (
        _ENUM_VALUES(CancelledReason)
    )


def assert_stale_return_claim(data: dict):
    _assert_common_fields(data, "StaleReturnClaim")
    assert isinstance(data["distributor_id"], str) and len(data["distributor_id"]) > 0
    items = data["items"]
    assert isinstance(items, list) and len(items) > 0
    for item in items:
        assert isinstance(item["sku"], str) and len(item["sku"]) > 0
        assert isinstance(item["delivery_date"], str)
        assert isinstance(item["pulled_qty"], int) and item["pulled_qty"] >= 1
        assert isinstance(item["pull_date"], str)
    assert data["status"] in _ENUM_VALUES(ClaimStatus)
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["provisional_credit_cents"] >= 0
    _assert_optional_int(data, "approved_credit_cents", "StaleReturnClaim")
    _assert_optional_int(data, "issued_credit_cents", "StaleReturnClaim")
    _assert_optional_int(data, "cap_truncated_cents", "StaleReturnClaim")
    assert data["denial_reason"] is None or data["denial_reason"] in (
        _ENUM_VALUES(DenialReason)
    )


def assert_territory_transfer(data: dict):
    _assert_common_fields(data, "TerritoryTransfer")
    assert isinstance(data["agreement_id"], str) and len(data["agreement_id"]) > 0
    assert data["mode"] in _ENUM_VALUES(TransferMode)
    assert isinstance(data["gross_valuation_cents"], int)
    detail = data["valuation_detail"]
    assert isinstance(detail, dict)
    for key in ("depreciation_cents", "goodwill_cents", "penalty_cents"):
        assert isinstance(detail[key], int) and detail[key] >= 0
    _assert_optional_int(data, "financing_payoff_cents", "TerritoryTransfer")
    _assert_optional_int(data, "distributor_payout_cents", "TerritoryTransfer")
    assert data["status"] in _ENUM_VALUES(TransferStatus)
    _assert_optional_timestamp(data, "settled_on", "TerritoryTransfer")


def assert_settlement_statement(data: dict):
    """Shape and internal arithmetic of the weekly settlement (PRD §3.4)."""
    assert isinstance(data["week"], str) and len(data["week"]) > 0
    for field in (
        "gross_charges_cents",
        "stale_credits_issued_cents",
        "net_trade_cents",
        "stale_cap_cents",
        "stale_cap_used_cents",
        "trade_balance_cents",
        "ledger_view_cents",
        "document_view_cents",
    ):
        assert isinstance(data[field], int), f"settlement: {field} must be int"
    assert data["net_trade_cents"] == (
        data["gross_charges_cents"] - data["stale_credits_issued_cents"]
    ), "net_trade_cents must equal gross charges minus issued stale credits"
    assert data["ledger_view_cents"] == data["trade_balance_cents"], (
        "ledger_view_cents is the running trade_balance_cents"
    )
    assert isinstance(data["reconciles"], bool)
    assert data["reconciles"] == (
        data["ledger_view_cents"] == data["document_view_cents"]
    ), "reconciles must be true exactly when ledger and document views agree"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_distributor_standing_invariants(data: dict):
    """Account-standing derivation visible from the distributor payload alone
    (PRD §2.9): balance above 80% of the credit limit forces PROBATION, and
    PROBATION is only reachable through that balance rule."""
    balance = data["trade_balance_cents"]
    limit = data["credit_limit_cents"]
    standing = data["account_standing"]
    if balance > 0.80 * limit:
        assert standing == AccountStanding.PROBATION.value, (
            f"balance {balance} exceeds 80% of limit {limit}; standing must be "
            f"PROBATION, got {standing}"
        )
    if standing == AccountStanding.PROBATION.value:
        assert balance > 0.80 * limit, (
            "PROBATION requires the trade balance to exceed 80% of the credit limit"
        )


def assert_production_day_invariants(data: dict):
    """Capacity conservation on a production day (PRD §3.3)."""
    assert 0 <= data["allocated_units"] <= data["capacity_units"], (
        f"allocated_units {data['allocated_units']} must stay within "
        f"capacity_units {data['capacity_units']}"
    )


def assert_transfer_invariants(data: dict):
    """Settled transfers conserve cents (PRD §3.8):
    gross_valuation == financing_payoff + distributor_payout."""
    if data["status"] == TransferStatus.SETTLED.value:
        assert data["financing_payoff_cents"] is not None
        assert data["distributor_payout_cents"] is not None
        assert data["gross_valuation_cents"] == (
            data["financing_payoff_cents"] + data["distributor_payout_cents"]
        ), (
            "gross_valuation_cents must equal financing_payoff_cents + "
            "distributor_payout_cents after settlement"
        )
