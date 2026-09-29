"""Neighbourhood feed: posts, flags, revisions and moderation (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from routes_resident import require_active
from store import db, now

bp = Blueprint("feed", __name__)

CATEGORIES = ("SAFETY_REPORT", "LOST_PET", "SUSPICIOUS_ACTIVITY", "GENERAL")
POST_STATES = ("PUBLISHED", "FLAGGED", "UNDER_REVIEW", "REVISION_REQUESTED",
               "REMOVED")
OPENED_REASONS = ("RESIDENT_FLAGS", "AUTO_SCORE", "AUTHOR_SUSPENDED")
DECISIONS = ("UPHELD_PUBLISH", "REQUEST_REVISION", "REMOVE_INACCURATE",
             "REMOVE_DISCRIMINATORY")
CASE_STATES = ("OPEN", "DECIDED", "SUPERSEDED")
CASE_DECISIONS = ("NONE",) + DECISIONS

SIGNALS = ("protected_class_term_count", "unverified_assertion_count",
           "location_profiling_count", "hostile_tone_count")


def require_not_suspended(resident):
    """Refusal ladder rule 31."""
    if resident is not None and resident["post_privilege_state"] == "POSTING_SUSPENDED":
        raise ApiError("ERR_POSTING_SUSPENDED",
                       "Resident %s may not post" % resident["id"])


def _score(post):
    post["discrimination_score"] = calc.discrimination_score(
        post["protected_class_term_count"], post["unverified_assertion_count"],
        post["location_profiling_count"], post["hostile_tone_count"])
    return post["discrimination_score"]


@bp.post("/neighborhood-safety/resident-posts")
def create_post():
    actor = auth.authenticate(("Resident",))
    body = v.body_json()
    v.require_present(body, "author_resident_id")
    author = fetch.must("Resident", body.get("author_resident_id"))
    parent = None
    if body.get("parent_post_id") is not None:
        parent = fetch.must("ResidentPost", body.get("parent_post_id"))
    text = v.str_field(body, "body", min_len=1, max_len=2000)
    category = v.enum_field(body, "category", CATEGORIES)
    post_x = v.coord_field(body, "post_x_m")
    post_y = v.coord_field(body, "post_y_m")
    cap = v.int_field(body, "alert_fanout_cap", required=False, default=50,
                      lo=0, hi=500)
    signals = {}
    for name in SIGNALS:
        signals[name] = v.int_field(body, name, required=False, default=0, lo=0,
                                    hi=50)
    auth.require_resident_scope(actor, author["id"])
    require_active(author)
    require_not_suspended(author)

    row = engine.new_row({
        "author_resident_id": author["id"],
        "parent_post_id": parent["id"] if parent is not None else None,
        "body": text,
        "category": category,
        "post_x_m": post_x,
        "post_y_m": post_y,
        "alert_fanout_cap": cap,
        "discrimination_score": None,
        "state": "PUBLISHED",
        "flag_count": 0,
        "flagged_by_resident_ids": [],
        "revision_count": 0,
        "alert_candidate_count": 0,
        "alert_fanout_count": 0,
        "alert_suppressed_count": 0,
        "auto_flag_reason": None,
    })
    row.update(signals)
    score = _score(row)
    db.posts[row["id"]] = row
    if calc.score_flags(score):
        row["state"] = "FLAGGED"
        row["auto_flag_reason"] = "DISCRIMINATION_SCORE"
    else:
        engine.post_fanout(row)
    return envelope.created(serialize.dump("ResidentPost", row))


@bp.post("/neighborhood-safety/resident-posts/<post_id>/flag")
def flag_post(post_id):
    actor = auth.authenticate(("Resident",))
    post = fetch.must("ResidentPost", post_id)
    body = v.body_json()
    v.str_field(body, "flag_reason", min_len=1)
    flagger_id = actor.user_id
    require_active(db.residents.get(flagger_id))
    if post["state"] != "PUBLISHED":
        raise ApiError("ERR_POST_NOT_PUBLISHED",
                       "Post %s is not in the feed" % post["id"])
    if post["author_resident_id"] == flagger_id:
        raise ApiError("ERR_SELF_FLAG_NOT_ALLOWED",
                       "An author may not flag their own post")
    if flagger_id in post["flagged_by_resident_ids"]:
        raise ApiError("ERR_DUPLICATE_FLAG",
                       "This resident has already flagged post %s" % post["id"])

    post["flag_count"] += 1
    post["flagged_by_resident_ids"] = post["flagged_by_resident_ids"] + [
        flagger_id]
    if post["flag_count"] >= calc.RESIDENT_FLAG_THRESHOLD:
        post["state"] = "FLAGGED"
        post["auto_flag_reason"] = "RESIDENT_FLAG_THRESHOLD"
    engine.touch(post)
    return envelope.ok(serialize.dump("ResidentPost", post))


@bp.post("/neighborhood-safety/resident-posts/<post_id>/revise")
def revise_post(post_id):
    actor = auth.authenticate(("Resident",))
    post = fetch.must("ResidentPost", post_id)
    body = v.body_json()
    text = v.str_field(body, "body", min_len=1, max_len=2000)
    signals = {}
    for name in SIGNALS:
        signals[name] = v.int_field(body, name, required=False, default=0, lo=0,
                                    hi=50)
    author = db.residents.get(post["author_resident_id"])
    auth.require_resident_scope(actor, post["author_resident_id"])
    require_active(author)
    if post["state"] != "REVISION_REQUESTED":
        raise ApiError("ERR_POST_NOT_REVISABLE",
                       "Post %s is not awaiting a revision" % post["id"])
    require_not_suspended(author)

    post["body"] = text
    post.update(signals)
    score = _score(post)
    post["revision_count"] += 1
    if calc.score_flags(score):
        post["state"] = "FLAGGED"
        post["auto_flag_reason"] = "DISCRIMINATION_SCORE"
    else:
        post["state"] = "PUBLISHED"
        post["auto_flag_reason"] = None
        engine.post_fanout(post)
    engine.touch(post)
    return envelope.ok(serialize.dump("ResidentPost", post))


@bp.get("/neighborhood-safety/resident-posts/<post_id>")
def read_post(post_id):
    auth.authenticate(("PlatformAdmin", "Moderator", "Resident", "Officer"))
    post = fetch.must("ResidentPost", post_id)
    return envelope.ok(serialize.dump("ResidentPost", post))


@bp.get("/neighborhood-safety/resident-posts")
def list_posts():
    auth.authenticate(("PlatformAdmin", "Moderator", "Resident", "Officer"))
    limit, offset = v.pagination()
    author_id = v.query_str("author_resident_id")
    parent_id = v.query_str("parent_post_id")
    state = v.query_enum("state", POST_STATES)
    category = v.query_enum("category", CATEGORIES)
    rows = list(db.posts.values())
    if author_id is not None:
        rows = [r for r in rows if r["author_resident_id"] == author_id]
    if parent_id is not None:
        rows = [r for r in rows if r["parent_post_id"] == parent_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("ResidentPost", page), limit,
                               offset, total)


# --------------------------------------------------------------------------
# moderation cases
# --------------------------------------------------------------------------

@bp.post("/neighborhood-safety/moderation-cases")
def open_case():
    actor = auth.authenticate(("Moderator",))
    body = v.body_json()
    v.require_present(body, "resident_post_id")
    post = fetch.must("ResidentPost", body.get("resident_post_id"))
    opened_reason = v.enum_field(body, "opened_reason", OPENED_REASONS)
    expected_version = v.int_field(body, "expected_resident_post_version")
    if post["state"] not in ("FLAGGED", "UNDER_REVIEW"):
        raise ApiError("ERR_POST_NOT_FLAGGED",
                       "Post %s is not awaiting moderation" % post["id"])
    if expected_version != post["version"]:
        raise ApiError("ERR_STALE_POST_VERSION",
                       "expected_resident_post_version does not match the post")

    case = engine.new_row({
        "resident_post_id": post["id"],
        "opened_reason": opened_reason,
        "opened_by_user_id": actor.user_id,
        "decided_by_user_id": None,
        "state": "OPEN",
        "decision": "NONE",
        "decision_note": None,
        "decided_at": None,
        "superseded_by_case_created_at": None,
        "post_discrimination_score_at_open": post["discrimination_score"],
    })
    db.cases[case["id"]] = case
    for other in store.by_created(_cases_of_post(post["id"])):
        if other["id"] == case["id"] or other["state"] != "OPEN":
            continue
        other["state"] = "SUPERSEDED"
        other["superseded_by_case_created_at"] = case["created_at"]
        engine.touch(other)
    post["state"] = "UNDER_REVIEW"
    engine.touch(post)
    return envelope.created(serialize.dump("ModerationCase", case))


def _cases_of_post(post_id):
    return [c for c in db.cases.values() if c["resident_post_id"] == post_id]


@bp.post("/neighborhood-safety/moderation-cases/<case_id>/decide")
def decide_case(case_id):
    actor = auth.authenticate(("Moderator",))
    case = fetch.must("ModerationCase", case_id)
    body = v.body_json()
    decision = v.enum_field(body, "decision", DECISIONS)
    decision_note = v.str_field(body, "decision_note", allow_empty=True)
    if case["opened_by_user_id"] == actor.user_id:
        auth.sod("The deciding moderator may not be the opening moderator")
    if case["state"] != "OPEN":
        raise ApiError("ERR_CASE_ALREADY_DECIDED",
                       "Case %s is already resolved" % case["id"])
    post = db.posts.get(case["resident_post_id"])
    if post is None or post["state"] != "UNDER_REVIEW":
        raise ApiError("ERR_POST_NOT_FLAGGED",
                       "The post under this case is not under review")

    case["state"] = "DECIDED"
    case["decision"] = decision
    case["decision_note"] = decision_note
    case["decided_by_user_id"] = actor.user_id
    case["decided_at"] = now()
    engine.touch(case)

    if decision == "UPHELD_PUBLISH":
        post["state"] = "PUBLISHED"
        post["auto_flag_reason"] = None
        engine.touch(post)
        engine.post_fanout(post)
    elif (decision == "REQUEST_REVISION"
            and post["revision_count"] < calc.MAX_REVISION_CYCLES):
        post["state"] = "REVISION_REQUESTED"
        engine.touch(post)
    else:
        post["state"] = "REMOVED"
        engine.touch(post)
        engine.removal_cascade(post, decision)
    return envelope.ok(serialize.dump("ModerationCase", case))


@bp.get("/neighborhood-safety/moderation-cases/<case_id>")
def read_case(case_id):
    auth.authenticate(("PlatformAdmin", "Moderator"))
    case = fetch.must("ModerationCase", case_id)
    return envelope.ok(serialize.dump("ModerationCase", case))


@bp.get("/neighborhood-safety/moderation-cases")
def list_cases():
    auth.authenticate(("PlatformAdmin", "Moderator"))
    limit, offset = v.pagination()
    post_id = v.query_str("resident_post_id")
    state = v.query_enum("state", CASE_STATES)
    decision = v.query_enum("decision", CASE_DECISIONS)
    opened_reason = v.query_enum("opened_reason", OPENED_REASONS)
    rows = list(db.cases.values())
    if post_id is not None:
        rows = [r for r in rows if r["resident_post_id"] == post_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if decision is not None:
        rows = [r for r in rows if r["decision"] == decision]
    if opened_reason is not None:
        rows = [r for r in rows if r["opened_reason"] == opened_reason]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("ModerationCase", page),
                               limit, offset, total)
