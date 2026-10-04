"""Entity serializers: every declared field, datetimes as ISO-8601 UTC with
three fractional digits, nulls preserved. Project reads recompute
provisional_total_cents while DRAFT/RETURNED and derive funded_cents."""
from util_time import iso_ms
from services import pricing, funding


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso_ms(rec["created_at"]),
        "updated_at": iso_ms(rec["updated_at"]),
        "version": rec["version"],
    }


def school_json(s):
    out = {
        "name": s["name"],
        "state_code": s["state_code"],
        "district": s["district"],
        "poverty_pct": s["poverty_pct"],
        "ell_pct": s["ell_pct"],
        "equity_score_banded": s["equity_score_banded"],
        "equity_score_weighted": s["equity_score_weighted"],
    }
    out.update(_common(s))
    return out


def teacher_json(t):
    out = {
        "school_id": t["school_id"],
        "full_name": t["full_name"],
        "email": t["email"],
        "subjects_taught": list(t["subjects_taught"]),
        "employment_status": t["employment_status"],
    }
    out.update(_common(t))
    return out


def vendor_json(v):
    out = {
        "name": v["name"],
        "ship_from_state": v["ship_from_state"],
        "contact_email": v["contact_email"],
        "status": v["status"],
    }
    out.update(_common(v))
    return out


def catalog_item_json(c):
    out = {
        "vendor_id": c["vendor_id"],
        "sku": c["sku"],
        "name": c["name"],
        "category": c["category"],
        "subject_tags": list(c["subject_tags"]),
        "unit_price_cents": c["unit_price_cents"],
        "weight_oz": c["weight_oz"],
        "shipping_zone": c["shipping_zone"],
        "fragile": c["fragile"],
        "max_quantity_per_project": c["max_quantity_per_project"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def project_json(p):
    provisional = None
    if p["status"] in ("DRAFT", "RETURNED"):
        provisional = pricing.provisional_total(p)
    out = {
        "teacher_id": p["teacher_id"],
        "school_id": p["school_id"],
        "title": p["title"],
        "description": p["description"],
        "subject": p["subject"],
        "grade_band": p["grade_band"],
        "funding_window_days": p["funding_window_days"],
        "status": p["status"],
        "provisional_total_cents": provisional,
        "pinned_items_total_cents": p["pinned_items_total_cents"],
        "pinned_shipping_total_cents": p["pinned_shipping_total_cents"],
        "goal_cents": p["goal_cents"],
        "funded_cents": funding.funded_cents(p),
        "funding_started_at": iso_ms(p["funding_started_at"]),
        "funding_deadline": iso_ms(p["funding_deadline"]),
        "screened_by_id": p["screened_by_id"],
        "vetted_by_id": p["vetted_by_id"],
    }
    out.update(_common(p))
    return out


def project_item_json(it):
    out = {
        "project_id": it["project_id"],
        "catalog_item_id": it["catalog_item_id"],
        "quantity": it["quantity"],
        "pinned_unit_price_cents": it["pinned_unit_price_cents"],
    }
    out.update(_common(it))
    return out


def donor_json(d):
    out = {
        "display_name": d["display_name"],
        "email": d["email"],
        "lifetime_donated_cents": d["lifetime_donated_cents"],
        "lifetime_refunded_cents": d["lifetime_refunded_cents"],
        "lifetime_reallocated_cents": d["lifetime_reallocated_cents"],
    }
    out.update(_common(d))
    return out


def donation_json(d):
    out = {
        "project_id": d["project_id"],
        "donor_id": d["donor_id"],
        "kind": d["kind"],
        "amount_cents": d["amount_cents"],
        "match_campaign_id": d["match_campaign_id"],
        "matched_cents": d["matched_cents"],
        "equity_fund_id": d["equity_fund_id"],
        "status": d["status"],
        "choice_deadline": iso_ms(d["choice_deadline"]),
        "refund_reason": d["refund_reason"],
    }
    out.update(_common(d))
    return out


def match_campaign_json(c):
    out = {
        "sponsor_name": c["sponsor_name"],
        "match_ratio": c["match_ratio"],
        "budget_cents": c["budget_cents"],
        "matched_so_far_cents": c["matched_so_far_cents"],
        "remaining_budget_cents": c["remaining_budget_cents"],
        "min_donation_cents": c["min_donation_cents"],
        "target_type": c["target_type"],
        "target_value": c["target_value"],
        "starts_at": iso_ms(c["starts_at"]),
        "ends_at": iso_ms(c["ends_at"]),
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def purchase_order_json(po):
    out = {
        "project_id": po["project_id"],
        "vendor_id": po["vendor_id"],
        "line_items": [dict(li) for li in po["line_items"]],
        "line_total_cents": po["line_total_cents"],
        "shipping_fee_cents": po["shipping_fee_cents"],
        "status": po["status"],
        "tracking_number": po["tracking_number"],
        "issued_at": iso_ms(po["issued_at"]),
        "ship_by_due": iso_ms(po["ship_by_due"]),
        "shipped_at": iso_ms(po["shipped_at"]),
        "delivered_at": iso_ms(po["delivered_at"]),
    }
    out.update(_common(po))
    return out


def thank_you_package_json(pkg):
    # ThankYouPackage carries id and created_at only (no updated_at/version).
    return {
        "id": pkg["id"],
        "created_at": iso_ms(pkg["created_at"]),
        "project_id": pkg["project_id"],
        "status": pkg["status"],
        "thank_you_note": pkg["thank_you_note"],
        "impact_report": pkg["impact_report"],
        "submitted_at": iso_ms(pkg["submitted_at"]),
    }


def fraud_case_json(fc):
    out = {
        "teacher_id": fc["teacher_id"],
        "project_id": fc["project_id"],
        "purchase_order_id": fc["purchase_order_id"],
        "reason": fc["reason"],
        "status": fc["status"],
    }
    out.update(_common(fc))
    return out


def equity_fund_json(f):
    out = {
        "name": f["name"],
        "state_code": f["state_code"],
        "subject": f["subject"],
        "min_poverty_pct": f["min_poverty_pct"],
        "budget_cents": f["budget_cents"],
        "remaining_cents": f["remaining_cents"],
        "window_start": iso_ms(f["window_start"]),
        "window_end": iso_ms(f["window_end"]),
        "status": f["status"],
    }
    out.update(_common(f))
    return out
