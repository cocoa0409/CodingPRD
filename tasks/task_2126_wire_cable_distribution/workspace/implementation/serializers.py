"""Resource representations (SCAFFOLD 1.1).

Common fields are id / created_at / updated_at / version.  A published copper
index entry is an immutable market record: it carries only id and created_at.
"""
import calculations as calc


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if versioned:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def branch(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "region_code": rec["region_code"],
        "concurrent_cut_capacity": rec["concurrent_cut_capacity"],
        "delivery_surcharge_cents": rec["delivery_surcharge_cents"],
        "scrap_ft_ytd": calc.as_number(rec["scrap_ft_ytd"]),
    })
    return out


def customer(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "open_balance_cents": rec["open_balance_cents"],
        "deposit_liability_cents": rec["deposit_liability_cents"],
        "available_credit_cents": calc.available_credit_cents(rec),
        "credit_status": rec["credit_status"],
    })
    return out


def product(rec):
    out = _common(rec)
    out.update({
        "part_number": rec["part_number"],
        "conductor_metal": rec["conductor_metal"],
        "copper_lbs_per_1000ft": rec["copper_lbs_per_1000ft"],
        "base_price_cents_per_ft": rec["base_price_cents_per_ft"],
        "min_cut_length_ft": rec["min_cut_length_ft"],
        "cut_charge_cents": rec["cut_charge_cents"],
        "reel_deposit_cents": rec["reel_deposit_cents"],
        "master_reel_length_ft": rec["master_reel_length_ft"],
        "reel_weight_lbs": rec["reel_weight_lbs"],
        "allowed_put_ups": list(rec["allowed_put_ups"]),
    })
    return out


def copper_index_entry(rec):
    out = _common(rec, versioned=False)
    out.update({
        "effective_date": rec["effective_date"],
        "price_cents_per_lb": rec["price_cents_per_lb"],
        "published_by_user_id": rec["published_by_user_id"],
        "voided_quote_count": rec["voided_quote_count"],
    })
    return out


def truck(rec):
    out = _common(rec)
    out.update({
        "branch_id": rec["branch_id"],
        "truck_code": rec["truck_code"],
        "has_boom_lift": rec["has_boom_lift"],
        "max_reel_slots": rec["max_reel_slots"],
    })
    return out


def reel(rec):
    out = _common(rec)
    out.update({
        "product_id": rec["product_id"],
        "branch_id": rec["branch_id"],
        "parent_reel_id": rec["parent_reel_id"],
        "reel_type": rec["reel_type"],
        "lot_code": rec["lot_code"],
        "nominal_length_ft": calc.as_number(rec["nominal_length_ft"]),
        "current_length_ft": calc.as_number(rec["current_length_ft"]),
        "allocated_length_ft": calc.as_number(rec["allocated_length_ft"]),
        "available_length_ft": calc.reel_available_length(rec),
        "scrap_ft": calc.as_number(rec["scrap_ft"]),
        "status": rec["status"],
        "delivered_sales_order_id": rec["delivered_sales_order_id"],
        "delivered_at": rec["delivered_at"],
    })
    return out


def quote(rec):
    out = _common(rec)
    out.update({
        "customer_id": rec["customer_id"],
        "branch_id": rec["branch_id"],
        "copper_index_entry_id": rec["copper_index_entry_id"],
        "created_by_user_id": rec["created_by_user_id"],
        "issued_by_user_id": rec["issued_by_user_id"],
        "status": rec["status"],
        "issued_at": rec["issued_at"],
        "valid_until": rec["valid_until"],
        "void_reason": rec["void_reason"],
        "line_subtotal_cents": rec["line_subtotal_cents"],
        "physical_reel_count": rec["physical_reel_count"],
        "gross_freight_cents": rec["gross_freight_cents"],
        "rebate_pct": rec["rebate_pct"],
        "rebate_cents": rec["rebate_cents"],
        "freight_cents": rec["freight_cents"],
        "quoted_total_cents": rec["quoted_total_cents"],
        "deposit_quoted_cents": rec["deposit_quoted_cents"],
    })
    return out


