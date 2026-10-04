"""Cross-entity cascades shared by the route modules.

Every mutation driven by a cascade bumps the affected resource's version and
refreshes its updated_at (PRD section 2.5), which ``helpers.bump`` performs.
"""

import constants
from helpers import bump, common_fields, now, stamp_now
from store import db


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def mediations_for_charge(charge):
    return [
        m for m in db.mediation_cases.values() if m["charge_id"] == charge["id"]
    ]


def sessions_for_mediation(mediation):
    return [
        s
        for s in db.mediation_sessions.values()
        if s["mediation_case_id"] == mediation["id"]
    ]


def investigation_for_charge(charge):
    inv_id = charge["investigation_case_id"]
    if inv_id is None:
        return None
    return db.investigation_cases.get(inv_id)


def requests_for_investigation(investigation):
    return [
        r
        for r in db.evidence_requests.values()
        if r["investigation_case_id"] == investigation["id"]
    ]


def linked_charges(systemic_case):
    return [
        c
        for c in db.charges.values()
        if c["systemic_case_id"] == systemic_case["id"]
    ]


# ---------------------------------------------------------------------------
# Investigation lifecycle cascades
# ---------------------------------------------------------------------------
def auto_create_investigation(charge):
    """Create the 1:1 InvestigationCase (OPEN, unassigned) and stamp it on
    the charge. No-op when the charge already has one."""
    if charge["investigation_case_id"] is not None:
        return db.investigation_cases[charge["investigation_case_id"]]
    investigation = {
        **common_fields(),
        "charge_id": charge["id"],
        "assigned_investigator_id": None,
        "status": constants.INVESTIGATION_OPEN,
        "open_request_count": 0,
        "overdue_request_count": 0,
        "priority_score": 0,
    }
    db.investigation_cases[investigation["id"]] = investigation
    charge["investigation_case_id"] = investigation["id"]
    return investigation


def waive_open_requests(investigation):
    for request_row in requests_for_investigation(investigation):
        if request_row["status"] in (
            constants.EVIDENCE_PENDING,
            constants.EVIDENCE_OVERDUE,
        ):
            request_row["status"] = constants.EVIDENCE_WAIVED
            bump(request_row)
    investigation["open_request_count"] = 0
    investigation["overdue_request_count"] = 0


def close_investigation(investigation):
    """InvestigationCase -> CLOSED with its PENDING/OVERDUE requests WAIVED."""
    if investigation["status"] == constants.INVESTIGATION_CLOSED:
        return
    waive_open_requests(investigation)
    investigation["status"] = constants.INVESTIGATION_CLOSED
    bump(investigation)


# ---------------------------------------------------------------------------
# Mediation cascades
# ---------------------------------------------------------------------------
def cancel_scheduled_sessions(mediation):
    for session in sessions_for_mediation(mediation):
        if session["status"] == constants.SESSION_SCHEDULED:
            session["status"] = constants.SESSION_CANCELLED
            bump(session)


def decline_open_mediations(charge):
    """Move any OFFERED or ACTIVE MediationCase of the charge to DECLINED,
    cancelling still-SCHEDULED sessions."""
    for mediation in mediations_for_charge(charge):
        if mediation["status"] in (
            constants.MEDIATION_OFFERED,
            constants.MEDIATION_ACTIVE,
        ):
            cancel_scheduled_sessions(mediation)
            mediation["status"] = constants.MEDIATION_DECLINED
            bump(mediation)


# ---------------------------------------------------------------------------
# Lazy transitions with no side effects
# ---------------------------------------------------------------------------
def refresh_session_lazy(session):
    """SCHEDULED -> HELD once the logical clock passes scheduled_end."""
    if (
        session["status"] == constants.SESSION_SCHEDULED
        and now() > session["scheduled_end"]
    ):
        session["status"] = constants.SESSION_HELD
        bump(session)


def refresh_notice_lazy(notice):
    """ISSUED -> EXPIRED once the clock date is strictly after the filing
    deadline (still ISSUED on the exact deadline date)."""
    if (
        notice["status"] == constants.RTS_ISSUED
        and now().date() > notice["court_filing_deadline"]
    ):
        notice["status"] = constants.RTS_EXPIRED
        bump(notice)


# ---------------------------------------------------------------------------
# Systemic consolidation / resolution
# ---------------------------------------------------------------------------
def reeval_systemic(systemic_case):
    """Re-evaluate linked_charge_count and the consolidation/resolution
    thresholds. Forward-only: OPENED -> EXPANDING -> CONSOLIDATED -> RESOLVED
    (RESOLVED is terminal; the status never regresses). Resolution lifts the
    seal on every linked charge. Bumps versions only on real change."""
    linked = linked_charges(systemic_case)
    non_terminal = [
        c
        for c in linked
        if c["case_status"] not in constants.SYSTEMIC_TERMINAL_CHARGE_STATES
    ]
    changed = False

    if systemic_case["linked_charge_count"] != len(linked):
        systemic_case["linked_charge_count"] = len(linked)
        changed = True

    if systemic_case["status"] != constants.SYSTEMIC_RESOLVED:
        if len(linked) >= 1 and len(non_terminal) == 0:
            systemic_case["status"] = constants.SYSTEMIC_RESOLVED
            changed = True
            for charge in linked:
                if charge["disclosure_hold"] == constants.HOLD_SEALED:
                    charge["disclosure_hold"] = constants.HOLD_NONE
                    bump(charge)
        else:
            if (
                systemic_case["status"] == constants.SYSTEMIC_OPENED
                and len(linked) >= 1
            ):
                systemic_case["status"] = constants.SYSTEMIC_EXPANDING
                changed = True
            if systemic_case["status"] == constants.SYSTEMIC_EXPANDING:
                sharing = [
                    c
                    for c in non_terminal
                    if set(c["basis_codes"]) & set(systemic_case["basis_focus"])
                ]
                if (
                    len(non_terminal) >= constants.CONSOLIDATION_MIN_CHARGES
                    and len(sharing) >= constants.CONSOLIDATION_MIN_SHARED_BASIS
                ):
                    systemic_case["status"] = constants.SYSTEMIC_CONSOLIDATED
                    changed = True

    if changed:
        bump(systemic_case)
    return systemic_case


def reeval_systemic_for_charge(charge):
    """Bubble a linked charge's transition up to its SystemicCase."""
    if charge["systemic_case_id"] is None:
        return
    systemic_case = db.systemic_cases.get(charge["systemic_case_id"])
    if systemic_case is not None:
        reeval_systemic(systemic_case)


# ---------------------------------------------------------------------------
# Disclosure audit
# ---------------------------------------------------------------------------
def record_disclosure(charge, accessor_role, accessor_user_id, legal_basis, target_description):
    """Append a DisclosureRecord (append-only: id + created_at only)."""
    record = {
        "id": common_fields()["id"],
        "created_at": stamp_now(),
        "_seq": db.next_seq(),
        "charge_id": charge["id"],
        "accessor_role": accessor_role,
        "accessor_user_id": accessor_user_id,
        "legal_basis": legal_basis,
        "target_description": target_description,
        "disclosed_at": now(),
    }
    db.disclosure_records[record["id"]] = record
    return record
