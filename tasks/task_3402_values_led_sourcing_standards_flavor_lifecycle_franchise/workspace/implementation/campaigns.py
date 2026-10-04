"""Activism campaigns under dual governance (PRD section 3.7).

The independent board proposes and decides campaigns; the parent company
schedules operations, dispatches retail-partner notices, and launches. The
board may veto from BOARD_APPROVED, OPS_SCHEDULED or LAUNCHED. Segregation
of duties: the decider must differ from the proposer.
"""
from flask import Blueprint

from auth import authenticate, authorize
from db import STORE, new_resource, public, touch
from envelope import ok
from errors import fail
from validate import (ISSUE_AREAS, RETAIL_IMPACTS, get_body, req_bool,
                      req_enum, req_str)

bp = Blueprint("campaigns", __name__)

READ_ROLES = ("IndependentBoardMember", "ParentOpsController",
              "FlavorManager")


def get_campaign(cid):
    c = STORE["campaigns"].get(cid)
    if c is None:
        fail("ERR_CAMPAIGN_NOT_FOUND", "Campaign id does not exist")
    return c


@bp.post("/campaigns")
def create_campaign():
    uid, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    body = get_body()
    title = req_str(body, "title")
    issue_area = req_enum(body, "issue_area", ISSUE_AREAS)
    impact = req_enum(body, "retail_partner_impact", RETAIL_IMPACTS)
    r = new_resource()
    r.update({
        "title": title,
        "issue_area": issue_area,
        "retail_partner_impact": impact,
        "proposer_user_id": uid,
        "approval_status": "BOARD_REVIEW",
        "retail_notice_status": ("NOT_REQUIRED" if impact == "NONE"
                                 else "PENDING"),
        "decided_by_user_id": None,
    })
    STORE["campaigns"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/campaigns/<cid>")
def read_campaign(cid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    return ok(public(get_campaign(cid)))


@bp.post("/campaigns/<cid>/board-decision")
def board_decision(cid):
    uid, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    c = get_campaign(cid)
    # Segregation of duties (ladder rung 4) before state evaluation.
    if uid == c["proposer_user_id"]:
        fail("ERR_SOD_CAMPAIGN_PROPOSER",
             "The decider must differ from the campaign's proposer")
    body = get_body()
    approve = req_bool(body, "approve")
    if c["approval_status"] != "BOARD_REVIEW":
        fail("ERR_INVALID_STATE",
             "Only a campaign in BOARD_REVIEW can receive a board decision")
    c["approval_status"] = "BOARD_APPROVED" if approve else "BOARD_REJECTED"
    c["decided_by_user_id"] = uid
    touch(c)
    return ok(public(c))


@bp.post("/campaigns/<cid>/schedule-ops")
def schedule_ops(cid):
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    c = get_campaign(cid)
    if c["approval_status"] != "BOARD_APPROVED":
        fail("ERR_INVALID_STATE",
             "Only a BOARD_APPROVED campaign can be operationally scheduled")
    c["approval_status"] = "OPS_SCHEDULED"
    touch(c)
    return ok(public(c))


@bp.post("/campaigns/<cid>/dispatch-retail-notices")
def dispatch_retail_notices(cid):
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    c = get_campaign(cid)
    if (c["approval_status"] not in ("BOARD_APPROVED", "OPS_SCHEDULED")
            or c["retail_notice_status"] != "PENDING"):
        fail("ERR_INVALID_STATE",
             "Retail notices can be dispatched only for a board-approved "
             "campaign with notices PENDING")
    c["retail_notice_status"] = "DISPATCHED"
    touch(c)
    return ok(public(c))


@bp.post("/campaigns/<cid>/launch")
def launch_campaign(cid):
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    c = get_campaign(cid)
    if c["approval_status"] != "OPS_SCHEDULED":
        fail("ERR_INVALID_STATE",
             "Only an OPS_SCHEDULED campaign can be launched")
    if c["retail_notice_status"] == "PENDING":
        fail("ERR_RETAIL_NOTICES_PENDING",
             "Retail-partner notices must be dispatched before launch")
    c["approval_status"] = "LAUNCHED"
    touch(c)
    return ok(public(c))


@bp.post("/campaigns/<cid>/veto")
def veto_campaign(cid):
    _, role = authenticate()
    authorize(role, ("IndependentBoardMember",))
    c = get_campaign(cid)
    if c["approval_status"] not in ("BOARD_APPROVED", "OPS_SCHEDULED",
                                    "LAUNCHED"):
        fail("ERR_INVALID_STATE",
             "Only a BOARD_APPROVED, OPS_SCHEDULED or LAUNCHED campaign can "
             "be vetoed")
    c["approval_status"] = "WITHDRAWN"
    touch(c)
    return ok(public(c))
