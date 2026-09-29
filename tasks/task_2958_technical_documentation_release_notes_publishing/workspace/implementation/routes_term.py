"""Terminology governance and deprecation timelines."""
from flask import Blueprint

import calc
from core import (
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
    snap,
    touch,
)
from validate import (
    authenticate,
    body,
    filters,
    pagination,
    v_date,
    v_enum,
    v_id,
    v_str,
    v_str_array,
)

bp = Blueprint("term_routes", __name__)


@bp.post("/terminology-terms")
def create_term():
    authenticate(("DocsLead",))
    data = body()
    term = v_str(data, "term", 2, 60, lower=True)
    preferred_form = v_str(data, "preferred_form", 2, 60)
    forbidden_forms = v_str_array(data, "forbidden_forms", 1, 20, 2, 60)
    enforcement_severity = v_enum(data, "enforcement_severity", ("BLOCKER", "WARNING"))

    for existing in db.terminology_terms.values():
        if existing["status"] == "ACTIVE" and existing["term"] == term:
            fail("ERR_DUPLICATE_TERM", "An active term with that spelling already exists.")

    record = base_record()
    record.update({
        "term": term,
        "preferred_form": preferred_form,
        "forbidden_forms": forbidden_forms,
        "enforcement_severity": enforcement_severity,
        "status": "ACTIVE",
        "retired_at": None,
    })
    db.terminology_terms[record["id"]] = record
    return ok(public(record), 201)


@bp.get("/terminology-terms/<term_id>")
def get_term(term_id):
    authenticate(("DocsLead", "Writer"))
    record = must_get("terminology_terms", term_id)
    return ok(public(record))


@bp.get("/terminology-terms")
def list_terms():
    authenticate(("DocsLead", "Writer"))
    limit, offset = pagination()
    keys = ("status", "enforcement_severity")
    f = filters(*keys)
    rows = all_of("terminology_terms")
    rows.sort(key=lambda r: r["term"])
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/terminology-terms/<term_id>/retire")
def retire_term(term_id):
    authenticate(("DocsLead",))
    body()
    record = must_get("terminology_terms", term_id)
    if record["status"] != "ACTIVE":
        fail("ERR_TERM_ALREADY_RETIRED", "That term is already retired.")

    record["status"] = "RETIRED"
    record["retired_at"] = db.now_iso()
    touch(record)

    for topic in all_of("topics"):
        revision = calc.latest_revision(topic["id"])
        if revision is None or record["id"] not in revision["violating_term_ids"]:
            continue
        before = snap(topic)
        calc.refresh_topic_live_counters(topic)
        if topic["health_score"] is not None:
            variant = topic.get("health_score_variant") or (
                "PRE_PUBLICATION" if topic["publication_state"] == "UNPUBLISHED"
                else "POST_PUBLICATION")
            calc.set_health(topic, variant)
        commit(topic, before)
    return ok(public(record))


# ---------------------------------------------------------------------------
# Deprecation notices
# ---------------------------------------------------------------------------
@bp.post("/deprecation-notices")
def create_notice():
    authenticate(("DocsLead",))
    data = body()
    release_train_id = v_id(data, "release_train_id")
    feature_key = v_str(data, "feature_key", 1, 60)
    severity_tier = v_enum(data, "severity_tier", ("BREAKING", "MAJOR", "MINOR"))
    announce_date = v_date(data, "announce_date")
    deprecated_date = v_date(data, "deprecated_date")
    removal_date = v_date(data, "removal_date")
    migration_guide_topic_id = v_id(data, "migration_guide_topic_id")

    train = must_get("release_trains", release_train_id)
    guide = must_get("topics", migration_guide_topic_id)

    guide_train = calc.topic_train(guide)
    if guide_train is None or guide_train["product_key"] != train["product_key"]:
        fail("ERR_MIGRATION_GUIDE_PRODUCT_MISMATCH",
             "The migration guide belongs to a different product line.")
    if announce_date > deprecated_date or deprecated_date >= removal_date:
        fail("ERR_INVALID_DATE_WINDOW", "The deprecation timeline is misordered.")

    notice_days, earliest_removal_date, minimum = calc.timeline_figures(
        announce_date, removal_date, severity_tier)
    if notice_days < minimum:
        fail("ERR_NOTICE_PERIOD_TOO_SHORT",
             "A %s deprecation requires at least %d days of notice." % (severity_tier, minimum))

    notice = base_record()
    notice.update({
        "release_train_id": train["id"],
        "feature_key": feature_key,
        "severity_tier": severity_tier,
        "announce_date": fmt_date(announce_date),
        "deprecated_date": fmt_date(deprecated_date),
        "removal_date": fmt_date(removal_date),
        "migration_guide_topic_id": guide["id"],
        "notice_days": notice_days,
        "earliest_removal_date": fmt_date(earliest_removal_date),
        "status": "DRAFTED",
        "published_at": None,
    })
    db.deprecation_notices[notice["id"]] = notice
    return ok(public(notice), 201)


@bp.get("/deprecation-notices/<notice_id>")
def get_notice(notice_id):
    authenticate(("DocsLead", "SupportAnalyst"))
    notice = must_get("deprecation_notices", notice_id)
    return ok(public(notice))


@bp.get("/deprecation-notices")
def list_notices():
    authenticate(("DocsLead", "SupportAnalyst"))
    limit, offset = pagination()
    keys = ("release_train_id", "migration_guide_topic_id", "status", "severity_tier")
    f = filters(*keys)
    rows = all_of("deprecation_notices")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/deprecation-notices/<notice_id>/publish")
def publish_notice(notice_id):
    authenticate(("DocsLead",))
    body()
    notice = must_get("deprecation_notices", notice_id)
    if notice["status"] != "DRAFTED":
        fail("ERR_DEPRECATION_NOTICE_ALREADY_PUBLISHED",
             "A notice in state %s cannot be published." % notice["status"])

    guide = db.topics.get(notice["migration_guide_topic_id"])
    if guide is None or guide["publication_state"] != "PUBLISHED":
        fail("ERR_MIGRATION_GUIDE_NOT_PUBLISHED",
             "The migration guide page is not live.")
    if db.today() < parse_date(notice["announce_date"]):
        fail("ERR_ANNOUNCE_DATE_NOT_REACHED",
             "Customers cannot be told before the announcement day.")

    notice["status"] = "PUBLISHED"
    notice["published_at"] = db.now_iso()
    touch(notice)
    return ok(public(notice))
