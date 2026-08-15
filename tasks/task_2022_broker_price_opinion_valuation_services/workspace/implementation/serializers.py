"""Entity serializers — emit exactly the declared fields (PRD 2.4, scaffold 1.1).

Common-fields entities carry id/created_at/updated_at/version.
Append-only entities (PhotoEvidence, QCRevisionRequest, VolumeForecast) carry
only id and created_at.
"""

from db import fmt_ts


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def _append_only(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
    }


def ser_client_account(r):
    out = _common(r)
    out.update({
        "client_code": r["client_code"],
        "display_name": r["display_name"],
        "sla_hours_standard": r["sla_hours_standard"],
        "sla_hours_rush": r["sla_hours_rush"],
        "late_penalty_bps_per_day": r["late_penalty_bps_per_day"],
        "scorecard_weight_turnaround": r["scorecard_weight_turnaround"],
        "scorecard_weight_quality": r["scorecard_weight_quality"],
        "scorecard_weight_revision": r["scorecard_weight_revision"],
        "status": r["status"],
    })
    return out


def ser_broker(r):
    out = _common(r)
    out.update({
        "broker_code": r["broker_code"],
        "full_name": r["full_name"],
        "email": r["email"],
        "max_concurrent_orders": r["max_concurrent_orders"],
        "status": r["status"],
        "composite_score": float(r["composite_score"]),
    })
    return out


def ser_broker_license(r):
    out = _common(r)
    out.update({
        "broker_id": r["broker_id"],
        "state_code": r["state_code"],
        "license_kind": r["license_kind"],
        "license_number": r["license_number"],
        "expires_on": fmt_ts(r["expires_on"]),
        "status": r["status"],
    })
    return out


def ser_state_regulation(r):
    out = _common(r)
    out.update({
        "state_code": r["state_code"],
        "bpo_permitted": r["bpo_permitted"],
        "appraisal_required_for_interior": r["appraisal_required_for_interior"],
        "min_driveby_radius_miles": float(r["min_driveby_radius_miles"]),
        "min_interior_radius_miles": float(r["min_interior_radius_miles"]),
        "status": r["status"],
    })
    return out


def ser_property(r):
    out = _common(r)
    out.update({
        "street_address": r["street_address"],
        "city": r["city"],
        "state_code": r["state_code"],
        "postal_code": r["postal_code"],
        "living_area_sqft": r["living_area_sqft"],
        "lot_area_sqft": r["lot_area_sqft"],
        "year_built": r["year_built"],
        "property_type": r["property_type"],
        "status": r["status"],
    })
    return out


def ser_order(r):
    out = _common(r)
    out.update({
        "client_id": r["client_id"],
        "property_id": r["property_id"],
        "assigned_broker_id": r["assigned_broker_id"],
        "order_kind": r["order_kind"],
        "inspection_level": r["inspection_level"],
        "priority": r["priority"],
        "agreed_fee_cents": r["agreed_fee_cents"],
        "sla_due_at": fmt_ts(r["sla_due_at"]),
        "completed_at": fmt_ts(r["completed_at"]),
        "days_late": r["days_late"],
        "late_penalty_cents": r["late_penalty_cents"],
        "net_payable_cents": r["net_payable_cents"],
        "fulfillment_status": r["fulfillment_status"],
        "payment_status": r["payment_status"],
        "revision_count": r["revision_count"],
        "is_rush_breach": r["is_rush_breach"],
    })
    return out


def ser_comparable(r):
    out = _common(r)
    out.update({
        "order_id": r["order_id"],
        "source_property_id": r["source_property_id"],
        "sale_price_cents": r["sale_price_cents"],
        "sale_date": fmt_ts(r["sale_date"]),
        "distance_miles": float(r["distance_miles"]),
        "adjustment_cents": r["adjustment_cents"],
        "adjusted_value_cents": r["adjusted_value_cents"],
        "status": r["status"],
    })
    return out


def ser_photo(r):
    out = _append_only(r)
    out.update({
        "order_id": r["order_id"],
        "photo_kind": r["photo_kind"],
        "file_url": r["file_url"],
        "captured_at": fmt_ts(r["captured_at"]),
        "uploaded_by_broker_id": r["uploaded_by_broker_id"],
    })
    return out


def ser_fee_line(r):
    out = _common(r)
    out.update({
        "order_id": r["order_id"],
        "fee_kind": r["fee_kind"],
        "description": r["description"],
        "amount_cents": r["amount_cents"],
        "status": r["status"],
    })
    return out


def ser_qc_review(r):
    out = _common(r)
    out.update({
        "order_id": r["order_id"],
        "reviewer_id": r["reviewer_id"],
        "cycle_index": r["cycle_index"],
        "verdict": r["verdict"],
        "defects_found": r["defects_found"],
        "notes": r["notes"],
        "reviewed_at": fmt_ts(r["reviewed_at"]),
        "is_segregation_violation": r["is_segregation_violation"],
    })
    return out


def ser_revision_request(r):
    out = _append_only(r)
    out.update({
        "order_id": r["order_id"],
        "qc_review_id": r["qc_review_id"],
        "cycle_index": r["cycle_index"],
        "reason": r["reason"],
        "due_at": fmt_ts(r["due_at"]),
        "resolved_at": fmt_ts(r["resolved_at"]),
        "outcome": r["outcome"],
    })
    return out


def ser_payout_batch(r):
    out = _common(r)
    out.update({
        "broker_id": r["broker_id"],
        "period_start": fmt_ts(r["period_start"]),
        "period_end": fmt_ts(r["period_end"]),
        "total_payable_cents": r["total_payable_cents"],
        "order_count": r["order_count"],
        "status": r["status"],
    })
    return out


def ser_volume_forecast(r):
    out = _append_only(r)
    out.update({
        "state_code": r["state_code"],
        "forecast_month": r["forecast_month"],
        "predicted_order_count": r["predicted_order_count"],
        "model_version": r["model_version"],
        "generated_at": fmt_ts(r["generated_at"]),
    })
    return out
