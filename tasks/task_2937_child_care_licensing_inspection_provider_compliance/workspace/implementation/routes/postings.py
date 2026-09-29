"""The public inspection register (PRD §3.9)."""

from flask import Blueprint, request

import calc
import clock
import constants as K
import envelope
import helpers
import serialize
import store
import validate
from auth import authenticate
from errors import ApiError
from validate import F

bp = Blueprint("postings", __name__)

POSTING_READERS = ("AgencyAdmin", "LicensingSupervisor", "Applicant", "PublicPortalReader")


@bp.post("/licensing/public-report-postings")
def create_posting():
    authenticate(("AgencyAdmin",))
    vals = validate.body(
        [
            F("inspection_id", "string", required=True),
            F(
                "consumer_summary",
                "string",
                required=True,
                min_len=1,
                max_len=2000,
                not_blank=True,
            ),
            F("redaction_complete", "bool"),
        ]
    )
    inspection = helpers.need("inspection", vals["inspection_id"])
    if inspection["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is not FINALIZED.")
    for posting in store.ordered(store.postings):
        if posting["inspection_id"] == inspection["id"]:
            raise ApiError(
                "ERR_INVALID_REQUEST", "This inspection already has a public posting."
            )
    record = {
        "inspection_id": inspection["id"],
        "provider_id": inspection["provider_id"],
        "posting_status": "PENDING_REDACTION",
        "redaction_complete": bool(vals.get("redaction_complete", False)),
        "consumer_summary": vals["consumer_summary"],
        "display_score": None,
        "enforcement_banner": "NONE",
        "posted_at": None,
        "expires_at": None,
        "corrected_at": None,
        "withdrawn_at": None,
        "revision_note": None,
        "correction_count": 0,
    }
    store.create(store.postings, record)
    return envelope.created(serialize.posting(record))


@bp.get("/licensing/public-report-postings")
def list_postings():
    authenticate(POSTING_READERS)
    limit, offset = envelope.pagination(request.args)
    posting_status = validate.query_enum("posting_status", K.POSTING_STATUSES)
    provider_id = validate.query_str("provider_id")
    inspection_id = validate.query_str("inspection_id")
    rows = store.ordered(store.postings)
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if posting_status is not None:
        rows = [r for r in rows if r["posting_status"] == posting_status]
    return helpers.listing(rows, serialize.posting, limit, offset)


@bp.get("/licensing/public-report-postings/<posting_id>")
def read_posting(posting_id):
    authenticate(POSTING_READERS)
    record = helpers.need("posting", posting_id)
    return envelope.ok(serialize.posting(record))


@bp.post("/licensing/public-report-postings/<posting_id>/post")
def publish_posting(posting_id):
    authenticate(("AgencyAdmin",))
    validate.body([])
    posting = helpers.need("posting", posting_id)
    inspection = store.inspections[posting["inspection_id"]]
    if inspection["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE", "The visit is no longer FINALIZED.")
    if posting["posting_status"] != "PENDING_REDACTION":
        raise ApiError("ERR_INVALID_POSTING_STATE", "The posting is not PENDING_REDACTION.")
    for complaint in store.by_provider(store.complaints, posting["provider_id"]):
        if complaint["status"] == "UNDER_INVESTIGATION":
            raise ApiError(
                "ERR_POSTING_BLOCKED_OPEN_INVESTIGATION",
                "An open investigation of this provider blocks publication.",
            )
    if not posting["redaction_complete"]:
        raise ApiError("ERR_REDACTION_INCOMPLETE", "Redaction is not complete.")

    provider = store.providers[posting["provider_id"]]
    posted_at = clock.now_dt()
    banner, score = calc.display_score(
        inspection["final_compliance_score"], provider["current_ladder_step"]
    )
    posting["posting_status"] = "POSTED"
    posting["posted_at"] = clock.fmt(posted_at)
    posting["expires_at"] = clock.fmt(clock.add_months(posted_at, K.POSTING_RETENTION_MONTHS))
    posting["enforcement_banner"] = banner
    posting["display_score"] = score
    store.touch(posting)
    return envelope.ok(serialize.posting(posting))


@bp.post("/licensing/public-report-postings/<posting_id>/revise")
def revise_posting(posting_id):
    authenticate(("AgencyAdmin",))
    vals = validate.body(
        [
            F("action", "enum", required=True, values=K.POSTING_ACTIONS),
            F(
                "revision_note",
                "string",
                required=True,
                min_len=1,
                max_len=2000,
                not_blank=True,
            ),
        ]
    )
    posting = helpers.need("posting", posting_id)
    if posting["posting_status"] not in ("POSTED", "CORRECTED"):
        raise ApiError(
            "ERR_INVALID_POSTING_STATE", "Only a live posting can be corrected or withdrawn."
        )
    if vals["action"] == "CORRECT" and posting["correction_count"] >= K.POSTING_MAX_CORRECTIONS:
        raise ApiError(
            "ERR_POSTING_CORRECTION_LIMIT", "The posting's correction allowance is exhausted."
        )

    posting["revision_note"] = vals["revision_note"]
    if vals["action"] == "CORRECT":
        inspection = store.inspections[posting["inspection_id"]]
        provider = store.providers[posting["provider_id"]]
        banner, score = calc.display_score(
            inspection["final_compliance_score"], provider["current_ladder_step"]
        )
        posting["posting_status"] = "CORRECTED"
        posting["correction_count"] += 1
        posting["corrected_at"] = clock.now()
        posting["enforcement_banner"] = banner
        posting["display_score"] = score
    else:
        posting["posting_status"] = "WITHDRAWN"
        posting["withdrawn_at"] = clock.now()
        posting["display_score"] = None
    store.touch(posting)
    return envelope.ok(serialize.posting(posting))
