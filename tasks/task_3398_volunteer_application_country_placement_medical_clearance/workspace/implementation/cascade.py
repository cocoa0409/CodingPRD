"""Cross-aggregate cascades (PRD 2.11) and the deterministic clock sweep.

Every resource a cascade touches is genuinely mutated: updated_at refreshes
and version increments per individual mutation (PRD 2.5, 2.7).
"""
from db import STORE, parse_dt, touch, ts_sec


def get_opening(oid):
    return STORE["assignment_openings"].get(oid)


def get_application(aid):
    return STORE["applications"].get(aid)


def release_provisional(inv):
    """An ISSUED invitation ends: held seat released."""
    opening = get_opening(inv["assignment_opening_id"])
    if opening is not None:
        opening["seats_provisional"] -= 1
        touch(opening)


def release_committed(inv):
    """An ACCEPTED invitation is rescinded: committed seat released; a FILLED
    opening drops back to OPEN when committed falls below seats_total."""
    opening = get_opening(inv["assignment_opening_id"])
    if opening is not None:
        opening["seats_committed"] -= 1
        touch(opening)
        if (opening["status"] == "FILLED"
                and opening["seats_committed"] < opening["seats_total"]):
            opening["status"] = "OPEN"
            touch(opening)


def accepted_invitation_of(app_id):
    for inv in STORE["invitations"].values():
        if inv["application_id"] == app_id and inv["status"] == "ACCEPTED":
            return inv
    return None


def issued_invitation_of(app_id):
    for inv in STORE["invitations"].values():
        if inv["application_id"] == app_id and inv["status"] == "ISSUED":
            return inv
    return None


def void_inflight_medical(app_id):
    for mc in STORE["medical_clearances"].values():
        if mc["application_id"] == app_id and mc["status"] in ("SUBMITTED", "DEFERRED"):
            mc["status"] = "VOID"
            touch(mc)


def void_legal(app_id):
    for lc in STORE["legal_clearances"].values():
        if lc["application_id"] == app_id and lc["lifecycle"] == "ACTIVE":
            lc["lifecycle"] = "VOID"
            touch(lc)


def legal_overall(lc):
    """Derived overall_status: VOID > DENIED > CLEARED > PENDING."""
    if lc["lifecycle"] == "VOID":
        return "VOID"
    if lc["background_check_status"] == "ADVERSE" or lc["suitability_status"] == "UNFAVORABLE":
        return "DENIED"
    if lc["background_check_status"] == "CLEAR" and lc["suitability_status"] == "FAVORABLE":
        return "CLEARED"
    return "PENDING"


def rescind_invitation(inv, revert_application=True):
    """Rescind an ISSUED or ACCEPTED invitation and release its seat. With
    revert_application the parent application returns to UNDER_REVIEW."""
    app = get_application(inv["application_id"])
    if inv["status"] == "ISSUED":
        inv["status"] = "RESCINDED"
        touch(inv)
        release_provisional(inv)
        if revert_application and app is not None and app["status"] == "INVITED":
            app["status"] = "UNDER_REVIEW"
            touch(app)
    elif inv["status"] == "ACCEPTED":
        inv["status"] = "RESCINDED"
        touch(inv)
        release_committed(inv)
        if revert_application and app is not None and app["status"] == "ACCEPTED":
            app["status"] = "UNDER_REVIEW"
            touch(app)


def denial_cascade(app_id):
    """Medical DENIED / legal ADVERSE / legal UNFAVORABLE: rescind the accepted
    invitation (reverting the application ACCEPTED -> UNDER_REVIEW and releasing
    the committed seat), void in-flight medical clearances, void the legal
    clearance lifecycle (a denial moves the application out of the pipeline)."""
    inv = accepted_invitation_of(app_id)
    if inv is not None:
        rescind_invitation(inv, revert_application=True)
    else:
        app = get_application(app_id)
        if app is not None and app["status"] == "ACCEPTED":
            app["status"] = "UNDER_REVIEW"
            touch(app)
    void_inflight_medical(app_id)
    void_legal(app_id)


def cancel_opening_cascade(opening):
    """Opening cancellation: rescind every ISSUED and ACCEPTED invitation;
    ISSUED applications revert INVITED -> UNDER_REVIEW; ACCEPTED applications
    revert ACCEPTED -> UNDER_REVIEW with in-flight clearances voided."""
    for inv in list(STORE["invitations"].values()):
        if inv["assignment_opening_id"] != opening["id"]:
            continue
        if inv["status"] == "ISSUED":
            rescind_invitation(inv, revert_application=True)
        elif inv["status"] == "ACCEPTED":
            rescind_invitation(inv, revert_application=True)
            void_inflight_medical(inv["application_id"])
            void_legal(inv["application_id"])


