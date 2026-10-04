import db


def _ts(dt):
    return None if dt is None else db.iso_ms(dt)


def _d(d):
    return None if d is None else db.iso_date(d)


def program_view(p):
    return {
        "id": p["id"],
        "program_code": p["program_code"],
        "program_name": p["program_name"],
        "outreach_mode": p["outreach_mode"],
        "is_active": p["is_active"],
        "population_size": p["population_size"],
        "attributed_count": p["attributed_count"],
        "adherent_count": p["adherent_count"],
        "measure_year": p["measure_year"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def patient_view(p):
    return {
        "id": p["id"],
        "external_ref": p["external_ref"],
        "date_of_birth": p["date_of_birth"],
        "risk_category": p["risk_category"],
        "contraindication_flags": list(p["contraindication_flags"]),
        "recent_symptoms": p["recent_symptoms"],
        "comorbidity": p["comorbidity"],
        "family_history": p["family_history"],
        "status": p["status"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def provider_view(p):
    return {
        "id": p["id"],
        "npi": p["npi"],
        "display_name": p["display_name"],
        "channel": p["channel"],
        "is_active": p["is_active"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def cohort_view(c):
    return {
        "id": c["id"],
        "program_id": c["program_id"],
        "patient_id": c["patient_id"],
        "enrolled_at": _d(c["enrolled_at"]),
        "attributed": c["attributed"],
        "adherence_window_start": _d(c["adherence_window_start"]),
        "adherence_window_end": _d(c["adherence_window_end"]),
        "status": c["status"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def order_view(o):
    return {
        "id": o["id"],
        "patient_id": o["patient_id"],
        "provider_id": o["provider_id"],
        "program_id": o["program_id"],
        "cohort_id": o["cohort_id"],
        "order_channel": o["order_channel"],
        "status": o["status"],
        "eligible_at": _ts(o["eligible_at"]),
        "shipped_at": _ts(o["shipped_at"]),
        "returned_at": _ts(o["returned_at"]),
        "abandonment_due_at": _d(o["abandonment_due_at"]),
        "recollection_round": o["recollection_round"],
        "active_kit_id": o["active_kit_id"],
        "quality_outcome": o["quality_outcome"],
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }


def outreach_event_view(e):
    return {
        "id": e["id"],
        "cohort_id": e["cohort_id"],
        "channel": e["channel"],
        "sent_at": _ts(e["sent_at"]),
        "template_code": e["template_code"],
        "created_at": _ts(e["created_at"]),
    }


def reminder_view(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "sequence_no": r["sequence_no"],
        "channel": r["channel"],
        "scheduled_for": _d(r["scheduled_for"]),
        "sent_at": _ts(r["sent_at"]),
        "status": r["status"],
        "created_at": _ts(r["created_at"]),
    }


def kit_view(k):
    return {
        "id": k["id"],
        "order_id": k["order_id"],
        "kit_serial": k["kit_serial"],
        "shipped_at": _ts(k["shipped_at"]),
        "returned_at": _ts(k["returned_at"]),
        "stabilization_expires_at": _ts(k["stabilization_expires_at"]),
        "status": k["status"],
        "created_at": _ts(k["created_at"]),
        "updated_at": _ts(k["updated_at"]),
        "version": k["version"],
    }


def specimen_view(s):
    return {
        "id": s["id"],
        "kit_id": s["kit_id"],
        "order_id": s["order_id"],
        "accessioned_at": _ts(s["accessioned_at"]),
        "adequacy": s["adequacy"],
        "adequacy_checked_at": _ts(s["adequacy_checked_at"]),
        "processing_started_at": _ts(s["processing_started_at"]),
        "status": s["status"],
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def result_view(r):
    return {
        "id": r["id"],
        "order_id": r["order_id"],
        "specimen_id": r["specimen_id"],
        "resulted_at": _ts(r["resulted_at"]),
        "outcome": r["outcome"],
        "delivered_to_provider_at": _ts(r["delivered_to_provider_at"]),
        "navigation_due_at": _d(r["navigation_due_at"]),
        "navigation_status": r["navigation_status"],
        "navigation_completed_at": _ts(r["navigation_completed_at"]),
        "created_at": _ts(r["created_at"]),
    }


def report_view(r):
    return {
        "id": r["id"],
        "program_id": r["program_id"],
        "measure_year": r["measure_year"],
        "numerator": r["numerator"],
        "denominator": r["denominator"],
        "adherence_rate": r["adherence_rate"],
        "snapshot_at": _ts(r["snapshot_at"]),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }
