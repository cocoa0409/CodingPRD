"""Review-gate endpoints (PRD section 3.5)."""

from flask import Blueprint, g

import calc
import envelope
import governance as gov
import serialize
import validate as v
from auth import (ALL_REVIEWERS_AND_SME, GATE_ROLE, ROLE_MANAGING_EDITOR,
                  ROLE_SME, endpoint)
from errors import ApiError
from store import store, touch

bp = Blueprint("gates", __name__)


@bp.post("/editorial/review-gates/<gid>/decide")
@endpoint(*ALL_REVIEWERS_AND_SME)
def decide_gate(gid):
    gate = gov.get_gate(gid)
    body = v.body()
    decision = v.v_enum(body, "decision", v.GATE_DECISIONS)
    notes = v.v_str(body, "decision_notes", required=False, minlen=0, maxlen=500)

    item = store.items[gate["content_item_id"]]
    brief = gov.brief_of_item(item)
    campaign = gov.campaign_of_item(item)

    # Ladder rule 10.
    if gate["gate_type"] == "SME" and g.role == ROLE_SME:
        if brief["sme_expert_id"] is None or brief["sme_expert_id"] != g.user_id:
            raise ApiError("ERR_SME_NOT_ASSIGNED_TO_BRIEF",
                           "caller is not the expert assigned to this brief")
    # Ladder rule 11 -- the one exception is a ManagingEditor waiver.
    waiver = decision == "WAIVED"
    if g.role != GATE_ROLE[gate["gate_type"]] and not (
            g.role == ROLE_MANAGING_EDITOR and waiver):
        raise ApiError("ERR_GATE_ROLE_MISMATCH",
                       "the acting role may not decide this gate type")
    # Ladder rule 12 -- legal segregation of duties.
    if gate["gate_type"] == "LEGAL":
        for claim in gov.claims_of_item(item["id"]):
            if claim["decided_by_user_id"] is not None \
                    and claim["decided_by_user_id"] == g.user_id:
                raise ApiError("ERR_SOD_LEGAL_CONFLICT",
                               "the operator who decided a claim may not clear "
                               "the legal gate")
    # Ladder rule 15.
    if gate["state"] != "PENDING":
        raise ApiError("ERR_GATE_ALREADY_DECIDED", "the gate is already decided")
    if item["workflow_state"] != "IN_REVIEW":
        raise ApiError("ERR_ITEM_STATE_INVALID", "the item is not IN_REVIEW")
    if waiver:
        # Ladder rules 22 and 23 -- a waiver demands an OPEN posture.
        gov.require_open_posture(campaign)
        # Ladder rule 26.
        if gate["gate_type"] not in ("BRAND", "ACCESSIBILITY"):
            raise ApiError("ERR_GATE_NOT_WAIVABLE",
                           "only BRAND and ACCESSIBILITY gates may be waived")

    gate["state"] = decision
    gate["decided_at"] = store.clock
    gate["decided_by_user_id"] = g.user_id
    gate["decision_notes"] = notes
    gate["turnaround_hours"] = calc.turnaround_hours(gate["opened_at"], store.clock)
    gate["sla_breached"] = store.clock > gate["due_at"]
    touch(gate)

    if decision == "CHANGES_REQUESTED":
        item["workflow_state"] = "CHANGES_REQUESTED"
        touch(item)
    else:
        siblings = gov.gates_of_item(item["id"])
        if all(gt["state"] in ("APPROVED", "WAIVED") for gt in siblings):
            item["workflow_state"] = "READY"
            touch(item)

    gov.reconcile_campaign(campaign)
    return envelope.ok(serialize.gate(gate))


@bp.get("/editorial/review-gates/<gid>")
@endpoint(*ALL_REVIEWERS_AND_SME)
def read_gate(gid):
    return envelope.ok(serialize.gate(gov.get_gate(gid)))
