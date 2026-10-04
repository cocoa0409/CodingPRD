"""Response projections.

Each resource is rendered with exactly the fields the entity table declares
(SCAFFOLD section 1.1) plus the shared audit spine of PRD 2.4.  Internal
bookkeeping (allocation dates, per-line source stores, derived revisions) never
leaves the process.
"""

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "CommercialAccount": [
        "shop_name", "tax_id", "billing_address", "shipping_address", "home_store_id",
        "credit_limit_cents", "credit_terms_days", "tier", "delivery_service_level",
        "petty_cash_cents", "credit_exposure_cents", "deposit_liability_cents",
        "receivable_balance_cents", "account_posture", "next_cutoff_at",
        "order_sequence", "is_archived",
    ],
    "Vehicle": [
        "vin", "year", "make", "model", "engine_code", "drive_type",
    ],
    "Part": [
        "sku", "description", "line_code", "list_price_cents", "core_charge_cents",
        "is_hazardous", "is_returnable", "is_archived", "superseded_by_part_id",
        "supersession_depth", "catalog_state",
    ],
    "ToolFitment": [
        "tool_catalog_id", "part_id", "placement", "depth_index",
    ],
    "PartInterchange": [
        "part_id", "interchange_sku", "interchange_brand",
    ],
    "PartFitment": [
        "part_id", "year_from", "year_to", "make", "model", "engine_code", "drive_type",
    ],
    "Store": [
        "store_code", "name", "store_type", "hub_store_id", "delivery_radius_miles",
        "cutoff_hour_local", "cutoff_buffer_minutes", "promise_time_minutes",
        "daily_capacity_units", "committed_units_today", "capacity_epoch_at", "is_archived",
    ],
    "InventoryItem": [
        "store_id", "part_id", "on_hand_units", "reserved_units", "available_units",
    ],
    "SalesRep": [
        "email", "full_name", "district_code", "home_store_id", "active_account_count",
    ],
    "RepCoverage": [
        "rep_id", "account_id", "effective_from", "effective_to", "coverage_posture",
    ],
    "PartOrder": [
        "account_id", "vehicle_id", "line_items", "member_sequence", "service_route_id",
        "fulfillment_route", "reserved_unit_count", "pricing_band",
        "parts_subtotal_cents", "core_charge_total_cents", "tier_discount_cents",
        "refundable_deposit_cents", "delivery_fee_cents", "promised_at", "delivered_at",
        "delivered_payment_due_at", "refundable_deposit_consumed_cents",
        "order_base_cents", "satisfaction_cents", "shipping_address", "destination_id",
        "status",
    ],
    "ToolLoan": [
        "account_id", "tool_catalog_id", "loaned_order_id", "deposit_amount_cents",
        "deposit_state", "loaned_at", "due_at", "returned_at", "overdue_days",
        "return_condition", "deposit_forfeited_cents", "replacement_part_id",
        "wear_intensity", "damage_multiplier", "forfeiture_rate", "status",
    ],
    "ToolCatalog": [
        "tool_sku", "tool_name", "deposit_amount_cents", "replacement_part_id",
        "replacement_unit_cost_cents", "wear_accumulated", "wear_band",
        "wear_multiplier_rate", "wear_forfeiture_rate", "wear_grace_period_hours",
    ],
    "CoreReturn": [
        "order_id", "account_id", "line_items", "core_subtotal_cents",
        "restocking_fee_cents", "warranty_covered", "credit_amount_cents", "status",
    ],
    "WarrantyRegistration": [
        "account_id", "part_id", "purchase_order_id", "purchased_at",
        "warranty_expires_at", "claim_reference",
    ],
    "RouteStop": [
        "route_id", "stop_sequence", "account_id", "order_ids", "delivery_window_start",
        "delivery_window_end", "travel_minutes_from_previous", "drop_minutes",
        "projected_arrival_at", "projected_departure_at", "lateness_minutes",
        "stop_kind", "delivered_at", "status",
    ],
    "ServiceRoute": [
        "route_code", "service_date", "driver_id", "driver_type", "departure_at",
        "shift_end_at", "return_at", "effective_departure_at", "total_miles",
        "run_credit_cents", "status",
    ],
}

# Entities that deliberately carry only `id` and `created_at` (PRD 2.4).
SLIM = ("ToolFitment", "PartInterchange", "PartFitment", "WarrantyRegistration")

LINE_FIELDS = ("part_id", "quantity", "unit_price_cents")


def _line(line):
    return {key: line.get(key) for key in LINE_FIELDS if key in line}


def render(kind, row, extra=None):
    if row is None:
        return None
    out = {}
    if kind not in SLIM:
        for key in COMMON:
            if key in row:
                out[key] = row[key]
    else:
        out["id"] = row.get("id")
        out["created_at"] = row.get("created_at")
    if kind == "Part":
        from services import common
        out["supersession_depth"] = common.supersession_depth(row["id"])
    for key in FIELDS.get(kind, []):
        if key == "supersession_depth":
            continue
        if key not in row:
            continue
        value = row.get(key)
        if key == "line_items" and isinstance(value, list):
            out[key] = [_line(entry) for entry in value]
        else:
            out[key] = value
    if kind == "InventoryItem":
        # PRD 3.2: "its `available_units` is read-only and always the larger of
        # zero and `on_hand_units` minus `reserved_units`" -- a derived reading
        # of the line, so it is recomputed on every render rather than stored.
        from services import common
        out["available_units"] = max(
            0, (row.get("on_hand_units") or 0) - (row.get("reserved_units") or 0))
    if extra:
        out.update(extra)
    return out


def render_all(kind, rows):
    return [render(kind, row) for row in rows]