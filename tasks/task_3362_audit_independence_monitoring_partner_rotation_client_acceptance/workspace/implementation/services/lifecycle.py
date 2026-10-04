"""Engagement lifecycle, acceptance decisions and client roll-up cascades."""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, new_row, store, touch
from core.errors import (
    ERR_ACCEPTANCE_CONDITIONS_UNMET,
    ERR_ATTESTATION_INCOMPLETE,
    ERR_ENGAGEMENT_FROZEN,
    ERR_FINDINGS_OPEN,
    ERR_INVALID_STATE,
    ApiError,
)
from services import calc
from services.independence import (
    commit_client,
    commit_engagement,
    live_findings,
    quality_review_required_for,
    recompute_client,
    recompute_engagement,
    refresh_all_assignments,
)


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------
def create_engagement_row(client, engagement_type, fiscal_year_end, is_multinational):
    row = new_row("engagements", {
        "client_id": client.get("id"),
        "engagement_type": engagement_type,
        "fiscal_year_end": fiscal_year_end,
        "is_multinational": bool(is_multinational),
        "status": "DRAFT",
        "independence_status": "CLEAR",
        "risk_tier": "LOW",
        "combined_risk_score": 0,
        "assigned_workload_points": 0,
        "lead_partner_id": None,
        "concurring_partner_id": None,
        "quality_review_required": bool(client.get("is_public_interest_entity")),
        "_suspended_by_independence": False,
        "_suspended_by_review_id": None,
    })
    return row


def _close_engagement(engagement, now):
    """End every ACTIVE assignment and retire the client when it was the last."""
    for assignment in all_rows("assignments"):
        if assignment.get("engagement_id") != engagement.get("id"):
            continue
        if assignment.get("status") != "ACTIVE":
            continue
        assignment["status"] = "ENDED"
        assignment["ended_on"] = now
        touch(assignment)
    refresh_all_assignments()
    engagement["_suspended_by_independence"] = False
    engagement["_suspended_by_review_id"] = None
    touch(engagement)
    client = store.clients.get(engagement.get("client_id"))
    if client is None:
        return
    remaining = [
        row for row in all_rows("engagements")
        if row.get("client_id") == client.get("id") and row.get("status") != "CLOSED"
    ]
    terminated = False
    if not remaining and client.get("status") in ("ACTIVE", "SUSPENDED"):
        client["status"] = "TERMINATED"
        terminated = True
    recompute_client(client)
    commit_client(client, force=terminated)


def apply_engagement_action(engagement, action, now=None):
    now = now or clock_now()
    status = engagement.get("status")
    if action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "SUSPEND requires an ACTIVE engagement.")
        engagement["status"] = "SUSPENDED"
        engagement["_suspended_by_independence"] = False
        touch(engagement)
    elif action == "RESUME":
        if status != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "RESUME requires a SUSPENDED engagement.")
        if engagement.get("independence_status") == "FROZEN":
            raise ApiError(ERR_ENGAGEMENT_FROZEN,
                           "A frozen engagement may not be resumed.")
        engagement["status"] = "ACTIVE"
        engagement["_suspended_by_independence"] = False
        engagement["_suspended_by_review_id"] = None
        touch(engagement)
    elif action == "CLOSE":
        if status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_STATE, "CLOSE requires an ACTIVE or SUSPENDED engagement.")
        if live_findings(engagement.get("id")):
            raise ApiError(ERR_FINDINGS_OPEN,
                           "The engagement still carries live independence findings.")
        if status == "ACTIVE":
            blocking = [
                row for row in all_rows("reviews")
                if row.get("engagement_id") == engagement.get("id")
                and row.get("status") in C.BLOCKING_REVIEW_STATUSES
            ]
            if blocking:
                raise ApiError(ERR_INVALID_STATE,
                               "The engagement still carries an open quality review.")
        engagement["status"] = "CLOSED"
        _close_engagement(engagement, now)
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown action '%s' for an engagement." % action)
    return engagement


# ---------------------------------------------------------------------------
# Client acceptances
# ---------------------------------------------------------------------------
def acceptance_variant(acceptance):
    return "PROVISIONAL" if acceptance.get("status") == "DRAFT" else "FINAL"


def acceptance_assessments(acceptance):
    return [
        row for row in all_rows("assessments")
        if row.get("acceptance_id") == acceptance.get("id")
    ]


