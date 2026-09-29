"""Entity assertions and domain invariant checkers.

Assertions here only demand what the PRD says the API returns. The two
immutable catalog records — brewer models and catalog products — carry only
`id` and `created_at`, so their checkers never demand `updated_at` or
`version`.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_common_fields(data: dict) -> None:
    """id + created_at + updated_at + version, for the eleven mutable resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data.get('version')}"


def assert_catalog_fields(data: dict) -> None:
    """id + created_at only — the immutable catalog records."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"


def assert_account(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 0 < len(data["legal_name"]) <= 200
    assert data["billing_mode"] in ("CONSOLIDATED", "PER_SITE")
    assert isinstance(data["green_index_baseline_micros"], int)
    assert data["green_index_baseline_micros"] >= 1
    assert data["program_posture"] in (
        "ONBOARDING",
        "ACTIVE",
        "AT_RISK",
        "CANCELLATION_PENDING",
        "CLOSED",
    )
    assert isinstance(data["green_price_factor_bps"], int)
    assert isinstance(data["receivable_balance_cents"], int)
    assert isinstance(data["escalated_site_count"], int)
    assert isinstance(data["allied_attachment_bps"], int)


def assert_site(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["route_id"])
    assert isinstance(data["site_name"], str) and 0 < len(data["site_name"]) <= 200
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["days_per_week"], int) and 1 <= data["days_per_week"] <= 7
    assert data["consumption_model"] in ("HEADCOUNT_MODEL", "TRAILING_USAGE")
    assert 1 <= data["service_minutes_estimate"] <= 480
    assert data["service_posture"] in ("ACTIVE", "ESCALATED", "SUSPENDED", "CLOSED")
    assert isinstance(data["escalation_score"], (int, float))
    assert isinstance(data["forecast_cups_per_week"], int)
    assert isinstance(data["required_peak_cups_per_hour"], int)
    assert isinstance(data["consecutive_shortfall_visit_count"], int)


def assert_route(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 100
    assert data["service_day"] in ("MON", "TUE", "WED", "THU", "FRI")
    assert 1 <= data["capacity_minutes"] <= 960
    assert 0 <= data["travel_buffer_minutes"] <= 120
    assert isinstance(data["booked_minutes_total"], int)
    assert data["booked_minutes_total"] >= 0


def assert_equipment_model(data: dict) -> None:
    assert_catalog_fields(data)
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert data["brewer_class"] in ("AIRPOT", "THERMAL", "SINGLE_CUP", "ESPRESSO")
    assert data["cups_per_hour_capacity"] >= 1
    assert data["min_headcount"] >= 1
    assert data["max_headcount"] >= data["min_headcount"]
    assert data["monthly_rent_cents"] >= 0
    assert data["descale_interval_days"] >= 1
    assert data["list_value_cents"] >= 0
    assert "version" not in data, "a brewer model exposes no version"
    assert "updated_at" not in data, "a brewer model exposes no updated_at"


def assert_product_item(data: dict) -> None:
    assert_catalog_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("COFFEE", "CREAMER", "TEA", "WATER", "PANTRY")
    assert isinstance(data["base_unit_price_micros"], int)
    assert data["base_unit_price_micros"] >= 1
    assert data["pack_units"] >= 1
    assert isinstance(data["green_coffee_linked"], bool)
    assert "version" not in data, "a catalog product exposes no version"
    assert "updated_at" not in data, "a catalog product exposes no updated_at"


def assert_equipment_asset(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["model_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["asset_role"] in ("PLACEMENT", "LOANER")
    assert data["asset_status"] in (
        "IN_STOCK",
        "PLACED",
        "ON_LOAN",
        "RECONDITIONING",
        "UNRETURNED",
        "RETIRED",
    )
    assert is_iso8601_timestamp(data["last_descale_at"])


def assert_par_level(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["source"] in ("FORECAST", "MANUAL")
    assert data["par_units"] >= 0
    assert 0 <= data["reorder_point_units"]
    assert data["stock_status"] in ("STOCKOUT", "LOW", "IN_STOCK")
    assert is_iso8601_timestamp(data["last_service_at"])
    assert_par_unit_invariant(data)


def assert_par_unit_invariant(data: dict) -> None:
    """on_hand_units always equals cumulative delivered less cumulative consumed."""
    expected = data["cumulative_delivered_units"] - data["cumulative_consumed_units"]
    assert data["on_hand_units"] == expected, (
        f"on_hand_units {data['on_hand_units']} must equal "
        f"cumulative_delivered_units {data['cumulative_delivered_units']} minus "
        f"cumulative_consumed_units {data['cumulative_consumed_units']}"
    )
    assert_stock_status_derived(data)


def assert_stock_status_derived(data: dict) -> None:
    """stock_status is derived from on_hand_units against reorder_point_units."""
    on_hand = data["on_hand_units"]
    reorder = data["reorder_point_units"]
    if on_hand == 0:
        expected = "STOCKOUT"
    elif on_hand <= reorder:
        expected = "LOW"
    else:
        expected = "IN_STOCK"
    assert data["stock_status"] == expected, (
        f"stock_status {data['stock_status']} should be {expected} for "
        f"on_hand_units {on_hand} against reorder_point_units {reorder}"
    )


def assert_placement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["asset_id"])
    assert data["terms_type"] in ("LOAN", "RENTAL")
    assert data["minimum_purchase_cents"] >= 0
    assert 1 <= data["min_term_months"] <= 60
    assert is_iso8601_timestamp(data["placed_at"])
    assert data["placement_status"] in (
        "ACTIVE",
        "RETRIEVAL_SCHEDULED",
        "RETRIEVED",
        "UNRETURNED_BILLED",
        "SUPERSEDED",
    )
    assert data["compliance_status"] in (
        "MEETING_MINIMUM",
        "SHORTFALL_WARNED",
        "SHORTFALL_BILLED",
    )
    for key in (
        "trailing_purchase_cents",
        "shortfall_fee_cents",
        "rent_charge_cents",
        "unreturned_billed_cents",
    ):
        assert isinstance(data[key], int), f"{key} must be an integer number of cents"


def assert_service_visit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["route_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert 1 <= data["planned_minutes"] <= 480
    assert data["visit_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "VOIDED")
    assert isinstance(data["lines"], list)
    assert isinstance(data["shortfall_flag"], bool)


def assert_work_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["asset_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["wo_type"] in ("PREVENTIVE", "DESCALE", "REPAIR")
    assert data["wo_status"] in ("OPEN", "IN_PROGRESS", "AWAITING_PARTS", "RESOLVED")
    assert data["loaner_status"] in (
        "NONE",
        "OUT",
        "RETURNED",
        "OVERDUE",
        "WRITTEN_OFF",
    )
    assert isinstance(data["awaiting_parts_cycles"], int)
    assert 0 <= data["awaiting_parts_cycles"] <= 3


def assert_invoice(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["invoice_status"] in (
        "DRAFT",
        "ISSUED",
        "PARTIALLY_CREDITED",
        "FULLY_CREDITED",
        "VOID",
    )
    for key in (
        "pre_freight_total_cents",
        "allied_discount_bps",
        "allied_discount_cents",
        "freight_cents",
        "total_cents",
        "line_count",
    ):
        assert isinstance(data[key], int), f"{key} must be an integer"


def assert_invoice_line(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["invoice_id"])
    assert data["line_type"] in (
        "PRODUCT",
        "RENT",
        "SHORTFALL",
        "UNRETURNED_ASSET",
        "ALLIED_DISCOUNT",
        "FREIGHT",
        "CREDIT",
    )
    assert isinstance(data["qty_units"], int)
    assert isinstance(data["unit_price_micros"], int)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["credits_applied_cents"], int)
    if data["line_type"] != "PRODUCT":
        assert data["product_id"] is None, "product_id is null on non-PRODUCT lines"
        assert data["qty_units"] == 0, "qty_units is 0 on non-PRODUCT lines"
        assert data["unit_price_micros"] == 0, (
            "unit_price_micros is 0 on non-PRODUCT lines"
        )
    if data["line_type"] != "CREDIT":
        assert data["target_line_id"] is None, "target_line_id is null off CREDIT lines"
        assert data["credit_reason"] is None, "credit_reason is null off CREDIT lines"


def assert_price_adjustment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["index_baseline_micros"], int)
    assert isinstance(data["index_current_micros"], int)
    assert isinstance(data["movement_bps"], int)
    assert isinstance(data["adjustment_pct_bps"], int)
    assert -1500 <= data["adjustment_pct_bps"] <= 1500, (
        "adjustment_pct_bps is clamped to the closed range -1500 to 1500"
    )
    assert data["adj_status"] in ("PROPOSED", "ACCEPTED", "DISPUTED", "DEFERRED")
    assert isinstance(data["revision_count"], int)


# --- Cross-entity invariant helpers ------------------------------------------


def assert_product_line_amount(line: dict) -> None:
    """A PRODUCT line's amount is its quantity times unit price over 10000,
    rounded half up, computed individually for that line."""
    from decimal import ROUND_HALF_UP, Decimal

    expected = int(
        (Decimal(line["qty_units"]) * Decimal(line["unit_price_micros"]) / Decimal(10000))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    assert line["amount_cents"] == expected, (
        f"PRODUCT line amount_cents {line['amount_cents']} should be {expected} for "
        f"{line['qty_units']} units at {line['unit_price_micros']} micro-dollars"
    )


def assert_invoice_total(invoice: dict) -> None:
    """total_cents is pre_freight_total_cents less allied_discount_cents plus freight."""
    expected = (
        invoice["pre_freight_total_cents"]
        - invoice["allied_discount_cents"]
        + invoice["freight_cents"]
    )
    assert invoice["total_cents"] == expected, (
        f"total_cents {invoice['total_cents']} should be {expected}"
    )


def assert_escalation_score(
    site: dict, stockouts: int, below_reorder: int, overdue_descales: int, missed_visits: int
) -> None:
    """The raw score is 20.0 per stockout, 7.5 per below-reorder line,
    15.0 per overdue descale and 10.0 per missed visit, capped at 100.0."""
    raw = (
        stockouts * 20.0
        + below_reorder * 7.5
        + overdue_descales * 15.0
        + missed_visits * 10.0
    )
    expected = min(100.0, raw)
    assert float(site["escalation_score"]) == expected, (
        f"escalation_score {site['escalation_score']} should be {expected}"
    )
