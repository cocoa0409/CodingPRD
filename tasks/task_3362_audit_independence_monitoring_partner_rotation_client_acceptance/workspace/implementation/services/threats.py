"""Personal independence threats: materiality, cooling-off and remediation."""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, new_row, store, touch
from core.errors import ERR_INVALID_STATE, ApiError
from services import calc
from services.findings import create_finding_row
from services.independence import (
    commit_client,
    commit_engagement,
    recompute_client,
    recompute_engagement,
)


def initial_threat_status(threat_type, is_material, cooling_off_months, now):
    if threat_type == "FINANCIAL_INTEREST":
        return "DECLARED", None
    if cooling_off_months > 0:
        return "IN_COOLING_OFF", None
    if is_material:
        return "MITIGATED", None
    return "CLEARED", now


def create_threat_row(professional_id, client_id, threat_type, instrument_type,
                      relationship_type, value_cents, effective_on):
    now = clock_now()
    professional = store.professionals.get(professional_id)
    client = store.clients.get(client_id)
    grade = professional.get("grade") if professional else None
    is_pie = bool(client.get("is_public_interest_entity")) if client else False
    is_material = calc.financial_interest_materiality(
        threat_type, instrument_type, value_cents, grade, is_pie)
    months = calc.cooling_off_months(relationship_type) if threat_type == "EMPLOYMENT_RELATIONSHIP" else 0
    if threat_type == "FINANCIAL_INTEREST":
        cooling_off_end_on = effective_on
    else:
        cooling_off_end_on = calc.cooling_off_end(effective_on, relationship_type)
    status, cleared_on = initial_threat_status(threat_type, is_material, months, now)
    row = new_row("threats", {
        "professional_id": professional_id,
        "client_id": client_id,
        "threat_type": threat_type,
        "instrument_type": instrument_type,
        "relationship_type": relationship_type,
        "value_cents": int(value_cents or 0),
        "effective_on": effective_on,
        "is_material": is_material,
        "cooling_off_end_on": cooling_off_end_on,
        "status": status,
        "cleared_on": cleared_on,
    })
    if is_material:
        raise_material_interest_findings(row)
    return row


def raise_material_interest_findings(threat):
    """One CRITICAL finding on every live engagement of the client."""
    now = clock_now()
    client_id = threat.get("client_id")
    for engagement in all_rows("engagements"):
        if engagement.get("client_id") != client_id:
            continue
        if engagement.get("status") not in C.FINDING_CASCADE_ENGAGEMENT_STATUSES:
            continue
        create_finding_row(
            professional_id=threat.get("professional_id"),
            engagement_id=engagement.get("id"),
            origin="FINANCIAL_INTEREST",
            origin_ref_id=threat.get("id"),
            finding_type="FINANCIAL_INTEREST",
            severity="CRITICAL",
            discovered_on=now,
        )
        recompute_engagement(engagement)
        commit_engagement(engagement)
    client = store.clients.get(client_id)
    if client is not None:
        recompute_client(client)
        commit_client(client)


def apply_threat_action(threat, action, now=None):
    now = now or clock_now()
    status = threat.get("status")
    if action == "DIVEST":
        if status != "DECLARED":
            raise ApiError(ERR_INVALID_STATE, "DIVEST requires a DECLARED threat.")
        if threat.get("threat_type") != "FINANCIAL_INTEREST":
            raise ApiError(ERR_INVALID_STATE, "DIVEST is only available for financial interests.")
        if threat.get("is_material") is not True:
            raise ApiError(ERR_INVALID_STATE, "DIVEST requires a material financial interest.")
        threat["status"] = "DIVESTED"
    elif action == "MITIGATE":
        if status != "DECLARED":
            raise ApiError(ERR_INVALID_STATE, "MITIGATE requires a DECLARED threat.")
        if threat.get("threat_type") != "EMPLOYMENT_RELATIONSHIP":
            raise ApiError(ERR_INVALID_STATE, "MITIGATE is only available for employment relationships.")
        if threat.get("cooling_off_end_on") != threat.get("effective_on"):
            raise ApiError(ERR_INVALID_STATE, "MITIGATE requires an empty cooling-off window.")
        threat["status"] = "MITIGATED"
    elif action == "CONFIRM_CLEARANCE":
        if status not in ("DIVESTED", "MITIGATED"):
            raise ApiError(ERR_INVALID_STATE,
                           "CONFIRM_CLEARANCE requires a DIVESTED or MITIGATED threat.")
        threat["status"] = "CLEARED"
        threat["cleared_on"] = now
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown action '%s' for an independence threat." % action)
    touch(threat)
    if action in ("DIVEST", "CONFIRM_CLEARANCE"):
        _recompute_client_engagements(threat.get("client_id"))
    return threat


def _recompute_client_engagements(client_id):
    for engagement in all_rows("engagements"):
        if engagement.get("client_id") != client_id:
            continue
        recompute_engagement(engagement)
        commit_engagement(engagement)
    client = store.clients.get(client_id)
    if client is not None:
        recompute_client(client)
        commit_client(client)


def cooling_off_bar(professional_id, client_id, started_on, now):
    """True when the professional is barred by an active cooling-off window."""
    for threat in all_rows("threats"):
        if threat.get("professional_id") != professional_id:
            continue
        if threat.get("client_id") != client_id:
            continue
        if threat.get("threat_type") != "EMPLOYMENT_RELATIONSHIP":
            continue
        if threat.get("status") != "IN_COOLING_OFF":
            continue
        end = threat.get("cooling_off_end_on")
        if end is None:
            continue
        if now >= end:
            continue
        effective = threat.get("effective_on")
        if effective is not None and started_on < effective:
            continue
        return True
    return False


def material_interest_bar(professional_id, client_id):
    """True when the professional holds a live material financial interest."""
    for threat in all_rows("threats"):
        if threat.get("professional_id") != professional_id:
            continue
        if threat.get("client_id") != client_id:
            continue
        if threat.get("threat_type") != "FINANCIAL_INTEREST":
            continue
        if threat.get("is_material") is not True:
            continue
        if threat.get("status") in ("DECLARED", "IN_COOLING_OFF"):
            return True
    return False
