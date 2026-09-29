"""Entity serializers.

Monetary amounts are emitted as JSON numbers (integers of whole cents), never as
strings. Percentages and ventilator hours are emitted as JSON numbers too.
Timestamps are ISO 8601 UTC with exactly three fractional digits.
"""

from decimal import Decimal

from clock import iso


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _date(value):
    if value is None:
        return None
    return value.isoformat()


def _common(row):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if "updated_at" in row:
        out["updated_at"] = iso(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def hospital(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "npi": row["npi"],
        "hospital_type": row["hospital_type"],
        "is_colocated": row["is_colocated"],
        "threshold_pct": _num(row["threshold_pct"]),
        "admissions_in_period": row["admissions_in_period"],
        "share_pct": _num(row["share_pct"]),
        "monitoring_state": row["monitoring_state"],
    })
    return out


def period(row):
    out = _common(row)
    out.update({
        "period_label": row["period_label"],
        "start_date": _date(row["start_date"]),
        "end_date": _date(row["end_date"]),
        "status": row["status"],
        "total_admissions": row["total_admissions"],
        "total_payment_cents": row["total_payment_cents"],
        "final_determination_count": row["final_determination_count"],
        "closed_at": iso(row["closed_at"]),
    })
    return out


def patient(row):
    out = _common(row)
    out.update({
        "mrn": row["mrn"],
        "full_name": row["full_name"],
        "birth_date": _date(row["birth_date"]),
        "primary_payer": row["primary_payer"],
        "open_referral_count": row["open_referral_count"],
    })
    return out


def physician(row):
    out = _common(row)
    out.update({
        "npi": row["npi"],
        "full_name": row["full_name"],
        "specialty": row["specialty"],
        "credential_status": row["credential_status"],
    })
    return out


def criteria_set(row):
    out = _common(row)
    out.update({
        "label": row["label"],
        "effective_from": _date(row["effective_from"]),
        "pmv_min_vent_hours": row["pmv_min_vent_hours"],
        "pmv_min_icu_days": row["pmv_min_icu_days"],
        "wound_min_stage": row["wound_min_stage"],
        "wound_min_count": row["wound_min_count"],
        "status": row["status"],
    })
    return out


def drg_rate(row):
    out = _common(row)
    out.update({
        "drg_code": row["drg_code"],
        "relative_weight": _num(row["relative_weight"]),
        "alos_days": row["alos_days"],
        "standard_federal_rate_cents": row["standard_federal_rate_cents"],
        "ipps_comparable_per_diem_cents": row["ipps_comparable_per_diem_cents"],
        "ipps_comparable_full_cents": row["ipps_comparable_full_cents"],
    })
    return out


def referral(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "referring_hospital_id": row["referring_hospital_id"],
        "drg_rate_id": row["drg_rate_id"],
        "pinned_criteria_set_id": row["pinned_criteria_set_id"],
        "vent_hours_at_referral": _num(row["vent_hours_at_referral"]),
        "icu_days_at_referral": row["icu_days_at_referral"],
        "wound_stage": row["wound_stage"],
        "wound_count": row["wound_count"],
        "prior_acute_discharge_at": iso(row["prior_acute_discharge_at"]),
        "data_complete": row["data_complete"],
        "missing_fields": list(row["missing_fields"]),
        "qualifying_track": row["qualifying_track"],
        "status": row["status"],
        "screened_count": row["screened_count"],
    })
    return out


def stay(row):
    out = _common(row)
    out.update({
        "patient_id": row["patient_id"],
        "referral_id": row["referral_id"],
        "cost_reporting_period_id": row["cost_reporting_period_id"],
        "interrupted_parent_stay_id": row["interrupted_parent_stay_id"],
        "admitted_at": iso(row["admitted_at"]),
        "discharged_at": iso(row["discharged_at"]),
        "resumed_at": iso(row["resumed_at"]),
        "clinical_status": row["clinical_status"],
        "payment_review_status": row["payment_review_status"],
        "carried_los_days": row["carried_los_days"],
        "interruption_days_total": row["interruption_days_total"],
        "interruption_count": row["interruption_count"],
        "covered_los_days": row["covered_los_days"],
        "sso_threshold_days": row["sso_threshold_days"],
        "short_stay_outlier_applied": row["short_stay_outlier_applied"],
        "discharge_payment_pct": _num(row["discharge_payment_pct"]),
        "discharge_disposition": row["discharge_disposition"],
        "estimated_cost_cents": row["estimated_cost_cents"],
        "counts_toward_admission_threshold": row["counts_toward_admission_threshold"],
        "admitted_with_override": row["admitted_with_override"],
        "override_reason": row["override_reason"],
    })
    return out


