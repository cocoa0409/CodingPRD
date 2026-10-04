"""Entity serializers — shape of each resource in responses."""

from db import store


def member_view(m):
    return {
        "id": m["id"],
        "legal_name": m["legal_name"],
        "org_id": m["org_id"],
        "org_id_type": m["org_id_type"],
        "member_type": m["member_type"],
        "termination_effective_date": m["termination_effective_date"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def signer_view(s):
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "effective_from": s["effective_from"],
        "effective_until": s["effective_until"],
        "role_scope": s["role_scope"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def loan_view(l):
    return {
        "id": l["id"],
        "min": l["min"],
        "serial": l["serial"],
        "registering_member_id": l["registering_member_id"],
        "loan_amount_cents": l["loan_amount_cents"],
        "property_state": l["property_state"],
        "closing_date": l["closing_date"],
        "foreclosure_mode": l["foreclosure_mode"],
        "current_investor_id": l["current_investor_id"],
        "current_servicer_id": l["current_servicer_id"],
        "status": l["status"],
        "assigned_out_at": l["assigned_out_at"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def transfer_view(t):
    return {
        "id": t["id"],
        "loan_id": t["loan_id"],
        "from_member_id": t["from_member_id"],
        "to_member_id": t["to_member_id"],
        "transfer_type": t["transfer_type"],
        "effective_date": t["effective_date"],
        "idempotency_key": t["idempotency_key"],
        "days_late": t["days_late"],
        "late_fee_cents": t["late_fee_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def match_view(m):
    return {
        "id": m["id"],
        "transfer_id": m["transfer_id"],
        "reported_by_member_id": m["reported_by_member_id"],
        "reported_at": m["reported_at"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def review_view(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "sample_size": r["sample_size"],
        "discrepancy_score": r["discrepancy_score"],
        "status": r["status"],
        "created_by": r["created_by"],
        "settled_by": r["settled_by"],
        "settled_at": r["settled_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def finding_view(f):
    return {
        "id": f["id"],
        "review_id": f["review_id"],
        "loan_id": f["loan_id"],
        "field_name": f["field_name"],
        "expected_value": f["expected_value"],
        "actual_value": f["actual_value"],
        "severity": f["severity"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def report_view(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "report_year": r["report_year"],
        "reporting_rate": r["reporting_rate"],
        "reporting_rate_amount_weighted": r["reporting_rate_amount_weighted"],
        "discrepancy_rate": r["discrepancy_rate"],
        "open_exceptions": r["open_exceptions"],
        "standing_score": r["standing_score"],
        "standing_band": r["standing_band"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def sanction_view(s):
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "review_id": s["review_id"],
        "total_amount_cents": s["total_amount_cents"],
        "line_count": s["line_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def run_view(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "total_records": r["total_records"],
        "matched_count": r["matched_count"],
        "registry_only_count": r["registry_only_count"],
        "platform_only_count": r["platform_only_count"],
        "field_mismatch_count": r["field_mismatch_count"],
        "match_rate": r["match_rate"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def exception_view(e):
    return {
        "id": e["id"],
        "run_id": e["run_id"],
        "loan_id": e["loan_id"],
        "exception_type": e["exception_type"],
        "detail": e["detail"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }
