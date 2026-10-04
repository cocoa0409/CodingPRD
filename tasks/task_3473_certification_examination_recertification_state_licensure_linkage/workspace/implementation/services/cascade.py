"""Ordered cascades (PRD §2.9, §3.2, §3.9): program revocation, completion
invalidation, attempt voiding, and the FINAL sanction cascade. Every hop
computes its target set only after the previous hop has landed; every mutation
refreshes updated_at and bumps version."""

from db import STORE, SUSPENSION_MONTHS, touch, now_dt
from util import add_months

SANCTION_RANK = {"NONE": 0, "WARNING": 1, "SUSPENSION_12M": 2,
                 "REVOCATION": 3, "PERMANENT_BAR": 4}


def _deny_license_apps_citing(cert_ids):
    """Credential-mediated license denial: UNDER_REVIEW | MORE_INFO_REQUIRED
    applications citing a just-revoked certification -> DENIED."""
    ids = set(cert_ids)
    if not ids:
        return
    for la in STORE.licenses.values():
        if (la.get("certification_id") in ids
                and la["status"] in ("UNDER_REVIEW", "MORE_INFO_REQUIRED")):
            la["status"] = "DENIED"
            la["decision_reason"] = "cited certification revoked"
            touch(la)


def _revoke_certification(cert, case_id=None):
    cert["pre_sanction_status"] = cert["status"]
    cert["status"] = "REVOKED"
    if case_id:
        cert["revoked_by_case_id"] = case_id
    touch(cert)


def _deny_exam_apps_citing(record_ids):
    ids = set(record_ids)
    for app in STORE.exam_apps.values():
        if app["completion_record_id"] in ids and app["status"] == "SUBMITTED":
            app["status"] = "DENIED"
            app["denial_reason"] = app.get("denial_reason") or "eligibility basis invalidated"
            app["decided_at"] = now_dt()
            touch(app)


def _certs_on_completion_basis(record_ids):
    ids = set(record_ids)
    return [c for c in STORE.certifications.values()
            if c["basis_completion_record_id"] in ids
            and c["status"] in ("ACTIVE", "SUSPENDED", "LAPSED")]


def _certs_on_attempt_basis(attempt_ids):
    ids = set(attempt_ids)
    return [c for c in STORE.certifications.values()
            if c["basis_attempt_id"] in ids
            and c["status"] in ("ACTIVE", "SUSPENDED", "LAPSED")]


def invalidate_completion_record(record, case_id=None):
    """VERIFIED -> INVALIDATED, then the published sub-hops (PRD §3.3)."""
    record["status"] = "INVALIDATED"
    if case_id:
        record["invalidated_by_case_id"] = case_id
    touch(record)
    _deny_exam_apps_citing([record["id"]])
    certs = _certs_on_completion_basis([record["id"]])
    for cert in certs:
        _revoke_certification(cert, case_id)
    _deny_license_apps_citing([c["id"] for c in certs])


def void_attempt(attempt, case_id):
    """SCORED_PASS | SCORED_FAIL -> VOIDED with compensation cascade (PRD §3.4)."""
    attempt["status"] = "VOIDED"
    attempt["voided_by_case_id"] = case_id
    touch(attempt)
    certs = _certs_on_attempt_basis([attempt["id"]])
    for cert in certs:
        _revoke_certification(cert, case_id)
    _deny_license_apps_citing([c["id"] for c in certs])


def program_revocation_cascade(program, effective_date):
    """Five ordered hops of the program-revocation cascade (PRD §3.2)."""
    # Hop 1: PENDING_VERIFICATION completion records -> REJECTED
    for r in STORE.completions.values():
        if r["program_id"] == program["id"] and r["status"] == "PENDING_VERIFICATION":
            r["status"] = "REJECTED"
            touch(r)
    # Hop 1b: VERIFIED records completed strictly after the revocation
    # effective_date -> INVALIDATED
    invalidated = []
    for r in STORE.completions.values():
        if (r["program_id"] == program["id"] and r["status"] == "VERIFIED"
                and r["completion_date"] > effective_date.date()):
            invalidated.append(r)
    for r in invalidated:
        r["status"] = "INVALIDATED"
        touch(r)
    # Hop 2: SUBMITTED exam applications citing those records -> DENIED
    inv_ids = {r["id"] for r in invalidated}
    for app in STORE.exam_apps.values():
        if app["completion_record_id"] in inv_ids and app["status"] == "SUBMITTED":
            app["status"] = "DENIED"
            app["denial_reason"] = "program revocation"
            app["decided_at"] = now_dt()
            touch(app)
    # Hop 3: certifications on those records (ACTIVE | SUSPENDED | LAPSED) -> REVOKED
    revoked = []
    for cert in STORE.certifications.values():
        if (cert["basis_completion_record_id"] in inv_ids
                and cert["status"] in ("ACTIVE", "SUSPENDED", "LAPSED")):
            _revoke_certification(cert)
            revoked.append(cert["id"])
    # Hop 4: license applications citing those certifications -> DENIED
    _deny_license_apps_citing(revoked)


def apply_sanction_cascade(case):
    """Sanction cascade on entry to FINAL (PRD §3.9), steps in pinned order."""
    now = now_dt()
    subject_id = case["subject_candidate_id"]
    sanction = case["sanction_type"]
    rank = SANCTION_RANK.get(sanction, 0)

    # Step 1: NONE | WARNING restores certifications this case interim-suspended.
    if sanction in ("NONE", "WARNING"):
        for cert in STORE.certifications.values():
            if (cert.get("_suspended_by_case_id") == case["id"]
                    and cert["status"] == "SUSPENDED"):
                cert["status"] = "ACTIVE" if cert["expires_on"] >= now else "LAPSED"
                cert["pre_sanction_status"] = None
                cert["suspension_ends"] = None
                cert["_suspended_by_case_id"] = None
                touch(cert)

    # Step 2: SUSPENSION_12M suspends the subject's ACTIVE | SUSPENDED certs.
    if sanction == "SUSPENSION_12M":
        for cert in STORE.certifications.values():
            if (cert["candidate_id"] == subject_id
                    and cert["status"] in ("ACTIVE", "SUSPENDED")):
                if cert["status"] != "SUSPENDED":
                    cert["pre_sanction_status"] = cert["status"]
                cert["status"] = "SUSPENDED"
                cert["suspension_ends"] = add_months(case["finalized_at"], SUSPENSION_MONTHS)
                touch(cert)

    # Step 3: REVOCATION | PERMANENT_BAR.
    if rank >= SANCTION_RANK["REVOCATION"]:
        revoked = []
        for cert in STORE.certifications.values():
            if (cert["candidate_id"] == subject_id
                    and cert["status"] in ("ACTIVE", "SUSPENDED", "LAPSED")):
                _revoke_certification(cert, case["id"])
                revoked.append(cert["id"])
        for att in STORE.atts.values():
            if att["candidate_id"] == subject_id and att["status"] == "ISSUED":
                att["status"] = "REVOKED"
                touch(att)
        for app in STORE.exam_apps.values():
            if app["candidate_id"] == subject_id and app["status"] == "SUBMITTED":
                app["status"] = "DENIED"
                app["denial_reason"] = "disciplinary sanction"
                app["decided_at"] = now
                touch(app)
        _deny_license_apps_citing(revoked)
        for ser in STORE.state_exams.values():
            if ser["candidate_id"] == subject_id and ser["status"] == "VALID":
                ser["status"] = "VOIDED"
                ser["voided_by_case_id"] = case["id"]
                touch(ser)
        if sanction == "PERMANENT_BAR":
            candidate = STORE.candidates.get(subject_id)
            if candidate and candidate["status"] != "BARRED":
                candidate["status"] = "BARRED"
                touch(candidate)

    # Step 4: FALSIFIED_EDUCATION at SUSPENSION_12M or higher invalidates the
    # implicated completion records (each with its own sub-cascade).
    if (case["violation_type"] == "FALSIFIED_EDUCATION"
            and rank >= SANCTION_RANK["SUSPENSION_12M"]):
        for rid in case.get("implicated_completion_record_ids") or []:
            record = STORE.completions.get(rid)
            if record and record["status"] == "VERIFIED":
                invalidate_completion_record(record, case["id"])

    # Step 5: EXAM_SECURITY at SUSPENSION_12M or higher voids the implicated
    # attempts (each with its compensation cascade).
    if (case["violation_type"] == "EXAM_SECURITY"
            and rank >= SANCTION_RANK["SUSPENSION_12M"]):
        for aid in case.get("implicated_attempt_ids") or []:
            attempt = STORE.attempts.get(aid)
            if attempt and attempt["status"] in ("SCORED_PASS", "SCORED_FAIL"):
                void_attempt(attempt, case["id"])
