"""Job posting endpoints: creation, feed-snapshot ingestion, versions, assessments."""

from urllib.parse import urlsplit

from flask import Blueprint

import auth
import validations as V
from db import iso, store
from models import (
    assessment_view,
    content_hash,
    create,
    dedupe_key,
    job_posting_view,
    touch,
    version_view,
)
from response import array, ok, page_meta, paginate
from services import calc

bp = Blueprint("job_postings", __name__)

APPLY_MODES = ("HOSTED", "ATS_REDIRECT")
POSTING_STATES = ("DRAFT", "ACTIVE", "STALE", "EXPIRED", "SUSPENDED")

# Misleading-posting keyword list (PRD 3.1: wire transfer / upfront fee / pay to start).
FRAUD_KEYWORDS = (
    "wire transfer", "wire transfers", "wire the money",
    "upfront fee", "up-front fee", "upfront payment", "upfront cost",
    "pay to start", "pay to apply", "pay to work", "pay to begin",
    "payment to start", "fee to start", "start-up fee", "startup fee",
    "advance fee", "advance payment", "western union", "money order",
    "processing fee", "registration fee", "application fee", "training fee",
    "equipment fee", "deposit required", "send money", "bank transfer",
    "cashier's check", "cashiers check", "no experience needed pay",
)


def scan_fraud(*texts):
    blob = " ".join(str(text).casefold() for text in texts if text)
    for keyword in FRAUD_KEYWORDS:
        if keyword in blob:
            return keyword
    return None


def valid_redirect_url(url):
    if not isinstance(url, str) or url.strip() == "":
        return False
    parts = urlsplit(url.strip())
    return parts.scheme == "https" and bool(parts.netloc)


def require_not_suspended(employer):
    if employer is None or employer["status"] == "SUSPENDED":
        from errors import ERR_EMPLOYER_SUSPENDED, fail
        fail(ERR_EMPLOYER_SUSPENDED,
             "A SUSPENDED employer may not create postings, snapshots, campaigns, "
             "sponsored jobs or events.")


def require_no_fraud(*texts):
    keyword = scan_fraud(*texts)
    if keyword is not None:
        from errors import ERR_FRAUD_KEYWORDS_DETECTED, fail
        fail(ERR_FRAUD_KEYWORDS_DETECTED,
             "The posting content contains the misleading-posting keyword '%s'." % keyword)


def load_posting_for_write(actor_id, role, posting_id):
    posting = V.get("job_posting", posting_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "job posting", "Employer", posting["employer_id"])
    return posting


def load_posting_for_read(actor_id, role, posting_id):
    return V.get("job_posting", posting_id)


@bp.post("/job-postings")
def create_posting():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["employer_id", "title", "location", "description_text", "apply_mode"])
    employer_id = V.require_string(data, "employer_id")
    title = V.require_string(data, "title")
    location = V.optional_string(data, "location") or ""
    description_text = V.optional_string(data, "description_text") or ""
    apply_mode = V.require_enum(data, "apply_mode", APPLY_MODES)
    redirect_url = V.optional_string(data, "apply_redirect_url")
    external_posting_id = V.optional_string(data, "external_posting_id")

    employer = V.get("employer", employer_id)
    auth.require_ownership(actor_id, role, "job posting", "Employer", employer["id"])

    # Tier 5: fraud / trust safety before the tier-6 ingestion checks.
    require_not_suspended(employer)
    require_no_fraud(title, description_text)

    # Tier 6: apply-mode coherence, then the per-employer dedupe key.
    if apply_mode == "ATS_REDIRECT" and not valid_redirect_url(redirect_url):
        from errors import ERR_INVALID_REDIRECT_URL, fail
        fail(ERR_INVALID_REDIRECT_URL,
             "apply_mode ATS_REDIRECT requires an absolute https apply_redirect_url.")
    if apply_mode == "HOSTED":
        redirect_url = None

    key = dedupe_key(title, location, external_posting_id)
    for existing in store.job_postings.values():
        if existing["employer_id"] != employer["id"]:
            continue
        if existing["dedupe_key"] == key:
            from errors import ERR_DUPLICATE_INGESTION, fail
            fail(ERR_DUPLICATE_INGESTION,
                 "This employer has already advertised this posting.")

    posting = create(
        "job_postings",
        employer_id=employer["id"],
        title=title,
        location=location,
        description_text=description_text,
        state="DRAFT",
        current_freshness=None,
        apply_mode=apply_mode,
        apply_redirect_url=redirect_url,
        posted_at=iso(store.clock),
        apply_started_count=0,
        apply_completed_count=0,
        dedupe_key=key,
    )

    # The posting is created together with its first feed snapshot.
    version = create(
        "job_posting_versions",
        job_posting_id=posting["id"],
        content_hash=content_hash(title, description_text),
        external_posting_id=external_posting_id,
        ingested_at=iso(store.clock),
        freshness=calc.freshness_of(iso(store.clock), store.clock),
    )
    calc.rederive_posting(posting)
    touch(posting)
    if posting["state"] in ("EXPIRED", "SUSPENDED"):
        calc.pause_sponsored_jobs_for_posting(posting)
    _ = version
    return ok(job_posting_view(posting), 201)