def withdraw_cascade(app):
    """Application withdrawal side effects, shaped by the pre-withdrawal state."""
    status = app["status"]
    if status in ("UNDER_REVIEW", "INTERVIEWING"):
        for iv in STORE["interviews"].values():
            if iv["application_id"] == app["id"] and iv["status"] == "SCHEDULED":
                iv["status"] = "CANCELLED"
                touch(iv)
    elif status == "INVITED":
        inv = issued_invitation_of(app["id"])
        if inv is not None:
            inv["status"] = "DECLINED"
            touch(inv)
            release_provisional(inv)
    elif status == "ACCEPTED":
        inv = accepted_invitation_of(app["id"])
        if inv is not None:
            rescind_invitation(inv, revert_application=False)
        void_inflight_medical(app["id"])
        void_legal(app["id"])
    elif status in ("CLEARED_TO_DEPART", "IN_TRAINING"):
        inv = accepted_invitation_of(app["id"])
        if inv is not None:
            rescind_invitation(inv, revert_application=False)
        for en in STORE["training_enrollments"].values():
            if (en["application_id"] == app["id"]
                    and en["status"] in ("ENROLLED", "REMEDIATION", "FAILED")):
                en["status"] = "SEPARATED"
                touch(en)
                cohort = STORE["training_cohorts"].get(en["training_cohort_id"])
                if cohort is not None:
                    cohort["enrolled_count"] -= 1
                    touch(cohort)


def separate_trainee(enrollment):
    """Second consecutive FAILED assessment: enrollment SEPARATED, application
    SEPARATED (terminal), accepted invitation rescinded, cohort count released."""
    enrollment["status"] = "SEPARATED"
    touch(enrollment)
    app = get_application(enrollment["application_id"])
    inv = accepted_invitation_of(enrollment["application_id"])
    if inv is not None:
        rescind_invitation(inv, revert_application=False)
    if app is not None:
        app["status"] = "SEPARATED"
        touch(app)
    cohort = STORE["training_cohorts"].get(enrollment["training_cohort_id"])
    if cohort is not None:
        cohort["enrolled_count"] -= 1
        touch(cohort)


def clock_sweep(to):
    """Pinned sweep order (PRD 2.4): invitations expire, openings close,
    cohorts start, cohorts conclude. Expiry/closure use strict <; session
    start/conclusion use <=; all comparisons at second precision."""
    t = ts_sec(to)
    # 1. Invitation expiry
    for inv in list(STORE["invitations"].values()):
        if inv["status"] == "ISSUED":
            deadline = parse_dt(inv["acceptance_deadline"])
            if deadline is not None and ts_sec(deadline) < t:
                inv["status"] = "EXPIRED"
                touch(inv)
                release_provisional(inv)
                app = get_application(inv["application_id"])
                if app is not None and app["status"] == "INVITED":
                    app["status"] = "UNDER_REVIEW"
                    touch(app)
    # 2. Opening closure
    for opening in list(STORE["assignment_openings"].values()):
        if opening["status"] == "OPEN":
            deadline = parse_dt(opening["invitation_issue_deadline"])
            if deadline is not None and ts_sec(deadline) < t:
                opening["status"] = "CLOSED"
                touch(opening)
    # 3. Cohort session start
    for cohort in list(STORE["training_cohorts"].values()):
        if cohort["status"] == "SCHEDULED":
            start = parse_dt(cohort["start_date"])
            if start is not None and ts_sec(start) <= t:
                cohort["status"] = "IN_SESSION"
                touch(cohort)
                for en in STORE["training_enrollments"].values():
                    if (en["training_cohort_id"] == cohort["id"]
                            and en["status"] in ("ENROLLED", "REMEDIATION")):
                        app = get_application(en["application_id"])
                        if app is not None and app["status"] == "CLEARED_TO_DEPART":
                            app["status"] = "IN_TRAINING"
                            touch(app)
    # 4. Cohort conclusion
    for cohort in list(STORE["training_cohorts"].values()):
        if cohort["status"] == "IN_SESSION":
            end = parse_dt(cohort["end_date"])
            if end is not None and ts_sec(end) <= t:
                cohort["status"] = "CONCLUDED"
                touch(cohort)
