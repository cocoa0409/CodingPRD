"""Entity serializers: exactly the declared fields plus the common fields.

Business datetime fields are emitted at second precision with a Z suffix;
created_at/updated_at are stored pre-formatted at millisecond precision.
"""
from clock import fmt_dt


def _dt(value):
    return fmt_dt(value) if value is not None else None


def _num(value):
    return float(value) if value is not None else None


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def contract_out(c):
    out = _common(c)
    out.update({
        "agency_code": c["agency_code"],
        "title": c["title"],
        "award_amount_cents": c["award_amount_cents"],
        "deliverable_report_count": c["deliverable_report_count"],
        "disbursed_cents": c["disbursed_cents"],
        "forfeited_cents": c["forfeited_cents"],
        "remaining_cents": c["remaining_cents"],
        "status": c["status"],
        "terminated_reason": c["terminated_reason"],
    })
    return out


def study_out(s):
    out = _common(s)
    out.update({
        "contract_id": s["contract_id"],
        "title": s["title"],
        "research_question": s["research_question"],
        "status": s["status"],
        "committed_projected_n": s["committed_projected_n"],
        "pipeline_projected_n": s["pipeline_projected_n"],
        "enrolled_total": s["enrolled_total"],
        "quarantined_record_count": s["quarantined_record_count"],
        "sample_adequacy": s["sample_adequacy"],
    })
    return out


def design_plan_out(p):
    out = _common(p)
    out.update({
        "study_id": p["study_id"],
        "design_type": p["design_type"],
        "mde": p["mde"],
        "cluster_size": p["cluster_size"],
        "icc": p["icc"],
        "attrition_rate": p["attrition_rate"],
        "alpha": p["alpha"],
        "power_target": p["power_target"],
        "randomization_ratio_num": p["randomization_ratio_num"],
        "randomization_ratio_den": p["randomization_ratio_den"],
        "n_per_arm": p["n_per_arm"],
        "required_total_n": p["required_total_n"],
        "revision_number": p["revision_number"],
        "status": p["status"],
    })
    return out


def irb_out(p):
    out = _common(p)
    out.update({
        "study_id": p["study_id"],
        "title": p["title"],
        "estimated_burden_minutes": p["estimated_burden_minutes"],
        "status": p["status"],
        "approval_start": _dt(p["approval_start"]),
        "approval_end": _dt(p["approval_end"]),
        "consent_form_version": p["consent_form_version"],
        "submitted_by_id": p["submitted_by_id"],
        "decided_by_id": p["decided_by_id"],
    })
    return out


def site_out(s):
    out = _common(s)
    out.update({
        "study_id": s["study_id"],
        "name": s["name"],
        "max_participants": s["max_participants"],
        "enrolled_count": s["enrolled_count"],
        "randomized_count": s["randomized_count"],
        "status": s["status"],
    })
    return out


def participant_out(p):
    out = _common(p)
    out.update({
        "site_id": p["site_id"],
        "external_ref": p["external_ref"],
        "status": p["status"],
        "consent_form_version": p["consent_form_version"],
        "consented_at": _dt(p["consented_at"]),
        "burden_total_minutes": p["burden_total_minutes"],
        "withdrawal_reason": p["withdrawal_reason"],
    })
    return out


def wave_out(w):
    out = _common(w)
    out.update({
        "study_id": w["study_id"],
        "wave_type": w["wave_type"],
        "site_id": w["site_id"],
        "open_at": _dt(w["open_at"]),
        "close_at": _dt(w["close_at"]),
        "status": w["status"],
    })
    return out


def record_out(r):
    out = _common(r)
    out.update({
        "wave_id": r["wave_id"],
        "participant_id": r["participant_id"],
        "instrument_minutes": r["instrument_minutes"],
        "payload_ref": r["payload_ref"],
        "billed_minutes": r["billed_minutes"],
        "linkage_key": r["linkage_key"],
        "status": r["status"],
    })
    return out


def analysis_plan_out(a):
    out = _common(a)
    out.update({
        "study_id": a["study_id"],
        "primary_outcomes": a["primary_outcomes"],
        "secondary_outcomes": a["secondary_outcomes"],
        "amendment_count": a["amendment_count"],
        "registered_at": _dt(a["registered_at"]),
        "status": a["status"],
    })
    return out


def report_out(r):
    out = _common(r)
    out.update({
        "study_id": r["study_id"],
        "title": r["title"],
        "report_type": r["report_type"],
        "addressed_primary_outcomes": r["addressed_primary_outcomes"],
        "payment_milestone_cents": r["payment_milestone_cents"],
        "revision_count": r["revision_count"],
        "submitted_by_id": r["submitted_by_id"],
        "reviewed_by_id": r["reviewed_by_id"],
        "submitted_at": _dt(r["submitted_at"]),
        "accepted_at": _dt(r["accepted_at"]),
        "peer_review_due": _dt(r["peer_review_due"]),
        "revision_due": _dt(r["revision_due"]),
        "publication_due": _dt(r["publication_due"]),
        "status": r["status"],
    })
    return out


def ruf_out(f):
    out = _common(f)
    out.update({
        "study_id": f["study_id"],
        "title": f["title"],
        "cell_counts": f["cell_counts"],
        "sensitivity_weights": f["sensitivity_weights"],
        "suppressed_cell_count": f["suppressed_cell_count"],
        "max_risk": _num(f["max_risk"]),
        "mean_risk": _num(f["mean_risk"]),
        "prepared_by_id": f["prepared_by_id"],
        "status": f["status"],
    })
    return out


def activity_out(a):
    out = _common(a)
    out.update({
        "study_id": a["study_id"],
        "activity_type": a["activity_type"],
        "title": a["title"],
        "scheduled_at": _dt(a["scheduled_at"]),
        "operator_count": a["operator_count"],
        "status": a["status"],
    })
    return out
