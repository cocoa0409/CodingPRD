"""Entity serializers. Computed fields (dealer standing, drop/slot ledgers,
infraction_state) are derived live from the store at serialization time, and
lazy clock transitions are applied to drops and slots before they are read."""
from calc import (
    dealer_allocation_score, dealer_committed_units, dealer_infraction_points,
    dealer_outstanding_balance, drop_unallocated_units, refresh_drop,
    refresh_slot, slot_available_minutes, slot_booked_minutes,
    warranty_reserved_units,
)
from envelope import fmt_dt
from store import get_clock


def _dt(v):
    return fmt_dt(v) if v is not None else None


def _common(e):
    return {"created_at": e["created_at"], "updated_at": e["updated_at"],
            "version": e["version"]}


def ser_dealer(d):
    out = {
        "id": d["id"],
        "legal_name": d["legal_name"],
        "storefront_address": d["storefront_address"],
        "region_code": d["region_code"],
        "tier": d["tier"],
        "credit_limit_cents": d["credit_limit_cents"],
        "sell_through_pct": d["sell_through_pct"],
        "tenure_years": d["tenure_years"],
        "status": d["status"],
        "storefront_verified": d["storefront_verified"],
        "brand_presentation_score": d["brand_presentation_score"],
        "infraction_points": dealer_infraction_points(d["id"]),
        "outstanding_balance_cents": dealer_outstanding_balance(d["id"]),
        "allocation_score": float(dealer_allocation_score(d)),
    }
    out.update(_common(d))
    return out


def ser_application(a):
    out = {
        "id": a["id"],
        "dealer_id": a["dealer_id"],
        "has_physical_storefront": a["has_physical_storefront"],
        "storefront_sqft": a["storefront_sqft"],
        "document_refs": a["document_refs"],
        "status": a["status"],
        "inspection_status": a["inspection_status"],
        "docs_status": a["docs_status"],
        "inspector_user_id": a["inspector_user_id"],
        "inspection_window_start": _dt(a["inspection_window_start"]),
        "inspection_window_end": _dt(a["inspection_window_end"]),
        "brand_presentation_score": a["brand_presentation_score"],
        "inspection_recorded_by": a["inspection_recorded_by"],
        "docs_reviewed_by": a["docs_reviewed_by"],
        "decision_reason": a["decision_reason"],
    }
    out.update(_common(a))
    return out


def _infraction_state(c):
    if c["status"] == "OVERTURNED":
        return "OVERTURNED"
    if c["status"] == "CONFIRMED_VIOLATION":
        exp = c["infraction_expires_at"]
        if exp is not None and get_clock() >= exp:
            return "EXPIRED"
        return "ACTIVE"
    return "NONE"


def ser_case(c):
    out = {
        "id": c["id"],
        "marketplace": c["marketplace"],
        "seller_handle": c["seller_handle"],
        "listing_url": c["listing_url"],
        "matched_dealer_id": c["matched_dealer_id"],
        "status": c["status"],
        "infraction_category": c["infraction_category"],
        "infraction_points": c["infraction_points"],
        "infraction_issued_at": _dt(c["infraction_issued_at"]),
        "infraction_expires_at": _dt(c["infraction_expires_at"]),
        "infraction_state": _infraction_state(c),
        "resolution_notes": c["resolution_notes"],
    }
    out.update(_common(c))
    return out


