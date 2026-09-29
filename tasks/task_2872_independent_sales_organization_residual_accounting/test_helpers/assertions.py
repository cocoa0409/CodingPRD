"""Entity assertions and domain invariant checkers for the residual ledger."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict) -> None:
    """Every entity but the chargeback event carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_processor_program(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["buy_rate_bps"], int) and 0 <= data["buy_rate_bps"] <= 500
    assert isinstance(data["buy_rate_per_item_cents"], int)
    assert data["buy_rate_per_item_cents"] >= 0
    assert isinstance(data["assessment_bps"], int) and 0 <= data["assessment_bps"] <= 100
    assert data["normalization_mode"] in ("NET_REVENUE_SPLIT", "GROSS_SPLIT")
    assert data["minimum_billing_mode"] in ("SHORTFALL_BILLED", "NO_MINIMUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["posted_batch_count"], int) and data["posted_batch_count"] >= 0


def assert_agent(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["parent_agent_id"] is None or is_valid_uuid(data["parent_agent_id"])
    assert 0.0 <= float(data["split_pct"]) <= 1.0
    assert 0.0 <= float(data["override_pct"]) <= 1.0
    assert isinstance(data["vesting_start_date"], str) and len(data["vesting_start_date"]) == 10
    assert data["status"] in ("ACTIVE", "DEPARTURE_NOTICE", "DEPARTED")
    assert isinstance(data["hierarchy_depth"], int) and 0 <= data["hierarchy_depth"] <= 4
    assert isinstance(data["vested_pct"], int) and 0 <= data["vested_pct"] <= 100
    assert data["vested_pct_at_departure"] is None or (
        isinstance(data["vested_pct_at_departure"], int)
        and 0 <= data["vested_pct_at_departure"] <= 100
    )
    assert isinstance(data["residual_hold"], bool)
    assert isinstance(data["portfolio_attrition_bps"], int)
    assert 0 <= data["portfolio_attrition_bps"] <= 10000
    for money in (
        "lifetime_clawback_cents",
        "trailing_residual_cents",
        "advance_outstanding_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer count of cents"
    assert isinstance(data["portfolio_merchant_count"], int)
    assert data["portfolio_merchant_count"] >= 0


def assert_agent_portfolio_summary(data: dict) -> None:
    """The computed snapshot reports exactly the ten declared fields."""
    for field in (
        "agent_id",
        "portfolio_merchant_count",
        "active_merchant_count",
        "attrited_merchant_count",
        "portfolio_attrition_bps",
        "residual_hold",
        "vested_pct",
        "trailing_residual_cents",
        "advance_outstanding_cents",
        "lifetime_clawback_cents",
    ):
        assert field in data, f"portfolio summary must report {field}"
    assert is_valid_uuid(data["agent_id"])
    assert isinstance(data["residual_hold"], bool)
    for field in (
        "portfolio_merchant_count",
        "active_merchant_count",
        "attrited_merchant_count",
        "portfolio_attrition_bps",
        "vested_pct",
        "trailing_residual_cents",
        "advance_outstanding_cents",
        "lifetime_clawback_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_merchant(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["owning_agent_id"])
    assert is_valid_uuid(data["processor_program_id"])
    assert isinstance(data["mid"], str) and 4 <= len(data["mid"]) <= 32
    for money in (
        "monthly_minimum_cents",
        "per_transaction_fee_cents",
        "equipment_lease_monthly_cents",
        "upfront_bonus_cents",
        "clawed_back_bonus_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"{money} must be a non-negative integer count of cents"
        )
    assert isinstance(data["boarded_on"], str) and len(data["boarded_on"]) == 10
    assert data["status"] in ("PENDING", "ACTIVE", "ATTRITED")
    assert data["attrition_date"] is None or len(data["attrition_date"]) == 10
    assert data["reactivation_date"] is None or len(data["reactivation_date"]) == 10


def assert_residual_batch(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["processor_program_id"])
    assert_period_month(data["period_month"])
    assert len(data["coverage_start"]) == 10 and len(data["coverage_end"]) == 10
    assert isinstance(data["file_checksum"], str) and 8 <= len(data["file_checksum"]) <= 80
    assert data["state"] in ("RECEIVED", "NORMALIZED", "POSTED", "REVERSED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    for money in (
        "gross_volume_cents",
        "total_normalized_net_revenue_cents",
        "iso_retained_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer count of cents"
    assert data["posted_at"] is None or is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["recall_count"], int) and data["recall_count"] >= 0


def assert_residual_line(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["residual_batch_id"])
    assert is_valid_uuid(data["merchant_id"])
    for money in (
        "transaction_count",
        "sales_volume_cents",
        "interchange_cents",
        "assessments_cents",
        "gross_income_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"{money} must be a non-negative integer"
        )
    assert isinstance(data["processor_cost_cents"], int)
    assert isinstance(data["normalized_net_revenue_cents"], int)
    assert data["normalization_mode_applied"] in (
        None,
        "NET_REVENUE_SPLIT",
        "GROSS_SPLIT",
    )


def assert_chargeback_event(data: dict) -> None:
    """A chargeback event carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a chargeback event must not carry updated_at"
    assert "version" not in data, "a chargeback event must not carry version"
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert len(data["occurred_on"]) == 10
    assert_period_month(data["period_month"])
    assert data["liability"] in ("AGENT_CHARGED", "ISO_ABSORBED")


def assert_merchant_profitability(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["residual_batch_id"])
    assert_period_month(data["period_month"])
    for money in (
        "normalized_net_revenue_cents",
        "chargeback_cost_cents",
        "agent_chargeable_chargeback_cents",
        "equipment_cost_cents",
        "profit_cents",
        "agent_basis_cents",
        "allocated_total_cents",
        "iso_retained_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer count of cents"
    assert data["chargeback_cost_cents"] >= data["agent_chargeable_chargeback_cents"], (
        "the both-liability chargeback total can never be smaller than the "
        "agent-charged subset"
    )


def assert_residual_allocation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["agent_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert_period_month(data["period_month"])
    assert data["allocation_type"] in ("DIRECT_SPLIT", "OVERRIDE")
    assert isinstance(data["tier_level"], int) and 0 <= data["tier_level"] <= 3
    assert 0.0 <= float(data["applied_pct"]) <= 1.0
    for money in ("basis_cents", "gross_allocation_cents", "vesting_withheld_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer count of cents"


def assert_agent_statement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["agent_id"])
    assert_period_month(data["period_month"])
    assert data["lifecycle_state"] in ("DRAFT", "ISSUED", "FINALIZED")
    assert data["settlement_state"] in ("UNSETTLED", "HELD", "SETTLED")
    for money in (
        "direct_residual_cents",
        "override_residual_cents",
        "minimum_true_up_cents",
        "gross_after_trueup_cents",
        "advance_recoupment_cents",
        "adjustment_cents",
        "opening_deficit_cents",
        "net_payable_cents",
        "carry_forward_deficit_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer count of cents"
    assert data["net_payable_cents"] >= 0, "net_payable_cents is floored at zero"
    assert data["carry_forward_deficit_cents"] >= 0
    assert data["issued_at"] is None or is_iso8601_timestamp(data["issued_at"])
    assert data["paid_on"] is None or len(data["paid_on"]) == 10


def assert_statement_adjustment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["statement_id"])
    assert data["source_merchant_id"] is None or is_valid_uuid(data["source_merchant_id"])
    assert data["kind"] in (
        "DISPUTE_CREDIT",
        "MANUAL_DEBIT",
        "BONUS_CLAWBACK",
        "CLAWBACK_REVERSAL",
        "VESTED_BUYOUT",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert isinstance(data["reason"], str) and 1 <= len(data["reason"]) <= 300
    assert data["state"] in (
        "PROPOSED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPLIED",
        "REJECTED",
    )
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert_adjustment_sign(data["kind"], data["amount_cents"])


def assert_agent_advance(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["agent_id"])
    assert data["advance_type"] in ("CASH_ADVANCE", "PORTFOLIO_BUYOUT")
    assert data["recoupment_mode"] in (
        "PERCENT_OF_RESIDUAL",
        "STRAIGHT_LINE_AMORTIZATION",
    )
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert data["recoupment_pct"] is None or 0.0 < float(data["recoupment_pct"]) <= 1.0
    assert data["amortization_months"] is None or 1 <= data["amortization_months"] <= 60
    assert_period_month(data["first_recoupment_month"])
    assert_period_month(data["last_recoupment_month"])
    assert len(data["funded_on"]) == 10
    for money in ("outstanding_cents", "cumulative_recouped_cents"):
        assert isinstance(data[money], int) and data[money] >= 0
    assert isinstance(data["months_recouped"], int) and data["months_recouped"] >= 0
    assert data["state"] in ("ACTIVE", "RECOUPED")
    assert_advance_principal_conserved(data)


def assert_period_month(value: str) -> None:
    assert isinstance(value, str) and len(value) == 7 and value[4] == "-", (
        f"an accounting month must be YYYY-MM, got {value!r}"
    )
    year, month = value.split("-")
    assert year.isdigit() and len(year) == 4
    assert month.isdigit() and 1 <= int(month) <= 12


def assert_adjustment_sign(kind: str, amount_cents: int) -> None:
    """Sign discipline: never zero, positive or negative according to the kind."""
    assert amount_cents != 0, "an adjustment amount may never be zero"
    if kind in ("DISPUTE_CREDIT", "CLAWBACK_REVERSAL", "VESTED_BUYOUT"):
        assert amount_cents > 0, f"{kind} must carry a strictly positive amount_cents"
    if kind in ("MANUAL_DEBIT", "BONUS_CLAWBACK"):
        assert amount_cents < 0, f"{kind} must carry a strictly negative amount_cents"


def assert_advance_principal_conserved(advance: dict) -> None:
    """principal_cents always equals outstanding_cents + cumulative_recouped_cents."""
    assert (
        advance["principal_cents"]
        == advance["outstanding_cents"] + advance["cumulative_recouped_cents"]
    ), (
        "advance principal is conserved: expected "
        f"{advance['principal_cents']} == {advance['outstanding_cents']} + "
        f"{advance['cumulative_recouped_cents']}"
    )


def assert_statement_money_lines_consistent(statement: dict) -> None:
    """gross_after_trueup and the pre-floor balance follow the pinned order."""
    expected_gross = (
        statement["direct_residual_cents"]
        + statement["override_residual_cents"]
        + statement["minimum_true_up_cents"]
    )
    assert statement["gross_after_trueup_cents"] == expected_gross, (
        "gross_after_trueup_cents must be direct + override + minimum true-up, "
        f"expected {expected_gross}, got {statement['gross_after_trueup_cents']}"
    )
    pre_floor = (
        statement["gross_after_trueup_cents"]
        - statement["advance_recoupment_cents"]
        + statement["adjustment_cents"]
        - statement["opening_deficit_cents"]
    )
    if pre_floor >= 0:
        assert statement["net_payable_cents"] == pre_floor
        assert statement["carry_forward_deficit_cents"] == 0
    else:
        assert statement["net_payable_cents"] == 0
        assert statement["carry_forward_deficit_cents"] == abs(pre_floor)


def assert_profitability_bottom_lines(row: dict) -> None:
    """The two divergent bottom lines follow their stated definitions."""
    expected_profit = (
        row["normalized_net_revenue_cents"]
        - row["chargeback_cost_cents"]
        - row["equipment_cost_cents"]
    )
    assert row["profit_cents"] == expected_profit, (
        f"profit_cents expected {expected_profit}, got {row['profit_cents']}"
    )
    expected_basis = (
        row["normalized_net_revenue_cents"]
        - row["agent_chargeable_chargeback_cents"]
        - row["equipment_cost_cents"]
    )
    assert row["agent_basis_cents"] == expected_basis, (
        f"agent_basis_cents expected {expected_basis}, got {row['agent_basis_cents']}"
    )
    assert row["iso_retained_cents"] == row["agent_basis_cents"] - row["allocated_total_cents"], (
        "iso_retained_cents must be agent_basis_cents minus allocated_total_cents"
    )


def find_statement(statements: list, agent_id: str, period_month: str) -> Optional[dict]:
    """The (agent_id, period_month) pair is unique, so at most one row matches."""
    for row in statements:
        if row["agent_id"] == agent_id and row["period_month"] == period_month:
            return row
    return None
