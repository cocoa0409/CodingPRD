"""Claim and evidence endpoints (PRD section 3.6)."""

from flask import Blueprint, g

import calc
import envelope
import governance as gov
import listing
import serialize
import validate as v
from auth import (ALL_REVIEWERS_AND_SME, ROLE_LEGAL, ROLE_MANAGING_EDITOR,
                  ROLE_SME, endpoint)
from errors import ApiError
from store import store, touch, new_row

bp = Blueprint("claims", __name__)


def _rescore(claim):
    rows = listing.sort_default(gov.evidence_of_claim(claim["id"]))
    score, contributing = calc.claim_evidence_score(rows, claim["claim_type"],
                                                    store.clock)
    claim["evidence_score"] = score
    return contributing


@bp.post("/editorial/claims/<cid>/evidence")
@endpoint(ROLE_MANAGING_EDITOR, ROLE_SME)
def file_evidence(cid):
    claim = gov.get_claim(cid)
    body = v.body()
    source_type = v.v_enum(body, "source_type", v.EVIDENCE_SOURCE_TYPES)
    citation = v.v_str(body, "citation", minlen=5, maxlen=300)
    collected_at = v.v_instant(body, "collected_at")
    valid_until = v.v_instant(body, "valid_until")
    if collected_at > store.clock:
        v.fail("collected_at must be at or before the logical clock")
    if valid_until <= collected_at:
        v.fail("valid_until must be strictly after collected_at")

    if claim["substantiation_state"] == "SUBSTANTIATED":
        raise ApiError("ERR_CLAIM_STATE_INVALID",
                       "a substantiated claim refuses new evidence")
    item = store.items[claim["content_item_id"]]
    if item["workflow_state"] == "PRUNED":
        raise ApiError("ERR_ITEM_STATE_INVALID", "the owning content item is PRUNED")

    row = new_row("evidence", {
        "claim_id": claim["id"],
        "source_type": source_type,
        "citation": citation,
        "collected_at": collected_at,
        "valid_until": valid_until,
        "weight": calc.EVIDENCE_SOURCE_WEIGHT[source_type],
        "submitted_by_user_id": g.user_id,
    })
    store.evidence[row["id"]] = row

    was_expired = claim["substantiation_state"] == "EXPIRED"
    claim["substantiation_state"] = "EVIDENCE_PENDING"
    claim["decided_by_user_id"] = None
    claim["decided_at"] = None
    _rescore(claim)
    if was_expired:
        claim["evidence_valid_until"] = None
    touch(claim)
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.created(serialize.evidence(row))


@bp.post("/editorial/claims/<cid>/decide")
@endpoint(ROLE_LEGAL)
def decide_claim(cid):
    claim = gov.get_claim(cid)
    body = v.body()
    decision = v.v_enum(body, "decision", v.CLAIM_DECISIONS)

    if claim["substantiation_state"] != "EVIDENCE_PENDING":
        raise ApiError("ERR_CLAIM_STATE_INVALID", "claim is not EVIDENCE_PENDING")

    contributing = _rescore(claim)
    if decision == "SUBSTANTIATED":
        # Ladder rule 36 before ladder rule 38.
        live = [row for row in contributing if row["valid_until"] > store.clock]
        if not live:
            raise ApiError("ERR_EVIDENCE_EXPIRED",
                           "no weight-contributing evidence row is still valid")
        if claim["evidence_score"] < claim["required_score"]:
            raise ApiError("ERR_EVIDENCE_INSUFFICIENT",
                           "evidence_score is below required_score")
        claim["substantiation_state"] = "SUBSTANTIATED"
        claim["evidence_valid_until"] = min(row["valid_until"] for row in contributing)
    else:
        claim["substantiation_state"] = "REJECTED"
    claim["decided_by_user_id"] = g.user_id
    claim["decided_at"] = store.clock
    touch(claim)
    item = store.items[claim["content_item_id"]]
    gov.reconcile_campaign(gov.campaign_of_item(item))
    return envelope.ok(serialize.claim(claim))


@bp.get("/editorial/claims/<cid>")
@endpoint(*ALL_REVIEWERS_AND_SME)
def read_claim(cid):
    return envelope.ok(serialize.claim(gov.get_claim(cid)))


@bp.get("/editorial/claims/<cid>/evidence")
@endpoint(ROLE_MANAGING_EDITOR, ROLE_LEGAL, ROLE_SME)
def list_evidence(cid):
    claim = gov.get_claim(cid)
    rows = listing.apply_filters(gov.evidence_of_claim(claim["id"]),
                                 [("source_type", "source_type")])
    rows = listing.sort_by(rows, ["collected_at"])
    window, pagination = envelope.page(rows)
    return envelope.ok_list([serialize.evidence(r) for r in window], pagination)
