"""JSON serializers for research-side entities."""
import core


def organization(o):
    return {
        "id": o["id"],
        "legal_name": o["legal_name"],
        "org_type": o["org_type"],
        "home_market": o["home_market"],
        "service_tier": o["service_tier"],
        "authorized_market_count": o["authorized_market_count"],
        "active_contract_count": o["active_contract_count"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def user(u):
    return {
        "id": u["id"],
        "organization_id": u["organization_id"],
        "email": u["email"],
        "full_name": u["full_name"],
        "role": u["role"],
        "assigned_market": u["assigned_market"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def property(p):
    return {
        "id": p["id"],
        "parent_property_id": p["parent_property_id"],
        "market": p["market"],
        "address_line": p["address_line"],
        "property_type": p["property_type"],
        "rentable_sqft": p["rentable_sqft"],
        "classification": p["classification"],
        "research_status": p["research_status"],
        "land_posture": p["land_posture"],
        "attribute_verified_count": p["attribute_verified_count"],
        "attribute_total_count": p["attribute_total_count"],
        "completeness_pct": p["completeness_pct"],
        "stale_source_count": p["stale_source_count"],
        "verified_sale_value_cents": p["verified_sale_value_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def source_document(sd):
    return {
        "id": sd["id"],
        "property_id": sd["property_id"],
        "source_type": sd["source_type"],
        "source_name": sd["source_name"],
        "contact_method": sd["contact_method"],
        "distributed_markets": sd["distributed_markets"],
        "obtained_at": sd["obtained_at"],
        "source_classification": sd["source_classification"],
        "created_at": sd["created_at"],
        "updated_at": sd["updated_at"],
        "version": sd["version"],
    }


def attribute(a):
    return {
        "id": a["id"],
        "property_id": a["property_id"],
        "source_document_id": a["source_document_id"],
        "field_name": a["field_name"],
        "value": a["value"],
        "proposed_value": a["proposed_value"],
        "proposed_status": a["proposed_status"],
        "created_by_user_id": a["created_by_user_id"],
        "verifier_user_id": a["verifier_user_id"],
        "last_verified_at": a["last_verified_at"],
        "attribute_market": a["attribute_market"],
        "from_third_party": a["from_third_party"],
        "third_party_approved": a["third_party_approved"],
        "revision_index": a["revision_index"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def lease_comparable(c):
    return {
        "id": c["id"],
        "property_id": c["property_id"],
        "tenant_name": c["tenant_name"],
        "lease_start": c["lease_start"],
        "lease_end": c["lease_end"],
        "escalated_rent_psf": c["escalated_rent_psf"],
        "effective_rent_psf": c["effective_rent_psf"],
        "renewal_option": c["renewal_option"],
        "recorded_at": c["recorded_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def sale_transaction(t):
    return {
        "id": t["id"],
        "property_id": t["property_id"],
        "buyer_name": t["buyer_name"],
        "close_date": t["close_date"],
        "gross_sale_price_cents": t["gross_sale_price_cents"],
        "cap_rate_bps": t["cap_rate_bps"],
        "subordination_deadline": t["subordination_deadline"],
        "subordination_status": t["subordination_status"],
        "subordinated_at": t["subordinated_at"],
        "subordinating_case_id": t["subordinating_case_id"],
        "rolled_attributions": t["rolled_attributions"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def listing(l):
    return {
        "id": l["id"],
        "property_id": l["property_id"],
        "organization_id": l["organization_id"],
        "listing_type": l["listing_type"],
        "monthly_rent_psf": l["monthly_rent_psf"],
        "available_sqft": l["available_sqft"],
        "duration_days": l["duration_days"],
        "published_at": l["published_at"],
        "expires_at": l["expires_at"],
        "redistributed_markets": l["redistributed_markets"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def analytics_run(r):
    return {
        "id": r["id"],
        "market": r["market"],
        "run_type": r["run_type"],
        "adjustment_mode": r["adjustment_mode"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "index_value": r["index_value"],
        "comp_count": r["comp_count"],
        "mean_effective_rent_psf": r["mean_effective_rent_psf"],
        "median_effective_rent_psf": r["median_effective_rent_psf"],
        "selector": r["selector"],
        "horizon_quarters": r["horizon_quarters"],
        "forecast_value": r["forecast_value"],
        "forecast_due_at": r["forecast_due_at"],
        "attributed_records_delta": r["attributed_records_delta"],
        "attribution_status": r["attribution_status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def enforcement_case(c):
    return {
        "id": c["id"],
        "organization_id": c["organization_id"],
        "contract_id": c["contract_id"],
        "case_type": c["case_type"],
        "finding_cents": c["finding_cents"],
        "fee_rate_pct": c["fee_rate_pct"],
        "penalty_cents": c["penalty_cents"],
        "escalated_at": c["escalated_at"],
        "escalated_from_case_id": c["escalated_from_case_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }