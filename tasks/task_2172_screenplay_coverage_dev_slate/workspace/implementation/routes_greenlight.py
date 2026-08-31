"""Committee seats, greenlight reviews and weighted ballots."""

from decimal import Decimal

from flask import Blueprint

import calc
from core import (
    Field, authenticate, collection_rows, created, db, fail, filter_eq, fmt_dt,
    json_body, lookup, new_row, now_str, ok, ok_list, paginate, pagination,
    parse_date, parse_fields, qp, qp_bool, round_half_up, touch,
)

bp = Blueprint("greenlight", __name__)

MEMBER_ROLES = ("SlateAdmin", "DevelopmentExec", "CommitteeMember")
REVIEW_ROLES = ("SlateAdmin", "DevelopmentExec", "CommitteeMember", "BusinessAffairs")


# --------------------------------------------------------------------------
# Committee members
# --------------------------------------------------------------------------
@bp.post("/committee-members")
def create_member():
    authenticate(("SlateAdmin",))
    body = json_body()
    data = parse_fields(body, [
        Field("display_name", "string", required=True),
        Field("vote_weight_bps", "integer", required=True, lo=1, hi=10000),
        Field("veto_power", "boolean", default=False),
        Field("exec_user_id", "string"),
        Field("status", "enum", default="ACTIVE", enum=calc.MEMBER_STATUSES),
    ])
    row = new_row("members", {
        "display_name": data["display_name"],
        "vote_weight_bps": data["vote_weight_bps"],
        "veto_power": data["veto_power"],
        "exec_user_id": data["exec_user_id"],
        "status": data["status"],
    })
    return created(row)


@bp.get("/committee-members/<mid>")
def read_member(mid):
    authenticate(MEMBER_ROLES)
    return ok(lookup("members", mid, "ERR_MEMBER_NOT_FOUND"))


@bp.get("/committee-members")
def list_members():
    authenticate(MEMBER_ROLES)
    limit, offset = pagination()
    rows = collection_rows("members")
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "veto_power", qp_bool("veto_power"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/committee-members/<mid>")
def patch_member(mid):
    authenticate(("SlateAdmin",))
    member = lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [
        Field("status", "enum", enum=calc.MEMBER_STATUSES),
        Field("vote_weight_bps", "integer", lo=1, hi=10000),
    ])
    if data["status"] is not None:
        member["status"] = data["status"]
    if data["vote_weight_bps"] is not None:
        member["vote_weight_bps"] = data["vote_weight_bps"]
    touch(member)
    return ok(member)


@bp.get("/committee-members/<mid>/votes")
def list_member_votes(mid):
    authenticate(MEMBER_ROLES)
    member = lookup("members", mid, "ERR_MEMBER_NOT_FOUND")
    limit, offset = pagination()
    rows = calc.rows_where("votes", member_id=member["id"])
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# Greenlight reviews
# --------------------------------------------------------------------------
@bp.post("/greenlight-reviews")
def create_review():
    authenticate(("SlateAdmin",))
    body = json_body()
    project = None
    if body.get("project_id") is not None:
        project = lookup("projects", body.get("project_id"), "ERR_PROJECT_NOT_FOUND")
    data = parse_fields(body, [
        Field("project_id", "string", required=True),
        Field("session_date", "date", required=True),
        Field("expected_project_version", "integer", required=True),
    ])
    parse_date(data["session_date"])
    if data["expected_project_version"] != project["version"]:
        fail("ERR_STALE_VERSION", "The project has changed since it was last observed.")
    if project["development_status"] in calc.DEV_BLOCKED_FOR_CREATE:
        fail("ERR_INVALID_STATE", "This project may not take a new greenlight review.")
    row = new_row("reviews", {
        "project_id": project["id"],
        "session_date": data["session_date"],
        "status": "OPEN",
        "eligible_weight_bps": 0,
        "cast_weight_bps": 0,
        "decisive_weight_bps": 0,
        "approve_weight_bps": 0,
        "quorum_pct": Decimal("0.00"),
        "approval_pct": Decimal("0.00"),
        "veto_cast": False,
        "decision_note": None,
        "withdrawal_reason": None,
    })
    for existing in calc.rows_where("reviews", project_id=project["id"]):
        if existing["id"] == row["id"]:
            continue
        if existing["status"] in ("OPEN", "VOTING"):
            existing["status"] = "WITHDRAWN"
            existing["withdrawal_reason"] = "SUPERSEDED_BY_NEW_REVIEW"
            touch(existing)
    touch(project)
    return created(row)


