"""Shared cross-entity cascades and time-driven transitions.

- reverse_jd_cascade: JD ISSUED -> REVERSED suspends in-flight applications
  and releases their RESERVED credit transactions (SCAFFOLD §1.2 JD machine).
- compensation_cascade: application DENY / WITHDRAW unwinds plan credits
  (RESERVED -> RELEASED, PURCHASED -> REFUNDED) and cancels non-terminal
  plans (§3.7).
- issue_permit: render-decision ISSUE side effects (§3.7).
- clock_transitions: the five pinned evaluation steps of §2.5.
"""

from datetime import timedelta
from decimal import Decimal

import calculations as calc
from db import STORE, bump, get_clock, new_entity

SUSPENDABLE_APPLICATION_STATES = (
    "SUBMITTED", "SCREENING", "RETURNED_TO_APPLICANT",
    "ALTERNATIVES_REVIEW", "PUBLIC_NOTICE_OPEN", "DECISION_PENDING",
)

PLAN_NON_TERMINAL = (
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "CREDITS_SECURED",
)

GENERAL_PATHWAY_CONDITIONS = [
    "SC-GP-01: Erosion and sediment controls must be maintained for the "
    "duration of the authorized work",
    "SC-GP-02: Work must be completed within the general permit activity "
    "limits",
]
INDIVIDUAL_PATHWAY_CONDITIONS = [
    "SC-IP-01: Five years of mitigation monitoring reports are required",
    "SC-IP-02: Long-term stewardship must be maintained by the designated "
    "stewardship entity",
    "SC-IP-03: Compensatory mitigation must remain secured for the life of "
    "the project",
]


def _plans_of(application_id):
    return [p for p in STORE["plans"].values()
            if p["application_id"] == application_id]


def _txns_of_plans(plan_ids):
    return [t for t in STORE["credit_txns"].values() if t["plan_id"] in plan_ids]


def release_reserved_transactions(application):
    """Every RESERVED credit transaction of the application's plans ->
    RELEASED (bank inventory restored on read)."""
    plan_ids = {p["id"] for p in _plans_of(application["id"])}
    for txn in _txns_of_plans(plan_ids):
        if txn["status"] == "RESERVED":
            txn["status"] = "RELEASED"
            bump(txn)


def reverse_jd_cascade(jd):
    """JD ISSUED -> REVERSED with the full suspension cascade."""
    jd["status"] = "REVERSED"
    bump(jd)
    for app in STORE["applications"].values():
        if app["jd_id"] == jd["id"] and app["status"] in \
                SUSPENDABLE_APPLICATION_STATES:
            app["status"] = "SUSPENDED_PENDING_JD"
            bump(app)
            release_reserved_transactions(app)


def compensation_cascade(application):
    """DENY / WITHDRAW unwind: RESERVED -> RELEASED, PURCHASED -> REFUNDED,
    every non-terminal plan -> CANCELLED."""
    plans = _plans_of(application["id"])
    plan_ids = {p["id"] for p in plans}
    for txn in _txns_of_plans(plan_ids):
        if txn["status"] == "RESERVED":
            txn["status"] = "RELEASED"
            bump(txn)
        elif txn["status"] == "PURCHASED":
            txn["status"] = "REFUNDED"
            bump(txn)
    for plan in plans:
        if plan["status"] in PLAN_NON_TERMINAL:
            plan["status"] = "CANCELLED"
            bump(plan)


