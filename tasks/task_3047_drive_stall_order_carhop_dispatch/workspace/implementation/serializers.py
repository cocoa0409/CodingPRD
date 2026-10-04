"""Resource serializers — produce the exact field sets from the PRD."""


def _fmt(dt):
    if dt is None:
        return None
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + ".{:03d}Z".format(dt.microsecond // 1000)


def base(r):
    return {
        "id": r["id"],
        "created_at": _fmt(r["created_at"]),
        "updated_at": _fmt(r["updated_at"]),
        "version": r["version"],
    }


def location(r):
    out = base(r)
    out.update({
        "code": r["code"],
        "name": r["name"],
        "timezone": r["timezone"],
        "weather_mode": r["weather_mode"],
        "stall_capacity": r["stall_capacity"],
        "stalls_available": r["stalls_available"],
        "lane_posture": r["lane_posture"],
        "rush_index": r["rush_index"],
    })
    return out


def menu_item(r):
    out = base(r)
    out.update({
        "sku": r["sku"],
        "name": r["name"],
        "category": r["category"],
        "base_price_cents": r["base_price_cents"],
        "size_scheme": r["size_scheme"],
        "half_price_eligible": r["half_price_eligible"],
        "status": r["status"],
    })
    return out


def customization_option(r):
    out = base(r)
    out.update({
        "code": r["code"],
        "applies_to_category": r["applies_to_category"],
        "price_cents": r["price_cents"],
        "is_size": r["is_size"],
        "size_upcharge_cents": r["size_upcharge_cents"],
        "status": r["status"],
    })
    return out


def customer(r):
    out = base(r)
    out.update({
        "email": r["email"],
        "display_name": r["display_name"],
        "app_user": r["app_user"],
        "stored_tip_default_pct": r["stored_tip_default_pct"],
        "wallet_credit_cents": r["wallet_credit_cents"],
    })
    return out


def stall(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "stall_number": r["stall_number"],
        "kind": r["kind"],
        "intercom_functional": r["intercom_functional"],
        "status": r["status"],
        "current_order_id": r["current_order_id"],
    })
    return out


def carhop(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "name": r["name"],
        "zone": r["zone"],
        "on_shift": r["on_shift"],
        "max_trays": r["max_trays"],
        "active_run_load": r["active_run_load"],
        "tips_outstanding_cents": r["tips_outstanding_cents"],
        "tips_settled_cents": r["tips_settled_cents"],
    })
    return out


def order(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "stall_id": r["stall_id"],
        "customer_id": r["customer_id"],
        "channel": r["channel"],
        "status": r["status"],
        "payment_status": r["payment_status"],
        "checked_in_at": _fmt(r["checked_in_at"]),
        "placed_at": _fmt(r["placed_at"]),
        "ready_at": _fmt(r["ready_at"]),
        "delivered_at": _fmt(r["delivered_at"]),
        "service_target_seconds": r["service_target_seconds"],
        "late_flag": r["late_flag"],
        "subtotal_cents": r["subtotal_cents"],
        "offer_discount_cents": r["offer_discount_cents"],
        "tax_cents": r["tax_cents"],
        "tip_cents": r["tip_cents"],
        "total_cents": r["total_cents"],
        "total_tendered_cents": r["total_tendered_cents"],
        "delivery_run_id": r["delivery_run_id"],
        "run_position": r["run_position"],
        "checked_in_rush_index": r.get("checked_in_rush_index"),
    })
    return out


def order_line(r):
    out = base(r)
    out.update({
        "order_id": r["order_id"],
        "menu_item_id": r["menu_item_id"],
        "quantity": r["quantity"],
        "size_option_code": r["size_option_code"],
        "addin_option_codes": list(r["addin_option_codes"]),
        "unit_price_cents": r["unit_price_cents"],
        "extended_price_cents": r["extended_price_cents"],
        "happy_hour_priced": r["happy_hour_priced"],
    })
    return out


def offer(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "code": r["code"],
        "kind": r["kind"],
        "discount_type": r["discount_type"],
        "discount_value": r["discount_value"],
        "window_start_local": r["window_start_local"],
        "window_end_local": r["window_end_local"],
        "app_only": r["app_only"],
        "status": r["status"],
    })
    return out


def delivery_run(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "carhop_id": r["carhop_id"],
        "status": r["status"],
        "order_count": r["order_count"],
        "staged_at": _fmt(r["staged_at"]),
        "out_at": _fmt(r["out_at"]),
        "route_note": r["route_note"],
    })
    return out


def tip_record(r):
    out = base(r)
    out.update({
        "order_id": r["order_id"],
        "carhop_id": r["carhop_id"],
        "tip_cents": r["tip_cents"],
        "status": r["status"],
        "adjusted_tip_cents": r["adjusted_tip_cents"],
    })
    return out


def equipment_fault(r):
    out = base(r)
    out.update({
        "stall_id": r["stall_id"],
        "reported_by_role": r["reported_by_role"],
        "kind": r["kind"],
        "note": r["note"],
        "status": r["status"],
    })
    return out


def service_target_profile(r):
    out = base(r)
    out.update({
        "location_id": r["location_id"],
        "channel": r["channel"],
        "weather_mode": r["weather_mode"],
        "target_seconds": r["target_seconds"],
        "status": r["status"],
    })
    return out
