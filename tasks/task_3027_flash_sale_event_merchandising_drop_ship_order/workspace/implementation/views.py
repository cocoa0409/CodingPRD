"""Entity -> API payload serialisation.

Field names, ordering and types are taken verbatim from SCAFFOLD §1.1 and the
PRD prose.  Every datetime is rendered as ISO 8601 UTC with three fractional
digits; every money value is an integer count of cents.
"""

from store import iso


def _common(e):
    out = {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e.get("updated_at")),
        "version": e.get("version", 1),
    }
    return out


def vendor(e):
    out = _common(e)
    out.update({
        "legal_name": e["legal_name"],
        "vendor_tier": e["vendor_tier"],
        "standing": e["standing"],
        "fill_rate_floor_pct": e["fill_rate_floor_pct"],
        "rolling_fill_rate_units_shipped": e["rolling_fill_rate_units_shipped"],
        "rolling_fill_rate_units_ordered": e["rolling_fill_rate_units_ordered"],
        "standing_evaluated_at": iso(e.get("standing_evaluated_at")),
    })
    return out


def shop(e):
    out = _common(e)
    out.update({
        "vendor_id": e["vendor_id"],
        "shop_name": e["shop_name"],
        "shop_status": e["shop_status"],
        "curated_sku_count": e["curated_sku_count"],
    })
    return out


def event(e):
    out = _common(e)
    out.update({
        "shop_id": e["shop_id"],
        "event_title": e["event_title"],
        "starts_at": iso(e["starts_at"]),
        "ends_at": iso(e["ends_at"]),
        "ship_time_quote_days": e["ship_time_quote_days"],
        "event_status": e["event_status"],
        "checkpoint_index": e["checkpoint_index"],
        "units_ordered_total": e["units_ordered_total"],
        "units_po_committed_total": e["units_po_committed_total"],
        "oversell_units_total": e["oversell_units_total"],
        "net_contribution_cents": e.get("net_contribution_cents"),
        "net_contribution_variant": e.get("net_contribution_variant"),
        "closed_at": iso(e.get("closed_at")),
        "open_event_for_shop": e["open_event_for_shop"],
    })
    return out


def listing(e):
    out = _common(e)
    out.update({
        "event_id": e["event_id"],
        "vendor_sku": e["vendor_sku"],
        "unit_price_cents": e["unit_price_cents"],
        "vendor_unit_cost_cents": e["vendor_unit_cost_cents"],
        "allocation_units": e["allocation_units"],
        "units_ordered": e["units_ordered"],
        "oversell_units": e["oversell_units"],
        "listing_status": e["listing_status"],
        "reveal_at": iso(e["reveal_at"]),
    })
    return out


def customer(e):
    out = _common(e)
    out.update({
        "email": e["email"],
        "full_name": e["full_name"],
        "account_status": e["account_status"],
        "store_credit_balance_cents": e["store_credit_balance_cents"],
        "refund_balance_cents": e["refund_balance_cents"],
        "lifetime_credit_issued_cents": e["lifetime_credit_issued_cents"],
    })
    return out


def order(e):
    out = _common(e)
    out.update({
        "customer_id": e["customer_id"],
        "event_id": e.get("event_id"),
        "order_status": e["order_status"],
        "payment_status": e["payment_status"],
        "disclosed_ship_time_days": e.get("disclosed_ship_time_days"),
        "cancellation_window_ends_at": iso(e.get("cancellation_window_ends_at")),
        "cancellation_waived": e["cancellation_waived"],
        "order_total_cents": e["order_total_cents"],
        "refund_due_cents": e["refund_due_cents"],
        "parcel_consolidated_at": iso(e.get("parcel_consolidated_at")),
        "ready_to_ship": e["ready_to_ship"],
        # supplementary money fields carried by the order's own transitions
        "captured_amount_cents": e.get("captured_amount_cents", 0),
        "refunded_amount_cents": e.get("refunded_amount_cents", 0),
        "discount_cents": e.get("discount_cents", 0),
    })
    return out


