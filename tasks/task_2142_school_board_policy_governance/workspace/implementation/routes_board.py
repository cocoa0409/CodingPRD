"""Trustees, committees, committee seats and conflict disclosures."""

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields, touch

bp = Blueprint("board", __name__)

OFFICES = ["PRESIDENT", "VICE_PRESIDENT", "MEMBER"]
CHARTER_TYPES = ["POLICY", "FINANCE", "PERSONNEL", "AUDIT"]
SEAT_ROLES = ["CHAIR", "MEMBER"]
ASSIGNMENT_STATUSES = ["ACTIVE", "RECUSED", "REMOVED"]
NATURES = ["FINANCIAL", "VENDOR", "EMPLOYMENT", "FAMILIAL"]
DISCLOSURE_STATUSES = ["RECUSAL_REQUIRED", "ADVISORY_ONLY", "CLEARED"]


# ---------------------------------------------------------------------------
# board members
# ---------------------------------------------------------------------------

@bp.post("/governance/board-members")
def create_board_member():
    auth.authorize(["BoardClerk"])
    body = v.body()
    full_name = v.req_str(body, "full_name")
    seat_number = v.req_int(body, "seat_number", 1, 15)
    term_start = v.req_dt(body, "term_start_date")
    term_end = v.req_dt(body, "term_end_date")
    employer = v.req_str(body, "employer_name")
    office = v.opt_enum(body, "office", OFFICES, "MEMBER")
    if term_end <= term_start:
        fail("ERR_INVALID_REQUEST",
             "term_end_date must be strictly after term_start_date.")

    for m in db["board_members"].values():
        if m["status"] != "SEATED":
            continue
        if m["seat_number"] == seat_number:
            fail("ERR_DUPLICATE_SEAT_NUMBER",
                 "Seat %s is already occupied." % seat_number)
        if office == "PRESIDENT" and m["office"] == "PRESIDENT":
            fail("ERR_DUPLICATE_SEAT_NUMBER",
                 "A seated trustee already holds the PRESIDENT office.")

    rec = store.create("board_members", "BoardMember", {
        "full_name": full_name,
        "seat_number": seat_number,
        "office": office,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "employer_name": employer,
        "status": "SEATED",
        "open_recusal_count": 0,
        "active_committee_count": 0,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/board-members/<member_id>")
def get_board_member(member_id):
    auth.authorize(auth.READ_ROLES_INTERNAL)
    rec = v.find("board_members", member_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/board-members/<member_id>/resign")
def resign_board_member(member_id):
    auth.authorize(["BoardClerk"])
    member = v.find("board_members", member_id)
    if member["status"] != "SEATED":
        fail("ERR_MEMBER_NOT_SEATED", "The trustee is not seated.")

    set_fields(member, status="RESIGNED")
    affected = set()
    for a in db["assignments"].values():
        if a["board_member_id"] != member["id"]:
            continue
        if a["status"] in ("ACTIVE", "RECUSED"):
            set_fields(a, status="REMOVED", removed_on=store.now())
            affected.add(a["committee_id"])
    for cid in affected:
        committee = db["committees"].get(cid)
        if committee is not None:
            calc.recompute_committee(committee)
    for d in db["disclosures"].values():
        if d["board_member_id"] == member["id"] \
                and d["status"] == "RECUSAL_REQUIRED":
            set_fields(d, status="CLEARED", cleared_on=store.now())
    calc.recompute_member_counts(member)
    return resp.ok(store.serialize(member))


# ---------------------------------------------------------------------------
# committees
# ---------------------------------------------------------------------------

@bp.post("/governance/committees")
def create_committee():
    auth.authorize(["BoardClerk"])
    body = v.body()
    name = v.req_str(body, "name")
    charter_type = v.req_enum(body, "charter_type", CHARTER_TYPES)
    seat_capacity = v.req_int(body, "seat_capacity", 3, 9)
    quorum_size = v.req_int(body, "quorum_size", 2, None)
    if quorum_size > seat_capacity:
        fail("ERR_INVALID_REQUEST", "quorum_size may not exceed seat_capacity.")

    rec = store.create("committees", "Committee", {
        "name": name,
        "charter_type": charter_type,
        "seat_capacity": seat_capacity,
        "quorum_size": quorum_size,
        "status": "INQUORATE",
        "filled_seat_count": 0,
        "voting_seat_count": 0,
        "vacant_seat_count": seat_capacity,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/committees/<committee_id>")
def get_committee(committee_id):
    auth.authorize(auth.READ_ROLES_INTERNAL)
    rec = v.find("committees", committee_id)
    return resp.ok(store.serialize(rec))


# ---------------------------------------------------------------------------
# committee assignments
# ---------------------------------------------------------------------------

@bp.post("/governance/committee-assignments")
def create_assignment():
    auth.authorize(["BoardClerk"])
    body = v.body()
    committee_id = v.req_id(body, "committee_id")
    member_id = v.req_id(body, "board_member_id")
    role_on_committee = v.opt_enum(body, "role_on_committee", SEAT_ROLES, "MEMBER")

    committee = v.find("committees", committee_id)
    member = v.find("board_members", member_id)

    for a in db["assignments"].values():
        if a["status"] not in ("ACTIVE", "RECUSED"):
            continue
        if a["committee_id"] != committee_id:
            continue
        if a["board_member_id"] == member_id:
            fail("ERR_DUPLICATE_ASSIGNMENT",
                 "The trustee already holds a seat on this committee.")
    if role_on_committee == "CHAIR":
        for a in db["assignments"].values():
            if a["committee_id"] == committee_id and a["status"] == "ACTIVE" \
                    and a["role_on_committee"] == "CHAIR":
                fail("ERR_DUPLICATE_ASSIGNMENT",
                     "The committee already has an active chair.")

    if committee["vacant_seat_count"] <= 0:
        fail("ERR_COMMITTEE_SEATS_FULL", "The committee has no vacant seats.")

    rec = store.create("assignments", "CommitteeAssignment", {
        "committee_id": committee_id,
        "board_member_id": member_id,
        "role_on_committee": role_on_committee,
        "status": "ACTIVE",
        "assigned_on": store.now(),
        "removed_on": None,
    })
    calc.recompute_committee(committee)
    calc.recompute_member_counts(member)
    return resp.created(store.serialize(rec))


@bp.get("/governance/committee-assignments")
def list_assignments():
    auth.authorize(auth.READ_ROLES_INTERNAL)
    limit, offset = v.pagination()
    committee_id = v.query_str("committee_id")
    member_id = v.query_str("board_member_id")
    status = v.query_enum("status", ASSIGNMENT_STATUSES)
    items = store.sorted_rows("assignments")
    if committee_id is not None:
        items = [a for a in items if a["committee_id"] == committee_id]
    if member_id is not None:
        items = [a for a in items if a["board_member_id"] == member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(a) for a in page], limit, offset, total)


@bp.get("/governance/committee-assignments/<assignment_id>")
def get_assignment(assignment_id):
    auth.authorize(auth.READ_ROLES_INTERNAL)
    rec = v.find("assignments", assignment_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/committee-assignments/<assignment_id>/status")
def assignment_status(assignment_id):
    auth.authorize(["BoardClerk"])
    assignment = v.find("assignments", assignment_id)
    body = v.body()
    action = v.req_enum(body, "action", ["RECUSE", "REINSTATE", "REMOVE"])

    if action == "RECUSE":
        if assignment["status"] != "ACTIVE":
            fail("ERR_ASSIGNMENT_STATE_INVALID",
                 "Only an active seat may be recused.")
        set_fields(assignment, status="RECUSED")
    elif action == "REINSTATE":
        if assignment["status"] != "RECUSED":
            fail("ERR_ASSIGNMENT_STATE_INVALID",
                 "Only a recused seat may be reinstated.")
        member = db["board_members"].get(assignment["board_member_id"])
        if member is None or member["status"] != "SEATED":
            fail("ERR_MEMBER_NOT_SEATED", "The trustee is no longer seated.")
        set_fields(assignment, status="ACTIVE")
    else:
        if assignment["status"] not in ("ACTIVE", "RECUSED"):
            fail("ERR_ASSIGNMENT_STATE_INVALID",
                 "The seat has already been removed.")
        set_fields(assignment, status="REMOVED", removed_on=store.now())

    committee = db["committees"].get(assignment["committee_id"])
    if committee is not None:
        calc.recompute_committee(committee)
    member = db["board_members"].get(assignment["board_member_id"])
    if member is not None:
        calc.recompute_member_counts(member)
    return resp.ok(store.serialize(assignment))


# ---------------------------------------------------------------------------
# conflict disclosures
# ---------------------------------------------------------------------------

@bp.post("/governance/conflict-disclosures")
def create_disclosure():
    user_id, role = auth.authorize(["BoardMember"])
    body = v.body()
    member_id = v.req_id(body, "board_member_id")
    policy_id = v.req_id(body, "policy_id")
    nature = v.req_enum(body, "nature", NATURES)
    narrative = v.req_str(body, "narrative")

    member = v.find("board_members", member_id)
    policy = v.find("policies", policy_id)

    if member_id != user_id:
        fail("ERR_IDENTITY_MISMATCH",
             "A trustee may only file a disclosure in their own name.")

    status = calc.classify_disclosure(nature, policy["category"])
    rec = store.create("disclosures", "ConflictDisclosure", {
        "board_member_id": member_id,
        "policy_id": policy_id,
        "nature": nature,
        "narrative": narrative,
        "status": status,
        "disclosed_on": store.now(),
        "cleared_on": None,
    })
    calc.recompute_member_counts(member)
    return resp.created(store.serialize(rec))


@bp.get("/governance/conflict-disclosures")
def list_disclosures():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    member_id = v.query_str("board_member_id")
    policy_id = v.query_str("policy_id")
    status = v.query_enum("status", DISCLOSURE_STATUSES)
    items = store.sorted_rows("disclosures")
    if member_id is not None:
        items = [d for d in items if d["board_member_id"] == member_id]
    if policy_id is not None:
        items = [d for d in items if d["policy_id"] == policy_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(d) for d in page], limit, offset, total)


@bp.get("/governance/conflict-disclosures/<disclosure_id>")
def get_disclosure(disclosure_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("disclosures", disclosure_id)
    return resp.ok(store.serialize(rec))


@bp.post("/governance/conflict-disclosures/<disclosure_id>/clear")
def clear_disclosure(disclosure_id):
    user_id, role = auth.authorize(["BoardPresident"])
    disclosure = v.find("disclosures", disclosure_id)
    auth.enforce_president(user_id, role)

    if disclosure["status"] == "CLEARED":
        fail("ERR_DISCLOSURE_ALREADY_CLEARED",
             "The disclosure has already been cleared.")

    for item in db["agenda_items"].values():
        if item["status"] != "POSTED":
            continue
        if calc.item_policy_id(item) != disclosure["policy_id"]:
            continue
        meeting = db["meetings"].get(item["meeting_id"])
        if meeting is not None and meeting["status"] == "OPEN":
            fail("ERR_INVALID_MEETING_STATE",
                 "The policy is on the agenda of a meeting currently in session.")

    set_fields(disclosure, status="CLEARED", cleared_on=store.now())
    member = db["board_members"].get(disclosure["board_member_id"])
    if member is not None:
        calc.recompute_member_counts(member)
    return resp.ok(store.serialize(disclosure))
