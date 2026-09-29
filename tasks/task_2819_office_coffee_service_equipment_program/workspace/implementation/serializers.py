"""Entity representations.

Field lists are explicit per resource so no internal bookkeeping member ever leaks.
EquipmentModel and ProductItem are immutable catalog records and carry only `id`
and `created_at` (PRD 2.4); the other eleven carry created_at, updated_at, version.
"""
import datetime as _dt

from timeutil import fmt_instant

COMMON = ("created_at", "updated_at", "version")
CATALOG_COMMON = ("created_at",)

ACCOUNT_FIELDS = (
    "legal_name", "billing_mode", "program_posture", "green_index_baseline_micros",
    "green_price_factor_bps", "price_protection_days", "price_protection_until",
    "escalated_site_count", "receivable_balance_cents", "allied_attachment_bps",
    "cancel_reason", "retrieval_due_by", "cancelled_at",
)
SITE_FIELDS = (
    "account_id", "route_id", "site_name", "headcount", "days_per_week",
    "consumption_model", "brew_style", "service_minutes_estimate", "service_posture",
    "forecast_cups_per_week", "required_peak_cups_per_hour", "recommended_model_id",
    "consecutive_shortfall_visit_count", "escalation_score",
)
ROUTE_FIELDS = (
    "name", "service_day", "capacity_minutes", "travel_buffer_minutes",
    "booked_minutes_total",
)
MODEL_FIELDS = (
    "model_code", "brewer_class", "cups_per_hour_capacity", "min_headcount",
    "max_headcount", "monthly_rent_cents", "descale_interval_days", "list_value_cents",
)
ASSET_FIELDS = (
    "model_id", "serial_number", "asset_role", "asset_status", "last_descale_at",
    "reconditioning_until",
)
PLACEMENT_FIELDS = (
    "site_id", "asset_id", "terms_type", "minimum_purchase_cents", "min_term_months",
    "placement_status", "compliance_status", "trailing_purchase_cents",
    "shortfall_fee_cents", "rent_charge_cents", "placed_at", "retrieval_due_by",
    "unreturned_billed_cents",
)
PRODUCT_FIELDS = ("sku", "category", "base_unit_price_micros", "pack_units",
                  "green_coffee_linked")
PAR_FIELDS = (
    "site_id", "product_id", "par_units", "reorder_point_units", "source",
    "on_hand_units", "cumulative_delivered_units", "cumulative_consumed_units",
    "last_service_at", "stock_status",
)
VISIT_FIELDS = (
    "site_id", "route_id", "window_start", "window_end", "planned_minutes",
    "visit_status", "lines", "shortfall_flag", "completed_at", "void_reason",
)
VISIT_LINE_FIELDS = (
    "product_id", "requested_units", "delivered_units", "consumed_units",
    "effective_unit_price_micros", "resulting_on_hand_units",
)
WORK_ORDER_FIELDS = (
    "asset_id", "site_id", "wo_type", "wo_status", "parts_eta",
    "awaiting_parts_cycles", "resolution_note", "loaner_asset_id", "loaner_out_date",
    "loaner_due_back_date", "loaner_returned_on", "loaner_status",
)
INVOICE_FIELDS = (
    "account_id", "site_id", "period_start", "period_end", "invoice_status",
    "allied_category_count", "allied_discount_bps", "pre_freight_total_cents",
    "allied_discount_cents", "freight_cents", "total_cents", "line_count", "issued_at",
)
INVOICE_LINE_FIELDS = (
    "invoice_id", "site_id", "target_line_id", "line_type", "product_id", "qty_units",
    "unit_price_micros", "amount_cents", "credits_applied_cents", "credit_reason",
)
ADJUSTMENT_FIELDS = (
    "account_id", "index_baseline_micros", "index_current_micros", "movement_bps",
    "adjustment_pct_bps", "adj_status", "dispute_reason", "revision_count",
    "effective_at", "accepted_at",
)


def _value(v):
    if isinstance(v, _dt.datetime):
        return fmt_instant(v)
    return v


def _render(row, fields, common=COMMON):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = _value(row.get(name))
    for name in common:
        out[name] = _value(row.get(name))
    return out


def account(row):
    return _render(row, ACCOUNT_FIELDS)


def site(row):
    out = _render(row, SITE_FIELDS)
    out["escalation_score"] = float(row.get("escalation_score") or 0.0)
    return out


def route(row):
    return _render(row, ROUTE_FIELDS)


def equipment_model(row):
    return _render(row, MODEL_FIELDS, CATALOG_COMMON)


def equipment_asset(row):
    return _render(row, ASSET_FIELDS)


def placement(row):
    return _render(row, PLACEMENT_FIELDS)


def product_item(row):
    return _render(row, PRODUCT_FIELDS, CATALOG_COMMON)


def par_level(row):
    return _render(row, PAR_FIELDS)


def visit_line(line):
    return {name: _value(line.get(name)) for name in VISIT_LINE_FIELDS}


def service_visit(row):
    out = _render(row, VISIT_FIELDS)
    out["lines"] = [visit_line(line) for line in row.get("lines") or []]
    return out


def work_order(row):
    return _render(row, WORK_ORDER_FIELDS)


def invoice(row):
    return _render(row, INVOICE_FIELDS)


def invoice_line(row):
    return _render(row, INVOICE_LINE_FIELDS)


def price_adjustment(row):
    return _render(row, ADJUSTMENT_FIELDS)
