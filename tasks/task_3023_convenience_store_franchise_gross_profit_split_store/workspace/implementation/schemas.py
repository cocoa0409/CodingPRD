"""Declared field order per entity (scaffold §1.1) and serializers."""

import serde

FIELD_ORDER = {
    "franchisees": [
        "id", "legal_name", "owner_name", "entity_type", "stated_net_worth_cents",
        "draw_outstanding_cents", "open_shrink_charge_cents",
        "audit_adjusted_net_worth_cents", "risk_band", "status",
        "created_at", "updated_at", "version",
    ],
    "stores": [
        "id", "franchisee_id", "store_number", "state_code", "format", "opened_on",
        "lease_owner", "equipment_owner", "monthly_rent_cents", "cold_chain_certified",
        "status", "transfer_status", "transfer_target_franchisee_id",
        "transfer_price_cents", "created_at", "updated_at", "version",
    ],
    "agreements": [
        "id", "franchisee_id", "store_id", "split_pct", "royalty_pct",
        "waste_share_pct", "shrink_responsibility_pct", "rebate_pass_pct",
        "minimum_net_worth_cents", "term_start", "term_end", "renewal_window_days",
        "performance_tier", "renewal_eligibility_score", "status",
        "created_at", "updated_at", "version",
    ],
    "settlements": [
        "id", "store_id", "franchisee_id", "period_start", "period_end",
        "trailing_avg_gross_profit_cents", "gross_sales_cents", "cost_of_goods_cents",
        "rebate_credit_cents", "gross_profit_cents", "provisional_gross_profit_cents",
        "eligible_split_pct", "provisional_split_cents", "franchisee_split_cents",
        "franchisor_share_cents", "shrink_charge_cents", "waste_charge_cents",
        "draw_recovery_cents", "net_settlement_cents", "provisional", "status",
        "dispute_reason", "created_at", "updated_at", "version",
    ],
    "revenue_lines": [
        "id", "settlement_id", "category", "gross_sales_cents", "cost_of_goods_cents",
        "line_gross_profit_cents", "created_at", "updated_at", "version",
    ],
    "draws": [
        "id", "franchisee_id", "store_id", "amount_cents", "drawn_on",
        "recovered_cents", "status", "created_at", "updated_at", "version",
    ],
    "rebates": [
        "id", "store_id", "vendor_name", "vendor_code", "recommended_vendor",
        "rebate_cents", "period_start", "period_end", "flowthrough_cents", "status",
        "created_at", "updated_at", "version",
    ],
    "shrink_audits": [
        "id", "store_id", "period_start", "period_end", "book_inventory_cents",
        "physical_inventory_cents", "shrink_cents", "shrink_charge_cents", "status",
        "created_at", "updated_at", "version",
    ],
    "delivery_windows": [
        "id", "store_id", "commissary_code", "day_of_week", "window_start",
        "window_end", "capacity_units", "reserved_units", "status",
        "created_at", "updated_at", "version",
    ],
    "fresh_orders": [
        "id", "store_id", "delivery_window_id", "sku_code", "ordered_units",
        "delivered_units", "waste_units", "unit_cost_cents", "line_waste_cents",
        "waste_share_cents", "status", "created_at", "updated_at", "version",
    ],
}


def dump(table, record):
    if record is None:
        return None
    return serde.serialize(record, FIELD_ORDER[table])


def dump_many(table, records):
    return [dump(table, record) for record in records]