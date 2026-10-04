"""Entity -> JSON-dict serializers. Datetimes: created_at/updated_at use the
three-fractional-digit format of PRD 2.5; clock-derived and input datetimes
use the canonical Z rendering (seconds, ms only when sub-second precision
exists). Decimal scores/totals render as JSON numbers via float()."""
import domain
from store import fmt_ts3, fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts3(e["created_at"]),
        "updated_at": fmt_ts3(e["updated_at"]),
        "version": e["version"],
    }


def _num(value):
    """Decimal/int/float -> JSON number; None passes through."""
    if value is None:
        return None
    return float(value)


def cycle(c):
    out = {
        "code": c["code"],
        "components": [
            {"code": comp["code"], "kind": comp["kind"], "weight": comp["weight"]}
            for comp in c["components"]
        ],
        "submission_window_open": fmt_dt(c["submission_window_open"]),
        "submission_window_close": fmt_dt(c["submission_window_close"]),
        "retake_window_close": fmt_dt(c["retake_window_close"]),
        "certification_threshold": c["certification_threshold"],
        "max_attempts_per_component": c["max_attempts_per_component"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def candidate(c):
    out = {
        "full_name": c["full_name"],
        "email": c["email"],
        "license_number": c["license_number"],
        "license_state": c["license_state"],
        "district_code": c["district_code"],
        "years_experience": c["years_experience"],
        "fte_fraction": c["fte_fraction"],
        "license_document_ref": c["license_document_ref"],
        "employer_verification_ref": c["employer_verification_ref"],
        "status": c["status"],
        "eligibility_note": c["eligibility_note"],
    }
    out.update(_common(c))
    return out


def center(c):
    out = {
        "name": c["name"],
        "region_code": c["region_code"],
        "slot_capacity": c["slot_capacity"],
    }
    out.update(_common(c))
    return out


def booking(b):
    out = {
        "candidate_id": b["candidate_id"],
        "center_id": b["center_id"],
        "cycle_id": b["cycle_id"],
        "slot_start_at": fmt_dt(b["slot_start_at"]),
        "slot_end_at": fmt_dt(b["slot_end_at"]),
        "status": b["status"],
        "earned_score": _num(b["earned_score"]),
    }
    out.update(_common(b))
    return out


def submission(s):
    out = {
        "candidate_id": s["candidate_id"],
        "cycle_id": s["cycle_id"],
        "component_code": s["component_code"],
        "kind": s["kind"],
        "attempt_number": s["attempt_number"],
        "prior_submission_id": s["prior_submission_id"],
        "status": s["status"],
        "final_score": _num(s["final_score"]),
        "counted_score": _num(domain.counted_score_for(
            s["candidate_id"], s["cycle_id"], s["component_code"])),
        "superseded": domain.superseded_of(s),
    }
    out.update(_common(s))
    return out


def artifact(a):
    # Immutable record (PRD 2.5): id + created_at only; no updated_at/version.
    return {
        "id": a["id"],
        "submission_id": a["submission_id"],
        "artifact_type": a["artifact_type"],
        "file_format": a["file_format"],
        "file_size_mb": a["file_size_mb"],
        "duration_minutes": a["duration_minutes"],
        "subject_student_count": a["subject_student_count"],
        "created_at": fmt_ts3(a["created_at"]),
    }


def assessor(a):
    count, exact_rate, adjacent_rate = domain.reliability_rates(a["id"])
    out = {
        "full_name": a["full_name"],
        "email": a["email"],
        "home_district_code": a["home_district_code"],
        "status": a["status"],
        "calibration_passes": a["calibration_passes"],
        "calibration_failures": a["calibration_failures"],
        "calibrated_at": fmt_dt(a["calibrated_at"]),
        "open_assignment_count": domain.open_assignment_count(a["id"]),
        "scored_read_count": count,
        "exact_agreement_rate": _num(exact_rate),
        "adjacent_agreement_rate": _num(adjacent_rate),
    }
    out.update(_common(a))
    return out


def benchmark(b):
    out = {
        "component_code": b["component_code"],
        "content_domain": b["content_domain"],
        "known_score": _num(b["known_score"]),
        "tolerance": b["tolerance"],
    }
    out.update(_common(b))
    return out


def assignment(x):
    out = {
        "assessor_id": x["assessor_id"],
        "submission_id": x["submission_id"],
        "benchmark_id": x["benchmark_id"],
        "read_number": x["read_number"],
        "status": x["status"],
        "score": _num(x["score"]),
        "score_submitted_at": fmt_dt(x["score_submitted_at"]),
        "is_within_tolerance": x["is_within_tolerance"],
    }
    out.update(_common(x))
    return out


def certification(c):
    out = {
        "candidate_id": c["candidate_id"],
        "cycle_id": c["cycle_id"],
        "status": c["status"],
        "weighted_total_provisional": _num(domain.provisional_total(c)),
        "weighted_total_final": _num(c["weighted_total_final"]),
        "certified_at": fmt_dt(c["certified_at"]),
        "valid_until": fmt_dt(c["valid_until"]),
    }
    out.update(_common(c))
    return out


def renewal(r):
    out = {
        "certification_id": r["certification_id"],
        "evidence_items": r["evidence_items"],
        "total_hours": _num(r["total_hours"]),
        "status": r["status"],
        "review_note": r["review_note"],
    }
    out.update(_common(r))
    return out


def program(p):
    out = {
        "name": p["name"],
        "sponsor_state": p["sponsor_state"],
        "sponsor_district_code": p["sponsor_district_code"],
        "budget_total_cents": p["budget_total_cents"],
        "budget_remaining_cents": domain.program_remaining(p["id"]),
        "base_stipend_cents": p["base_stipend_cents"],
        "early_bird_multiplier": p["early_bird_multiplier"],
        "early_bird_deadline": fmt_dt(p["early_bird_deadline"]),
        "status": domain.program_status(p["id"]),
    }
    out.update(_common(p))
    return out


def stipend(s):
    out = {
        "program_id": s["program_id"],
        "certification_id": s["certification_id"],
        "amount_cents": s["amount_cents"],
        "status": s["status"],
    }
    out.update(_common(s))
    return out