def ser_product_line(p):
    out = {
        "id": p["id"],
        "name": p["name"],
        "category": p["category"],
        "base_sku": p["base_sku"],
        "base_custom_price_cents": p["base_custom_price_cents"],
        "map_price_cents": p["map_price_cents"],
        "min_custom_quantity": p["min_custom_quantity"],
        "warranty_months_lid": p["warranty_months_lid"],
        "warranty_months_insulation": p["warranty_months_insulation"],
        "warranty_months_hardware": p["warranty_months_hardware"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def ser_drop(drop):
    refresh_drop(drop)
    committed = dealer_committed_units(drop["id"])
    warranty = warranty_reserved_units(drop["id"])
    out = {
        "id": drop["id"],
        "product_line_id": drop["product_line_id"],
        "color_name": drop["color_name"],
        "pantone_code": drop["pantone_code"],
        "drop_type": drop["drop_type"],
        "total_units": drop["total_units"],
        "dtc_reserved_units": drop["dtc_reserved_units"],
        "dealer_unit_price_cents": drop["dealer_unit_price_cents"],
        "allocation_opens_at": _dt(drop["allocation_opens_at"]),
        "allocation_closes_at": _dt(drop["allocation_closes_at"]),
        "go_live_at": _dt(drop["go_live_at"]),
        "sales_end_at": _dt(drop["sales_end_at"]),
        "status": drop["status"],
        "dealer_committed_units": committed,
        "warranty_reserved_units": warranty,
        "unallocated_units": drop_unallocated_units(drop),
    }
    out.update(_common(drop))
    return out


def ser_allocation(a):
    out = {
        "id": a["id"],
        "dealer_id": a["dealer_id"],
        "drop_id": a["drop_id"],
        "requested_units": a["requested_units"],
        "unit_price_cents": a["unit_price_cents"],
        "allocated_units": a["allocated_units"],
        "status": a["status"],
        "forfeit_reason": a["forfeit_reason"],
    }
    out.update(_common(a))
    return out


def ser_order(o):
    out = {
        "id": o["id"],
        "buyer_type": o["buyer_type"],
        "buyer_ref": o["buyer_ref"],
        "product_line_id": o["product_line_id"],
        "colorway_drop_id": o["colorway_drop_id"],
        "quantity": o["quantity"],
        "declared_color_count": o["declared_color_count"],
        "declared_placement_count": o["declared_placement_count"],
        "print_technology": o["print_technology"],
        "requested_ship_date": _dt(o["requested_ship_date"]),
        "order_state": o["order_state"],
        "artwork_status": o["artwork_status"],
        "proof_round": o["proof_round"],
        "schedule_status": o["schedule_status"],
        "payment_status": o["payment_status"],
        "return_status": o["return_status"],
        "return_reason": o["return_reason"],
        "return_resolution": o["return_resolution"],
        "affected_unit_count": o["affected_unit_count"],
        "slot_id": o["slot_id"],
        "reservation_status": o["reservation_status"],
        "reserved_minutes": o["reserved_minutes"],
        "quote_variant": o["quote_variant"],
        "peak_applied": o["peak_applied"],
        "provisional_quote_cents": o["provisional_quote_cents"],
        "final_quote_cents": o["final_quote_cents"],
        "cancellation_fee_cents": o["cancellation_fee_cents"],
        "refund_cents": o["refund_cents"],
        "qc_fail_count": o["qc_fail_count"],
        "completed_at": _dt(o["completed_at"]),
    }
    out.update(_common(o))
    return out


def ser_proof(p):
    out = {
        "id": p["id"],
        "order_id": p["order_id"],
        "artwork_file_ref": p["artwork_file_ref"],
        "color_count": p["color_count"],
        "placement_count": p["placement_count"],
        "pantone_codes": p["pantone_codes"],
        "round_number": p["round_number"],
        "status": p["status"],
        "review_notes": p["review_notes"],
        "submitted_by": p["submitted_by"],
    }
    out.update(_common(p))
    return out


def ser_slot(s):
    refresh_slot(s)
    booked = slot_booked_minutes(s["id"])
    out = {
        "id": s["id"],
        "station_code": s["station_code"],
        "technology": s["technology"],
        "window_start": _dt(s["window_start"]),
        "window_end": _dt(s["window_end"]),
        "capacity_minutes": s["capacity_minutes"],
        "peak_overlap": s["peak_overlap"],
        "booked_minutes": booked,
        "available_minutes": slot_available_minutes(s),
        "status": s["status"],
    }
    out.update(_common(s))
    return out


def ser_claim(c):
    out = {
        "id": c["id"],
        "claim_source": c["claim_source"],
        "dealer_id": c["dealer_id"],
        "buyer_ref": c["buyer_ref"],
        "order_id": c["order_id"],
        "product_line_id": c["product_line_id"],
        "serial_number": c["serial_number"],
        "component": c["component"],
        "failure_description": c["failure_description"],
        "purchase_date": _dt(c["purchase_date"]),
        "filed_at": _dt(c["filed_at"]),
        "warranty_anchor_at": _dt(c["warranty_anchor_at"]),
        "warranty_expires_at": _dt(c["warranty_expires_at"]),
        "fraud_flag": c["fraud_flag"],
        "replacement_colorway_resolution": c["replacement_colorway_resolution"],
        "credit_equivalent_cents": c["credit_equivalent_cents"],
        "status": c["status"],
        "decision_reason": c["decision_reason"],
    }
    out.update(_common(c))
    return out
