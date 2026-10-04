"""Routes: departure cases and committee votes."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    err_dup_vote,
    err_exit_not_reached,
    err_invalid,
    err_no_voters,
    err_not_found,
    err_ownership,
    err_perms,
    err_transition,
)
from middleware import get_context, require_roles
from response import created, new_entity, ok, paginate, parse_pagination, touch
from services import departure_penalty, practice_depart
from validate import body_json, require_date, require_enum, require_str

bp = Blueprint("governance", __name__)


# ---------------------------------------------------------------------------
# DepartureCase
# ---------------------------------------------------------------------------

NON_TERMINAL_CASE_STATUSES = {"UNDER_REVIEW", "SETTLEMENT_PENDING", "DISPUTED"}


@bp.route("/api/departure-cases", methods=["POST"])
def create_case():
    user_id, _role = require_roles("PracticeExecutive")
    data = body_json()
    practice_id = require_str(data, "practice_id")
    requested_exit = require_date(data, "requested_exit_date")
    if user_id != practice_id:
        raise err_ownership()
    practice = store.practices.get(practice_id)
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    if practice["status"] != "AFFILIATED":
        raise err_transition("Practice must be AFFILIATED")
    for c in store.departure_cases.values():
        if c["practice_id"] == practice_id and c["status"] in NON_TERMINAL_CASE_STATUSES:
            raise err_transition("A non-terminal departure case already exists")
    group = store.medical_groups.get(practice["medical_group_id"])
    notice_date = store.clock_date()
    earliest_exit = notice_date + timedelta(days=int(group["departure_notice_days"]))
    notice_sufficient = requested_exit >= earliest_exit
    assumed_exit = max(requested_exit, earliest_exit)
    est_penalty, nc = departure_penalty(
        group, practice, requested_exit, earliest_exit, assumed_exit
    )
    c = new_entity()
    c.update(
        practice_id=practice_id,
        notice_date=notice_date.isoformat(),
        requested_exit_date=requested_exit.isoformat(),
        earliest_exit_date=earliest_exit.isoformat(),
        notice_sufficient=notice_sufficient,
        assumed_exit_date=assumed_exit.isoformat(),
        estimated_penalty_cents=est_penalty,
        actual_exit_date=None,
        final_penalty_cents=None,
        non_compete_applies=nc,
        status="UNDER_REVIEW",
    )
    store.departure_cases[c["id"]] = c
    practice["status"] = "DEPARTING"
    touch(practice)
    return created(c)


@bp.route("/api/departure-cases", methods=["GET"])
def list_cases():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.departure_cases.values())
    pid = request.args.get("practice_id")
    if pid is not None:
        items = [c for c in items if c["practice_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/departure-cases/<cid>", methods=["GET"])
def get_case(cid):
    get_context()
    c = store.departure_cases.get(cid)
    if c is None:
        raise err_not_found("DEPARTURE_CASE", "Departure case not found")
    return ok(c)


def _get_case_or_404(cid):
    c = store.departure_cases.get(cid)
    if c is None:
        raise err_not_found("DEPARTURE_CASE", "Departure case not found")
    return c


@bp.route("/api/departure-cases/<cid>/complete-review", methods=["POST"])
def complete_review(cid):
    require_roles("ComplianceOfficer")
    c = _get_case_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise err_transition("Case is not UNDER_REVIEW")
    c["status"] = "SETTLEMENT_PENDING"
    touch(c)
    return ok(c)


@bp.route("/api/departure-cases/<cid>/dispute", methods=["POST"])
def dispute_case(cid):
    user_id, _role = require_roles("PracticeExecutive")
    c = _get_case_or_404(cid)
    if user_id != c["practice_id"]:
        raise err_ownership()
    if c["status"] != "SETTLEMENT_PENDING":
        raise err_transition("Case is not SETTLEMENT_PENDING")
    c["status"] = "DISPUTED"
    touch(c)
    return ok(c)


@bp.route("/api/departure-cases/<cid>/resettle", methods=["POST"])
def resettle_case(cid):
    require_roles("ComplianceOfficer")
    c = _get_case_or_404(cid)
    if c["status"] != "DISPUTED":
        raise err_transition("Case is not DISPUTED")
    c["status"] = "SETTLEMENT_PENDING"
    touch(c)
    return ok(c)


@bp.route("/api/departure-cases/<cid>/settle", methods=["POST"])
def settle_case(cid):
    require_roles("ComplianceOfficer")
    c = _get_case_or_404(cid)
    if c["status"] != "SETTLEMENT_PENDING":
        raise err_transition("Case is not SETTLEMENT_PENDING")
    from datetime import date as _date

    today = store.clock_date()
    earliest = _date.fromisoformat(c["earliest_exit_date"])
    if today < earliest:
        raise err_exit_not_reached()
    practice = store.practices.get(c["practice_id"])
    if practice is None:
        raise err_not_found("PRACTICE", "Practice not found")
    group = store.medical_groups.get(practice["medical_group_id"])
    requested = _date.fromisoformat(c["requested_exit_date"])
    actual_exit = max(requested, earliest, today)
    penalty, nc = departure_penalty(group, practice, requested, earliest, actual_exit)
    c["actual_exit_date"] = actual_exit.isoformat()
    c["final_penalty_cents"] = penalty
    c["non_compete_applies"] = nc
    c["status"] = "SETTLED"
    touch(c)
    if practice["status"] == "DEPARTING":
        practice_depart(practice, actual_exit)
    return ok(c)


@bp.route("/api/departure-cases/<cid>/rescind", methods=["POST"])
def rescind_case(cid):
    user_id, _role = require_roles("PracticeExecutive")
    c = _get_case_or_404(cid)
    if user_id != c["practice_id"]:
        raise err_ownership()
    if c["status"] not in ("UNDER_REVIEW", "SETTLEMENT_PENDING", "DISPUTED"):
        raise err_transition("Case cannot be rescinded from its current state")
    c["status"] = "RESCINDED"
    touch(c)
    practice = store.practices.get(c["practice_id"])
    if practice is not None and practice["status"] == "DEPARTING":
        practice["status"] = "AFFILIATED"
        touch(practice)
    return ok(c)


# ---------------------------------------------------------------------------
# CommitteeVote
# ---------------------------------------------------------------------------

def _eligible_voters(market_id):
    """Providers with provider_role PHYSICIAN, status != DEACTIVATED, whose
    practice is in this market with status ONBOARDING or AFFILIATED."""
    practice_ids = {
        p["id"]
        for p in store.practices.values()
        if p["market_id"] == market_id and p["status"] in ("ONBOARDING", "AFFILIATED")
    }
    return [
        pr
        for pr in store.providers.values()
        if pr["practice_id"] in practice_ids
        and pr["provider_role"] == "PHYSICIAN"
        and pr["status"] != "DEACTIVATED"
    ]


@bp.route("/api/committee-votes", methods=["POST"])
def create_vote():
    require_roles("MarketCommitteeChair")
    data = body_json()
    market_id = require_str(data, "market_id")
    motion_type = require_enum(
        data, "motion_type", {"PAYER_CONTRACT_RATIFICATION", "FEE_SCHEDULE_ADOPTION"}
    )
    subject_contract_id = require_str(data, "subject_contract_id")
    if market_id not in store.markets:
        raise err_not_found("MARKET", "Market not found")
    if subject_contract_id not in store.payer_contracts:
        raise err_not_found("PAYER_CONTRACT", "Payer contract not found")
    eligible = _eligible_voters(market_id)
    if not eligible:
        raise err_no_voters()
    v = new_entity()
    v.update(
        market_id=market_id,
        motion_type=motion_type,
        subject_contract_id=subject_contract_id,
        eligible_voter_count=len(eligible),
        votes_for=0,
        votes_against=0,
        voted_provider_ids=[],
        status="OPEN",
    )
    store.votes[v["id"]] = v
    return created(v)


@bp.route("/api/committee-votes", methods=["GET"])
def list_votes():
    get_context()
    limit, offset = parse_pagination()
    items = list(store.votes.values())
    mid = request.args.get("market_id")
    if mid is not None:
        items = [v for v in items if v["market_id"] == mid]
    sc = request.args.get("subject_contract_id")
    if sc is not None:
        items = [v for v in items if v["subject_contract_id"] == sc]
    st = request.args.get("status")
    if st is not None:
        items = [v for v in items if v["status"] == st]
    return paginate(items, limit, offset)


@bp.route("/api/committee-votes/<vid>", methods=["GET"])
def get_vote(vid):
    get_context()
    v = store.votes.get(vid)
    if v is None:
        raise err_not_found("VOTE", "Vote not found")
    return ok(v)


@bp.route("/api/committee-votes/<vid>/cast", methods=["POST"])
def cast_vote(vid):
    user_id, _role = require_roles("PhysicianBoardMember")
    data = body_json()
    ballot = require_enum(data, "ballot", {"FOR", "AGAINST"})
    v = store.votes.get(vid)
    if v is None:
        raise err_not_found("VOTE", "Vote not found")
    if v["status"] != "OPEN":
        raise err_transition("Vote is not OPEN")
    eligible_ids = {p["id"] for p in _eligible_voters(v["market_id"])}
    if user_id not in eligible_ids:
        raise err_perms("Caller is not an eligible voter of this vote's market")
    if user_id in v["voted_provider_ids"]:
        raise err_dup_vote()
    if ballot == "FOR":
        v["votes_for"] += 1
    else:
        v["votes_against"] += 1
    v["voted_provider_ids"].append(user_id)
    half_floor = v["eligible_voter_count"] // 2
    if v["votes_for"] > half_floor:
        v["status"] = "PASSED"
    elif v["votes_against"] > half_floor:
        v["status"] = "REJECTED"
    elif len(v["voted_provider_ids"]) >= v["eligible_voter_count"]:
        v["status"] = "REJECTED"
    touch(v)
    return ok(v)
