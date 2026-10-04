"""HostReview services: the symmetric review exchange and its rating aggregates."""

import errors
import recompute
import serializers
import store
import validation as v
from envelope import created_object, ok_array, ok_object
from services_hosts import load_host
from services_members import _new_incident, load_member


def load_review(review_id):
    review = store.get(store.REVIEWS, review_id)
    if review is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No review with that id.")
    return review


def create_review(actor, body):
    v.authorize(actor, ("HostOperator", "Member"))
    host_author = actor["role"] == "HostOperator"

    # --- priority 3: resolve every referenced id (outer first) --------------
    provided_host_id = v.text_field(body, "host_id")
    provided_subject_host_id = v.text_field(body, "subject_host_id")
    provided_subject_member_id = v.text_field(body, "subject_member_id")
    provided_author_member_id = v.text_field(body, "author_member_id")
    provided_author_review_id = v.text_field(body, "author_review_id")

    host = None
    host_id = None
    if host_author:
        host_id = provided_host_id or actor["id"]
        v.require_host_scope(actor, host_id)
        if store.get(store.HOSTS, host_id) is None:
            errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
        if provided_author_member_id is not None:
            errors.fail("ERR_INVALID_REQUEST", "author_member_id is not declared for a host-author review.")
        if provided_subject_host_id is not None:
            errors.fail("ERR_INVALID_REQUEST", "subject_host_id is not declared for a host-author review.")
        if provided_subject_member_id is None:
            errors.fail("ERR_INVALID_REQUEST", "Missing required field: subject_member_id.")
        subject_member = load_member(provided_subject_member_id)
        author_member_id = None
    else:
        host_id = provided_host_id or provided_subject_host_id
        if host_id is None:
            errors.fail("ERR_INVALID_REQUEST", "Missing required field: subject_host_id.")
        if store.get(store.HOSTS, host_id) is None:
            errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
        if provided_subject_member_id is not None:
            errors.fail("ERR_INVALID_REQUEST", "subject_member_id is not declared for a member-author review.")
        if provided_author_member_id is not None and provided_author_member_id != actor["id"]:
            errors.fail("ERR_UNAUTHORIZED")
        author_member_id = actor["id"]
        subject_member = load_member(author_member_id)

    author_review = None
    if provided_author_review_id is not None:
        author_review = load_review(provided_author_review_id)

    # --- priority 4: payload well-formedness --------------------------------
    rating = v.int_field(body, "rating", required=True, minimum=1, maximum=5)
    public_note = v.text_field(body, "public_note", required=True)
    private_report = v.text_field(body, "private_report") if host_author else None
    advance_notice_hours = v.int_field(body, "advance_notice_hours", minimum=0)
    if host_author:
        if "private_report" in body and body["private_report"] is not None:
            private_report = v.text_field(body, "private_report")
        v.require_fields(body, ["expected_host_version"])
        expected_host_version = v.int_field(body, "expected_host_version")
    else:
        if "private_report" in body and body["private_report"] is not None:
            errors.fail("ERR_INVALID_REQUEST", "private_report is not declared for a member-author review.")
        expected_host_version = None

    # --- priority 19: member reviewers need a completed stay ----------------
    if not host_author:
        if not _has_completed_stay(author_member_id, host_id):
            errors.fail("ERR_REVIEW_NOT_ELIGIBLE")

    # --- priority 24: host version precondition ----------------------------
    if host_author and expected_host_version is not None:
        host = store.get(store.HOSTS, host_id)
        if expected_host_version != host.get("version"):
            errors.fail("ERR_STALE_HOST_VERSION")

    review = {
        "id": store.new_id(),
        "host_id": host_id,
        "author_review_id": provided_author_review_id,
        "subject_member_id": subject_member["id"] if host_author else None,
        "subject_host_id": None if host_author else host_id,
        "author_kind": "HOST" if host_author else "MEMBER",
        "author_member_id": author_member_id,
        "rating": rating,
        "public_note": public_note,
        "private_report": private_report,
        "review_status": "PUBLISHED",
        "advance_notice_hours": advance_notice_hours,
        "counter_review_count": 0,
    }
    review["created_at"] = store.now()
    store.add(store.REVIEWS, review)

    # A counter-review raises the answered review's counter_review_count.
    if author_review is not None:
        author_review["counter_review_count"] = _counter_count(author_review["id"])

    # Recompute the aggregates for whichever side this review belongs to.
    _recompute_aggregates(review)

    # A non-empty private report on a host-author review raises a MAJOR
    # REVIEW_REPORT incident against the member being reviewed.
    if host_author and private_report:
        incident = _new_incident(
            subject_member["id"], host_id, "MAJOR", "REVIEW_REPORT", private_report
        )
        incident["source_review_id"] = review["id"]
        review["incident_id"] = incident["id"]
        recompute.recompute_member(subject_member)

    return created_object(serializers.review_row(review))


