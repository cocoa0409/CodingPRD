"""Locale profiles and the translation-job pipeline."""
from flask import Blueprint

import calc
from core import (
    add_days,
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
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("loc_routes", __name__)


def job_train(job):
    topic = db.topics.get(job["topic_id"])
    if topic is None:
        return None
    return calc.topic_train(topic)


def settle_job_ledgers(job):
    locale = db.locale_profiles.get(job["locale_profile_id"])
    if locale is not None:
        before = snap(locale)
        calc.recompute_locale(locale)
        commit(locale, before)
    train = job_train(job)
    if train is not None:
        before = snap(train)
        calc.recompute_train(train)
        commit(train, before)


# ---------------------------------------------------------------------------
# Locale profiles
# ---------------------------------------------------------------------------
@bp.post("/locale-profiles")
def create_locale():
    authenticate(("LocalizationCoordinator",))
    data = body()
    locale_code = v_str(data, "locale_code", 5, 5, charset=r"^[a-z]{2}-[A-Z]{2}$")
    publication_mode = v_enum(data, "publication_mode", ("SIMULTANEOUS", "DELAYED"))
    tm_coverage_pct = v_num(data, "tm_coverage_pct", low=0, high=100)
    per_word_rate_cents = v_num(data, "per_word_rate_cents", low=0, exclusive_low=True)
    sla_days = v_int(data, "sla_days", low=1, high=120)
    parallel_job_limit = v_int(data, "parallel_job_limit", low=1, high=20)
    status = v_enum(data, "status", ("ACTIVE", "PAUSED"), required=False) or "ACTIVE"

    for existing in db.locale_profiles.values():
        if existing["locale_code"] == locale_code:
            fail("ERR_DUPLICATE_LOCALE_CODE", "That locale code is already registered.")

    locale = base_record()
    locale.update({
        "locale_code": locale_code,
        "publication_mode": publication_mode,
        "tm_coverage_pct": tm_coverage_pct,
        "per_word_rate_cents": per_word_rate_cents,
        "sla_days": sla_days,
        "parallel_job_limit": parallel_job_limit,
        "status": status,
        "committed_source_words": 0,
        "open_job_count": 0,
    })
    db.locale_profiles[locale["id"]] = locale
    return ok(public(locale), 201)


@bp.get("/locale-profiles/<locale_id>")
def get_locale(locale_id):
    authenticate(("DocsLead", "LocalizationCoordinator"))
    locale = must_get("locale_profiles", locale_id)
    return ok(public(locale))


@bp.get("/locale-profiles")
def list_locales():
    authenticate(("DocsLead", "LocalizationCoordinator"))
    limit, offset = pagination()
    keys = ("status", "publication_mode")
    f = filters(*keys)
    rows = all_of("locale_profiles")
    rows.sort(key=lambda r: r["locale_code"])
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


# ---------------------------------------------------------------------------
# Localization jobs
# ---------------------------------------------------------------------------
@bp.post("/localization-jobs")
def create_job():
    authenticate(("LocalizationCoordinator",))
    data = body()
    topic_id = v_id(data, "topic_id")
    locale_profile_id = v_id(data, "locale_profile_id")
    window_start_date = v_date(data, "window_start_date")
    window_end_date = v_date(data, "window_end_date")

    topic = must_get("topics", topic_id)
    locale = must_get("locale_profiles", locale_profile_id)

    if topic["publication_state"] != "PUBLISHED":
        fail("ERR_SOURCE_TOPIC_NOT_PUBLISHED", "Only a live page can be translated.")
    if locale["status"] != "ACTIVE":
        fail("ERR_LOCALE_PAUSED", "A paused locale accepts no new jobs.")
    if window_end_date < window_start_date:
        fail("ERR_INVALID_DATE_WINDOW",
             "A translation window may not end before it starts.")

    for job in calc.topic_jobs(topic["id"]):
        if (job["locale_profile_id"] == locale["id"]
                and job["state"] in calc.OPEN_JOB_STATES):
            fail("ERR_DUPLICATE_LOCALIZATION_JOB",
                 "This topic already has an open job for that locale.")

    overlapping = 0
    for job in calc.locale_open_jobs(locale["id"]):
        if job["auto_created"]:
            continue
        existing_start = parse_date(job["window_start_date"])
        existing_end = parse_date(job["window_end_date"])
        if window_start_date <= existing_end and window_end_date >= existing_start:
            overlapping += 1
    if overlapping >= locale["parallel_job_limit"]:
        fail("ERR_LOCALE_PARALLEL_JOB_LIMIT_EXCEEDED",
             "The locale cannot sustain another overlapping vendor window.")

    job = base_record()
    job.update({
        "topic_id": topic["id"],
        "locale_profile_id": locale["id"],
        "source_revision_number": topic["current_revision_number"],
        "reserved_source_words": topic["latest_body_word_count"],
        "window_start_date": fmt_date(window_start_date),
        "window_end_date": fmt_date(window_end_date),
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
        "auto_created": False,
        "cancel_reason": None,
    })
    calc.apply_provisional_quote(job, locale, window_start_date, window_end_date)
    db.localization_jobs[job["id"]] = job
    settle_job_ledgers(job)
    return ok(public(job), 201)


@bp.get("/localization-jobs/<job_id>")
def get_job(job_id):
    authenticate(("DocsLead", "LocalizationCoordinator"))
    job = must_get("localization_jobs", job_id)
    return ok(public(job))


@bp.get("/localization-jobs")
def list_jobs():
    authenticate(("DocsLead", "LocalizationCoordinator"))
    limit, offset = pagination()
    keys = ("topic_id", "locale_profile_id", "state", "cost_variant")
    f = filters(*keys)
    rows = all_of("localization_jobs")
    for key in keys:
        if f[key] is not None:
            rows = [r for r in rows if r[key] == f[key]]
    window, total = page(rows, limit, offset)
    return ok_list(public_list(window), limit, offset, total)


@bp.post("/localization-jobs/<job_id>/deliver")
def deliver_job(job_id):
    authenticate(("LocalizationCoordinator",))
    data = body()
    translated_word_count = v_int(data, "translated_word_count", low=1, high=400000)
    tm_matched_word_count = v_int(data, "tm_matched_word_count", low=0, high=400000)
    if tm_matched_word_count > translated_word_count:
        fail("ERR_INVALID_REQUEST",
             "tm_matched_word_count may not exceed translated_word_count.")

    job = must_get("localization_jobs", job_id)
    if job["state"] not in ("QUEUED", "REWORK_REQUESTED"):
        fail("ERR_LOCALIZATION_JOB_NOT_DELIVERABLE",
             "A job in state %s cannot accept a delivery." % job["state"])
    window_end = parse_date(job["window_end_date"])
    if db.today() > add_days(window_end, calc.SLA_GRACE_DAYS):
        fail("ERR_LOCALIZATION_SLA_BREACH",
             "The delivery arrived after the service-level grace period.")

    locale = db.locale_profiles.get(job["locale_profile_id"])
    job["translated_word_count"] = translated_word_count
    job["tm_matched_word_count"] = tm_matched_word_count
    job["state"] = "TRANSLATED"
    calc.apply_final_quote(job, locale,
                           parse_date(job["window_start_date"]), window_end)
    touch(job)
    settle_job_ledgers(job)
    return ok(public(job))


@bp.post("/localization-jobs/<job_id>/rework")
def rework_job(job_id):
    authenticate(("LocalizationCoordinator",))
    body()
    job = must_get("localization_jobs", job_id)
    if job["state"] != "TRANSLATED":
        fail("ERR_LOCALIZATION_JOB_NOT_TRANSLATED",
             "Only a delivered translation can be bounced back.")
    job["state"] = "REWORK_REQUESTED"
    job["rework_count"] = job["rework_count"] + 1
    touch(job)
    return ok(public(job))


@bp.post("/localization-jobs/<job_id>/publish")
def publish_job(job_id):
    authenticate(("LocalizationCoordinator",))
    body()
    job = must_get("localization_jobs", job_id)
    if job["state"] not in ("TRANSLATED", "SCHEDULED_DELAYED"):
        fail("ERR_LOCALIZATION_JOB_NOT_TRANSLATED",
             "A job in state %s cannot be published." % job["state"])
    topic = db.topics.get(job["topic_id"])
    if topic is None or topic["publication_state"] != "PUBLISHED":
        fail("ERR_SOURCE_TOPIC_NOT_PUBLISHED", "The source page is not live.")

    locale = db.locale_profiles.get(job["locale_profile_id"])
    if locale is not None and locale["publication_mode"] == "SIMULTANEOUS":
        train = calc.topic_train(topic)
        if train is None or train["status"] not in ("GA", "MAINTENANCE"):
            fail("ERR_TRAIN_NOT_GA",
                 "A simultaneous locale publishes only once the train is generally available.")
        job["state"] = "PUBLISHED_LOCALIZED"
        job["published_at"] = db.now_iso()
        job["publication_mode_applied"] = "SIMULTANEOUS"
        job["scheduled_publish_date"] = None
        touch(job)
        settle_job_ledgers(job)
        return ok(public(job))

    if job["state"] == "SCHEDULED_DELAYED":
        scheduled = parse_date(job["scheduled_publish_date"])
        if scheduled is not None and db.today() < scheduled:
            return ok(public(job))
        job["state"] = "PUBLISHED_LOCALIZED"
        job["published_at"] = db.now_iso()
        job["publication_mode_applied"] = "DELAYED"
        touch(job)
        settle_job_ledgers(job)
        return ok(public(job))

    from core import date_of_instant
    source_date = date_of_instant(topic["published_at"])
    target = add_days(source_date, locale["sla_days"])
    job["publication_mode_applied"] = "DELAYED"
    job["scheduled_publish_date"] = fmt_date(target)
    if db.today() < target:
        job["state"] = "SCHEDULED_DELAYED"
        job["published_at"] = None
        touch(job)
        return ok(public(job))
    job["state"] = "PUBLISHED_LOCALIZED"
    job["published_at"] = db.now_iso()
    touch(job)
    settle_job_ledgers(job)
    return ok(public(job))


@bp.post("/localization-jobs/<job_id>/cancel")
def cancel_job(job_id):
    authenticate(("LocalizationCoordinator",))
    data = body()
    cancel_reason = v_str(data, "cancel_reason", 5, 200)

    job = must_get("localization_jobs", job_id)
    if job["state"] not in calc.OPEN_JOB_STATES:
        fail("ERR_LOCALIZATION_JOB_NOT_CANCELLABLE",
             "A job in state %s cannot be cancelled." % job["state"])
    job["state"] = "CANCELLED"
    job["cancel_reason"] = cancel_reason
    touch(job)
    settle_job_ledgers(job)
    return ok(public(job))
