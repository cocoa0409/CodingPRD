"""Documentation plan items: creation, assignment economics, cancellation."""
from flask import Blueprint

import calc
from core import (
    D,
    all_of,
    base_record,
    commit,
    db,
    fail,
    fmt_date,
    must_get,
    ok,
    ok_list,
    page,
    parse_date,
    public,
    public_list,
    r2,
    snap,
    touch,
)
from flows import supersede_topic_signoffs
from validate import (
    authenticate,
    body,
    filters,
    pagination,
    v_date,
    v_enum,
    v_id,
    v_int,
    v_str,
)

bp = Blueprint("plan_routes", __name__)


@bp.post("/plan-items")
def create_plan_item():
    authenticate(("DocsLead",))
    data = body()
    release_train_id = v_id(data, "release_train_id")
    feature_key = v_str(data, "feature_key", 1, 60)
    ia_placement = v_enum(data, "ia_placement",
                          ("NEW_TOPIC", "EXISTING_TOPIC_UPDATE", "CONCEPT_HUB"))
    audience_tier = v_enum(data, "audience_tier", ("CRITICAL", "STANDARD", "INTERNAL"))
    planned_page_count = v_int(data, "planned_page_count", low=1, high=500)
    complexity_points = v_int(data, "complexity_points", low=0, high=100)

    train = must_get("release_trains", release_train_id)

    item = base_record()
    item.update({
        "release_train_id": release_train_id,
        "feature_key": feature_key,
        "ia_placement": ia_placement,
        "audience_tier": audience_tier,
        "planned_page_count": planned_page_count,
        "complexity_points": complexity_points,
        "assigned_writer_id": None,
        "window_start_date": None,
        "window_end_date": None,
        "load_points": r2(D(0)),
        "rework_count": 0,
        "status": "DRAFTED",
        "cancel_reason": None,
        "_base_load_points": r2(D(0)),
    })
    db.plan_items[item["id"]] = item

    before = snap(train)
    calc.recompute_train(train)
    commit(train, before)
    return ok(public(item), 201)


@bp.get("/plan-items/<item_id>")
def get_plan_item(item_id):
    authenticate(("DocsLead", "Writer", "Reviewer"))
    item = must_get("plan_items", item_id)
    return ok(public(item))


@bp.get("/plan-items")
def list_plan_items():
    authenticate(("DocsLead", "Writer", "Reviewer"))
    limit, offset = pagination()
    f = filters("release_train_id", "assigned_writer_id", "status", "audience_tier")
    rows = all_of("plan_items")
    for key in ("release_train_id", "assigned_writer_id", "status", "audience_tier"):
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/plan-items/<item_id>/assign")
def assign_plan_item(item_id):
    authenticate(("DocsLead",))
    data = body()
    writer_id = v_id(data, "writer_id")
    window_start_date = v_date(data, "window_start_date")
    window_end_date = v_date(data, "window_end_date")

    item = must_get("plan_items", item_id)
    writer = must_get("writers", writer_id)

    if item["status"] not in ("DRAFTED", "ASSIGNED", "IN_AUTHORING"):
        fail("ERR_PLAN_ITEM_NOT_ASSIGNABLE",
             "A deliverable in state %s cannot change hands." % item["status"])
    train = db.release_trains.get(item["release_train_id"])
    if train is not None and train["status"] not in ("PLANNED", "DOC_FREEZE"):
        fail("ERR_RELEASE_TRAIN_CLOSED_FOR_PLANNING",
             "The release train is closed for planning.")
    if writer["status"] != "ACTIVE":
        fail("ERR_WRITER_ON_LEAVE", "An on-leave writer cannot receive work.")
    if window_end_date <= window_start_date:
        fail("ERR_INVALID_DATE_WINDOW",
             "An authoring window must end strictly later than it starts.")

    for other in calc.writer_counted_items(writer_id):
        if other["id"] == item["id"]:
            continue
        if other["window_start_date"] is None or other["window_end_date"] is None:
            continue
        if calc.windows_collide(window_start_date, window_end_date,
                                parse_date(other["window_start_date"]),
                                parse_date(other["window_end_date"])):
            fail("ERR_WRITER_WINDOW_OVERLAP",
                 "The requested authoring window collides with an existing one.")

    base_load, new_load = calc.compute_load_points(item, writer)
    existing_total = D(0)
    for other in calc.writer_counted_items(writer_id):
        if other["id"] == item["id"]:
            continue
        existing_total += D(other["load_points"])
    if r2(existing_total + new_load) > D(writer["capacity_points"]):
        fail("ERR_WRITER_CAPACITY_EXCEEDED",
             "The assignment would push the writer past their capacity ceiling.")

    previous_writer_id = item["assigned_writer_id"]
    item["assigned_writer_id"] = writer_id
    item["window_start_date"] = fmt_date(window_start_date)
    item["window_end_date"] = fmt_date(window_end_date)
    item["_base_load_points"] = base_load
    item["load_points"] = new_load
    if item["status"] == "DRAFTED":
        item["status"] = "ASSIGNED"
    touch(item)

    if previous_writer_id is not None and previous_writer_id != writer_id:
        previous = db.writers.get(previous_writer_id)
        if previous is not None:
            before = snap(previous)
            calc.recompute_writer(previous)
            commit(previous, before)
    before = snap(writer)
    calc.recompute_writer(writer)
    commit(writer, before)
    if train is not None:
        before = snap(train)
        calc.recompute_train(train)
        commit(train, before)
    return ok(public(item))


@bp.post("/plan-items/<item_id>/cancel")
def cancel_plan_item(item_id):
    authenticate(("DocsLead",))
    data = body()
    cancel_reason = v_str(data, "cancel_reason", 1, 500)

    item = must_get("plan_items", item_id)
    if item["status"] not in ("DRAFTED", "ASSIGNED", "IN_AUTHORING", "IN_REVIEW", "IN_REVISION"):
        fail("ERR_PLAN_ITEM_NOT_CANCELLABLE",
             "A deliverable in state %s cannot be cancelled." % item["status"])

    writer = db.writers.get(item["assigned_writer_id"])
    item["cancel_reason"] = cancel_reason
    item["status"] = "CANCELLED"
    item["assigned_writer_id"] = None
    touch(item)

    for topic in calc.by_seq([t for t in db.topics.values()
                              if t["plan_item_id"] == item["id"]]):
        superseded = False
        reviewers = []
        for signoff in calc.topic_signoffs(topic["id"]):
            if signoff["state"] == "SUPERSEDED":
                continue
            signoff["state"] = "SUPERSEDED"
            signoff["pinned_revision_number"] = None
            touch(signoff)
            superseded = True
            reviewer = db.reviewers.get(signoff["reviewer_id"])
            if reviewer is not None and reviewer not in reviewers:
                reviewers.append(reviewer)
        for reviewer in reviewers:
            before = snap(reviewer)
            calc.recompute_reviewer(reviewer)
            commit(reviewer, before)
        if superseded:
            before = snap(topic)
            topic["review_state"] = "NOT_SUBMITTED"
            commit(topic, before)

    if writer is not None:
        before = snap(writer)
        calc.recompute_writer(writer)
        commit(writer, before)
    train = db.release_trains.get(item["release_train_id"])
    if train is not None:
        before = snap(train)
        calc.recompute_train(train)
        commit(train, before)
    return ok(public(item))