def _counter_count(review_id):
    return sum(
        1 for r in store.all_of(store.REVIEWS) if r.get("author_review_id") == review_id
    )


def _recompute_aggregates(review):
    host = store.get(store.HOSTS, review.get("host_id"))
    if review.get("author_kind") == "HOST":
        if host is not None:
            recompute.recompute_host(host)
        subject = store.get(store.MEMBERS, review.get("subject_member_id"))
        if subject is not None:
            subject["member_rating_average"] = recompute.member_rating_average(subject["id"])
            store.stamp(subject)
    else:
        author = store.get(store.MEMBERS, review.get("author_member_id"))
        if author is not None:
            author["member_rating_average"] = recompute.member_rating_average(author["id"])
            store.stamp(author)
        if host is not None:
            average = recompute.host_rating_average(host["id"])
            if average != host.get("host_rating_average"):
                host["host_rating_average"] = average
                store.stamp(host)


def _has_completed_stay(member_id, host_id):
    instant = store.now()
    for stay in store.all_of(store.STAYS):
        if stay.get("member_id") != member_id or stay.get("host_id") != host_id:
            continue
        if stay.get("request_status") not in ("CHECKED_IN", "CHECKED_OUT"):
            continue
        if stay.get("occupancy_end") is None or stay["occupancy_end"] > instant:
            continue
        return True
    return False


def list_reviews(actor):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    limit, offset = v.pagination()
    keys = (
        "host_id",
        "author_member_id",
        "subject_member_id",
        "subject_host_id",
        "author_review_id",
        "author_kind",
        "review_status",
    )
    filters = {key: v.query(key) for key in keys}
    rows = []
    for review in store.all_of(store.REVIEWS):
        if any(
            filters[key] is not None and review.get(key) != filters[key] for key in keys
        ):
            continue
        rows.append(serializers.review_row(review))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def get_review(actor, review_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    review = load_review(review_id)
    return ok_object(serializers.review_row(review))


def withdraw_review(actor, review_id, body):
    v.authorize(actor, ("HostOperator", "Member", "PlatformAdmin"))
    review = load_review(review_id)
    if review.get("review_status") != "PUBLISHED":
        errors.fail("ERR_REVIEW_ALREADY_WITHDRAWN")

    review["review_status"] = "WITHDRAWN"

    # Retract the conduct incident this review raised, if any.
    incident = _incident_for(review)
    if incident is not None and incident.get("incident_status") != "WITHDRAWN":
        incident["incident_status"] = "WITHDRAWN"
        incident["waived_days_remaining"] = 0
        store.stamp(incident)
        subject = store.get(store.MEMBERS, incident.get("member_id"))
        if subject is not None:
            recompute.recompute_member(subject)

    _recompute_aggregates(review)
    return ok_object(serializers.review_row(review))


def _incident_for(review):
    incident_id = review.get("incident_id")
    if incident_id:
        return store.get(store.INCIDENTS, incident_id)
    for incident in store.all_of(store.INCIDENTS):
        if incident.get("source_review_id") == review["id"]:
            return incident
    return None