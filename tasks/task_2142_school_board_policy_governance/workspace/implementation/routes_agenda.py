"""Agenda items, roll-call votes and speaker cards."""

from flask import Blueprint

import auth
import calc
import resp
import store
import validate as v
from errors import fail
from store import db, set_fields, touch

bp = Blueprint("agenda", __name__)

ITEM_TYPES = ["POLICY_FIRST_READING", "POLICY_SECOND_READING", "WAIVER_DECISION",
              "SUPERINTENDENT_EVALUATION", "CONSENT"]
ITEM_STATUSES = ["PROPOSED", "POSTED", "TABLED", "ACTED", "WITHDRAWN"]
AFFILIATIONS = ["PARENT", "STAFF", "STUDENT", "COMMUNITY", "VENDOR"]
CARD_STATUSES = ["REQUESTED", "GRANTED", "DENIED", "RELEASED"]
READING_TYPES = ("POLICY_FIRST_READING", "POLICY_SECOND_READING")


# ---------------------------------------------------------------------------
# downstream cascades
# ---------------------------------------------------------------------------

def adopt_version(version, meeting, emergency):
    now = store.now()
    effective = now if emergency else store.add_days(now, calc.EFFECTIVE_DELAY_DAYS)
    set_fields(version, status="ADOPTED", reading_count=2,
               adopting_meeting_id=meeting["id"], adopted_at=now,
               effective_date=effective)

    policy = db["policies"].get(version["policy_id"])
    if policy is None:
        return
    for other in db["policy_versions"].values():
        if other["policy_id"] == policy["id"] and other["id"] != version["id"] \
                and other["status"] == "ADOPTED":
            set_fields(other, status="SUPERSEDED", superseded_at=now)

    set_fields(policy, status="ADOPTED",
               adopted_version_no=version["version_no"], last_review_date=now)
    touch(policy)

    for m in calc.policy_mandates(policy["id"]):
        if m["status"] in ("OPEN", "IN_PROGRESS", "OVERDUE") \
                and m["required_action"] in ("ADOPT_NEW", "REVISE_EXISTING") \
                and m["issued_on"] <= now:
            set_fields(m, status="SATISFIED",
                       satisfied_by_version_no=version["version_no"],
                       days_past_deadline=0)

    calc.policy_scoped_recompute(policy)


def grant_waiver(waiver):
    start, end, days = calc.grant_waiver_window(waiver)
    set_fields(waiver, status="GRANTED", granted_start_date=start,
               granted_end_date=end, granted_days=days)
    policy = db["policies"].get(waiver["policy_id"])
    if policy is not None:
        calc.policy_scoped_recompute(policy)


# ---------------------------------------------------------------------------
# agenda items
# ---------------------------------------------------------------------------

@bp.post("/governance/agenda-items")
def create_agenda_item():
    auth.authorize(["BoardClerk"])
    body = v.body()
    meeting_id = v.req_id(body, "meeting_id")
    item_type = v.req_enum(body, "item_type", ITEM_TYPES)
    title = v.req_str(body, "title")
    expected = v.req_int(body, "expected_meeting_version")
    policy_version_id = v.opt_id(body, "policy_version_id")
    waiver_request_id = v.opt_id(body, "waiver_request_id")

    if item_type in READING_TYPES:
        if policy_version_id is None:
            fail("ERR_INVALID_REQUEST",
                 "policy_version_id is required for a policy reading item.")
    elif policy_version_id is not None:
        fail("ERR_INVALID_REQUEST",
             "policy_version_id must be null for this item type.")
    if item_type == "WAIVER_DECISION":
        if waiver_request_id is None:
            fail("ERR_INVALID_REQUEST",
                 "waiver_request_id is required for a waiver decision item.")
    elif waiver_request_id is not None:
        fail("ERR_INVALID_REQUEST",
             "waiver_request_id must be null for this item type.")

    meeting = v.find("meetings", meeting_id)
    version = None
    waiver = None
    if policy_version_id is not None:
        version = v.find("policy_versions", policy_version_id)
    if waiver_request_id is not None:
        waiver = v.find("waivers", waiver_request_id)

    if expected != meeting["version"]:
        fail("ERR_STALE_VERSION",
             "expected_meeting_version does not match the meeting's version.")

    if meeting.get("agenda_locked_at") is not None:
        fail("ERR_AGENDA_LOCKED", "The agenda is locked.")

    if item_type == "POLICY_FIRST_READING":
        if version["status"] != "DRAFT":
            fail("ERR_POLICY_VERSION_NOT_ELIGIBLE",
                 "A first reading requires a draft version.")
    elif item_type == "POLICY_SECOND_READING":
        if version["status"] not in ("DRAFT", "FIRST_READING_PASSED"):
            fail("ERR_POLICY_VERSION_NOT_ELIGIBLE",
                 "The version is no longer eligible for a reading.")
    elif item_type == "WAIVER_DECISION":
        if waiver["status"] not in ("SUBMITTED", "BOARD_PENDING"):
            fail("ERR_WAIVER_NOT_IN_REVIEW",
                 "The waiver is not under review.")

    existing = calc.meeting_items(meeting_id)
    next_seq = max([i["sequence_no"] for i in existing] or [0]) + 1

    rec = store.create("agenda_items", "AgendaItem", {
        "meeting_id": meeting_id,
        "sequence_no": next_seq,
        "item_type": item_type,
        "title": title,
        "policy_version_id": policy_version_id,
        "waiver_request_id": waiver_request_id,
        "requires_public_comment": item_type in (
            "POLICY_FIRST_READING", "POLICY_SECOND_READING", "WAIVER_DECISION"),
        "status": "PROPOSED",
        "vote_yes": 0,
        "vote_no": 0,
        "vote_abstain": 0,
        "recused_member_count": 0,
        "absent_member_count": 0,
        "required_yes_votes": None,
        "vote_outcome": None,
        "acted_at": None,
        "meeting_version_after": None,
    })
    touch(meeting)
    rec["meeting_version_after"] = meeting["version"]
    return resp.created(store.serialize(rec))


