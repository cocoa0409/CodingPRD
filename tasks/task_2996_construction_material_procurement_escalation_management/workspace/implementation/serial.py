"""Entity serializers. Derived fields (PRD 2.10) are computed here, on read."""

import calc
from store import store
from util import fmt_instant, num


def _audit(row, out, versioned=True):
    out["created_at"] = fmt_instant(row["created_at"])
    if versioned:
        out["updated_at"] = fmt_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def project(row):
    rollups = calc.project_rollups(row)
    out = {
        "id": row["id"],
        "name": row["name"],
        "contract_number": row["contract_number"],
        "owner_name": row["owner_name"],
        "schedule_data_date": fmt_instant(row["schedule_data_date"]),
        "escalation_contingency_budget": num(row["escalation_contingency_budget"]),
        "estimated_total_cost": num(rollups["estimated_total_cost"]),
        "committed_total_cost": num(rollups["committed_total_cost"]),
        "buyout_variance": num(rollups["buyout_variance"]),
        "bought_out_variance": num(rollups["bought_out_variance"]),
        "escalation_contingency_committed": num(rollups["escalation_contingency_committed"]),
        "escalation_contingency_remaining": num(rollups["escalation_contingency_remaining"]),
        "change_order_recovered_amount": num(rollups["change_order_recovered_amount"]),
    }
    return _audit(row, out)


def package(row):
    float_days = calc.package_float_days(row)
    out = {
        "id": row["id"],
        "project_id": row["project_id"],
        "scope_code": row["scope_code"],
        "description": row["description"],
        "commodity_index_code": row["commodity_index_code"],
        "estimated_cost": num(row["estimated_cost"]),
        "baseline_estimated_cost": num(row["baseline_estimated_cost"]),
        "required_onsite_date": fmt_instant(row["required_onsite_date"]),
        "fabrication_duration_days": row["fabrication_duration_days"],
        "baseline_fabrication_duration_days": row["baseline_fabrication_duration_days"],
        "delivery_transit_days": row["delivery_transit_days"],
        "submittal_review_days": row["submittal_review_days"],
        "lead_time_days": calc.package_lead_time_days(row),
        "release_for_fabrication_date": fmt_instant(calc.package_release_date(row)),
        "is_long_lead": calc.package_is_long_lead(row),
        "float_days": float_days,
        "rff_risk_band": calc.package_risk_band(float_days),
        "open_quote_count": calc.package_open_quote_count(row["id"]),
        "status": row["status"],
    }
    return _audit(row, out)


def supplier(row):
    score, band, count = calc.supplier_exposure(row, forward=False)
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "country_of_origin": row["country_of_origin"],
        "is_domestic": row["country_of_origin"] == "US",
        "declared_tariff_rate_pct": num(row["declared_tariff_rate_pct"]),
        "open_disruption_count": count,
        "exposure_score_snapshot": num(score),
        "exposure_band_snapshot": band,
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
    }
    return _audit(row, out)


def quote(row):
    out = {
        "id": row["id"],
        "material_package_id": row["material_package_id"],
        "supplier_id": row["supplier_id"],
        "supersedes_quote_id": row["supersedes_quote_id"],
        "base_price": num(row["base_price"]),
        "received_at": fmt_instant(row["received_at"]),
        "price_hold_days": row["price_hold_days"],
        "expires_at": fmt_instant(row["expires_at"]),
        "status": row["status"],
    }
    return _audit(row, out)


def agreement(row):
    out = {
        "id": row["id"],
        "quote_id": row["quote_id"],
        "index_code": row["index_code"],
        "baseline_index_period": row["baseline_index_period"],
        "baseline_index_value": num(row["baseline_index_value"]),
        "deadband_pct": num(row["deadband_pct"]),
        "cap_pct": num(row["cap_pct"]),
        "contractor_share_pct": num(row["contractor_share_pct"]),
        "price_hold_through": fmt_instant(row["price_hold_through"]),
        "proposed_terms_note": row["proposed_terms_note"],
        "counter_note": row["counter_note"],
        "round_number": row["round_number"],
        "executed_at": fmt_instant(row["executed_at"]),
        "status": row["status"],
    }
    return _audit(row, out)


def index_reading(row):
    out = {
        "id": row["id"],
        "index_code": row["index_code"],
        "period": row["period"],
        "value": num(row["value"]),
        "published_at": fmt_instant(row["published_at"]),
    }
    return _audit(row, out, versioned=False)