@bp.get("/greenlight-reviews/<rid>")
def read_review(rid):
    authenticate(REVIEW_ROLES)
    return ok(lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND"))


@bp.get("/greenlight-reviews")
def list_reviews():
    authenticate(REVIEW_ROLES)
    limit, offset = pagination()
    rows = collection_rows("reviews")
    rows = filter_eq(rows, "project_id", qp("project_id"))
    rows = filter_eq(rows, "status", qp("status"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/greenlight-reviews/<rid>/open-voting")
def open_voting(rid):
    authenticate(("SlateAdmin",))
    review = lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND")
    if review["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN review may move to VOTING.")
    project = db.projects.get(review["project_id"])
    if project is None or project["rights_status"] != "OWNED":
        fail("ERR_RIGHTS_NOT_OWNED", "The project's rights axis is not OWNED.")
    if project["development_status"] not in ("DRAFT_DELIVERED", "POLISH_DELIVERED"):
        fail("ERR_INVALID_STATE", "The project is not at a delivered development state.")
    active = [m for m in collection_rows("members") if m["status"] == "ACTIVE"]
    if len(active) < calc.GREENLIGHT_MIN_ACTIVE_MEMBERS:
        fail("ERR_COMMITTEE_TOO_SMALL", "Too few active committee seats.")
    review["status"] = "VOTING"
    review["eligible_weight_bps"] = sum(m["vote_weight_bps"] for m in active)
    touch(review)
    return ok(review)


@bp.post("/greenlight-reviews/<rid>/votes")
def cast_vote(rid):
    user_id, _role = authenticate(("CommitteeMember",))
    review = lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [
        Field("vote_value", "enum", required=True, enum=calc.VOTE_VALUES),
        Field("comment", "string"),
    ])
    member = lookup("members", user_id, "ERR_MEMBER_NOT_FOUND")
    if review["status"] != "VOTING":
        fail("ERR_INVALID_STATE", "Ballots may only be cast on a VOTING review.")
    if member["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The committee seat is not ACTIVE.")
    project = db.projects.get(review["project_id"])
    if (project is not None and member.get("exec_user_id") is not None
            and member["exec_user_id"] == project["owning_exec_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A member who owns the project may not vote on it.")
    for existing in calc.rows_where("votes", review_id=review["id"]):
        if existing["member_id"] == member["id"]:
            fail("ERR_DUPLICATE_VOTE", "This member has already cast a ballot on this review.")
    vote = new_row("votes", {
        "review_id": review["id"],
        "member_id": member["id"],
        "vote_value": data["vote_value"],
        "weight_bps_snapshot": member["vote_weight_bps"],
        "comment": data["comment"],
        "_veto_power": bool(member["veto_power"]),
    }, versioned=False)
    calc.recompute_review_tallies(review)
    touch(review)
    return created(vote)


@bp.get("/greenlight-reviews/<rid>/votes")
def list_review_votes(rid):
    authenticate(REVIEW_ROLES)
    review = lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND")
    limit, offset = pagination()
    rows = calc.rows_where("votes", review_id=review["id"])
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/greenlight-reviews/<rid>/close")
def close_review(rid):
    authenticate(("SlateAdmin",))
    review = lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("decision_note", "string")])
    if review["status"] != "VOTING":
        fail("ERR_INVALID_STATE", "Only a VOTING review may be closed.")
    calc.recompute_review_tallies(review)
    eligible = review["eligible_weight_bps"]
    if eligible:
        quorum = round_half_up(
            Decimal(100) * Decimal(review["cast_weight_bps"]) / Decimal(eligible), 2)
    else:
        quorum = Decimal("0.00")
    decisive = review["decisive_weight_bps"]
    if decisive > 0:
        approval = round_half_up(
            Decimal(100) * Decimal(review["approve_weight_bps"]) / Decimal(decisive), 2)
    else:
        approval = Decimal("0.00")
    if quorum < calc.GREENLIGHT_QUORUM_PCT:
        fail("ERR_QUORUM_NOT_MET", "Quorum has not been met.")
    review["quorum_pct"] = quorum
    review["approval_pct"] = approval
    review["decision_note"] = data["decision_note"]
    if review["veto_cast"]:
        outcome = "DECLINED"
    elif decisive == 0:
        outcome = "DEFERRED"
    elif approval >= calc.GREENLIGHT_APPROVAL_PCT:
        outcome = "PASSED"
    else:
        outcome = "DECLINED"
    review["status"] = outcome
    touch(review)
    if outcome == "PASSED":
        project = db.projects.get(review["project_id"])
        if project is not None:
            project["development_status"] = "GREENLIT"
            calc.recompute_greenlight_ready(project)
            touch(project)
            prop = db.properties.get(project["property_id"])
            if prop is not None:
                prop["tracking_tier"] = "PRIORITY"
                touch(prop)
                for entry in calc.rows_where("board_entries", property_id=prop["id"]):
                    if entry["status"] == "LIVE":
                        entry["status"] = "ARCHIVED"
                        touch(entry)
    return ok(review)


@bp.post("/greenlight-reviews/<rid>/withdraw")
def withdraw_review(rid):
    authenticate(("SlateAdmin",))
    review = lookup("reviews", rid, "ERR_REVIEW_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if review["status"] in calc.REVIEW_TERMINAL:
        fail("ERR_TERMINAL_STATE", "This review is already in a terminal state.")
    review["status"] = "WITHDRAWN"
    review["withdrawal_reason"] = data["reason"]
    touch(review)
    return ok(review)