@bp.get("/governance/agenda-items")
def list_agenda_items():
    auth.authorize(auth.READ_ROLES_PUBLIC)
    limit, offset = v.pagination()
    meeting_id = v.query_str("meeting_id")
    policy_version_id = v.query_str("policy_version_id")
    waiver_request_id = v.query_str("waiver_request_id")
    status = v.query_enum("status", ITEM_STATUSES)
    items = store.sorted_rows("agenda_items")
    if meeting_id is not None:
        items = [i for i in items if i["meeting_id"] == meeting_id]
    if policy_version_id is not None:
        items = [i for i in items if i.get("policy_version_id") == policy_version_id]
    if waiver_request_id is not None:
        items = [i for i in items if i.get("waiver_request_id") == waiver_request_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(i) for i in page], limit, offset, total)


@bp.get("/governance/agenda-items/<item_id>")
def get_agenda_item(item_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    rec = v.find("agenda_items", item_id)
    return resp.ok(store.serialize(rec))


# ---------------------------------------------------------------------------
# roll-call vote
# ---------------------------------------------------------------------------

@bp.post("/governance/agenda-items/<item_id>/record-vote")
def record_vote(item_id):
    user_id, role = auth.authorize(["BoardPresident"])
    item = v.find("agenda_items", item_id)
    body = v.body()
    yes_ids = v.req_id_list(body, "yes_member_ids")
    no_ids = v.req_id_list(body, "no_member_ids")
    abstain_ids = v.req_id_list(body, "abstain_member_ids")
    auth.enforce_president(user_id, role)

    if item["status"] != "POSTED":
        fail("ERR_AGENDA_ITEM_NOT_POSTED",
             "Only a posted agenda item may be voted on.")

    meeting = db["meetings"].get(item["meeting_id"])
    if meeting is None or meeting["status"] != "OPEN":
        fail("ERR_MEETING_NOT_OPEN", "The parent meeting is not open.")

    version = None
    waiver = None
    if item["item_type"] == "POLICY_FIRST_READING":
        version = db["policy_versions"].get(item.get("policy_version_id"))
        if version is None or version["status"] != "DRAFT":
            fail("ERR_POLICY_VERSION_NOT_ELIGIBLE",
                 "A first reading requires a draft version.")
    elif item["item_type"] == "POLICY_SECOND_READING":
        version = db["policy_versions"].get(item.get("policy_version_id"))
        if version is None or version["status"] != "FIRST_READING_PASSED":
            fail("ERR_POLICY_VERSION_NOT_ELIGIBLE",
                 "A second reading requires a version that passed its first reading.")
    elif item["item_type"] == "WAIVER_DECISION":
        waiver = db["waivers"].get(item.get("waiver_request_id"))
        if waiver is None or waiver["status"] != "BOARD_PENDING":
            fail("ERR_WAIVER_NOT_IN_REVIEW",
                 "The waiver is not pending a board decision.")

    policy_id = calc.item_policy_id(item)
    policy = db["policies"].get(policy_id) if policy_id else None
    all_ids = list(yes_ids) + list(no_ids) + list(abstain_ids)

    for member_id in all_ids:
        if calc.recused_on_policy(member_id, policy_id):
            fail("ERR_RECUSED_MEMBER_VOTED",
                 "A recused trustee may not be counted in this vote.")

    recused_count = calc.count_recused(meeting, policy_id)
    votes_cast = len(yes_ids) + len(no_ids) + len(abstain_ids)
    if votes_cast + recused_count < store.meeting_quorum_required(meeting):
        fail("ERR_QUORUM_NOT_MET", "The vote does not meet quorum.")

    if item["item_type"] == "POLICY_SECOND_READING":
        if version.get("first_reading_meeting_id") == meeting["id"]:
            fail("ERR_SECOND_READING_SAME_MEETING",
                 "A second reading may not be held at the first-reading meeting.")
        first_meeting = db["meetings"].get(version.get("first_reading_meeting_id"))
        if first_meeting is None or first_meeting["minutes_status"] != "APPROVED":
            fail("ERR_MINUTES_NOT_APPROVED",
                 "The first-reading meeting's minutes are not approved.")

    attending = set(meeting.get("attending_member_ids") or [])
    for member_id in all_ids:
        if member_id not in attending:
            fail("ERR_VOTER_NOT_IN_ATTENDANCE",
                 "Trustee %s is not recorded in attendance." % member_id)

    if len(all_ids) != len(set(all_ids)):
        fail("ERR_DUPLICATE_VOTER", "A trustee was counted more than once.")

    snapshot = meeting.get("seated_member_count_snapshot") or 0
    vote_yes = len(yes_ids)
    vote_no = len(no_ids)
    vote_abstain = len(abstain_ids)
    absent = snapshot - (vote_yes + vote_no + vote_abstain + recused_count)
    required = calc.required_yes_votes(item, snapshot, votes_cast, policy)
    outcome = "PASSED" if vote_yes >= required else "FAILED"

    set_fields(item, vote_yes=vote_yes, vote_no=vote_no,
               vote_abstain=vote_abstain, recused_member_count=recused_count,
               absent_member_count=absent, required_yes_votes=required,
               vote_outcome=outcome, status="ACTED", acted_at=store.now())

    if item["item_type"] == "POLICY_FIRST_READING" and outcome == "PASSED":
        emergency = (meeting["meeting_type"] == "EMERGENCY"
                     and vote_yes >= snapshot - 1)
        if emergency:
            adopt_version(version, meeting, True)
        else:
            set_fields(version, status="FIRST_READING_PASSED", reading_count=1,
                       first_reading_meeting_id=meeting["id"])
    elif item["item_type"] == "POLICY_SECOND_READING":
        if outcome == "PASSED":
            adopt_version(version, meeting, False)
        else:
            set_fields(version, status="DRAFT", reading_count=0,
                       first_reading_meeting_id=None)
    elif item["item_type"] == "WAIVER_DECISION":
        if outcome == "PASSED":
            grant_waiver(waiver)
        else:
            set_fields(waiver, status="DENIED", denial_stage="BOARD")

    return resp.ok(store.serialize(item))


# ---------------------------------------------------------------------------
# speaker cards
# ---------------------------------------------------------------------------

@bp.post("/governance/agenda-items/<item_id>/public-comments")
def create_public_comment(item_id):
    auth.authorize(["Public", "BoardClerk"])
    item = v.find("agenda_items", item_id)
    body = v.body()
    speaker_name = v.req_str(body, "speaker_name")
    affiliation = v.req_enum(body, "speaker_affiliation", AFFILIATIONS)
    requested = v.req_int(body, "requested_minutes", 1, 5)

    meeting = db["meetings"].get(item["meeting_id"])
    if meeting is None or meeting["status"] not in ("DRAFT", "NOTICED"):
        fail("ERR_PUBLIC_COMMENT_CLOSED", "Speaker sign-up is closed.")

    if meeting["public_comment_minutes_budget"] <= 0 \
            or not item["requires_public_comment"]:
        fail("ERR_PUBLIC_COMMENT_NOT_PERMITTED",
             "This item carries no public-comment period.")

    live = [c for c in calc.item_cards(item_id)
            if c["status"] in ("REQUESTED", "GRANTED")]
    if len(live) >= calc.MAX_SPEAKERS_PER_ITEM:
        fail("ERR_SPEAKER_LIMIT_REACHED",
             "The speaker limit for this item has been reached.")

    rec = store.create("public_comments", "PublicComment", {
        "agenda_item_id": item_id,
        "speaker_name": speaker_name,
        "speaker_affiliation": affiliation,
        "requested_minutes": requested,
        "submitted_at": store.now(),
        "allotted_minutes": 0,
        "status": "REQUESTED",
        "denial_reason": None,
    })
    return resp.created(store.serialize(rec))


@bp.get("/governance/agenda-items/<item_id>/public-comments")
def list_public_comments(item_id):
    auth.authorize(auth.READ_ROLES_PUBLIC)
    v.find("agenda_items", item_id)
    limit, offset = v.pagination()
    status = v.query_enum("status", CARD_STATUSES)
    items = [c for c in db["public_comments"].values()
             if c["agenda_item_id"] == item_id]
    items.sort(key=lambda c: (c["submitted_at"], c["_seq"]))
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = v.paginate(items, limit, offset)
    return resp.listing([store.serialize(c) for c in page], limit, offset, total)