@bp.get("/job-postings")
def list_postings():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "JobSeeker"))
    V.reject_unknown_query({"employer_id", "state", "limit", "offset"})
    employer_id = V.str_filter("employer_id")
    state = V.enum_filter("state", POSTING_STATES)
    limit, offset = V.pagination()
    if employer_id is not None:
        V.get("employer", employer_id)

    items = [
        posting for posting in store.job_postings.values()
        if (employer_id is None or posting["employer_id"] == employer_id)
        and (state is None or posting["state"] == state)
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([job_posting_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))


@bp.get("/job-postings/<posting_id>")
def get_posting(posting_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "JobSeeker"))
    posting = load_posting_for_read(actor_id, role, posting_id)
    return ok(job_posting_view(posting))


@bp.post("/job-postings/<posting_id>/versions")
def ingest_version(posting_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["external_posting_id"])
    external_posting_id = V.require_string(data, "external_posting_id")
    posting = load_posting_for_write(actor_id, role, posting_id)
    employer = store.employers.get(posting["employer_id"])

    # Content fields default to the posting's newest existing snapshot.
    title = V.optional_string(data, "title")
    if title is None:
        title = posting["title"]
    description_text = V.optional_string(data, "description_text")
    if description_text is None:
        description_text = posting["description_text"]
    apply_mode = V.strict_enum(data, "apply_mode", APPLY_MODES)
    if apply_mode is None:
        apply_mode = posting["apply_mode"]
    redirect_url = V.optional_string(data, "apply_redirect_url")
    if "apply_redirect_url" not in data:
        redirect_url = posting["apply_redirect_url"]

    # Tier 5: fraud / trust safety.
    require_not_suspended(employer)
    require_no_fraud(title, description_text)

    # Tier 6: apply-mode coherence, duplicate ingestion, dedupe key.
    if apply_mode == "ATS_REDIRECT" and not valid_redirect_url(redirect_url):
        from errors import ERR_INVALID_REDIRECT_URL, fail
        fail(ERR_INVALID_REDIRECT_URL,
             "apply_mode ATS_REDIRECT requires an absolute https apply_redirect_url.")
    if apply_mode == "HOSTED":
        redirect_url = None

    incoming_hash = content_hash(title, description_text)
    for version in store.job_posting_versions.values():
        if version["job_posting_id"] != posting["id"]:
            continue
        if version["content_hash"] != incoming_hash:
            continue
        # A repeated hash inside the 30-day window is a feed replay.
        age_days = calc.age_days(version["ingested_at"], store.clock)
        if age_days < calc.STALE_AFTER_DAYS:
            from errors import ERR_DUPLICATE_INGESTION, fail
            fail(ERR_DUPLICATE_INGESTION,
                 "This snapshot duplicates a version ingested within the last 30 days.")

    key = dedupe_key(title, posting["location"], external_posting_id)
    for other in store.job_postings.values():
        if other["id"] == posting["id"] or other["employer_id"] != posting["employer_id"]:
            continue
        if other["dedupe_key"] == key:
            from errors import ERR_DUPLICATE_INGESTION, fail
            fail(ERR_DUPLICATE_INGESTION,
                 "This employer has already advertised this posting.")

    version = create(
        "job_posting_versions",
        job_posting_id=posting["id"],
        content_hash=incoming_hash,
        external_posting_id=external_posting_id,
        ingested_at=iso(store.clock),
        freshness=calc.freshness_of(iso(store.clock), store.clock),
    )

    posting["title"] = title
    posting["description_text"] = description_text
    posting["apply_mode"] = apply_mode
    posting["apply_redirect_url"] = redirect_url
    posting["dedupe_key"] = key
    posting["posted_at"] = iso(store.clock)
    before_state = posting["state"]
    calc.rederive_posting(posting)
    if before_state in ("EXPIRED", "SUSPENDED") and posting["state"] not in ("EXPIRED", "SUSPENDED"):
        posting["state"] = "SUSPENDED" if before_state == "SUSPENDED" else posting["state"]
    touch(posting)

    # An EXPIRED (or suspended) posting pauses every SponsoredJob sponsoring it.
    if posting["state"] in ("EXPIRED", "SUSPENDED"):
        calc.pause_sponsored_jobs_for_posting(posting)
    if posting["state"] == "STALE":
        # Excluded from the sponsored placement candidate set.
        pass
    return ok(version_view(version), 201)


@bp.get("/job-postings/<posting_id>/versions")
def list_versions(posting_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    posting = load_posting_for_read(actor_id, role, posting_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "job posting", "Employer", posting["employer_id"])
    V.reject_unknown_query({"limit", "offset"})
    limit, offset = V.pagination()
    items = [
        version for version in store.job_posting_versions.values()
        if version["job_posting_id"] == posting["id"]
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([version_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))


@bp.get("/job-postings/<posting_id>/assessments")
def list_posting_assessments(posting_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer"))
    posting = load_posting_for_read(actor_id, role, posting_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "job posting", "Employer", posting["employer_id"])
    V.reject_unknown_query({"limit", "offset"})
    limit, offset = V.pagination()
    items = [
        assessment for assessment in store.assessments.values()
        if assessment["job_posting_id"] == posting["id"]
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([assessment_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))