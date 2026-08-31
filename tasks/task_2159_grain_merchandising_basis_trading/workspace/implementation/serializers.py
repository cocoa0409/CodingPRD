"""Entity representations. Common fields per PRD 2.4."""
from store import fmt_ts, num


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_ts(row["created_at"])
    out["updated_at"] = fmt_ts(row["updated_at"])
    out["version"] = row["version"]
    return out


def desk_out(row):
    return _common(row, {
        "desk_code": row["desk_code"],
        "name": row["name"],
        "credit_line_usd": num(row["credit_line_usd"]),
        "margin_requirement_usd": num(row["margin_requirement_usd"]),
        "open_margin_call_usd": num(row["open_margin_call_usd"]),
        "credit_utilization": num(row["credit_utilization"]),
        "available_credit_usd": num(row["available_credit_usd"]),
        "posture": row["posture"],
        "committed_hedge_lots": row["committed_hedge_lots"],
        "open_bushel_commitment": num(row["open_bushel_commitment"]),
        "unpriced_bushels": num(row["unpriced_bushels"]),
        "realized_hedge_pnl_usd": num(row["realized_hedge_pnl_usd"]),
    })


def location_out(row):
    return _common(row, {
        "desk_id": row["desk_id"],
        "location_code": row["location_code"],
        "name": row["name"],
        "intake_capacity_bushels": row["intake_capacity_bushels"],
        "rail_served": row["rail_served"],
        "committed_intake_bushels": num(row["committed_intake_bushels"]),
    })


def schedule_out(row):
    return _common(row, {
        "commodity_code": row["commodity_code"],
        "effective_from": fmt_ts(row["effective_from"]),
        "moisture_standard_pct": num(row["moisture_standard_pct"]),
        "shrink_factor_pct_per_point": num(row["shrink_factor_pct_per_point"]),
        "tiers": [{
            "factor": t["factor"],
            "direction": t["direction"],
            "threshold_value": num(t["threshold_value"]),
            "unit_step": num(t["unit_step"]),
            "rate_cents_per_bushel_per_step": num(t["rate_cents_per_bushel_per_step"]),
        } for t in row["tiers"]],
        "status": row["status"],
    })


def risk_limit_out(row):
    return _common(row, {
        "desk_id": row["desk_id"],
        "commodity_code": row["commodity_code"],
        "max_unpriced_bushels": row["max_unpriced_bushels"],
        "max_net_short_lots": row["max_net_short_lots"],
        "status": row["status"],
    })


def fleet_out(row):
    return _common(row, {
        "home_location_id": row["home_location_id"],
        "fleet_code": row["fleet_code"],
        "car_count": row["car_count"],
    })


def bid_out(row):
    return _common(row, {
        "location_id": row["location_id"],
        "commodity_code": row["commodity_code"],
        "futures_month": row["futures_month"],
        "delivery_period_start": row["delivery_period_start"],
        "delivery_period_end": row["delivery_period_end"],
        "basis_cents": num(row["basis_cents"]),
        "max_bushels": row["max_bushels"],
        "expires_at": fmt_ts(row["expires_at"]),
        "contracted_bushels": num(row["contracted_bushels"]),
        "status": row["status"],
    })


def position_out(row):
    return _common(row, {
        "desk_id": row["desk_id"],
        "commodity_code": row["commodity_code"],
        "futures_month": row["futures_month"],
        "side": row["side"],
        "lots_open": row["lots_open"],
        "avg_entry_price_cents": num(row["avg_entry_price_cents"]),
        "lots_committed": row["lots_committed"],
        "lots_available": row["lots_available"],
        "posted_margin_usd": num(row["posted_margin_usd"]),
        "last_settlement_price_cents": num(row["last_settlement_price_cents"]),
        "unrealized_pnl_usd": num(row["unrealized_pnl_usd"]),
        "realized_pnl_usd": num(row["realized_pnl_usd"]),
        "status": row["status"],
    })


