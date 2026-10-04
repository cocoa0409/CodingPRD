"""Independence posture ladder and its propagation across the object graph.

Recomputes mark a row dirty instead of touching it, so a caller can guarantee
exactly one version increment per business operation via commit_*.
"""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, set_fields, store, touch
from services import calc
from services.staffing import (
    refresh_engagement_staffing,
    refresh_professional,
    refresh_rotation,
)


def live_findings(engagement_id):
    return [
        row for row in all_rows("findings")
        if row.get("engagement_id") == engagement_id
        and row.get("status") in C.LIVE_FINDING_STATUSES
    ]


def escalated_findings(engagement_id):
    return [
        row for row in live_findings(engagement_id)
        if int(row.get("remediation_attempts") or 0) >= C.REMEDIATION_ATTEMPT_LIMIT
    ]


def posture_counts(engagement):
    engagement_id = engagement.get("id")
    client_id = engagement.get("client_id")
    critical_open = 0
    high_open = 0
    for row in live_findings(engagement_id):
        if row.get("severity") == "CRITICAL":
            critical_open += 1
        elif row.get("severity") == "HIGH":
            high_open += 1
    prohibited = 0
    for row in all_rows("services"):
        if row.get("engagement_id") == engagement_id or row.get("client_id") == client_id:
            if row.get("is_prohibited_for_pie") is True and \
                    row.get("status") in C.PROHIBITED_SERVICE_POSTURE_STATUSES:
                prohibited += 1
    breached = sum(
        1 for row in all_rows("attestations")
        if row.get("engagement_id") == engagement_id
        and row.get("attestation_status") == "BREACHED"
    )
    material = sum(
        1 for row in all_rows("threats")
        if row.get("client_id") == client_id
        and row.get("threat_type") == "FINANCIAL_INTEREST"
        and row.get("is_material") is True
        and row.get("status") in ("DECLARED", "IN_COOLING_OFF")
    )
    network = calc.affiliate_network_risk(
        engagement, all_rows("attestations"), store.affiliates)
    return {
        "critical_open_count": critical_open,
        "high_open_count": high_open,
        "prohibited_service_count": prohibited,
        "breached_attestation_count": breached,
        "material_interest_count": material,
        "network_risk_points": network,
    }


def posture_for(counts, escalated=False):
    if escalated:
        return "FROZEN"
    if counts["critical_open_count"] >= C.FROZEN_CRITICAL_MIN:
        return "FROZEN"
    if counts["high_open_count"] >= C.FROZEN_HIGH_MIN:
        return "FROZEN"
    if counts["prohibited_service_count"] >= 1:
        return "FROZEN"
    if counts["material_interest_count"] >= 1:
        return "FROZEN"
    if counts["network_risk_points"] >= C.FROZEN_NETWORK_MIN:
        return "FROZEN"
    if counts["high_open_count"] == C.RESTRICTED_HIGH_EXACT:
        return "RESTRICTED"
    if counts["breached_attestation_count"] >= 1:
        return "RESTRICTED"
    if counts["network_risk_points"] >= C.RESTRICTED_NETWORK_MIN:
        return "RESTRICTED"
    return "CLEAR"


def recompute_engagement(engagement):
    """Recompute posture, then let it drive the lifecycle status."""
    if engagement is None:
        return None
    counts = posture_counts(engagement)
    escalated = bool(escalated_findings(engagement.get("id")))
    target = posture_for(counts, escalated)
    changed = False
    if engagement.get("independence_status") != target:
        engagement["independence_status"] = target
        changed = True
    status = engagement.get("status")
    if target == "FROZEN" and status == "ACTIVE":
        engagement["status"] = "SUSPENDED"
        engagement["_suspended_by_independence"] = True
        changed = True
    elif target != "FROZEN" and status == "SUSPENDED" and engagement.get("_suspended_by_independence"):
        if not any(row.get("severity") == "CRITICAL" for row in live_findings(engagement.get("id"))):
            engagement["status"] = "ACTIVE"
            engagement["_suspended_by_independence"] = False
            changed = True
    if changed:
        engagement["_dirty"] = True
    return counts


