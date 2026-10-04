"""Deterministic clock sweep (PRD §2.5 / disciplinary_due_process_schedule).
Runs in the pinned order; returns the per-step counters."""

from db import STORE, touch
from services.cascade import apply_sanction_cascade


def run_sweep(now):
    counters = {
        "att_expired_count": 0,
        "attempts_no_show_count": 0,
        "certifications_lapsed_count": 0,
        "certifications_expired_count": 0,
        "suspensions_lifted_count": 0,
        "cases_advanced_count": 0,
        "cases_finalized_count": 0,
    }

    # 1. ATT ISSUED with expires_on < now -> EXPIRED
    for att in STORE.atts.values():
        if att["status"] == "ISSUED" and att["expires_on"] < now:
            att["status"] = "EXPIRED"
            touch(att)
            counters["att_expired_count"] += 1

    # 2. Attempt SCHEDULED with scheduled_end < now -> NO_SHOW (ATT -> CONSUMED)
    for attempt in STORE.attempts.values():
        if attempt["status"] == "SCHEDULED" and attempt["scheduled_end"] < now:
            attempt["status"] = "NO_SHOW"
            touch(attempt)
            att = STORE.atts.get(attempt["att_id"])
            if att and att["status"] == "ISSUED":
                att["status"] = "CONSUMED"
                touch(att)
            counters["attempts_no_show_count"] += 1

    # 3. Certification ACTIVE with expires_on < now -> LAPSED
    for cert in STORE.certifications.values():
        if cert["status"] == "ACTIVE" and cert["expires_on"] < now:
            cert["status"] = "LAPSED"
            touch(cert)
            counters["certifications_lapsed_count"] += 1

    # 4. Certification LAPSED with lapse_deadline < now -> EXPIRED
    for cert in STORE.certifications.values():
        if cert["status"] == "LAPSED" and cert["lapse_deadline"] < now:
            cert["status"] = "EXPIRED"
            touch(cert)
            counters["certifications_expired_count"] += 1

    # 5. Certification SUSPENDED with suspension_ends <= now -> lifted
    for cert in STORE.certifications.values():
        if (cert["status"] == "SUSPENDED"
                and cert.get("suspension_ends") is not None
                and cert["suspension_ends"] <= now):
            cert["status"] = "ACTIVE" if cert["expires_on"] >= now else "LAPSED"
            cert["suspension_ends"] = None
            cert["_suspended_by_case_id"] = None
            touch(cert)
            counters["suspensions_lifted_count"] += 1

    # 6. DisciplinaryCase NOTICE_ISSUED with response_deadline < now -> UNDER_REVIEW
    for case in STORE.cases.values():
        if (case["status"] == "NOTICE_ISSUED"
                and case.get("response_deadline") is not None
                and case["response_deadline"] < now):
            case["status"] = "UNDER_REVIEW"
            touch(case)
            counters["cases_advanced_count"] += 1

    # 7. DisciplinaryCase DECIDED with appeal_deadline < now -> FINAL (cascades)
    for case in list(STORE.cases.values()):
        if (case["status"] == "DECIDED"
                and case.get("appeal_deadline") is not None
                and case["appeal_deadline"] < now):
            case["status"] = "FINAL"
            case["finalized_at"] = now
            touch(case)
            counters["cases_finalized_count"] += 1
            apply_sanction_cascade(case)

    return counters