def refresh_acceptance_scores(acceptance, touch_row=False):
    now = clock_now()
    client = store.clients.get(acceptance.get("client_id"))
    assessments = acceptance_assessments(acceptance)
    variant = acceptance_variant(acceptance)
    integrity = calc.integrity_score(assessments, now)
    risk = calc.client_risk_score(client, assessments, variant, now)
    combined = calc.clamp_score(risk)
    changed = (
        acceptance.get("integrity_score") != integrity
        or acceptance.get("risk_score") != risk
        or acceptance.get("combined_risk_score") != combined
    )
    acceptance["integrity_score"] = integrity
    acceptance["risk_score"] = risk
    acceptance["combined_risk_score"] = combined
    if changed and touch_row:
        touch(acceptance)
    return acceptance


def create_acceptance_row(client, engagement, proposed_by, industry_expertise_required,
                          industry_expertise_confirmed):
    row = new_row("acceptances", {
        "client_id": client.get("id"),
        "engagement_id": engagement.get("id"),
        "proposed_by": proposed_by,
        "industry_expertise_required": industry_expertise_required,
        "industry_expertise_confirmed": bool(industry_expertise_confirmed),
        "integrity_score": 0,
        "risk_score": 0,
        "combined_risk_score": 0,
        "status": "DRAFT",
        "decision_notes": None,
        "decided_at": None,
    })
    refresh_acceptance_scores(row)
    return row


def _unresolved_critical(acceptance):
    return any(
        row.get("severity") == "CRITICAL" and row.get("resolved") is not True
        for row in acceptance_assessments(acceptance)
    )


def _has_unresolved(acceptance):
    return any(row.get("resolved") is not True for row in acceptance_assessments(acceptance))


def submit_acceptance(acceptance):
    now = clock_now()
    if acceptance.get("status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT evaluation may be submitted.")
    assessments = acceptance_assessments(acceptance)
    if not assessments:
        raise ApiError(ERR_INVALID_STATE,
                       "At least one integrity assessment is required before submission.")
    if acceptance.get("industry_expertise_confirmed") is not True:
        raise ApiError(ERR_INVALID_STATE,
                       "Industry expertise must be confirmed before submission.")
    for row in assessments:
        assessed_on = row.get("assessed_on")
        if assessed_on is not None and assessed_on > now:
            from core.errors import ERR_ASSESSMENT_DATE_IN_FUTURE
            raise ApiError(ERR_ASSESSMENT_DATE_IN_FUTURE,
                           "An integrity assessment is dated later than the logical clock.")
    acceptance["status"] = "SUBMITTED"
    refresh_acceptance_scores(acceptance)
    touch(acceptance)
    engagement = store.engagements.get(acceptance.get("engagement_id"))
    if engagement is not None:
        engagement["status"] = "ACCEPTANCE_PENDING"
        touch(engagement)
    return acceptance


def _activation_gates(engagement):
    if engagement.get("independence_status") == "FROZEN":
        raise ApiError(ERR_ENGAGEMENT_FROZEN,
                       "A frozen engagement may not be activated.")
    for assignment in all_rows("assignments"):
        if assignment.get("engagement_id") != engagement.get("id"):
            continue
        if assignment.get("status") != "ACTIVE":
            continue
        for finding in live_findings(engagement.get("id")):
            if finding.get("professional_id") != assignment.get("professional_id"):
                continue
            if finding.get("severity") in ("HIGH", "CRITICAL"):
                raise ApiError(ERR_INVALID_STATE,
                               "An assigned professional carries a live high-severity finding.")
    if engagement.get("is_multinational"):
        for row in all_rows("attestations"):
            if row.get("engagement_id") == engagement.get("id") \
                    and row.get("attestation_status") == "PENDING":
                raise ApiError(ERR_ATTESTATION_INCOMPLETE,
                               "A multinational engagement still has a pending attestation.")


