"""Topics, source revisions, review submission, reader feedback, deflection."""
from flask import Blueprint

import calc
from core import (
    all_of,
    base_record,
    by_seq,
    commit,
    db,
    fail,
    must_get,
    num_out,
    ok,
    ok_list,
    page,
    public,
    public_list,
    snap,
    touch,
)
from flows import invalidate_topic_review
from validate import (
    authenticate,
    body,
    filters,
    pagination,
    v_enum,
    v_id,
    v_int,
    v_str,
    v_str_array,
)

bp = Blueprint("topic_routes", __name__)

ALL_ROLES = ("DocsLead", "Writer", "Reviewer", "LocalizationCoordinator",
             "SupportAnalyst", "Reader")
ALL_BUT_READER = ("DocsLead", "Writer", "Reviewer", "LocalizationCoordinator", "SupportAnalyst")


@bp.post("/topics")
def create_topic():
    caller = authenticate(("Writer",))
    data = body()
    plan_item_id = v_id(data, "plan_item_id")
    slug = v_str(data, "slug", 3, 60, charset=r"^[a-z0-9\-]{3,60}$")
    title = v_str(data, "title", 1, 160)
    parent_topic_id = v_id(data, "parent_topic_id", required=False)

    item = must_get("plan_items", plan_item_id)
    parent = None
    if parent_topic_id is not None:
        parent = must_get("topics", parent_topic_id, "ERR_PARENT_TOPIC_NOT_FOUND")

    if item["assigned_writer_id"] != caller.user_id:
        fail("ERR_NOT_ASSIGNED_WRITER",
             "Only the writer assigned to this deliverable may create its topics.")

    ia_depth = 0
    if parent is not None:
        if parent["plan_item_id"] != item["id"]:
            fail("ERR_PARENT_TOPIC_MISMATCH",
                 "The parent topic belongs to a different deliverable.")
        ia_depth = parent["ia_depth"] + 1
        if ia_depth > calc.MAX_IA_DEPTH:
            fail("ERR_IA_DEPTH_EXCEEDED",
                 "The information-architecture depth may not exceed %d." % calc.MAX_IA_DEPTH)

    for existing in calc.train_topics(item["release_train_id"]):
        if existing["slug"] == slug:
            fail("ERR_DUPLICATE_TOPIC_SLUG",
                 "That slug is already used by a topic of this release train.")

    first_topic = not [t for t in db.topics.values() if t["plan_item_id"] == item["id"]]

    topic = base_record()
    topic.update({
        "plan_item_id": plan_item_id,
        "parent_topic_id": parent_topic_id,
        "slug": slug,
        "title": title,
        "ia_depth": ia_depth,
        "current_revision_number": 0,
        "last_submitted_revision_number": 0,
        "latest_body_word_count": 0,
        "open_blocker_violations": 0,
        "open_warning_violations": 0,
        "review_state": "NOT_SUBMITTED",
        "publication_state": "UNPUBLISHED",
        "submitted_at": None,
        "approved_at": None,
        "signoff_latency_days": None,
        "published_at": None,
        "published_in_doc_set_version_id": None,
        "health_score": None,
        "health_score_variant": None,
    })
    db.topics[topic["id"]] = topic

    if first_topic and item["status"] == "ASSIGNED":
        item["status"] = "IN_AUTHORING"
        touch(item)
    return ok(public(topic), 201)


@bp.get("/topics/<topic_id>")
def get_topic(topic_id):
    authenticate(ALL_ROLES)
    topic = must_get("topics", topic_id)
    if topic["publication_state"] == "PUBLISHED":
        topic["health_score"] = calc.health_score(topic, "POST_PUBLICATION")
        topic["health_score_variant"] = "POST_PUBLICATION"
    return ok(public(topic))


@bp.get("/topics")
def list_topics():
    authenticate(ALL_BUT_READER)
    limit, offset = pagination()
    keys = ("plan_item_id", "parent_topic_id", "published_in_doc_set_version_id",
            "review_state", "publication_state")
    f = filters(*keys)
    rows = all_of("topics")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/topics/<topic_id>/revisions")
def create_revision(topic_id):
    caller = authenticate(("Writer",))
    data = body()
    body_word_count = v_int(data, "body_word_count", low=1, high=200000)
    used_terms = v_str_array(data, "used_terms", 0, 200, 1, 60)
    summary = v_str(data, "summary", 1, 200)

    topic = must_get("topics", topic_id)
    item = db.plan_items.get(topic["plan_item_id"])
    if item is None or item["assigned_writer_id"] != caller.user_id:
        fail("ERR_NOT_ASSIGNED_WRITER",
             "Only the writer assigned to this deliverable may append revisions.")

    blockers, warnings, violating = calc.terminology_scan(used_terms)
    revision = base_record(versioned=False)
    revision.update({
        "topic_id": topic["id"],
        "author_writer_id": caller.user_id,
        "revision_number": topic["current_revision_number"] + 1,
        "body_word_count": body_word_count,
        "used_terms": used_terms,
        "summary": summary,
        "blocker_violation_count": blockers,
        "warning_violation_count": warnings,
        "violating_term_ids": violating,
    })
    db.source_revisions[revision["id"]] = revision

    topic["current_revision_number"] = revision["revision_number"]
    topic["latest_body_word_count"] = body_word_count
    calc.refresh_topic_live_counters(topic)
    train = db.release_trains.get(item["release_train_id"])
    invalidate_topic_review(topic, item, train)
    touch(topic)
    return ok(public(revision), 201)


