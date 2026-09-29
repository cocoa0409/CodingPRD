"""Shared multi-hop side effects: supersession, job cancellation, archive and
end-of-life cascades.  Hop order is contractual (PRD section 2.8)."""
from calc import (
    OPEN_JOB_STATES,
    recompute_locale,
    recompute_reviewer,
    recompute_train,
    recompute_writer,
    set_health,
    topic_jobs,
    topic_signoffs,
    train_topics,
)
from core import by_seq, commit, db, snap, touch


def supersede_topic_signoffs(topic, exclude_id=None):
    """Move every PENDING or APPROVED sign-off of the topic to SUPERSEDED,
    clearing its pin, in created_at ascending order.  Returns True when any
    sign-off was superseded."""
    touched = False
    reviewers = []
    for signoff in topic_signoffs(topic["id"]):
        if exclude_id is not None and signoff["id"] == exclude_id:
            continue
        if signoff["state"] not in ("PENDING", "APPROVED"):
            continue
        signoff["state"] = "SUPERSEDED"
        signoff["pinned_revision_number"] = None
        touch(signoff)
        touched = True
        reviewer = db.reviewers.get(signoff["reviewer_id"])
        if reviewer is not None and reviewer not in reviewers:
            reviewers.append(reviewer)
    for reviewer in reviewers:
        before = snap(reviewer)
        recompute_reviewer(reviewer)
        commit(reviewer, before)
    return touched


def cancel_jobs_of_topics(topics, reason):
    """Cancel every open translation job of the given topics, in created_at
    ascending order, then settle each affected locale's ledger."""
    locales = []
    for topic in topics:
        for job in topic_jobs(topic["id"]):
            if job["state"] not in OPEN_JOB_STATES:
                continue
            job["state"] = "CANCELLED"
            job["cancel_reason"] = reason
            touch(job)
            locale = db.locale_profiles.get(job["locale_profile_id"])
            if locale is not None and locale not in locales:
                locales.append(locale)
    for locale in locales:
        before = snap(locale)
        recompute_locale(locale)
        commit(locale, before)


def archive_doc_set(doc_set, notice_text, train):
    """Hops one through five of the documentation-set archive cascade."""
    doc_set["status"] = "ARCHIVED"
    doc_set["archived_at"] = db.now_iso()
    doc_set["eol_notice_text"] = notice_text
    touch(doc_set)

    archived_topics = []
    for topic in train_topics(train["id"]):
        if (topic.get("published_in_doc_set_version_id") == doc_set["id"]
                and topic["publication_state"] == "PUBLISHED"):
            topic["publication_state"] = "ARCHIVED"
            set_health(topic, "POST_PUBLICATION")
            touch(topic)
            archived_topics.append(topic)

    cancel_jobs_of_topics(by_seq(archived_topics), "CASCADE_DOC_SET_ARCHIVED")
    return archived_topics


def eol_notice_text_for(train):
    return ("End of life: support for %s %s ended on %s."
            % (train["product_key"], train["version_label"], train["support_end_date"]))


def end_of_life_cascade(train):
    """The train's terminal hop: five ordered hops plus notice retirement."""
    train["status"] = "END_OF_LIFE"
    train["doc_readiness_posture"] = "FROZEN"
    train["eol_notice_posted"] = True

    notice_text = eol_notice_text_for(train)
    published_sets = [s for s in db.doc_set_versions.values()
                      if s["release_train_id"] == train["id"] and s["status"] == "PUBLISHED"]
    for doc_set in by_seq(published_sets):
        doc_set["status"] = "ARCHIVED"
        doc_set["archived_at"] = db.now_iso()
        doc_set["eol_notice_text"] = notice_text
        touch(doc_set)

    archived_set_ids = set(s["id"] for s in published_sets)
    archived_topics = []
    for topic in train_topics(train["id"]):
        if (topic.get("published_in_doc_set_version_id") in archived_set_ids
                and topic["publication_state"] == "PUBLISHED"):
            topic["publication_state"] = "ARCHIVED"
            set_health(topic, "POST_PUBLICATION")
            touch(topic)
            archived_topics.append(topic)

    cancel_jobs_of_topics(by_seq(archived_topics), "CASCADE_DOC_SET_ARCHIVED")

    notices = [n for n in db.deprecation_notices.values()
               if n["release_train_id"] == train["id"] and n["status"] == "PUBLISHED"]
    for notice in by_seq(notices):
        notice["status"] = "RETIRED"
        touch(notice)

    recompute_train(train)
    train["doc_readiness_posture"] = "FROZEN"


def invalidate_topic_review(topic, item, train):
    """A new revision on a page in review or approved falls all the way back to
    NOT_SUBMITTED, superseding sign-offs (PRD 3.3)."""
    was_approved = topic["review_state"] == "FULLY_APPROVED"
    if topic["review_state"] in ("PENDING_SIGNOFF", "FULLY_APPROVED"):
        topic["review_state"] = "NOT_SUBMITTED"
        supersede_topic_signoffs(topic)
        if was_approved:
            topic["approved_at"] = None
            topic["signoff_latency_days"] = None
    if item is not None and item["status"] in ("IN_REVIEW", "APPROVED_CONTENT"):
        before = snap(item)
        item["status"] = "IN_AUTHORING"
        commit(item, before)
        writer = db.writers.get(item.get("assigned_writer_id"))
        if writer is not None:
            writer_before = snap(writer)
            recompute_writer(writer)
            commit(writer, writer_before)
    if train is not None:
        train_before = snap(train)
        recompute_train(train)
        commit(train, train_before)
