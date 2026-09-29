"""Technical-accuracy sign-offs: requests, reads, decisions."""
from flask import Blueprint

import calc
from core import (
    D,
    all_of,
    base_record,
    commit,
    db,
    fail,
    must_get,
    ok,
    ok_list,
    page,
    parse_instant,
    public,
    public_list,
    r2,
    snap,
    touch,
)
from validate import authenticate, body, filters, pagination, v_enum, v_id, v_str

bp = Blueprint("signoff_routes", __name__)


@bp.post("/topics/<topic_id>/sign-offs")
def request_signoff(topic_id):
    authenticate(("DocsLead",))
    data = body()
    reviewer_id = v_id(data, "reviewer_id")

    topic = must_get("topics", topic_id)
    reviewer = must_get("reviewers", reviewer_id)

    if topic["review_state"] != "PENDING_SIGNOFF":
        fail("ERR_TOPIC_NOT_IN_REVIEW", "The page is not currently in review.")

    revision = calc.latest_revision(topic["id"])
    if revision is not None:
        author = db.writers.get(revision["author_writer_id"])
        if author is not None and author["person_key"] == reviewer["person_key"]:
            fail("ERR_SELF_REVIEW_FORBIDDEN", "An author may never review their own page.")

    for existing in calc.topic_signoffs(topic["id"]):
        if (existing["discipline"] == reviewer["discipline"]
                and existing["state"] in ("PENDING", "APPROVED", "CHANGES_REQUESTED")):
            fail("ERR_DUPLICATE_SIGNOFF_DISCIPLINE",
                 "This topic already holds a sign-off for that discipline.")

    signoff = base_record()
    signoff.update({
        "topic_id": topic["id"],
        "reviewer_id": reviewer["id"],
        "discipline": reviewer["discipline"],
        "state": "PENDING",
        "pinned_revision_number": None,
        "requested_at": db.now_iso(),
        "decided_at": None,
        "comment": None,
    })
    db.signoffs[signoff["id"]] = signoff

    before = snap(reviewer)
    calc.recompute_reviewer(reviewer)
    commit(reviewer, before)
    return ok(public(signoff), 201)


@bp.get("/topics/<topic_id>/sign-offs")
def list_topic_signoffs(topic_id):
    authenticate(("DocsLead", "Writer", "Reviewer"))
    limit, offset = pagination()
    must_get("topics", topic_id)
    f = filters("state")
    rows = calc.topic_signoffs(topic_id)
    if f["state"] is not None:
        rows = [r for r in rows if r["state"] == f["state"]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.get("/sign-offs/<signoff_id>")
def get_signoff(signoff_id):
    authenticate(("DocsLead", "Writer", "Reviewer"))
    signoff = must_get("signoffs", signoff_id)
    return ok(public(signoff))


@bp.get("/sign-offs")
def list_signoffs():
    authenticate(("DocsLead", "Reviewer"))
    limit, offset = pagination()
    keys = ("topic_id", "reviewer_id", "state", "discipline")
    f = filters(*keys)
    rows = all_of("signoffs")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


def _latency_days(submitted_at, approved_at):
    start = parse_instant(submitted_at)
    end = parse_instant(approved_at)
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() // 86400)


@bp.post("/sign-offs/<signoff_id>/decide")
def decide_signoff(signoff_id):
    caller = authenticate(("Reviewer",))
    data = body()
    decision = v_enum(data, "decision", ("APPROVED", "CHANGES_REQUESTED"))
    comment = v_str(data, "comment", 0, 500, required=False)

    signoff = must_get("signoffs", signoff_id)
    if signoff["reviewer_id"] != caller.user_id:
        fail("ERR_SIGNOFF_NOT_OWNED", "Only the named reviewer may decide this sign-off.")
    if signoff["state"] != "PENDING":
        fail("ERR_SIGNOFF_ALREADY_DECIDED", "This sign-off has already been decided.")

    topic = db.topics.get(signoff["topic_id"])
    if topic is None or topic["review_state"] != "PENDING_SIGNOFF":
        fail("ERR_TOPIC_NOT_IN_REVIEW", "The page is not currently in review.")

    item = db.plan_items.get(topic["plan_item_id"])
    train = db.release_trains.get(item["release_train_id"]) if item is not None else None
    reviewer = db.reviewers.get(signoff["reviewer_id"])

    signoff["decided_at"] = db.now_iso()
    signoff["comment"] = comment
    topic_before = snap(topic)

    if decision == "APPROVED":
        signoff["state"] = "APPROVED"
        signoff["pinned_revision_number"] = topic["current_revision_number"]
        touch(signoff)
        if reviewer is not None:
            reviewer_before = snap(reviewer)
            calc.recompute_reviewer(reviewer)
            commit(reviewer, reviewer_before)

        current = topic["current_revision_number"]
        disciplines = set()
        for other in calc.topic_signoffs(topic["id"]):
            if other["state"] == "APPROVED" and other["pinned_revision_number"] == current:
                disciplines.add(other["discipline"])
        if "ENGINEERING" in disciplines and "PRODUCT" in disciplines:
            topic["review_state"] = "FULLY_APPROVED"
            topic["approved_at"] = db.now_iso()
            topic["signoff_latency_days"] = _latency_days(
                topic["submitted_at"], topic["approved_at"])
            calc.set_health(topic, "PRE_PUBLICATION")
            if item is not None and item["status"] == "IN_REVIEW":
                item["status"] = "APPROVED_CONTENT"
                touch(item)
            if train is not None:
                train_before = snap(train)
                calc.recompute_train(train)
                commit(train, train_before)
    else:
        signoff["state"] = "CHANGES_REQUESTED"
        signoff["pinned_revision_number"] = None
        touch(signoff)
        if reviewer is not None:
            reviewer_before = snap(reviewer)
            calc.recompute_reviewer(reviewer)
            commit(reviewer, reviewer_before)

        from flows import supersede_topic_signoffs
        topic["review_state"] = "CHANGES_REQUESTED"
        supersede_topic_signoffs(topic, exclude_id=signoff["id"])

        if item is not None and item["status"] == "IN_REVIEW":
            item["status"] = "IN_REVISION"
            item["rework_count"] = item["rework_count"] + 1
            calc.apply_rework_points(item)
            touch(item)
            writer = db.writers.get(item.get("assigned_writer_id"))
            if writer is not None:
                writer_before = snap(writer)
                calc.recompute_writer(writer)
                commit(writer, writer_before)
        if train is not None:
            train_before = snap(train)
            calc.recompute_train(train)
            commit(train, train_before)

    commit(topic, topic_before)
    return ok(public(signoff))
