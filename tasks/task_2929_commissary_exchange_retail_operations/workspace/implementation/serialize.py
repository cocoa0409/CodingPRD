"""Entity representations.

Stores, patrons, delegations, products, assortments, sales, capital projects,
MWR programs and special orders carry id / created_at / updated_at / version.
Sale lines and fund ledger entries are append-only and carry only id and
created_at — updated_at and version are absent from them entirely (PRD 2.4).
"""

import derive
from envelope import iso_millis


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso_millis(record["created_at"]),
        "updated_at": iso_millis(record["updated_at"]),
        "version": record["version"],
    }


def _append_only(record):
    return {"id": record["id"], "created_at": iso_millis(record["created_at"])}


def store_out(store):
    out = _common(store)
    out.update({
        "name": store["name"],
        "channel": store["channel"],
        "region": store["region"],
        "surcharge_rate_bp": store["surcharge_rate_bp"],
        "exchange_markup_bp": store["exchange_markup_bp"],
        "shelf_block_capacity_facings": store["shelf_block_capacity_facings"],
        "surcharge_fund_balance_cents": derive.surcharge_fund_balance_cents(store["id"]),
        "surcharge_obligated_cents": derive.surcharge_obligated_cents(store["id"]),
        "dividend_fund_balance_cents": derive.dividend_fund_balance_cents(store["id"]),
        "shipping_allowance_committed_cents": derive.shipping_allowance_committed_cents(store["id"]),
        "fund_posture": derive.fund_posture(store["id"]),
        "period_close_index": store["period_close_index"],
    })
    return out


def patron_out(patron):
    out = _common(patron)
    out.update({
        "full_name": patron["full_name"],
        "id_card_class": patron["id_card_class"],
        "sponsor_patron_id": patron["sponsor_patron_id"],
        "card_status": patron["card_status"],
        "suspension_reason": patron["suspension_reason"],
        "resale_watch_status": patron["resale_watch_status"],
        "resale_risk_score": patron["resale_risk_score"],
        "recent_sales_risk_score": patron["recent_sales_risk_score"],
        "restricted_units_30d": patron["restricted_units_30d"],
        "flagged_sale_count_30d": patron["flagged_sale_count_30d"],
        "manual_strike_count": patron["manual_strike_count"],
    })
    return out


def delegation_out(delegation):
    out = _common(delegation)
    out.update({
        "sponsor_patron_id": delegation["sponsor_patron_id"],
        "delegate_patron_id": delegation["delegate_patron_id"],
        "valid_from": iso_millis(delegation["valid_from"]),
        "valid_to": iso_millis(delegation["valid_to"]),
        "per_sale_spend_cap_cents": delegation["per_sale_spend_cap_cents"],
        "status": delegation["status"],
        "superseded_by_delegation_id": delegation["superseded_by_delegation_id"],
    })
    return out


def product_out(product):
    out = _common(product)
    out.update({
        "sku": product["sku"],
        "name": product["name"],
        "category": product["category"],
        "unit_cost_cents": product["unit_cost_cents"],
        "unit_weight_grams": product["unit_weight_grams"],
        "resale_restricted": product["resale_restricted"],
        "quantity_limit_per_visit": product["quantity_limit_per_visit"],
    })
    return out


def assortment_out(assortment):
    out = _common(assortment)
    out.update({
        "store_id": assortment["store_id"],
        "product_id": assortment["product_id"],
        "shelf_block": assortment["shelf_block"],
        "facings": assortment["facings"],
        "supply_mode": assortment["supply_mode"],
        "vendor_name": assortment["vendor_name"],
        "promo_allowance_bp": assortment["promo_allowance_bp"],
        "promo_window_start": iso_millis(assortment["promo_window_start"]),
        "promo_window_end": iso_millis(assortment["promo_window_end"]),
        "effective_from": iso_millis(assortment["effective_from"]),
        "effective_to": iso_millis(assortment["effective_to"]),
        "overseas_shipping_allowance_cents": assortment["overseas_shipping_allowance_cents"],
        "status": assortment["status"],
    })
    return out


def sale_out(sale):
    out = _common(sale)
    out.update({
        "store_id": sale["store_id"],
        "patron_id": sale["patron_id"],
        "acting_delegation_id": sale["acting_delegation_id"],
        "business_date": iso_millis(sale["business_date"]),
        "tender_state": sale["tender_state"],
        "compliance_state": sale["compliance_state"],
        "line_count": sale["line_count"],
        "merchandise_cents": sale["merchandise_cents"],
        "markup_total_cents": sale["markup_total_cents"],
        "surcharge_total_cents": sale["surcharge_total_cents"],
        "tax_cents": sale["tax_cents"],
        "total_due_cents": sale["total_due_cents"],
        "provisional_allowance_cents": sale["provisional_allowance_cents"],
        "settled_allowance_cents": sale["settled_allowance_cents"],
        "allowance_variance_cents": sale["allowance_variance_cents"],
        "subsidized_shipping_cents": sale["subsidized_shipping_cents"],
        "voided_reason": sale["voided_reason"],
    })
    return out


def sale_line_out(line):
    out = _append_only(line)
    out.update({
        "sale_id": line["sale_id"],
        "product_id": line["product_id"],
        "quantity": line["quantity"],
        "unit_price_cents": line["unit_price_cents"],
        "extended_cents": line["extended_cents"],
        "line_markup_cents": line["line_markup_cents"],
        "line_surcharge_cents": line["line_surcharge_cents"],
        "line_allowance_cents": line["line_allowance_cents"],
        "line_shipping_allowance_cents": line["line_shipping_allowance_cents"],
        "restricted_units": line["restricted_units"],
    })
    return out


def ledger_entry_out(entry):
    out = _append_only(entry)
    out.update({
        "store_id": entry["store_id"],
        "fund": entry["fund"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "balance_after_cents": derive.balance_after_cents(entry),
        "source_ref_kind": entry["source_ref_kind"],
        "source_ref_id": entry["source_ref_id"],
        "period_close_index": entry["period_close_index"],
    })
    return out


def project_out(project):
    out = _common(project)
    out.update({
        "store_id": project["store_id"],
        "title": project["title"],
        "requested_amount_cents": project["requested_amount_cents"],
        "contingency_bp": project["contingency_bp"],
        "contingency_cents": project["contingency_cents"],
        "obligation_cents": project["obligation_cents"],
        "outlay_cents": project["outlay_cents"],
        "state": project["state"],
        "revision_count": project["revision_count"],
        "submitted_by_user_id": project["submitted_by_user_id"],
        "decided_by_user_id": project["decided_by_user_id"],
        "closed_by_user_id": project["closed_by_user_id"],
    })
    return out


def program_out(program):
    out = _common(program)
    out.update({
        "store_id": program["store_id"],
        "name": program["name"],
        "priority_rank": program["priority_rank"],
        "funding_ceiling_cents": program["funding_ceiling_cents"],
        "ytd_funded_cents": derive.ytd_funded_cents(program["id"]),
        "status": program["status"],
    })
    return out


def special_order_out(order):
    out = _common(order)
    out.update({
        "store_id": order["store_id"],
        "patron_id": order["patron_id"],
        "product_id": order["product_id"],
        "quantity": order["quantity"],
        "route": order["route"],
        "state": order["state"],
        "billable_weight_kg": order["billable_weight_kg"],
        "gross_ship_cents": order["gross_ship_cents"],
        "patron_share_cents": order["patron_share_cents"],
        "shipping_allowance_cents": order["shipping_allowance_cents"],
        "cancelled_reason": order["cancelled_reason"],
    })
    return out
