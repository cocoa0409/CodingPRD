"""Multi-hop cascade routines shared by the write endpoints."""
import domain as D
from services import compute, money
from store import clock_date, db, iso_date, ordered, pd, set_field, set_fields


def cancel_scheduled_visits(authorization, outcome):
    for visit in compute.auth_visits(authorization["id"]):
        if visit["visit_status"] != "SCHEDULED":
            continue
        set_fields(visit, {
            "visit_status": outcome,
            "billing_status": "CANCELLED_NO_CHARGE",
            "actual_units": 0,
            "family_share_cents": 0,
        })


def release_authorization(authorization, reason, outcome):
    """Move an authorization to REVOKED, releasing its unspent units."""
    set_fields(authorization, {
        "status": "REVOKED",
        "units_released": (authorization["units_released"] or 0)
                          + max(0, authorization["units_remaining"] or 0),
        "revoked_date": iso_date(clock_date()),
        "revocation_reason_code": reason,
    })
    compute.recompute_auth_units(authorization)
    cancel_scheduled_visits(authorization, outcome)
    compute.recompute_provider_count(db.providers.get(authorization["provider_id"]))


def suspend_authorization(authorization):
    set_field(authorization, "status", "SUSPENDED")
    cancel_scheduled_visits(authorization, "CANCELLED_PROVIDER")
    compute.recompute_provider_count(db.providers.get(authorization["provider_id"]))


def provider_cascade(provider, terminated):
    """Hop chain for provider suspension / termination."""
    touched_lines = []
    for authorization in ordered(db.authorizations,
                                 [a for a in db.authorizations.values()
                                  if a["provider_id"] == provider["id"]]):
        if authorization["status"] != "ACTIVE":
            continue
        if terminated:
            release_authorization(authorization, "PROVIDER_TERMINATED",
                                  "CANCELLED_PROVIDER")
        else:
            suspend_authorization(authorization)
        line = compute.line_of_auth(authorization)
        if line is not None and line["id"] not in [l["id"] for l in touched_lines]:
            touched_lines.append(line)
    referrals = []
    for line in touched_lines:
        compute.recompute_line_pool(line)
        compute.recompute_makeup(line)
        referral = compute.referral_of_line(line)
        if referral is not None and referral["id"] not in [r["id"] for r in referrals]:
            referrals.append(referral)
    for referral in referrals:
        compute.recompute_service_gap(referral)
        compute.recompute_case_weight(referral)
        compute.recompute_coordinator(db.coordinators.get(referral["coordinator_id"]))


def discontinue_plan_lines(plan, authorization_reason, visit_outcome):
    lines = []
    for line in compute.ifsp_lines(plan["id"]):
        if line["status"] == "DISCONTINUED":
            continue
        for authorization in compute.line_authorizations(line["id"]):
            if authorization["status"] in D.AUTHORIZATION_REVOCABLE:
                release_authorization(authorization, authorization_reason,
                                      visit_outcome)
        set_field(line, "status", "DISCONTINUED")
        compute.recompute_line_pool(line)
        lines.append(line)
    compute.recompute_ifsp_counts(plan)
    return lines


def cancel_draft_transition_plans(plan):
    for tp in compute.ifsp_transition_plans(plan["id"]):
        if tp["status"] == "DRAFT":
            set_field(tp, "status", "CANCELLED")


def supersede_plan(plan):
    """Prior ACTIVE plan retired by an activated ANNUAL successor."""
    set_field(plan, "status", "SUPERSEDED")
    discontinue_plan_lines(plan, "PLAN_SUPERSEDED", "CANCELLED_PROGRAM")
    cancel_draft_transition_plans(plan)


def withdraw_draft_plans(referral):
    """Plans still unratified are withdrawn when the case steps back."""
    for plan in compute.referral_ifsps(referral["id"]):
        if plan["status"] not in ("DRAFT", "PENDING_CONSENT"):
            continue
        set_field(plan, "status", "WITHDRAWN")
        for line in compute.ifsp_lines(plan["id"]):
            if line["status"] != "DISCONTINUED":
                set_field(line, "status", "DISCONTINUED")
                compute.recompute_line_pool(line)
        compute.recompute_ifsp_counts(plan)
        cancel_draft_transition_plans(plan)


def exit_service_cascade(referral):
    """Full teardown when a case in ACTIVE_SERVICES exits."""
    for plan in compute.referral_ifsps(referral["id"]):
        if plan["status"] not in ("ACTIVE", "AMENDMENT_PENDING"):
            continue
        set_field(plan, "status", "CLOSED")
        discontinue_plan_lines(plan, "CASE_EXITED", "CANCELLED_PROGRAM")
        for tp in compute.ifsp_transition_plans(plan["id"]):
            if tp["status"] in ("NOTIFIED", "OPT_OUT"):
                set_field(tp, "status", "COMPLETE")
            elif tp["status"] == "DRAFT":
                set_field(tp, "status", "CANCELLED")
    for cost_share in compute.referral_cost_shares(referral["id"]):
        if cost_share["status"] in D.COST_SHARE_LIVE:
            set_field(cost_share, "status", "CLOSED")


def cancel_scheduled_assessments(referral):
    for assessment in compute.referral_assessments(referral["id"]):
        if assessment["status"] == "SCHEDULED":
            set_field(assessment, "status", "CANCELLED")


def expire_authorizations():
    """Clock-advance hop: ACTIVE windows whose end_date has passed."""
    today = clock_date()
    lines = []
    for authorization in ordered(db.authorizations):
        if authorization["status"] != "ACTIVE":
            continue
        end = pd(authorization["end_date"])
        if end is None or end >= today:
            continue
        set_fields(authorization, {
            "status": "EXPIRED",
            "units_released": (authorization["units_released"] or 0)
                              + max(0, authorization["units_remaining"] or 0),
        })
        compute.recompute_auth_units(authorization)
        compute.recompute_provider_count(db.providers.get(authorization["provider_id"]))
        line = compute.line_of_auth(authorization)
        if line is not None:
            lines.append(line)
    seen = set()
    for line in lines:
        if line["id"] in seen:
            continue
        seen.add(line["id"])
        compute.recompute_line_pool(line)


def clock_cascade():
    """Everything the logical clock governs is recomputed on a clock set."""
    expire_authorizations()
    coordinators = []
    for referral in ordered(db.referrals):
        if referral["status"] not in D.REFERRAL_TERMINAL:
            compute.recompute_timeline(referral)
            compute.recompute_case_weight(referral)
            compute.recompute_monthly_contact(referral)
            coordinator = db.coordinators.get(referral["coordinator_id"])
            if coordinator is not None and coordinator["id"] not in coordinators:
                coordinators.append(coordinator["id"])
    for coordinator_id in coordinators:
        compute.recompute_coordinator(db.coordinators.get(coordinator_id))
