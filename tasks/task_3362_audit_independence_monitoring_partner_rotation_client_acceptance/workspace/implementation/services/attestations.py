"""Affiliate attestations: the network breach channel."""

from core import constants as C
from core.clock import now as clock_now
from core.db import all_rows, new_row, store, touch
from core.errors import ERR_INVALID_STATE, ApiError
from services.findings import create_finding_row
from services.independence import (
    commit_client,
    commit_engagement,
    recompute_client,
    recompute_engagement,
)


def create_attestation_row(affiliate_id, engagement_id, breach_count):
    return new_row("attestations", {
        "affiliate_id": affiliate_id,
        "engagement_id": engagement_id,
        "attestation_status": "PENDING",
        "attested_on": None,
        "breach_count": int(breach_count or 0),
    })


def recompute_affiliate(affiliate):
    if affiliate is None:
        return
    open_count = sum(
        1 for row in all_rows("attestations")
        if row.get("affiliate_id") == affiliate.get("id")
        and row.get("attestation_status") == "BREACHED"
    )
    affiliate["open_breach_count"] = open_count
    if open_count >= C.AFFILIATE_SUSPENSION_BREACH_COUNT:
        affiliate["status"] = "SUSPENDED"
    elif affiliate.get("status") == "SUSPENDED":
        affiliate["status"] = "ACTIVE"


def _recompute_engagement(engagement_id):
    engagement = store.engagements.get(engagement_id)
    if engagement is None:
        return
    recompute_engagement(engagement)
    commit_engagement(engagement)
    client = store.clients.get(engagement.get("client_id"))
    if client is not None:
        recompute_client(client)
        commit_client(client)


def apply_attestation_action(attestation, action, now=None):
    now = now or clock_now()
    status = attestation.get("attestation_status")
    if action == "ATTEST":
        if status != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "ATTEST requires a PENDING attestation.")
        attestation["attestation_status"] = "ATTESTED"
        attestation["attested_on"] = now
    elif action == "WAIVE":
        if status != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "WAIVE requires a PENDING attestation.")
        affiliate = store.affiliates.get(attestation.get("affiliate_id"))
        engagement = store.engagements.get(attestation.get("engagement_id"))
        tier = affiliate.get("network_tier") if affiliate else None
        multinational = bool(engagement.get("is_multinational")) if engagement else False
        if tier != "ALLIANCE" and multinational:
            raise ApiError(ERR_INVALID_STATE,
                           "WAIVE is only available for alliance-tier firms or non-multinational engagements.")
        attestation["attestation_status"] = "WAIVED"
        attestation["attested_on"] = now
    elif action == "REPORT_BREACH":
        if status != "ATTESTED":
            raise ApiError(ERR_INVALID_STATE, "REPORT_BREACH requires an ATTESTED attestation.")
        attestation["attestation_status"] = "BREACHED"
        attestation["breach_count"] = int(attestation.get("breach_count") or 0) + 1
        affiliate = store.affiliates.get(attestation.get("affiliate_id"))
        recompute_affiliate(affiliate)
        if affiliate is not None:
            touch(affiliate)
        create_finding_row(
            professional_id=None,
            engagement_id=attestation.get("engagement_id"),
            origin="AFFILIATE_BREACH",
            origin_ref_id=attestation.get("id"),
            finding_type="AFFILIATE_OBLIGATION",
            severity="HIGH",
            discovered_on=now,
        )
    elif action == "RESET_ATTESTATION":
        if status != "BREACHED":
            raise ApiError(ERR_INVALID_STATE, "RESET_ATTESTATION requires a BREACHED attestation.")
        for finding in all_rows("findings"):
            if finding.get("origin_ref_id") != attestation.get("id"):
                continue
            if finding.get("status") in C.LIVE_FINDING_STATUSES:
                raise ApiError(ERR_INVALID_STATE,
                               "A finding raised from this attestation is still live.")
        attestation["attestation_status"] = "PENDING"
        attestation["attested_on"] = None
        affiliate = store.affiliates.get(attestation.get("affiliate_id"))
        recompute_affiliate(affiliate)
        if affiliate is not None:
            touch(affiliate)
    else:
        raise ApiError(ERR_INVALID_STATE, "Unknown action '%s' for an affiliate attestation." % action)
    touch(attestation)
    _recompute_engagement(attestation.get("engagement_id"))
    return attestation
