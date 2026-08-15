"""Entity serializers — one function per resource, exact PRD field names."""

from datetime import timedelta

import logic
import store
from constants import EMERGENCY_ACK_WINDOW_HOURS
from timeutil import fmt_dt


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_dt(entity["created_at"]),
        "updated_at": fmt_dt(entity["updated_at"]),
        "version": entity["version"],
    }


def ser_patient(p):
    data = _common(p)
    data.update({
        "mrn": p["mrn"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "special_requirements": list(p["special_requirements"]),
        "current_abo_type": p["current_abo_type"],
        "current_rh_type": p["current_rh_type"],
        "antibody_status": p["antibody_status"],
        "identified_antibodies": list(p["identified_antibodies"]),
        "abo_confirmed": p["abo_confirmed"],
        "has_active_type_and_screen": logic.patient_has_active_ts(p["id"]),
        "active_mtp": logic.patient_has_activated_mtp(p["id"]),
        "total_units_transfused": p["total_units_transfused"],
    })
    return data


def ser_supplier(s):
    data = _common(s)
    data.update({
        "name": s["name"],
        "license_number": s["license_number"],
        "default_lead_time_hours": s["default_lead_time_hours"],
        "status": s["status"],
        "suspended_at": fmt_dt(s["suspended_at"]),
        "suspend_reason": s["suspend_reason"],
    })
    return data


def ser_supplier_order(o):
    data = _common(o)
    data.update({
        "supplier_id": o["supplier_id"],
        "is_emergency": o["is_emergency"],
        "lines": [dict(line) for line in o["lines"]],
        "expected_delivery_at": fmt_dt(o["expected_delivery_at"]),
        "status": o["status"],
        "estimated_cost_cents": o["estimated_cost_cents"],
        "received_summary": [dict(entry) for entry in o["received_summary"]],
        "total_units_received": o["total_units_received"],
        "backordered": o["backordered"],
    })
    return data


def ser_unit(u):
    data = _common(u)
    data.update({
        "unit_number": u["unit_number"],
        "supplier_order_id": u["supplier_order_id"],
        "supplier_id": u["supplier_id"],
        "donor_id": u["donor_id"],
        "lot_number": u["lot_number"],
        "product_type": u["product_type"],
        "abo_type": u["abo_type"],
        "rh_type": u["rh_type"],
        "volume_ml": u["volume_ml"],
        "collected_at": fmt_dt(u["collected_at"]),
        "thawed_at": fmt_dt(u["thawed_at"]),
        "pooled_at": fmt_dt(u["pooled_at"]),
        "expires_at": fmt_dt(u["expires_at"]),
        "antigen_negative": list(u["antigen_negative"]),
        "irradiated": u["irradiated"],
        "cmv_negative": u["cmv_negative"],
        "washed": u["washed"],
        "derived_from_unit_id": u["derived_from_unit_id"],
        "status": u["status"],
        "hold_origin_state": u["hold_origin_state"],
        "hold_reason": u["hold_reason"],
        "intake_reject_reason": u["intake_reject_reason"],
    })
    return data


def ser_ts(ts):
    data = _common(ts)
    data.update({
        "patient_id": ts["patient_id"],
        "specimen_collected_at": fmt_dt(ts["specimen_collected_at"]),
        "expires_at": fmt_dt(ts["expires_at"]),
        "abo_result": ts["abo_result"],
        "rh_result": ts["rh_result"],
        "antibody_screen": ts["antibody_screen"],
        "antibody_identifications": list(ts["antibody_identifications"]),
        "resulted_at": fmt_dt(ts["resulted_at"]),
        "resulted_by_user_id": ts["resulted_by_user_id"],
        "validated_at": fmt_dt(ts["validated_at"]),
        "validated_by_user_id": ts["validated_by_user_id"],
        "status": ts["status"],
        "reject_reason": ts["reject_reason"],
    })
    return data


def ser_order(o):
    data = _common(o)
    data.update({
        "patient_id": o["patient_id"],
        "ordering_physician_id": o["ordering_physician_id"],
        "product_type": o["product_type"],
        "units_requested": o["units_requested"],
        "urgency": o["urgency"],
        "indication_code": o["indication_code"],
        "requires_crossmatch": o["requires_crossmatch"],
        "type_restriction": o["type_restriction"],
        "demand_bucket": o["demand_bucket"],
        "special_requirements_snapshot": list(o["special_requirements_snapshot"]),
        "units_crossmatched": o["units_crossmatched"],
        "units_issued_net": o["units_issued_net"],
        "units_transfused": o["units_transfused"],
        "verified_by_user_id": o["verified_by_user_id"],
        "verified_at": fmt_dt(o["verified_at"]),
        "status": o["status"],
        "rejection_reason": o["rejection_reason"],
        "cancel_reason": o["cancel_reason"],
    })
    return data


def ser_xm(x):
    data = _common(x)
    data.update({
        "order_id": x["order_id"],
        "unit_id": x["unit_id"],
        "patient_id": x["patient_id"],
        "method": x["method"],
        "status": x["status"],
        "auto_selected": x["auto_selected"],
        "resulted_at": fmt_dt(x["resulted_at"]),
        "resulted_by_user_id": x["resulted_by_user_id"],
        "reserved_until": fmt_dt(x["reserved_until"]),
    })
    return data


def ser_mtp(m):
    data = _common(m)
    data.update({
        "patient_id": m["patient_id"],
        "activated_by_physician_id": m["activated_by_physician_id"],
        "activation_reason": m["activation_reason"],
        "status": m["status"],
        "packs_dispatched": m["packs_dispatched"],
        "units_issued_total": m["units_issued_total"],
        "units_wasted_total": m["units_wasted_total"],
        "activated_at": fmt_dt(m["activated_at"]),
        "stood_down_at": fmt_dt(m["stood_down_at"]),
        "deactivated_at": fmt_dt(m["deactivated_at"]),
    })
    return data


def ser_issue(i):
    ack_overdue = (
        i["is_emergency_release"]
        and i["physician_acknowledged_at"] is None
        and store.now() > i["issued_at"] + timedelta(hours=EMERGENCY_ACK_WINDOW_HOURS)
    )
    data = _common(i)
    data.update({
        "order_id": i["order_id"],
        "unit_id": i["unit_id"],
        "patient_id": i["patient_id"],
        "mtp_activation_id": i["mtp_activation_id"],
        "is_emergency_release": i["is_emergency_release"],
        "emergency_justification": i["emergency_justification"],
        "verified_by_user_id": i["verified_by_user_id"],
        "issued_by_user_id": i["issued_by_user_id"],
        "issued_at": fmt_dt(i["issued_at"]),
        "transfusion_started_at": fmt_dt(i["transfusion_started_at"]),
        "completed_at": fmt_dt(i["completed_at"]),
        "returned_at": fmt_dt(i["returned_at"]),
        "return_seal_intact": i["return_seal_intact"],
        "return_temperature_excursion": i["return_temperature_excursion"],
        "return_disposition": i["return_disposition"],
        "physician_acknowledged_at": fmt_dt(i["physician_acknowledged_at"]),
        "ack_overdue": ack_overdue,
        "lookback_notified": i["lookback_notified"],
        "status": i["status"],
    })
    return data


def ser_reaction(r):
    data = _common(r)
    data.update({
        "issue_record_id": r["issue_record_id"],
        "patient_id": r["patient_id"],
        "unit_id": r["unit_id"],
        "reaction_type": r["reaction_type"],
        "severity": r["severity"],
        "symptoms": r["symptoms"],
        "reported_by_user_id": r["reported_by_user_id"],
        "investigator_user_id": r["investigator_user_id"],
        "clerical_check_passed": r["clerical_check_passed"],
        "dat_result": r["dat_result"],
        "hemolysis_present": r["hemolysis_present"],
        "workup_recorded_at": fmt_dt(r["workup_recorded_at"]),
        "conclusion": r["conclusion"],
        "final_classification": r["final_classification"],
        "linked_recall_case_id": r["linked_recall_case_id"],
        "status": r["status"],
    })
    return data


def ser_recall(r):
    data = _common(r)
    data.update({
        "scope_type": r["scope_type"],
        "donor_id": r["donor_id"],
        "lot_number": r["lot_number"],
        "unit_id": r["unit_id"],
        "implicated_since": fmt_dt(r["implicated_since"]),
        "reason": r["reason"],
        "disposition": r["disposition"],
        "auto_created": r["auto_created"],
        "implicated_unit_ids": list(r["implicated_unit_ids"]),
        "implicated_unit_count": r["implicated_unit_count"],
        "quarantined_count": r["quarantined_count"],
        "transfused_issue_count": r["transfused_issue_count"],
        "notifications_sent_count": r["notifications_sent_count"],
        "status": r["status"],
    })
    return data


def ser_wastage(w):
    # Append-only log: no updated_at / version by design (PRD 2.5).
    return {
        "id": w["id"],
        "created_at": fmt_dt(w["created_at"]),
        "unit_id": w["unit_id"],
        "product_type": w["product_type"],
        "abo_type": w["abo_type"],
        "rh_type": w["rh_type"],
        "reason": w["reason"],
        "quantity_units": w["quantity_units"],
        "recorded_by_user_id": w["recorded_by_user_id"],
        "note": w["note"],
    }


def ser_policy(p):
    bucket = (p["product_type"], p["abo_type"], p["rh_type"])
    data = _common(p)
    data.update({
        "product_type": p["product_type"],
        "abo_type": p["abo_type"],
        "rh_type": p["rh_type"],
        "watch_threshold": p["watch_threshold"],
        "shortage_threshold": p["shortage_threshold"],
        "critical_threshold": p["critical_threshold"],
        "min_shelf_life_hours": p["min_shelf_life_hours"],
        "status": p["status"],
        "current_posture": logic.physical_posture(*bucket),
        "usable_units": logic.bucket_usable_units(*bucket),
        "inbound_units_24h": logic.bucket_inbound_units_24h(*bucket),
        "excessive_wastage": logic.bucket_excessive_wastage(*bucket),
    })
    return data


def ser_cooler(c):
    data = _common(c)
    data.update({
        "cooler_tag": c["cooler_tag"],
        "status": c["status"],
        "restock_until": fmt_dt(c["restock_until"]),
    })
    return data


def ser_checkout(c):
    overdue = c["status"] == "OPEN" and store.now() > c["planned_end"]
    data = _common(c)
    data.update({
        "cooler_id": c["cooler_id"],
        "planned_start": fmt_dt(c["planned_start"]),
        "planned_end": fmt_dt(c["planned_end"]),
        "checked_out_by_user_id": c["checked_out_by_user_id"],
        "actual_returned_at": fmt_dt(c["actual_returned_at"]),
        "status": c["status"],
        "overdue": overdue,
    })
    return data
