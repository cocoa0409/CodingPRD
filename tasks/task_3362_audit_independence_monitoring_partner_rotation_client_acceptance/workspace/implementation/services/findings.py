"""Independence findings: creation factory and the remediation state machine."""

from core import constants as C
from core.clock import now as clock_now
from core.db import new_row, store, touch
from core.errors import ERR_INVALID_STATE, ERR_REMEDIATION_ATTEMPTS_EXHAUSTED, ApiError
from services import calc
from services.independence import (
    commit_client,
    commit_engagement,
    propagate_client,
    recompute_client,
    recompute_engagement,
)


def create_finding_row(professional_id, engagement_id, origin, origin_ref_id,
                       finding_type, severity, discovered_on):
    """Build a finding row. Callers own the posture recompute."""
    return new_row("findings", {
        "professional_id": professional_id,
        "engagement_id": engagement_id,
        "origin": origin,
        "origin_ref_id": origin_ref_id,
        "finding_type": finding_type,
        "severity": severity,
        "status": "OPEN",
        "discovered_on": discovered_on,
        "remediation_due_on": calc.remediation_due(discovered_on, severity),
        "closed_on": None,
        "remediation_attempts": 0,
    })


def cascade_finding_posture(finding, force_engagement=True):
    """Recompute the engagement posture and the client roll-up for a finding."""
    engagement = store.engagements.get(finding.get("engagement_id"))
    if engagement is None:
        return
    recompute_engagement(engagement)
    commit_engagement(engagement, force=force_engagement)
    client = store.clients.get(engagement.get("client_id"))
    if client is not None:
        recompute_client(client)
        commit_client(client)


def apply_finding_action(finding, action, now=None):
    now = now or clock_now()
    status = finding.get("status")
    attempts = int(finding.get("remediation_attempts") or 0)
    if action == "START_REMEDIATION":
        if status != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "START_REMEDIATION requires an OPEN finding.")
        if attempts >= C.REMEDIATION_ATTEMPT_LIMIT:
            raise ApiError(ERR_REMEDIATION_ATTEMPTS_EXHAUSTED,
                           "The finding already carries three failed re-tests.")
        finding["status"] = "REMEDIATION"
        finding["remediation_due_on"] = calc.remediation_due(
            finding.get("discovered_on"), finding.get("severity"))
    elif action == "CLOSE_NO_ACTION":
        if status != "OPEN":
            raise ApiError(ERR_INVALID_STATE, "CLOSE_NO_ACTION requires an OPEN finding.")
        if finding.get("severity") != "LOW":
            raise ApiError(ERR_INVALID_STATE,
                           "CLOSE_NO_ACTION is only available for LOW severity findings.")
        finding["status"] = "CLOSED"
        finding["closed_on"] = now
    elif action == "SUBMIT_FOR_RETEST":
        if status != "REMEDIATION":
            raise ApiError(ERR_INVALID_STATE, "SUBMIT_FOR_RETEST requires a finding in REMEDIATION.")
        finding["status"] = "RE_TEST"
    elif action == "PASS_RETEST":
        if status != "RE_TEST":
            raise ApiError(ERR_INVALID_STATE, "PASS_RETEST requires a finding in RE_TEST.")
        finding["status"] = "CLOSED"
        finding["closed_on"] = now
    elif action == "FAIL_RETEST":
        if status != "RE_TEST":
            raise ApiError(ERR_INVALID_STATE, "FAIL_RETEST requires a finding in RE_TEST.")
        finding["status"] = "REOPENED"
        finding["remediation_attempts"] = attempts + 1
        finding["remediation_due_on"] = calc.remediation_due(now, finding.get("severity"))
    elif action == "RESTART_REMEDIATION":
        if status != "REOPENED":
            raise ApiError(ERR_INVALID_STATE, "RESTART_REMEDIATION requires a REOPENED finding.")
        if attempts >= C.REMEDIATION_ATTEMPT_LIMIT:
            raise ApiError(ERR_REMEDIATION_ATTEMPTS_EXHAUSTED,
                           "The finding already carries three failed re-tests.")
        finding["status"] = "REMEDIATION"
        finding["remediation_due_on"] = calc.remediation_due(now, finding.get("severity"))
    else:
        raise ApiError(ERR_INVALID_STATE,
                       "Unknown action '%s' for an independence finding." % action)
    touch(finding)
    cascade_finding_posture(finding, force_engagement=True)
    return finding