def commitment(row):
    out = {
        "id": row["id"],
        "quote_id": row["quote_id"],
        "material_package_id": row["material_package_id"],
        "escalation_agreement_id": row["escalation_agreement_id"],
        "po_number": row["po_number"],
        "committed_base_cost": num(row["committed_base_cost"]),
        "is_early_buyout": row["is_early_buyout"],
        "requires_storage_arrangement": row["is_early_buyout"],
        "commitment_status": row["commitment_status"],
        "delivery_posture": row["delivery_posture"],
        "released_for_fab_at": fmt_instant(row["released_for_fab_at"]),
        "delivered_at": fmt_instant(row["delivered_at"]),
        "escalation_variant": row["escalation_variant"],
        "escalation_accrued": num(row["escalation_accrued"]),
        "escalation_index_period": row["escalation_index_period"],
        "cancellation_reason": row["cancellation_reason"],
    }
    return _audit(row, out)


def arrangement(row):
    count, doc_status = calc.documentation_completeness(row)
    out = {
        "id": row["id"],
        "purchase_commitment_id": row["purchase_commitment_id"],
        "warehouse_name": row["warehouse_name"],
        "warehouse_address": row["warehouse_address"],
        "stored_value": num(row["stored_value"]),
        "monthly_storage_rate_pct": num(row["monthly_storage_rate_pct"]),
        "stored_from": fmt_instant(row["stored_from"]),
        "planned_release_date": fmt_instant(row["planned_release_date"]),
        "documentation_status": doc_status,
        "verified_doc_type_count": count,
        "carrying_cost_accrued": num(calc.carrying_cost(row)),
        "carrying_cost_frozen_at": fmt_instant(row["carrying_cost_frozen_at"]),
        "status": row["status"],
    }
    return _audit(row, out)


def document(row):
    out = {
        "id": row["id"],
        "storage_arrangement_id": row["storage_arrangement_id"],
        "doc_type": row["doc_type"],
        "reference_number": row["reference_number"],
        "effective_date": fmt_instant(row["effective_date"]),
        "expires_at": fmt_instant(row["expires_at"]),
        "coverage_amount": num(row["coverage_amount"]),
        "verified": row["verified"],
        "revoked": row["revoked"],
        "revoked_at": fmt_instant(row["revoked_at"]),
        "revocation_reason": row["revocation_reason"],
    }
    return _audit(row, out)


def substitution(row):
    out = {
        "id": row["id"],
        "material_package_id": row["material_package_id"],
        "proposed_supplier_id": row["proposed_supplier_id"],
        "disruption_event_id": row["disruption_event_id"],
        "driver": row["driver"],
        "proposed_product": row["proposed_product"],
        "cost_delta": num(row["cost_delta"]),
        "schedule_delta_days": row["schedule_delta_days"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "engineer_conditions": row["engineer_conditions"],
        "revision_round": row["revision_round"],
        "applied_cost_delta": num(row["applied_cost_delta"]),
        "applied_schedule_delta_days": row["applied_schedule_delta_days"],
        "status": row["status"],
    }
    return _audit(row, out)


def change_order(row):
    out = {
        "id": row["id"],
        "purchase_commitment_id": row["purchase_commitment_id"],
        "claimed_amount": num(row["claimed_amount"]),
        "narrative": row["narrative"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "gross_documented_amount": num(row["gross_documented_amount"]),
        "admin_fee_pct": num(row["admin_fee_pct"]),
        "admin_fee_amount": num(row["admin_fee_amount"]),
        "substantiated_amount": num(row["substantiated_amount"]),
        "owner_note": row["owner_note"],
        "status": row["status"],
    }
    return _audit(row, out)


def disruption(row):
    out = {
        "id": row["id"],
        "supplier_id": row["supplier_id"],
        "event_type": row["event_type"],
        "tariff_rate_pct": num(row["tariff_rate_pct"]),
        "effective_date": fmt_instant(row["effective_date"]),
        "description": row["description"],
        "status": row["status"],
        "mitigated_at": fmt_instant(row["mitigated_at"]),
    }
    return _audit(row, out)


def find(collection, row_id, error_id):
    """Resolve an id against a collection or raise the collection's 404 code."""
    from errors import ApiError

    row = getattr(store, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row