@bp.get("/topics/<topic_id>/revisions")
def list_revisions(topic_id):
    authenticate(("DocsLead", "Writer", "Reviewer"))
    limit, offset = pagination()
    must_get("topics", topic_id)
    rows = calc.topic_revisions(topic_id)
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/topics/<topic_id>/submit-review")
def submit_review(topic_id):
    caller = authenticate(("Writer",))
    body()
    topic = must_get("topics", topic_id)
    item = db.plan_items.get(topic["plan_item_id"])
    if item is None or item["assigned_writer_id"] != caller.user_id:
        fail("ERR_NOT_ASSIGNED_WRITER",
             "Only the writer assigned to this deliverable may submit it for review.")
    if topic["review_state"] not in ("NOT_SUBMITTED", "CHANGES_REQUESTED"):
        fail("ERR_TOPIC_ALREADY_IN_REVIEW", "The page is already under review.")
    if topic["current_revision_number"] < 1:
        fail("ERR_NO_REVISIONS", "The page has no authored revision to review.")
    if topic["current_revision_number"] <= topic["last_submitted_revision_number"]:
        fail("ERR_NO_NEW_REVISION", "The newest revision has already been submitted.")

    train = db.release_trains.get(item["release_train_id"])
    posture = train["doc_readiness_posture"] if train is not None else "OPEN"
    if posture == "FROZEN" or (posture == "RESTRICTED" and item["audience_tier"] != "CRITICAL"):
        fail("ERR_DOC_FREEZE_POSTURE_BLOCKED",
             "The release train's readiness posture blocks this submission.")
    if topic["open_blocker_violations"] != 0:
        fail("ERR_TERMINOLOGY_BLOCKER_PRESENT",
             "The page has open blocker-severity terminology violations.")

    topic["review_state"] = "PENDING_SIGNOFF"
    topic["submitted_at"] = db.now_iso()
    topic["last_submitted_revision_number"] = topic["current_revision_number"]
    touch(topic)
    if item["status"] in ("IN_AUTHORING", "IN_REVISION"):
        item["status"] = "IN_REVIEW"
        touch(item)
    return ok(public(topic))


@bp.post("/topics/<topic_id>/feedback")
def create_feedback(topic_id):
    authenticate(("Reader",))
    data = body()
    rating = v_int(data, "rating", low=1, high=5)
    outcome = v_enum(data, "outcome",
                     ("RESOLVED_SELF_SERVE", "OPENED_TICKET", "ABANDONED"))
    locale_code = v_str(data, "locale_code", 5, 5, charset=r"^[a-z]{2}-[A-Z]{2}$")
    session_key = v_str(data, "session_key", 6, 60)
    comment = v_str(data, "comment", 0, 500, required=False)

    topic = must_get("topics", topic_id)
    known = [l for l in db.locale_profiles.values() if l["locale_code"] == locale_code]
    if not known:
        fail("ERR_LOCALE_PROFILE_NOT_FOUND", "No locale profile carries that locale code.")
    if topic["publication_state"] != "PUBLISHED":
        fail("ERR_FEEDBACK_TOPIC_NOT_PUBLISHED", "Feedback is only accepted on a live page.")

    row = base_record(versioned=False)
    row.update({
        "topic_id": topic["id"],
        "rating": rating,
        "outcome": outcome,
        "locale_code": locale_code,
        "session_key": session_key,
        "comment": comment,
    })
    db.page_feedback[row["id"]] = row

    before = snap(topic)
    calc.set_health(topic, "POST_PUBLICATION")
    commit(topic, before)
    return ok(public(row), 201)


@bp.get("/topics/<topic_id>/feedback")
def list_feedback(topic_id):
    authenticate(("DocsLead", "SupportAnalyst"))
    limit, offset = pagination()
    must_get("topics", topic_id)
    f = filters("outcome")
    rows = by_seq([r for r in db.page_feedback.values() if r["topic_id"] == topic_id])
    if f["outcome"] is not None:
        rows = [r for r in rows if r["outcome"] == f["outcome"]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.get("/topics/<topic_id>/deflection-summary")
def deflection_summary(topic_id):
    authenticate(("DocsLead", "SupportAnalyst"))
    topic = must_get("topics", topic_id)
    metrics = calc.deflection_metrics(topic["id"])
    return ok({
        "sample_count": metrics["sample_count"],
        "mean_rating": num_out(metrics["mean_rating"]),
        "deflection_pct": num_out(metrics["deflection_pct"]),
        "ticket_rate_pct": num_out(metrics["ticket_rate_pct"]),
        "window_start_date": metrics["window_start_date"],
        "window_end_date": metrics["window_end_date"],
    })
