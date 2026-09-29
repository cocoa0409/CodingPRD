"""Cross-entity effects: provider scoring, standing cascades, evidence minting
and system-raised incidents. Every cascade runs to completion in the request
that triggered it."""
from datetime import timedelta
from decimal import Decimal

import store
from common import now, round2
from store import new_row, touch

INCIDENT_BASE_WEIGHTS = {
    "SEV1": Decimal("25.00"),
    "SEV2": Decimal("15.00"),
    "SEV3": Decimal("5.00"),
}
ESCALATION_MULTIPLIER = Decimal("1.5")
LATE_FILING_DEDUCTION = Decimal("5.00")
ROLLING_WINDOW_DAYS = 90
PENALTY_PROBATION_THRESHOLD = 100000

LIVE_ENGAGEMENT_STATUSES = (
    "ACTIVE",
    "REMEDIATION_REQUIRED",
    "TRANSITION_PLANNED",
    "TRANSITION_IN_PROGRESS",
)


def escalated_weight(severity):
    return round2(INCIDENT_BASE_WEIGHTS[severity] * ESCALATION_MULTIPLIER)


# ---------------------------------------------------------------------------
# provider_service_score
# ---------------------------------------------------------------------------
def recompute_provider_score(provider):
    """Recompute service_score and score_variant_applied, then re-derive the
    provider's standing (which may cascade)."""
    engagements = store.engagements_of_provider(provider["id"])
    variant = "ENGAGEMENT_TO_DATE"
    for engagement in engagements:
        if engagement["closed_cycle_count"] >= 1:
            variant = "ROLLING_WINDOW"
            break
    window_start = now() - timedelta(days=ROLLING_WINDOW_DAYS)

    deduction = Decimal("0.00")
    for engagement in engagements:
        for incident in store.incidents_of_engagement(engagement["id"]):
            if incident["status"] not in ("CONFIRMED", "ESCALATED"):
                continue
            if variant == "ROLLING_WINDOW" and incident["occurred_at"] < window_start:
                continue
            deduction += incident["weight_points"]
        for cycle in store.cycles_of_engagement(engagement["id"]):
            for filing in store.filings_of_cycle(cycle["id"]):
                if filing["late_days"] is None or filing["late_days"] <= 0:
                    continue
                if variant == "ROLLING_WINDOW" and filing["due_at"] < window_start:
                    continue
                deduction += LATE_FILING_DEDUCTION

    score = round2(Decimal("100.00") - deduction)
    if score < Decimal("0.00"):
        score = Decimal("0.00")

    if provider["service_score"] != score or provider["score_variant_applied"] != variant:
        provider["service_score"] = score
        provider["score_variant_applied"] = variant
        touch(provider)

    derive_provider_status(provider)
    return provider


def derive_provider_status(provider):
    """Re-derive standing from the score and the open penalty exposure.
    OFFBOARDED is never entered or left through scoring."""
    if provider["status"] == "OFFBOARDED":
        return provider
    score = provider["service_score"]
    if score < Decimal("40.00"):
        target = "SUSPENDED"
    elif score < Decimal("55.00"):
        target = "PROBATION"
    else:
        target = (
            "ACTIVE"
            if provider["open_penalty_minor"] <= PENALTY_PROBATION_THRESHOLD
            else "PROBATION"
        )
    if target != provider["status"]:
        apply_provider_status(provider, target)
    elif target == "ACTIVE":
        # The provider is already healthy: an engagement whose last finding has
        # just been remediated still recovers (the per-engagement condition is
        # what gates recovery, not the provider's own transition).
        _recover(provider)
    return provider


def apply_provider_status(provider, target):
    previous = provider["status"]
    provider["status"] = target
    touch(provider)
    if target in ("PROBATION", "SUSPENDED"):
        _degrade(provider, previous, target)
    elif target == "ACTIVE":
        _recover(provider)
    return provider


def _degrade(provider, previous, target):
    reason = "PROVIDER_PROBATION" if target == "PROBATION" else "PROVIDER_SUSPENSION"
    for engagement in store.engagements_of_provider(provider["id"]):
        if engagement["status"] == "ACTIVE":
            engagement["status"] = "REMEDIATION_REQUIRED"
            engagement["transition_required"] = True
            touch(engagement)
            for cycle in store.cycles_of_engagement(engagement["id"]):
                if cycle["status"] == "DRAFT":
                    cycle["status"] = "ON_HOLD"
                    cycle["hold_reason"] = reason
                    touch(cycle)
    if previous in ("PROBATION", "SUSPENDED"):
        # A slide or a partial recovery re-labels holds already in place.
        for engagement in store.engagements_of_provider(provider["id"]):
            for cycle in store.cycles_of_engagement(engagement["id"]):
                if cycle["status"] == "ON_HOLD" and cycle["hold_reason"] != reason:
                    cycle["hold_reason"] = reason
                    touch(cycle)


def _recover(provider):
    for engagement in store.engagements_of_provider(provider["id"]):
        if engagement["status"] != "REMEDIATION_REQUIRED":
            continue
        unresolved = [
            incident
            for incident in store.incidents_of_engagement(engagement["id"])
            if incident["status"] in ("CONFIRMED", "ESCALATED")
        ]
        if unresolved:
            continue
        engagement["status"] = "ACTIVE"
        engagement["transition_required"] = False
        touch(engagement)
    # Cycles already ON_HOLD wait for an explicit hold release.


def offboard_if_idle(provider):
    """The outgoing provider of a completed transition is offboarded when it has
    no live engagement left. Its score is frozen at its last computed value."""
    if provider["status"] == "OFFBOARDED":
        return provider
    for engagement in store.engagements_of_provider(provider["id"]):
        if engagement["status"] in LIVE_ENGAGEMENT_STATUSES:
            return provider
    provider["status"] = "OFFBOARDED"
    touch(provider)
    return provider


# ---------------------------------------------------------------------------
# Audit evidence
# ---------------------------------------------------------------------------
def mint_system_evidence(cycle_id, control_ref):
    """Mint a system-attributed evidence item unless the control is already
    evidenced for the cycle."""
    for item in store.evidence_of_cycle(cycle_id):
        if item["control_ref"] == control_ref:
            return None
    return record_evidence(
        cycle_id,
        control_ref,
        "SYSTEM_ATTESTATION",
        "sys:%s:%s" % (control_ref, cycle_id),
        "SYSTEM",
        "system",
    )


def record_evidence(cycle_id, control_ref, evidence_type, payload_hash, role, user_id):
    sequence_no = len(store.evidence_of_cycle(cycle_id)) + 1
    row = new_row(
        {
            "cycle_id": cycle_id,
            "control_ref": control_ref,
            "evidence_type": evidence_type,
            "payload_hash": payload_hash,
            "recorded_by_role": role,
            "recorded_by_user_id": user_id,
            "sequence_no": sequence_no,
        },
        common=False,
    )
    store.evidence_items[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# System-raised incidents
# ---------------------------------------------------------------------------
def raise_incident(engagement_id, cycle_id, incident_type, severity, note=None):
    row = new_row(
        {
            "engagement_id": engagement_id,
            "cycle_id": cycle_id,
            "incident_type": incident_type,
            "severity": severity,
            "occurred_at": now(),
            "note": note,
            "status": "OPEN",
            "escalation_level": 0,
            "weight_points": Decimal("0.00"),
            "remediation_ref": None,
        }
    )
    store.incidents[row["id"]] = row
    return row