def issue_permit(application):
    """Create the Permit, activate the secured plan, generate the five-report
    monitoring schedule, and close an after-the-fact case. Returns the new
    Permit."""
    clock = get_clock()
    pathway = application["pathway"]
    is_general = pathway in ("GENERAL", "ATF_GENERAL")
    permit = new_entity({
        "application_id": application["id"],
        "permit_number": "WP-%04d" % (len(STORE["permits"]) + 1),
        "issue_date": clock,
        "expiration_date": clock + timedelta(days=calc.JD_VALIDITY_DAYS),
        "special_conditions": list(GENERAL_PATHWAY_CONDITIONS if is_general
                                   else INDIVIDUAL_PATHWAY_CONDITIONS),
        "status": "ISSUED",
    })
    STORE["permits"][permit["id"]] = permit

    secured_plan = None
    for plan in _plans_of(application["id"]):
        if plan["status"] == "CREDITS_SECURED":
            secured_plan = plan
            break
    if secured_plan is not None:
        secured_plan["status"] = "ACTIVE"
        bump(secured_plan)
        for index in range(1, calc.MONITORING_REPORT_COUNT + 1):
            report = new_entity({
                "permit_id": permit["id"],
                "plan_id": secured_plan["id"],
                "period_index": index,
                "due_date": clock + timedelta(
                    days=calc.MONITORING_INTERVAL_DAYS * index),
                "coverage_start": None,
                "coverage_end": None,
                "findings_text": None,
                "submitted_date": None,
                "outcome": None,
                "deficiency_notes": None,
                "status": "DUE",
            })
            STORE["reports"][report["id"]] = report

    if application["is_after_the_fact"] and application.get(
            "enforcement_case_id"):
        case = STORE["cases"].get(application["enforcement_case_id"])
        if case is not None and case["case_status"] == "RESOLUTION_PENDING":
            # ATF track: penalty fixed in full at closure (no offset),
            # rounded half-up to cents at fixation.
            case["case_status"] = "CLOSED"
            case["penalty_final_dollars"] = calc.q2(
                calc.penalty_accrued(case, clock))
            bump(case)
    return permit


def _active_plan_of_application(application_id):
    for plan in _plans_of(application_id):
        if plan["status"] == "ACTIVE":
            return plan
    return None


def clock_transitions(new_clock):
    """The five pinned time-driven evaluation steps (PRD §2.5), in order."""
    # (1) Published notices whose comment window has fully elapsed close.
    for app in STORE["applications"].values():
        if app["notice_status"] != "PUBLISHED":
            continue
        close_at = app["notice_published_date"] + timedelta(
            days=app["comment_period_days"])
        if new_clock > close_at:
            app["notice_status"] = "COMMENT_PERIOD_CLOSED"
            bump(app)

    # (2) Permits ISSUED or ACTIVE past expiration_date -> EXPIRED; each such
    #     permit's linked ACTIVE plan -> DEFAULTED.
    for permit in STORE["permits"].values():
        if permit["status"] in ("ISSUED", "ACTIVE") \
                and new_clock > permit["expiration_date"]:
            permit["status"] = "EXPIRED"
            bump(permit)
            plan = _active_plan_of_application(permit["application_id"])
            if plan is not None:
                plan["status"] = "DEFAULTED"
                bump(plan)

    # (3) DUE reports whose due_date has passed -> OVERDUE, only for permits
    #     still ACTIVE after step 2.
    for report in STORE["reports"].values():
        if report["status"] != "DUE":
            continue
        permit = STORE["permits"].get(report["permit_id"])
        if permit is None or permit["status"] != "ACTIVE":
            continue
        if new_clock > report["due_date"]:
            report["status"] = "OVERDUE"
            bump(report)

    # (4) Breach escalation: OVERDUE reports strictly past due_date + 60 days
    #     on a permit still ACTIVE suspend the permit and auto-open a
    #     MONITORING_BREACH enforcement case.
    for report in STORE["reports"].values():
        if report["status"] != "OVERDUE":
            continue
        permit = STORE["permits"].get(report["permit_id"])
        if permit is None or permit["status"] != "ACTIVE":
            continue
        if new_clock > report["due_date"] + timedelta(
                days=calc.OVERDUE_BREACH_DAYS):
            permit["status"] = "SUSPENDED"
            bump(permit)
            application = STORE["applications"].get(permit["application_id"])
            case = new_entity({
                "site_id": application["site_id"] if application else None,
                "responsible_applicant_id": (
                    application["applicant_id"] if application else None),
                "unauthorized_fill_acres": Decimal("0"),
                "description": "Monitoring report overdue by more than 60 "
                               "days (compliance breach)",
                "case_source": "MONITORING_BREACH",
                "opened_by_officer_id": "SYSTEM",
                "opened_date": new_clock,
                "confirmed_date": None,
                "penalty_final_dollars": None,
                "resolution_track": "NONE",
                "atf_application_id": None,
                "restoration_deadline": None,
                "extension_used": False,
                "case_status": "OPENED",
            })
            STORE["cases"][case["id"]] = case

    # (5) RESTORATION-track cases in RESOLUTION_PENDING past their deadline
    #     -> DEFAULTED.
    for case in STORE["cases"].values():
        if case["case_status"] == "RESOLUTION_PENDING" \
                and case["resolution_track"] == "RESTORATION" \
                and case["restoration_deadline"] is not None \
                and new_clock > case["restoration_deadline"]:
            case["case_status"] = "DEFAULTED"
            bump(case)