def confirmation(e):
    out = _common(e)
    out.update({
        "customer_order_id": e["customer_order_id"],
        "listing_id": e["listing_id"],
        "quantity": e["quantity"],
        "confirmation_status": e["confirmation_status"],
        "confirmed_units": e.get("confirmed_units"),
        "short_shipped_units": e["short_shipped_units"],
        "oversold_units": e["oversold_units"],
        "line_unit_price_cents": e.get("line_unit_price_cents"),
        "refund_due_cents": e["refund_due_cents"],
        "confirmed_at": iso(e.get("confirmed_at")),
        "cancellation_reason": e.get("cancellation_reason"),
        "total_oversold_units": e.get("total_oversold_units", 0),
    })
    return out


def purchase_order(e):
    out = _common(e)
    out.update({
        "vendor_id": e["vendor_id"],
        "event_id": e["event_id"],
        "po_status": e["po_status"],
        "quantity_ordered": e["quantity_ordered"],
        "quantity_shipped": e["quantity_shipped"],
        "fill_rate_pct": e.get("fill_rate_pct"),
        "fill_rate_floor_pct": e.get("fill_rate_floor_pct"),
        "due_at": iso(e.get("due_at")),
        "issued_at": iso(e.get("issued_at")),
        "closed_at": iso(e.get("closed_at")),
    })
    return out


def poline(e):
    out = _common(e)
    out.update({
        "purchase_order_id": e["purchase_order_id"],
        "listing_id": e["listing_id"],
        "quantity_ordered": e["quantity_ordered"],
        "quantity_confirmed": e["quantity_confirmed"],
        "quantity_shipped": e["quantity_shipped"],
        "poline_status": e["poline_status"],
    })
    return out


def shipment(e):
    out = _common(e)
    out.update({
        "purchase_order_id": e["purchase_order_id"],
        "quantity_shipped": e["quantity_shipped"],
        "carrier_tracking_code": e["carrier_tracking_code"],
        "shipped_at": iso(e.get("shipped_at")),
        "arrived_at": iso(e.get("arrived_at")),
        "shipment_status": e["shipment_status"],
        "allocations": [
            {"listing_id": a["listing_id"], "quantity": a["quantity"]}
            for a in e.get("allocations", [])
        ],
        "rejection_reason_code": e.get("rejection_reason_code"),
    })
    return out


def parcel(e):
    out = _common(e)
    out.update({
        "customer_order_id": e["customer_order_id"],
        "parcel_status": e["parcel_status"],
        "contained_line_ids": list(e["contained_line_ids"]),
        "vendor_shipment_count": e["vendor_shipment_count"],
        "sealed_at": iso(e.get("sealed_at")),
        "dispatch_eta": iso(e.get("dispatch_eta")),
    })
    return out


def ret(e):
    out = _common(e)
    out.update({
        "confirmation_id": e["confirmation_id"],
        "reason_code": e["reason_code"],
        "return_status": e["return_status"],
        "settlement_basis": e.get("settlement_basis"),
        "settlement_amount_cents": e.get("settlement_amount_cents"),
        "cs_user_id": e.get("cs_user_id"),
        "decided_at": iso(e.get("decided_at")),
    })
    return out


def ledger(e):
    """CreditLedger is the append-only exception: id and created_at only."""
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "customer_id": e["customer_id"],
        "source_kind": e["source_kind"],
        "source_ref_id": e["source_ref_id"],
        "amount_cents": e["amount_cents"],
        "entry_status": e["entry_status"],
        "idempotency_key": e.get("idempotency_key"),
        "label": e.get("label"),
    }


SERIALISERS = {
    "vendors": vendor,
    "shops": shop,
    "events": event,
    "listings": listing,
    "customers": customer,
    "orders": order,
    "confirmations": confirmation,
    "purchase_orders": purchase_order,
    "polines": poline,
    "shipments": shipment,
    "parcels": parcel,
    "returns": ret,
    "ledger": ledger,
}


def ser(collection, entity):
    return SERIALISERS[collection](entity)


def ser_all(collection, entities):
    return [SERIALISERS[collection](e) for e in entities]