def commit_engagement(engagement, force=False):
    dirty = engagement.pop("_dirty", False)
    if force or dirty:
        touch(engagement)
    return engagement


def recompute_client(client):
    """Roll the engagements' postures up onto the client and track its status."""
    if client is None:
        return None
    engagements = [row for row in all_rows("engagements") if row.get("client_id") == client.get("id")]
    if any(row.get("independence_status") == "FROZEN" for row in engagements):
        aggregate = "FROZEN"
    elif any(row.get("independence_status") == "RESTRICTED" for row in engagements):
        aggregate = "RESTRICTED"
    else:
        aggregate = "CLEAR"
    open_count = 0
    for row in all_rows("findings"):
        if row.get("status") == "CLOSED":
            continue
        engagement = store.engagements.get(row.get("engagement_id"))
        if engagement is not None and engagement.get("client_id") == client.get("id"):
            open_count += 1
    changed = False
    if client.get("aggregate_independence_status") != aggregate:
        client["aggregate_independence_status"] = aggregate
        changed = True
    if client.get("open_finding_count") != open_count:
        client["open_finding_count"] = open_count
        changed = True
    status = client.get("status")
    if status in ("ACTIVE", "SUSPENDED"):
        if aggregate == "FROZEN" and status == "ACTIVE":
            client["status"] = "SUSPENDED"
            changed = True
        elif aggregate != "FROZEN" and status == "SUSPENDED":
            client["status"] = "ACTIVE"
            changed = True
    if changed:
        client["_dirty"] = True
    return aggregate


def commit_client(client, force=False):
    dirty = client.pop("_dirty", False)
    if force or dirty:
        touch(client)
    return client


def propagate_client(client_id):
    """Recompute every engagement of a client, then the client roll-up."""
    client = store.clients.get(client_id)
    if client is None:
        return None
    for engagement in all_rows("engagements"):
        if engagement.get("client_id") == client_id:
            recompute_engagement(engagement)
            commit_engagement(engagement)
    recompute_client(client)
    commit_client(client)
    return client


def refresh_engagement_derived(engagement):
    """Refresh the purely derived staffing fields of an engagement."""
    if engagement is None:
        return None
    refresh_engagement_staffing(engagement, all_rows("assignments"), store.engagements)
    return engagement


def quality_review_required_for(engagement, client):
    if engagement.get("risk_tier") in ("HIGH", "SIGNIFICANT"):
        return True
    return bool(client and client.get("is_public_interest_entity"))


def refresh_assignments_for(engagement_id):
    """Recompute tenure, professional workload and engagement staffing totals."""
    now = clock_now()
    engagements = store.engagements
    assignments = all_rows("assignments")
    professionals = set()
    for row in assignments:
        if row.get("engagement_id") == engagement_id:
            refresh_rotation(row, assignments, engagements, store.clients, now)
            professionals.add(row.get("professional_id"))
    for professional_id in professionals:
        professional = store.professionals.get(professional_id)
        if professional is not None:
            refresh_professional(professional, assignments, engagements, now)
    engagement = engagements.get(engagement_id)
    if engagement is not None:
        refresh_engagement_staffing(engagement, assignments, engagements)


def refresh_all_assignments():
    """Global recompute used after risk-tier moves and closures."""
    now = clock_now()
    assignments = all_rows("assignments")
    engagements = store.engagements
    for row in assignments:
        refresh_rotation(row, assignments, engagements, store.clients, now)
    for professional in all_rows("professionals"):
        refresh_professional(professional, assignments, engagements, now)
    for engagement in all_rows("engagements"):
        refresh_engagement_staffing(engagement, assignments, engagements)


def sweep_cooling_off():
    """Auto-clear threats whose cooling-off window the clock has reached."""
    now = clock_now()
    for threat in all_rows("threats"):
        if threat.get("status") != "IN_COOLING_OFF":
            continue
        end = threat.get("cooling_off_end_on")
        if end is not None and now >= end:
            set_fields(threat, status="CLEARED", cleared_on=now)