def weaning_plan(row):
    out = _common(row)
    out.update({
        "stay_id": row["stay_id"],
        "closed_by_physician_id": row["closed_by_physician_id"],
        "protocol_label": row["protocol_label"],
        "vent_hours_total": _num(row["vent_hours_total"]),
        "current_step": row["current_step"],
        "sbt_attempt_count": row["sbt_attempt_count"],
        "consecutive_failed_sbt": row["consecutive_failed_sbt"],
        "max_tolerated_sbt_hours": _num(row["max_tolerated_sbt_hours"]),
        "liberation_eligible": row["liberation_eligible"],
        "last_progression_at": iso(row["last_progression_at"]),
        "status": row["status"],
        "closed_at": iso(row["closed_at"]),
    })
    return out


def idt_note(row):
    out = _common(row)
    out.update({
        "stay_id": row["stay_id"],
        "discipline": row["discipline"],
        "note_text": row["note_text"],
        "goals_documented": row["goals_documented"],
        "documented_at": iso(row["documented_at"]),
        "week_index": row["week_index"],
    })
    return out


def interruption(row):
    out = _common(row)
    out.update({
        "stay_id": row["stay_id"],
        "destination": row["destination"],
        "left_at": iso(row["left_at"]),
        "returned_at": iso(row["returned_at"]),
        "window_days": row["window_days"],
        "interruption_days": row["interruption_days"],
        "within_window": row["within_window"],
        "status": row["status"],
    })
    return out


def determination(row):
    out = _common(row)
    out.update({
        "stay_id": row["stay_id"],
        "payment_variant": row["payment_variant"],
        "drg_code_used": row["drg_code_used"],
        "relative_weight_used": _num(row["relative_weight_used"]),
        "alos_days_used": row["alos_days_used"],
        "ipps_per_diem_used_cents": row["ipps_per_diem_used_cents"],
        "ipps_full_used_cents": row["ipps_full_used_cents"],
        "covered_los_days_used": row["covered_los_days_used"],
        "full_standard_amount_cents": row["full_standard_amount_cents"],
        "standard_variant_amount_cents": row["standard_variant_amount_cents"],
        "site_neutral_variant_amount_cents": row["site_neutral_variant_amount_cents"],
        "base_payment_cents": row["base_payment_cents"],
        "outlier_payment_cents": row["outlier_payment_cents"],
        "total_payment_cents": row["total_payment_cents"],
        "discharge_payment_pct": _num(row["discharge_payment_pct"]),
        "short_stay_outlier_applied": row["short_stay_outlier_applied"],
        "status": row["status"],
        "priced_by_user_id": row["priced_by_user_id"],
        "finalized_by_user_id": row["finalized_by_user_id"],
        "recalculation_reason": row["recalculation_reason"],
        "void_reason": row["void_reason"],
    })
    return out


def review(row):
    out = _common(row)
    out.update({
        "stay_id": row["stay_id"],
        "as_documented_score": row["as_documented_score"],
        "query_adjusted_score": row["query_adjusted_score"],
        "effective_score": row["effective_score"],
        "risk_band": row["risk_band"],
        "missing_discipline_count": row["missing_discipline_count"],
        "answered_query_count": row["answered_query_count"],
        "status": row["status"],
        "opened_by_user_id": row["opened_by_user_id"],
        "resolved_by_user_id": row["resolved_by_user_id"],
        "resolution_note": row["resolution_note"],
    })
    return out


def query(row):
    out = _common(row)
    out.update({
        "denial_risk_review_id": row["denial_risk_review_id"],
        "stay_id": row["stay_id"],
        "answered_by_physician_id": row["answered_by_physician_id"],
        "query_type": row["query_type"],
        "prompt_text": row["prompt_text"],
        "response_text": row["response_text"],
        "issued_at": iso(row["issued_at"]),
        "due_at": iso(row["due_at"]),
        "answered_at": iso(row["answered_at"]),
        "status": row["status"],
        "issued_by_user_id": row["issued_by_user_id"],
        "closed_by_user_id": row["closed_by_user_id"],
    })
    return out
