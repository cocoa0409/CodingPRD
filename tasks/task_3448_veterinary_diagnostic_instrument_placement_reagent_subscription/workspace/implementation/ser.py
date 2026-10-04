"""Entity -> public JSON dict serializers. Underscore-prefixed internal
fields (parsed datetimes, insertion seq) never leave the process."""
import db
import util


def gpa(g):
    return {
        "id": g["id"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
        "group_type": g["group_type"],
        "group_code": g["group_code"],
        "effective_from": util.iso_z(g["_from"]),
        "effective_to": util.iso_z(g["_to"]),
        "discount_pct": g["discount_pct"],
        "sku_overrides": g["sku_overrides"],
        "status": g["status"],
    }


def clinic(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "name": c["name"],
        "corporate_group_code": c["corporate_group_code"],
        "buying_group_code": c["buying_group_code"],
        "caseload_baseline_tests": c["caseload_baseline_tests"],
        "caseload_current_tests": c["caseload_current_tests"],
        "status": c["status"],
    }


def agreement(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "clinic_id": a["clinic_id"],
        "model": a["model"],
        "program_type": a["program_type"],
        "term_months": a["term_months"],
        "start_date": util.iso_z(a["_start"]),
        "end_date": util.iso_z(a["_end"]),
        "monthly_minimum_cents": a["monthly_minimum_cents"],
        "lease_rate_cents": a["lease_rate_cents"],
        "purchase_price_cents": a["purchase_price_cents"],
        "baseline_caseload_snapshot": a["baseline_caseload_snapshot"],
        "proposed_minimum_cents": a["proposed_minimum_cents"],
        "cumulative_billed_cents": a["cumulative_billed_cents"],
        "cumulative_unpaid_billed_cents": a["cumulative_unpaid_billed_cents"],
        "service_credit_cents": a["service_credit_cents"],
        "status": a["status"],
    }


def analyzer(an):
    return {
        "id": an["id"],
        "created_at": an["created_at"],
        "updated_at": an["updated_at"],
        "version": an["version"],
        "clinic_id": an["clinic_id"],
        "agreement_id": an["agreement_id"],
        "model": an["model"],
        "serial_number": an["serial_number"],
        "is_loaner_unit": an["is_loaner_unit"],
        "operational_status": an["operational_status"],
        "connectivity_status": an["connectivity_status"],
        "proficiency_standing": an["proficiency_standing"],
        "qc_valid_until": (util.iso_z(an["_qc_valid_until"])
                           if an["_qc_valid_until"] is not None else None),
        "total_downtime_hours": an["total_downtime_hours"],
        "reported_uptime_pct": an["reported_uptime_pct"],
        "breach_uptime_pct": an["breach_uptime_pct"],
    }


def order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "clinic_id": o["clinic_id"],
        "agreement_id": o["agreement_id"],
        "order_month": o["order_month"],
        "lines": o["lines"],
        "pricing_detail": o["pricing_detail"],
        "list_total_cents": o["list_total_cents"],
        "final_total_cents": o["final_total_cents"],
        "fulfilled_at": (util.iso_z(o["_fulfilled_at"])
                         if o["_fulfilled_at"] is not None else None),
        "status": o["status"],
    }


def provisional_fulfilled_cents(p):
    """OPEN-period read-time attribution: FULFILLED orders whose fulfilled_at
    calendar month equals the period month."""
    total = 0
    for o in db.orders.values():
        if (o["agreement_id"] == p["agreement_id"]
                and o["status"] == "FULFILLED"
                and o["_fulfilled_at"] is not None
                and util.month_of(o["_fulfilled_at"]) == p["period_month"]):
            total += o["final_total_cents"]
    return total


def period(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "agreement_id": p["agreement_id"],
        "period_month": p["period_month"],
        "minimum_cents": p["minimum_cents"],
        "provisional_fulfilled_cents": (provisional_fulfilled_cents(p)
                                        if p["period_status"] == "OPEN"
                                        else None),
        "fulfilled_cents": p["fulfilled_cents"],
        "shortfall_cents": p["shortfall_cents"],
        "billed_cents": p["billed_cents"],
        "period_status": p["period_status"],
        "billing_status": p["billing_status"],
    }


def test_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "clinic_id": o["clinic_id"],
        "analyzer_id": o["analyzer_id"],
        "origin": o["origin"],
        "order_kind": o["order_kind"],
        "test_code": o["test_code"],
        "expected_result": o["expected_result"],
        "status": o["status"],
        "delivery_status": o["delivery_status"],
    }


def result(r):
    """LabResult: the one resource without updated_at / version."""
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "test_order_id": r["test_order_id"],
        "source": r["source"],
        "result_value": r["result_value"],
        "expected_value": r["expected_value"],
        "verdict": r["verdict"],
        "resulted_at": r["resulted_at"],
    }


def case(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "analyzer_id": c["analyzer_id"],
        "case_type": c["case_type"],
        "loaner_analyzer_id": c["loaner_analyzer_id"],
        "status": c["status"],
        "opened_at": c["opened_at"],
        "response_due_at": c["response_due_at"],
        "resolved_at": (util.iso_z(c["_resolved_at"])
                        if c["_resolved_at"] is not None else None),
        "downtime_hours": c["downtime_hours"],
        "sla_met": c["sla_met"],
        "resolution_note": c["resolution_note"],
    }
