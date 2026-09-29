"""Fee remittances: drafting, submission and the national decision (PRD 3.3)."""

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import authenticate, body_ref, fetch, require_treasurer
from clock import clock, elapsed_whole_days
from envelope import ok
from errors import ApiError
from store import store, insert, touch, apply_changes

remit = Blueprint("remit", __name__)

DRAFTABLE_SANCTION = ("UNSANCTIONED", "PENDING_REMITTANCE")
DRAFTABLE_REMITTANCE = ("UNPAID", "REFUNDED")


@remit.post("/fee-remittances")
def draft_remittance():
    uid, role = authenticate(["LeagueTreasurer"])
    payload = shape.body()
    league = body_ref("league", payload.get("league_id"))
    raw_ids = payload.get("membership_ids")
    if isinstance(raw_ids, list):
        for element in raw_ids:
            body_ref("membership", element)
    if league is not None:
        require_treasurer(league, uid, role)
    league_id = shape.req_id(payload, "league_id")
    membership_ids = shape.req_list(payload, "membership_ids", 1, 60)
    for element in membership_ids:
        if not isinstance(element, str) or element.strip() == "":
            shape.bad("every membership_ids element is an identifier string.")
    if len(set(membership_ids)) != len(membership_ids):
        shape.bad("membership_ids must not repeat an identifier.")
    declared = shape.req_int(payload, "declared_amount_cents", 0, 10000000)
    league = fetch("league", league_id)
    memberships = [fetch("membership", mid) for mid in membership_ids]
    for membership in memberships:
        if membership["league_id"] != league["id"]:
            raise ApiError("ERR_CROSS_LEAGUE_REFERENCE")
    for membership in memberships:
        if (membership["sanction_status"] not in DRAFTABLE_SANCTION
                or membership["remittance_status"] not in DRAFTABLE_REMITTANCE):
            raise ApiError("ERR_MEMBERSHIP_STATE_INVALID")
    live = [r for r in store.fee_remittances.values()
            if r["league_id"] == league["id"] and r["status"] != "REJECTED"]
    for membership in memberships:
        for other in live:
            if membership["id"] in other["membership_ids"]:
                raise ApiError("ERR_DUPLICATE_MEMBERSHIP")
    row = insert(store.fee_remittances, {
        "league_id": league["id"],
        "membership_ids": list(membership_ids),
        "declared_amount_cents": declared,
        "computed_amount_cents": 0,
        "penalty_cents": 0,
        "member_count": len(membership_ids),
        "status": "DRAFT",
        "submitted_at": None,
        "submitted_by_user_id": None,
        "national_receipt_no": None,
        "rejection_reason": None,
    })
    return ok(serialize.fee_remittance(row), 201)


@remit.post("/fee-remittances/<remittance_id>/submit")
def submit_remittance(remittance_id):
    uid, role = authenticate(["LeagueTreasurer"])
    remittance = fetch("fee_remittance", remittance_id)
    league = store.leagues[remittance["league_id"]]
    require_treasurer(league, uid, role)
    payload = shape.body()
    declared = shape.opt_int(payload, "declared_amount_cents", 0, 10000000)
    if league["status"] not in ("BYLAWS_ADOPTED", "SANCTIONED", "IN_SEASON"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if remittance["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_REMITTANCE_STATE_INVALID")
    memberships = [store.memberships[mid] for mid in remittance["membership_ids"]
                   if mid in store.memberships]
    for membership in memberships:
        if membership["sanction_status"] != "UNSANCTIONED":
            raise ApiError("ERR_MEMBERSHIP_STATE_INVALID")
    elapsed = elapsed_whole_days(league["bylaws_adopted_at"], clock.now())
    classes = [store.members[m["member_id"]]["member_class"] for m in memberships]
    member_count, penalty_cents, computed = calc.remittance_pricing(elapsed,
                                                                    classes)
    if declared is not None:
        remittance["declared_amount_cents"] = declared
    if remittance["declared_amount_cents"] != computed:
        raise ApiError("ERR_REMITTANCE_AMOUNT_MISMATCH")
    remittance["member_count"] = member_count
    remittance["penalty_cents"] = penalty_cents
    remittance["computed_amount_cents"] = computed
    remittance["status"] = "SUBMITTED"
    remittance["submitted_at"] = clock.now()
    remittance["submitted_by_user_id"] = uid
    touch(remittance)
    for membership in memberships:
        derive.set_and_recompute(membership, {
            "sanction_status": "PENDING_REMITTANCE",
            "remittance_status": "INVOICED",
        })
    return ok(serialize.fee_remittance(remittance))


@remit.post("/fee-remittances/<remittance_id>/national-decision")
def national_decision(remittance_id):
    authenticate(["AssociationOfficer"])
    remittance = fetch("fee_remittance", remittance_id)
    league = store.leagues[remittance["league_id"]]
    payload = shape.body()
    decision = shape.req_enum(payload, "decision", ["ACCEPT", "REJECT"])
    receipt = None
    reason = None
    if decision == "ACCEPT":
        receipt = shape.req_str(payload, "national_receipt_no")
    else:
        reason = shape.req_str(payload, "rejection_reason")
    if remittance["status"] != "SUBMITTED":
        raise ApiError("ERR_REMITTANCE_STATE_INVALID")
    memberships = [store.memberships[mid] for mid in remittance["membership_ids"]
                   if mid in store.memberships]
    if decision == "ACCEPT":
        remittance["status"] = "ACCEPTED"
        remittance["national_receipt_no"] = receipt
        remittance["rejection_reason"] = None
        touch(remittance)
        # hop 1 - the memberships
        for membership in memberships:
            derive.set_and_recompute(membership, {
                "sanction_status": "SANCTIONED",
                "remittance_status": "REMITTED",
            }, include_entering=True)
        pending = []
        for membership in memberships:
            member = store.members[membership["member_id"]]
            if member["national_member_number"] is None and member not in pending:
                pending.append(member)
        pending.sort(key=lambda m: (m["created_at"], m["_seq"]))
        for member in pending:
            member["national_member_number"] = store.next_national_number()
            touch(member)
        seen = []
        for membership in memberships:
            member = store.members[membership["member_id"]]
            if member["id"] not in seen:
                seen.append(member["id"])
                derive.recompute_member(member)
        # hop 2 - the teams
        team_ids = []
        for membership in memberships:
            if membership["team_id"] and membership["team_id"] not in team_ids:
                team_ids.append(membership["team_id"])
        for team_id in team_ids:
            team = store.teams.get(team_id)
            if team is not None:
                derive.recompute_team(team)
        # hop 3 - the league
        derive.recompute_league_counters(league)
        if (league["status"] == "BYLAWS_ADOPTED"
                and league["confirmed_team_count"] == league["declared_team_count"]):
            league["status"] = "SANCTIONED"
            touch(league)
        # hop 4 - the matches
        if league["status"] in ("SANCTIONED", "IN_SEASON"):
            for match in derive.matches_of_league(league["id"]):
                if match["status"] == "DRAFT":
                    apply_changes(match, {"status": "SCHEDULED"})
    else:
        remittance["status"] = "REJECTED"
        remittance["rejection_reason"] = reason
        remittance["national_receipt_no"] = None
        touch(remittance)
        for membership in memberships:
            derive.set_and_recompute(membership, {
                "sanction_status": "UNSANCTIONED",
                "remittance_status": "REFUNDED",
            })
        seen = []
        for membership in memberships:
            member = store.members[membership["member_id"]]
            if member["id"] not in seen:
                seen.append(member["id"])
                derive.recompute_member(member)
    return ok(serialize.fee_remittance(remittance))
