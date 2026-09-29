"""Versioned documentation sets: drafting, publication, archival."""
from flask import Blueprint

import calc
from core import (
    add_days,
    all_of,
    base_record,
    by_seq,
    commit,
    db,
    fail,
    fmt_date,
    must_get,
    ok,
    ok_list,
    page,
    public,
    public_list,
    snap,
    touch,
)
from flows import archive_doc_set
from validate import authenticate, body, filters, pagination, v_id, v_int, v_str

bp = Blueprint("docset_routes", __name__)

READ_ROLES = ("DocsLead", "LocalizationCoordinator", "SupportAnalyst")


@bp.post("/doc-set-versions")
def create_doc_set():
    authenticate(("DocsLead",))
    data = body()
    release_train_id = v_id(data, "release_train_id")
    version_label = v_str(data, "version_label", 1, 40)
    expected_version = v_int(data, "expected_release_train_version")

    train = must_get("release_trains", release_train_id)
    if expected_version != train["version"]:
        fail("ERR_STALE_RELEASE_TRAIN_VERSION",
             "The release train has moved on since you last read it.")

    for existing in all_of("doc_set_versions"):
        if (existing["release_train_id"] == train["id"]
                and existing["version_label"] == version_label):
            fail("ERR_DUPLICATE_VERSION_LABEL",
                 "That version label is already used by a documentation set of this train.")

    for existing in all_of("doc_set_versions"):
        if existing["release_train_id"] == train["id"] and existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    doc_set = base_record()
    doc_set.update({
        "release_train_id": train["id"],
        "version_label": version_label,
        "status": "DRAFT",
        "published_topic_count": 0,
        "projected_localization_budget_cents": 0,
        "eol_notice_text": None,
        "published_at": None,
        "archived_at": None,
    })
    db.doc_set_versions[doc_set["id"]] = doc_set
    touch(train)
    return ok(public(doc_set), 201)


@bp.get("/doc-set-versions/<doc_set_id>")
def get_doc_set(doc_set_id):
    authenticate(READ_ROLES)
    doc_set = must_get("doc_set_versions", doc_set_id)
    return ok(public(doc_set))


@bp.get("/doc-set-versions")
def list_doc_sets():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    keys = ("release_train_id", "status")
    f = filters(*keys)
    rows = all_of("doc_set_versions")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


def _seed_translation_jobs(topics):
    """Publication seeds the translation pipeline (PRD 3.6)."""
    locales = calc.simultaneous_locales()
    if not locales:
        return
    touched_locales = []
    for topic in topics:
        for locale in locales:
            blocked = False
            for job in calc.topic_jobs(topic["id"]):
                if (job["locale_profile_id"] == locale["id"]
                        and job["state"] in calc.OPEN_JOB_STATES):
                    blocked = True
                    break
            if blocked:
                continue
            window_start = db.today()
            window_end = add_days(window_start, locale["sla_days"])
            job = base_record()
            job.update({
                "topic_id": topic["id"],
                "locale_profile_id": locale["id"],
                "source_revision_number": topic["current_revision_number"],
                "reserved_source_words": topic["latest_body_word_count"],
                "window_start_date": fmt_date(window_start),
                "window_end_date": fmt_date(window_end),
                "state": "QUEUED",
                "translated_word_count": None,
                "tm_matched_word_count": None,
                "leverage_pct": None,
                "cost_variant": "PROVISIONAL",
                "rush_surcharge_cents": 0,
                "volume_discount_cents": 0,
                "estimated_cost_cents": 0,
                "final_cost_cents": None,
                "publication_mode_applied": None,
                "scheduled_publish_date": None,
                "published_at": None,
                "rework_count": 0,
                "auto_created": True,
                "cancel_reason": None,
            })
            calc.apply_provisional_quote(job, locale, window_start, window_end)
            db.localization_jobs[job["id"]] = job
            if locale not in touched_locales:
                touched_locales.append(locale)
    for locale in touched_locales:
        before = snap(locale)
        calc.recompute_locale(locale)
        commit(locale, before)


@bp.post("/doc-set-versions/<doc_set_id>/publish")
def publish_doc_set(doc_set_id):
    authenticate(("DocsLead",))
    body()
    doc_set = must_get("doc_set_versions", doc_set_id)
    train = db.release_trains.get(doc_set["release_train_id"])

    if doc_set["status"] != "DRAFT":
        fail("ERR_DOC_SET_NOT_DRAFT",
             "A documentation set in state %s cannot be published." % doc_set["status"])
    approved = [t for t in calc.train_topics(doc_set["release_train_id"])
                if t["review_state"] == "FULLY_APPROVED"]
    if not approved:
        fail("ERR_NO_APPROVED_TOPICS", "No topic of this train is fully approved.")
    projection = calc.budget_projection(doc_set["release_train_id"])
    if train is not None and projection > train["localization_budget_cap_cents"]:
        fail("ERR_LOCALIZATION_BUDGET_EXCEEDED",
             "The projected translation spend exceeds the train's budget cap.")

    doc_set["status"] = "PUBLISHED"
    doc_set["published_at"] = db.now_iso()
    doc_set["projected_localization_budget_cents"] = projection

    live_topics = []
    writers = []
    for topic in by_seq(approved):
        if topic["publication_state"] != "UNPUBLISHED":
            continue
        topic["publication_state"] = "PUBLISHED"
        topic["published_at"] = db.now_iso()
        topic["published_in_doc_set_version_id"] = doc_set["id"]
        calc.set_health(topic, "POST_PUBLICATION")
        touch(topic)
        live_topics.append(topic)
        item = db.plan_items.get(topic["plan_item_id"])
        if item is not None and item["status"] == "APPROVED_CONTENT":
            item["status"] = "PUBLISHED"
            touch(item)
            writer = db.writers.get(item.get("assigned_writer_id"))
            if writer is not None and writer not in writers:
                writers.append(writer)

    doc_set["published_topic_count"] = len(live_topics)
    touch(doc_set)

    for writer in writers:
        before = snap(writer)
        calc.recompute_writer(writer)
        commit(writer, before)

    _seed_translation_jobs(live_topics)

    if train is not None:
        before = snap(train)
        calc.recompute_train(train)
        commit(train, before)
    return ok(public(doc_set))


@bp.post("/doc-set-versions/<doc_set_id>/archive")
def archive_doc_set_route(doc_set_id):
    authenticate(("DocsLead",))
    data = body()
    eol_notice_text = v_str(data, "eol_notice_text", 10, 300)

    doc_set = must_get("doc_set_versions", doc_set_id)
    if doc_set["status"] != "PUBLISHED":
        fail("ERR_DOC_SET_NOT_PUBLISHED",
             "Only a published documentation set can be archived.")

    train = db.release_trains.get(doc_set["release_train_id"])
    before = snap(train) if train is not None else None
    if train is not None:
        train["eol_notice_posted"] = True
    archive_doc_set(doc_set, eol_notice_text, train)
    if train is not None:
        calc.recompute_train(train)
        commit(train, before)
    return ok(public(doc_set))