def _activate_engagement(acceptance, engagement, now):
    _activation_gates(engagement)
    client = store.clients.get(engagement.get("client_id"))
    engagement["combined_risk_score"] = acceptance.get("combined_risk_score")
    engagement["risk_tier"] = calc.risk_tier_for(acceptance.get("combined_risk_score"))
    engagement["quality_review_required"] = quality_review_required_for(engagement, client)
    engagement["status"] = "ACTIVE"
    engagement["_suspended_by_independence"] = False
    refresh_all_assignments()
    recompute_engagement(engagement)
    commit_engagement(engagement, force=True)
    if client is not None:
        promoted = client.get("status") in ("PROSPECT", "TERMINATED")
        if promoted:
            client["status"] = "ACTIVE"
        recompute_client(client)
        commit_client(client, force=promoted)


def apply_acceptance_decision(acceptance, decision, decision_notes, now=None):
    now = now or clock_now()
    status = acceptance.get("status")
    engagement = store.engagements.get(acceptance.get("engagement_id"))
    client = store.clients.get(acceptance.get("client_id"))
    if decision == "RETURN":
        if status != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "RETURN requires a SUBMITTED evaluation.")
        acceptance["status"] = "DRAFT"
        if decision_notes is not None:
            acceptance["decision_notes"] = decision_notes
        touch(acceptance)
        if engagement is not None:
            engagement["status"] = "DRAFT"
            engagement["risk_tier"] = "LOW"
            engagement["combined_risk_score"] = 0
            touch(engagement)
    elif decision == "APPROVE":
        if status not in ("SUBMITTED", "CONDITIONAL"):
            raise ApiError(ERR_INVALID_STATE, "APPROVE requires a SUBMITTED or CONDITIONAL evaluation.")
        combined = acceptance.get("combined_risk_score") or 0
        if status == "SUBMITTED":
            if combined >= C.APPROVAL_RISK_CEILING:
                raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                               "The combined risk score is not admissible for approval.")
            if _unresolved_critical(acceptance):
                raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                               "An unresolved CRITICAL integrity assessment remains.")
        else:
            if acceptance.get("industry_expertise_confirmed") is not True:
                raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                               "Industry expertise must be confirmed before approval.")
            if _unresolved_critical(acceptance):
                raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                               "An unresolved CRITICAL integrity assessment remains.")
        if engagement is None:
            raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                           "The governing engagement no longer exists.")
        _activate_engagement(acceptance, engagement, now)
        acceptance["status"] = "APPROVED"
        acceptance["decided_at"] = now
        if decision_notes is not None:
            acceptance["decision_notes"] = decision_notes
        touch(acceptance)
    elif decision == "CONDITIONAL":
        if status != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "CONDITIONAL requires a SUBMITTED evaluation.")
        combined = acceptance.get("combined_risk_score") or 0
        if not (C.CONDITIONAL_RISK_FLOOR <= combined < C.APPROVAL_RISK_CEILING):
            raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                           "The combined risk score is not admissible for a conditional decision.")
        if not _has_unresolved(acceptance):
            raise ApiError(ERR_ACCEPTANCE_CONDITIONS_UNMET,
                           "A conditional decision requires at least one unresolved assessment.")
        acceptance["status"] = "CONDITIONAL"
        acceptance["decided_at"] = now
        if decision_notes is not None:
            acceptance["decision_notes"] = decision_notes
        touch(acceptance)
        if engagement is not None:
            engagement["quality_review_required"] = True
            touch(engagement)
    elif decision == "REJECT":
        if status != "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, "REJECT requires a SUBMITTED evaluation.")
        acceptance["status"] = "REJECTED"
        acceptance["decided_at"] = now
        if decision_notes is not None:
            acceptance["decision_notes"] = decision_notes
        touch(acceptance)
        if engagement is not None:
            engagement["status"] = "DRAFT"
            engagement["risk_tier"] = "LOW"
            engagement["combined_risk_score"] = 0
            touch(engagement)
        if client is not None:
            others = [
                row for row in all_rows("engagements")
                if row.get("client_id") == client.get("id") and row.get("status") != "DRAFT"
            ]
            if not others:
                client["status"] = "PROSPECT"
                touch(client)
    elif decision == "WITHDRAW":
        if status != "CONDITIONAL":
            raise ApiError(ERR_INVALID_STATE, "WITHDRAW requires a CONDITIONAL evaluation.")
        acceptance["status"] = "WITHDRAWN"
        if decision_notes is not None:
            acceptance["decision_notes"] = decision_notes
        touch(acceptance)
        if engagement is not None:
            engagement["status"] = "DRAFT"
            touch(engagement)
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown decision '%s'." % decision)
    return acceptance
