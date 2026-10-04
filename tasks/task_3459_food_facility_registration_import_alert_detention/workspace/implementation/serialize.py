"""Serializers: internal entity dicts -> API representations.

Internal dicts hold datetime/Decimal values; serializers render datetimes in
the canonical logical-clock format and percentages as JSON numbers.
"""
from db import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def facility(f):
    d = _common(f)
    d.update(
        {
            "legal_name": f["legal_name"],
            "facility_kind": f["facility_kind"],
            "country_code": f["country_code"],
            "ufi": f["ufi"],
            "registration_number": f["registration_number"],
            "registration_status": f["registration_status"],
            "registered_at": fmt_dt(f["registered_at"]),
            "expires_at": fmt_dt(f["expires_at"]),
            "violation_count": f["violation_count"],
            "open_detention_count": f["open_detention_count"],
        }
    )
    return d


def importer(m):
    d = _common(m)
    d.update(
        {
            "firm_name": m["firm_name"],
            "account_code": m["account_code"],
            "standing": m["standing"],
            "refusal_count": m["refusal_count"],
            "terminal_entry_count": m["terminal_entry_count"],
        }
    )
    return d


def laboratory(lab):
    d = _common(lab)
    d.update(
        {
            "lab_code": lab["lab_code"],
            "daily_sample_capacity": lab["daily_sample_capacity"],
        }
    )
    return d


def prior_notice(p):
    d = _common(p)
    d.update(
        {
            "importer_id": p["importer_id"],
            "facility_id": p["facility_id"],
            "product_code": p["product_code"],
            "product_risk_class": p["product_risk_class"],
            "transport_mode": p["transport_mode"],
            "arrival_eta": fmt_dt(p["arrival_eta"]),
            "declared_units": p["declared_units"],
            "unit_value_cents": p["unit_value_cents"],
            "port_code": p["port_code"],
            "status": p["status"],
            "is_amendment": p["is_amendment"],
            "parent_pn_id": p["parent_pn_id"],
        }
    )
    return d


def entry(e):
    d = _common(e)
    d.update(
        {
            "prior_notice_id": e["prior_notice_id"],
            "importer_id": e["importer_id"],
            "facility_id": e["facility_id"],
            "product_code": e["product_code"],
            "product_risk_class": e["product_risk_class"],
            "declared_units": e["declared_units"],
            "unit_value_cents": e["unit_value_cents"],
            "is_amendment_pn": e["is_amendment_pn"],
            "review_status": e["review_status"],
            "disposition_status": e["disposition_status"],
            "screening_decision": e["screening_decision"],
            "screening_score": e["screening_score"],
            "scoring_variant_applied": e["scoring_variant_applied"],
            "probation_adjustment_applied": e["probation_adjustment_applied"],
            "detained_at": fmt_dt(e["detained_at"]),
            "response_deadline_at": fmt_dt(e["response_deadline_at"]),
            "detained_under_alert_id": e["detained_under_alert_id"],
            "units_held": e["units_held"],
            "units_released": e["units_released"],
            "units_refused": e["units_refused"],
            "units_exported": e["units_exported"],
            "units_destroyed": e["units_destroyed"],
            "bond_amount_cents": e["bond_amount_cents"],
            "disposition_completed_at": fmt_dt(e["disposition_completed_at"]),
        }
    )
    return d


def sample(s):
    d = _common(s)
    d.update(
        {
            "entry_id": s["entry_id"],
            "lab_code": s["lab_code"],
            "sample_units": s["sample_units"],
            "analysis_date": s["analysis_date"],
            "status": s["status"],
            "result": s["result"],
        }
    )
    return d


def alert(a):
    d = _common(a)
    d.update(
        {
            "scope_type": a["scope_type"],
            "facility_id": a["facility_id"],
            "country_code": a["country_code"],
            "product_code": a["product_code"],
            "reason": a["reason"],
            "status": a["status"],
            "created_by_user_id": a["created_by_user_id"],
            "lifted_at": fmt_dt(a["lifted_at"]),
        }
    )
    return d


def petition(p):
    d = _common(p)
    d.update(
        {
            "alert_id": p["alert_id"],
            "filed_by_facility_id": p["filed_by_facility_id"],
            "evidence_links": list(p["evidence_links"]),
            "status": p["status"],
            "consecutive_compliant_count": p["consecutive_compliant_count"],
        }
    )
    return d


def inspection(i):
    d = _common(i)
    d.update(
        {
            "facility_id": i["facility_id"],
            "inspector_user_id": i["inspector_user_id"],
            "scheduled_start_at": fmt_dt(i["scheduled_start_at"]),
            "scheduled_end_at": fmt_dt(i["scheduled_end_at"]),
            "status": i["status"],
            "findings_violation_count": i["findings_violation_count"],
        }
    )
    return d


def recall(r):
    d = _common(r)
    d.update(
        {
            "facility_id": r["facility_id"],
            "product_code": r["product_code"],
            "quantity_distributed": r["quantity_distributed"],
            "classification": r["classification"],
            "status": r["status"],
            "quantity_recovered": r["quantity_recovered"],
            "quantity_corrected": r["quantity_corrected"],
            "quantity_destroyed": r["quantity_destroyed"],
            "quantity_outstanding": r["quantity_outstanding"],
            "effectiveness_pct": float(r["effectiveness_pct"]),
            "consignees_contacted": r["consignees_contacted"],
            "consignees_total": r["consignees_total"],
            "consignee_contact_pct": float(r["consignee_contact_pct"]),
        }
    )
    return d