def quote_line(rec):
    out = _common(rec)
    out.update({
        "quote_id": rec["quote_id"],
        "product_id": rec["product_id"],
        "line_number": rec["line_number"],
        "put_up": rec["put_up"],
        "requested_length_ft": calc.as_number(rec["requested_length_ft"]),
        "parallel_set_size": rec["parallel_set_size"],
        "billable_length_ft": calc.as_number(rec["billable_length_ft"]),
        "reel_count": rec["reel_count"],
        "copper_adder_cents_per_ft": rec["copper_adder_cents_per_ft"],
        "metal_cents": rec["metal_cents"],
        "base_cents": rec["base_cents"],
        "cut_charge_cents_total": rec["cut_charge_cents_total"],
        "deposit_cents_total": rec["deposit_cents_total"],
        "quoted_extended_cents": rec["quoted_extended_cents"],
    })
    return out


def sales_order(rec):
    out = _common(rec)
    out.update({
        "quote_id": rec["quote_id"],
        "customer_id": rec["customer_id"],
        "branch_id": rec["branch_id"],
        "fulfillment_status": rec["fulfillment_status"],
        "billing_status": rec["billing_status"],
        "allocation_policy": rec["allocation_policy"],
        "line_subtotal_cents": rec["line_subtotal_cents"],
        "freight_cents": rec["freight_cents"],
        "rebate_cents": rec["rebate_cents"],
        "quoted_total_cents": rec["quoted_total_cents"],
        "invoiced_total_cents": rec["invoiced_total_cents"],
        "metal_variance_cents": rec["metal_variance_cents"],
        "deposit_charged_cents": rec["deposit_charged_cents"],
        "deposit_credited_cents": rec["deposit_credited_cents"],
        "delivered_at": rec["delivered_at"],
    })
    return out


def order_line(rec):
    out = _common(rec)
    out.update({
        "sales_order_id": rec["sales_order_id"],
        "product_id": rec["product_id"],
        "line_number": rec["line_number"],
        "put_up": rec["put_up"],
        "requested_length_ft": calc.as_number(rec["requested_length_ft"]),
        "parallel_set_size": rec["parallel_set_size"],
        "billable_length_ft": calc.as_number(rec["billable_length_ft"]),
        "required_length_ft": calc.as_number(rec["required_length_ft"]),
        "allocated_length_ft": calc.as_number(rec["allocated_length_ft"]),
        "allocation_status": rec["allocation_status"],
        "lot_code": rec["lot_code"],
        "returnable": rec["returnable"],
        "quoted_extended_cents": rec["quoted_extended_cents"],
        "invoiced_extended_cents": rec["invoiced_extended_cents"],
    })
    return out


def allocation(rec):
    out = _common(rec)
    out.update({
        "order_line_id": rec["order_line_id"],
        "sales_order_id": rec["sales_order_id"],
        "reel_id": rec["reel_id"],
        "remnant_reel_id": rec["remnant_reel_id"],
        "sequence_no": rec["sequence_no"],
        "length_ft": calc.as_number(rec["length_ft"]),
        "status": rec["status"],
        "commit_mode": rec["commit_mode"],
        "cut_window_start": rec["cut_window_start"],
        "cut_window_end": rec["cut_window_end"],
        "cut_charge_applied_cents": rec["cut_charge_applied_cents"],
        "scrap_ft": calc.as_number(rec["scrap_ft"]),
    })
    return out


def delivery_run(rec):
    out = _common(rec)
    out.update({
        "sales_order_id": rec["sales_order_id"],
        "truck_id": rec["truck_id"],
        "branch_id": rec["branch_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "jobsite_address": rec["jobsite_address"],
        "jobsite_has_forklift": rec["jobsite_has_forklift"],
        "heaviest_reel_lbs": rec["heaviest_reel_lbs"],
        "reel_handling": rec["reel_handling"],
        "status": rec["status"],
        "dispatched_at": rec["dispatched_at"],
        "delivered_at": rec["delivered_at"],
    })
    return out
