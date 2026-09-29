"""Partnership agreements (fork-join signatures) and resource commitments."""

from datetime import timedelta

from flask import Blueprint, g

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  now_iso, ok, ok_list, paginate, parse_date, public, raw_field,
                  sorted_asc, touch, v_date, v_enum, v_id, v_int, v_num, v_str)

bp = Blueprint("partnerships", __name__)


@bp.post("/partnership-agreements")
def create_agreement():
    authenticate([K.CBO])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    party_id = v_str(body, "party_id", 1, None)
    pledged = v_int(body, "pledged_cents", 1)
    metric = v_str(body, "accountability_metric", 1, 160)
    shared_pct = v_num(body, "shared_accountability_pct", 0, 100, places=2)
    term_start = v_date(body, "term_start")
    term_end = v_date(body, "term_end")
    if term_end < term_start:
        fail("ERR_VALIDATION", "'term_end' must fall on or after 'term_start'.")

    cycle = D.cycle_or_404(cycle_id)
    party = D.party_or_404(party_id)
    if party["party_type"] != "PARTNER":
        fail("ERR_PARTY_TYPE_MISMATCH")
    D.gate_frozen(cycle)

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "party_id": party["id"],
        "pledged_cents": pledged,
        "funded_cents": 0,
        "accountability_metric": metric,
        "shared_accountability_pct": shared_pct,
        "term_start": term_start.isoformat(),
        "term_end": term_end.isoformat(),
        "signature_state": "NEGOTIATING",
        "funding_state": "UNFUNDED",
        "hospital_signed_at": None,
        "partner_signed_at": None,
        "hospital_signatory_user_id": None,
        "partner_signatory_user_id": None,
        "terminate_reason": None,
    })
    db.agreements[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/partnership-agreements")
def list_agreements():
    authenticate([K.CBO, K.CO, K.PR])
    rows = list(db.agreements.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "party_id")
    rows = filter_eq(rows, "signature_state")
    rows = filter_eq(rows, "funding_state")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/partnership-agreements/<agreement_id>")
def get_agreement(agreement_id):
    authenticate([K.CBO, K.CO, K.PR])
    return ok(public(D.agreement_or_404(agreement_id)))


@bp.post("/partnership-agreements/<agreement_id>/sign")
def sign_agreement(agreement_id):
    user_id, _role = authenticate([K.CBO, K.PR])
    body = body_or_empty()
    # Rung 2 refinement: the acting role must match the signatory_side recorded.
    requested = raw_field(body, "signatory_side")
    if requested == "HOSPITAL" and g.role != K.CBO:
        fail("ERR_UNAUTHORIZED", "A HOSPITAL signature requires CommunityBenefitOfficer.")
    if requested == "PARTNER" and g.role != K.PR:
        fail("ERR_UNAUTHORIZED", "A PARTNER signature requires PartnerRepresentative.")

    agreement = D.agreement_or_404(agreement_id)
    side = v_enum(body, "signatory_side", K.SIGNATORY_SIDES)

    if g.role == K.PR and user_id != agreement["party_id"]:
        fail("ERR_NOT_AGREEMENT_PARTY")

    cycle = db.cycles.get(agreement["cycle_id"])
    D.gate_frozen(cycle)

    state = agreement["signature_state"]
    stamp = now_iso()
    if side == "HOSPITAL" and state == "NEGOTIATING":
        agreement["hospital_signed_at"] = stamp
        agreement["hospital_signatory_user_id"] = user_id
        agreement["signature_state"] = "HOSPITAL_SIGNED"
    elif side == "PARTNER" and state == "NEGOTIATING":
        agreement["partner_signed_at"] = stamp
        agreement["partner_signatory_user_id"] = user_id
        agreement["signature_state"] = "PARTNER_SIGNED"
    elif side == "PARTNER" and state == "HOSPITAL_SIGNED":
        agreement["partner_signed_at"] = stamp
        agreement["partner_signatory_user_id"] = user_id
        agreement["signature_state"] = "EXECUTED"
        if agreement["funding_state"] == "UNFUNDED":
            agreement["funding_state"] = "PLEDGED"
    elif side == "HOSPITAL" and state == "PARTNER_SIGNED":
        agreement["hospital_signed_at"] = stamp
        agreement["hospital_signatory_user_id"] = user_id
        agreement["signature_state"] = "EXECUTED"
        if agreement["funding_state"] == "UNFUNDED":
            agreement["funding_state"] = "PLEDGED"
    else:
        fail("ERR_INVALID_STATE")
    touch(agreement)
    return ok(public(agreement))


@bp.post("/partnership-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authenticate([K.CBO])
    agreement = D.agreement_or_404(agreement_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    cycle = db.cycles.get(agreement["cycle_id"])
    D.gate_frozen(cycle)
    if agreement["signature_state"] not in ("NEGOTIATING", "HOSPITAL_SIGNED",
                                            "PARTNER_SIGNED", "EXECUTED"):
        fail("ERR_INVALID_STATE")

    agreement["terminate_reason"] = reason
    agreement["signature_state"] = "TERMINATED"
    touch(agreement)

    for com in sorted(db.commitments.values(), key=lambda c: c["_seq"]):
        if com.get("partnership_id") != agreement["id"]:
            continue
        if com["status"] in ("PENDING", "COMMITTED"):
            D.release_commitment(com, K.REASON_PARTNERSHIP_TERMINATED)
    if agreement["funded_cents"] != 0:
        agreement["funded_cents"] = 0
    if agreement["funding_state"] != "RELEASED":
        agreement["funding_state"] = "RELEASED"
    touch(agreement)
    D.sync_cycle(cycle)
    return ok(public(agreement))


@bp.post("/resource-commitments")
def create_commitment():
    authenticate([K.CBO])
    body = body_or_empty()
    strategy_id = v_str(body, "strategy_id", 1, None)
    party_id = v_str(body, "party_id", 1, None)
    partnership_id = v_id(body, "partnership_id", required=False)
    fte_bp = v_int(body, "fte_bp", 0, K.MAX_FTE_BP)
    funding_cents = v_int(body, "funding_cents", 0)
    effective_from = v_date(body, "effective_from")
    effective_to = v_date(body, "effective_to")
    if not effective_to > effective_from:
        fail("ERR_VALIDATION", "'effective_to' must be strictly later than 'effective_from'.")

    strat = D.strategy_or_404(strategy_id)
    party = D.party_or_404(party_id)
    agreement = D.agreement_or_404(partnership_id) if partnership_id else None

    cycle = D.cycle_of_strategy(strat)
    D.gate_child_write(cycle, restricted=True)
    if strat["approval_state"] not in ("DRAFT", "RETURNED"):
        fail("ERR_STRATEGY_LOCKED")
    if cycle is None or cycle["status"] != "STRATEGY_DEVELOPMENT":
        fail("ERR_INVALID_STATE")

    if agreement is not None:
        if agreement["signature_state"] != "EXECUTED":
            fail("ERR_PARTNERSHIP_NOT_EXECUTED")
        term_start = parse_date(agreement["term_start"])
        term_end = parse_date(agreement["term_end"])
        if effective_from < term_start or effective_to > term_end + timedelta(days=1):
            fail("ERR_COMMITMENT_OUTSIDE_TERM")

    if party["committed_fte_bp"] + fte_bp > party["fte_capacity_bp"]:
        fail("ERR_PARTY_FTE_CAPACITY_EXCEEDED")

    if agreement is not None:
        overlapping = 0
        for sibling in db.commitments.values():
            if sibling.get("partnership_id") != agreement["id"]:
                continue
            if sibling["status"] not in ("PENDING", "COMMITTED"):
                continue
            s_from = parse_date(sibling["effective_from"])
            s_to = parse_date(sibling["effective_to"])
            if effective_from < s_to and s_from < effective_to:
                overlapping += sibling["funding_cents"]
        if funding_cents + overlapping > agreement["pledged_cents"]:
            fail("ERR_PARTNERSHIP_PLEDGE_WINDOW_EXCEEDED")

    if funding_cents > strat["budget_available_cents"]:
        fail("ERR_STRATEGY_BUDGET_EXCEEDED")

    rec = new_record()
    rec.update({
        "strategy_id": strat["id"],
        "party_id": party["id"],
        "partnership_id": agreement["id"] if agreement else None,
        "fte_bp": fte_bp,
        "funding_cents": funding_cents,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat(),
        "status": "PENDING",
        "committed_at": None,
        "released_at": None,
        "release_reason": None,
    })
    db.commitments[rec["id"]] = rec
    D.recompute_party_fte(party)
    D.recompute_strategy_budget(strat)
    return ok(public(rec), 201)


@bp.get("/resource-commitments")
def list_commitments():
    authenticate([K.CBO, K.CO, K.PR])
    rows = list(db.commitments.values())
    rows = filter_eq(rows, "strategy_id")
    rows = filter_eq(rows, "party_id")
    rows = filter_eq(rows, "partnership_id")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/resource-commitments/<commitment_id>")
def get_commitment(commitment_id):
    authenticate([K.CBO, K.CO, K.PR])
    return ok(public(D.commitment_or_404(commitment_id)))


@bp.post("/resource-commitments/<commitment_id>/release")
def release_commitment(commitment_id):
    authenticate([K.CBO])
    com = D.commitment_or_404(commitment_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    cycle = D.cycle_of_commitment(com)
    D.gate_frozen(cycle)
    if com["status"] not in ("PENDING", "COMMITTED"):
        fail("ERR_INVALID_STATE")

    D.release_commitment(com, reason)
    return ok(public(com))
