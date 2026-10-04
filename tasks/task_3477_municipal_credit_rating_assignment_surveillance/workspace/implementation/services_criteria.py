"""Criteria activation cascade (PRD §3.6, scaffold criteria_review_fanout):
supersede the segment's prior ACTIVE version, then — only when a prior ACTIVE
existed — fan out PENDING review items to every PUBLISHED rating of the
segment in (published_at ASC, created_at ASC) order, flag review_pending and
notify REVIEW_OPENED."""
import timeutil
from constants import EVENT_REVIEW_OPENED, REVIEW_COMPLETION_DAYS
from store import db, new_entity, notify, touch


def activate(criteria):
    """DRAFT -> ACTIVE. Caller has already validated state. Returns criteria."""
    clock = db.now()
    prior = None
    for cv in db.criteria_versions.values():
        if (
            cv["id"] != criteria["id"]
            and cv["jurisdiction_code"] == criteria["jurisdiction_code"]
            and cv["credit_type"] == criteria["credit_type"]
            and cv["status"] == "ACTIVE"
        ):
            prior = cv
            break

    criteria["status"] = "ACTIVE"
    criteria["activated_at"] = clock
    touch(criteria)

    if prior is None:
        return criteria  # first activation of the segment: no fan-out

    # Cascade hop 1: supersede the prior ACTIVE version.
    prior["status"] = "SUPERSEDED"
    touch(prior)

    # Cascade hop 2/3: portfolio-wide review items in pinned fan-out order.
    eligible = [
        r
        for r in db.ratings.values()
        if r["status"] == "PUBLISHED"
        and r["jurisdiction_code"] == criteria["jurisdiction_code"]
        and r["credit_type"] == criteria["credit_type"]
    ]
    eligible.sort(key=lambda r: (r["published_at"], r["created_at"], r["_seq"]))
    for rating in eligible:
        item = new_entity()
        item.update(
            criteria_version_id=criteria["id"],
            rating_id=rating["id"],
            due_at=timeutil.add_days(clock, REVIEW_COMPLETION_DAYS),
            status="PENDING",
            outcome_notch=None,
            rationale=None,
            completed_at=None,
        )
        db.review_items[item["id"]] = item
        rating["review_pending"] = True
        notify(
            rating["issuer_id"],
            EVENT_REVIEW_OPENED,
            item["id"],
            "Criteria review opened for rating %s under criteria version %s."
            % (rating["id"], criteria["id"]),
        )
    return criteria