def contract_out(row):
    return _common(row, {
        "bid_id": row["bid_id"],
        "desk_id": row["desk_id"],
        "location_id": row["location_id"],
        "hedge_position_id": row["hedge_position_id"],
        "rolled_from_contract_id": row["rolled_from_contract_id"],
        "contract_type": row["contract_type"],
        "commodity_code": row["commodity_code"],
        "futures_month": row["futures_month"],
        "seller_name": row["seller_name"],
        "bushels": num(row["bushels"]),
        "delivery_start": row["delivery_start"],
        "delivery_end": row["delivery_end"],
        "settlement_basis": row["settlement_basis"],
        "futures_price_cents": num(row["futures_price_cents"]),
        "basis_cents": num(row["basis_cents"]),
        "roll_adjustment_cents": num(row["roll_adjustment_cents"]),
        "gross_unit_price_cents": num(row["gross_unit_price_cents"]),
        "priced_futures_bushels": num(row["priced_futures_bushels"]),
        "priced_basis_bushels": num(row["priced_basis_bushels"]),
        "unpriced_bushels": num(row["unpriced_bushels"]),
        "hedge_lots_assigned": row["hedge_lots_assigned"],
        "delivered_bushels": num(row["delivered_bushels"]),
        "settled_value_usd": num(row["settled_value_usd"]),
        "damages_usd": num(row["damages_usd"]),
        "termination_reason": row["termination_reason"],
        "created_by_user_id": row["created_by_user_id"],
        "pricing_locked": row["pricing_locked"],
        "pricing_status": row["pricing_status"],
        "delivery_status": row["delivery_status"],
        "status": row["status"],
    })


def pricing_order_out(row):
    # Immutable event row: id and created_at only — no updated_at, no version.
    return {
        "id": row["id"],
        "created_at": fmt_ts(row["created_at"]),
        "contract_id": row["contract_id"],
        "component": row["component"],
        "bushels": num(row["bushels"]),
        "price_cents": num(row["price_cents"]),
        "placed_by_user_id": row["placed_by_user_id"],
    }


def margin_call_out(row):
    return _common(row, {
        "hedge_position_id": row["hedge_position_id"],
        "call_amount_usd": num(row["call_amount_usd"]),
        "issued_at": fmt_ts(row["issued_at"]),
        "cure_deadline_at": fmt_ts(row["cure_deadline_at"]),
        "cured_amount_usd": num(row["cured_amount_usd"]),
        "status": row["status"],
    })


def ticket_out(row):
    return _common(row, {
        "contract_id": row["contract_id"],
        "location_id": row["location_id"],
        "freight_booking_id": row["freight_booking_id"],
        "discount_schedule_id": row["discount_schedule_id"],
        "gross_bushels": num(row["gross_bushels"]),
        "moisture_pct": num(row["moisture_pct"]),
        "test_weight_lbs": num(row["test_weight_lbs"]),
        "foreign_material_pct": num(row["foreign_material_pct"]),
        "damage_pct": num(row["damage_pct"]),
        "shrink_pct": num(row["shrink_pct"]),
        "net_bushels": num(row["net_bushels"]),
        "discount_total_usd": num(row["discount_total_usd"]),
        "gross_contract_value_usd": num(row["gross_contract_value_usd"]),
        "service_fee_cents_per_bushel": num(row["service_fee_cents_per_bushel"]),
        "net_unit_price_cents": num(row["net_unit_price_cents"]),
        "settlement_value_usd": num(row["settlement_value_usd"]),
        "disposition_reason": row["disposition_reason"],
        "graded_by_user_id": row["graded_by_user_id"],
        "status": row["status"],
    })


def booking_out(row):
    return _common(row, {
        "fleet_id": row["fleet_id"],
        "contract_id": row["contract_id"],
        "cars_requested": row["cars_requested"],
        "placement_at": fmt_ts(row["placement_at"]),
        "release_at": fmt_ts(row["release_at"]),
        "occupancy_end_at": fmt_ts(row["occupancy_end_at"]),
        "substitution_count": row["substitution_count"],
        "cancellation_reason": row["cancellation_reason"],
        "status": row["status"],
    })
