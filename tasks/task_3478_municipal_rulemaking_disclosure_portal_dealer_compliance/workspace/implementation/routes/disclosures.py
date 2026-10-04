"""Disclosure submission intake, scoping, and portal review endpoints."""
from flask import Blueprint, request

import serializers
import services
import store
from errors import (
    ApiError,
    ERR_COVERAGE_PERIOD_OVERLAP,
    ERR_EVENT_CATEGORY_REQUIRED,
    ERR_INVALID_STATE,
    ERR_ORG_NOT_FOUND,
    ERR_ORG_SUSPENDED,
    ERR_ORG_TYPE_NOT_PERMITTED,
    ERR_SUBMISSION_NOT_FOUND,
)
from respond import ok, ok_list
from validators import (
    forbid_cross_org,
    get_body,
    paginate,
    req_datetime,
    req_enum,
    req_nonempty_str,
    req_str,
    require_auth,
    require_role,
    _bad,
)

bp = Blueprint("disclosures", __name__)

SUBMISSION_TYPES = ("OFFICIAL_STATEMENT", "ANNUAL_FINANCIAL", "EVENT_NOTICE", "VOLUNTARY")
EVENT_CATEGORIES = (
    "PAYMENT_DEFAULT",
    "RATING_CHANGE",
    "BOND_CALL",
    "MERGER_ANNOUNCEMENT",
    "MATERIAL_LITIGATION",
    "OTHER",
)
SUBMISSION_READ_ROLES = ("PortalOperator", "IssuerRep", "PublicReader", "ComplianceOfficer")
FILING_ORG_TYPES = ("ISSUER", "OBLIGATED_PERSON")


def _visible(submission, uid, role):
    if role == "IssuerRep":
        return submission["issuer_org_id"] == uid
    if role == "PublicReader":
        return submission["status"] == "PUBLISHED"
    return True


@bp.route("/msrb/disclosure-submissions", methods=["POST"])
def create_submission():
    uid, role = require_auth()
    require_role(role, ("IssuerRep",))
    body = get_body()
    # Priority 2 ownership: IssuerRep's X-User-ID must equal issuer_org_id.
    forbid_cross_org(uid, body.get("issuer_org_id"))
    # Priority 3 schema checks.
    submission_type = req_enum(body, "submission_type", SUBMISSION_TYPES)
    document_uri = req_str(body, "document_uri")
    cusip = req_str(body, "cusip")
    if len(cusip) != 9:
        raise _bad("cusip must be exactly 9 characters.")
    issuer_org_id = req_str(body, "issuer_org_id")
    event_occurred_at = None
    period_start = None
    period_end = None
    if submission_type == "EVENT_NOTICE":
        event_occurred_at = req_datetime(body, "event_occurred_at")
        if event_occurred_at > store.now():
            raise _bad("event_occurred_at must not be in the future.")
    elif body.get("event_category") is not None:
        raise _bad("event_category is forbidden unless submission_type is EVENT_NOTICE.")
    if submission_type == "ANNUAL_FINANCIAL":
        period_start = req_datetime(body, "period_start")
        period_end = req_datetime(body, "period_end")
        if not (period_start < period_end):
            raise _bad("period_start must be strictly before period_end.")
    # Priority 3.1: EVENT_NOTICE requires event_category.
    event_category = None
    if submission_type == "EVENT_NOTICE":
        if body.get("event_category") is None:
            raise ApiError(
                ERR_EVENT_CATEGORY_REQUIRED,
                "EVENT_NOTICE submissions require an event_category.",
                422,
            )
        event_category = req_enum(body, "event_category", EVENT_CATEGORIES)
    # Priority 5: referenced organization must exist.
    org = store.organizations.get(issuer_org_id)
    if org is None:
        raise ApiError(ERR_ORG_NOT_FOUND, "issuer_org_id does not exist.", 404)
    # Priority 10: organization must be ACTIVE.
    if org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, "The filing organization is SUSPENDED.", 409)
    # Priority 19: organization type gate.
    if org["org_type"] not in FILING_ORG_TYPES:
        raise ApiError(
            ERR_ORG_TYPE_NOT_PERMITTED,
            "Disclosure issuer must be ISSUER or OBLIGATED_PERSON.",
            422,
        )
    # Priority 22: closed-interval annual coverage overlap.
    if submission_type == "ANNUAL_FINANCIAL":
        for sibling in store.disclosure_submissions.values():
            if (
                sibling["issuer_org_id"] == issuer_org_id
                and sibling["submission_type"] == "ANNUAL_FINANCIAL"
                and sibling["status"] in ("RECEIVED", "PUBLISHED")
                and not (
                    period_end < sibling["period_start"]
                    or period_start > sibling["period_end"]
                )
            ):
                raise ApiError(
                    ERR_COVERAGE_PERIOD_OVERLAP,
                    "The coverage interval intersects a sibling ANNUAL_FINANCIAL submission.",
                    409,
                )
    now = store.now()
    if submission_type == "EVENT_NOTICE":
        elapsed_days = (now.date() - event_occurred_at.date()).days
        timeliness = (
            "TIMELY" if elapsed_days <= services.EVENT_NOTICE_LIMIT_DAYS else "LATE"
        )
    else:
        timeliness = "NOT_APPLICABLE"
    submission = {
        "id": store.new_id(),
        "issuer_org_id": issuer_org_id,
        "submission_type": submission_type,
        "event_category": event_category,
        "event_occurred_at": event_occurred_at,
        "period_start": period_start,
        "period_end": period_end,
        "document_uri": document_uri,
        "cusip": cusip,
        "status": "RECEIVED",
        "timeliness": timeliness,
        "deficiency_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.disclosure_submissions[submission["id"]] = submission
    return ok(serializers.disclosure_submission(submission), 201)


@bp.route("/msrb/disclosure-submissions", methods=["GET"])
def list_submissions():
    uid, role = require_auth()
    require_role(role, SUBMISSION_READ_ROLES)
    items = [s for s in store.disclosure_submissions.values() if _visible(s, uid, role)]
    issuer_filter = request.args.get("issuer_org_id")
    if issuer_filter is not None:
        items = [s for s in items if s["issuer_org_id"] == issuer_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    type_filter = request.args.get("submission_type")
    if type_filter is not None:
        items = [s for s in items if s["submission_type"] == type_filter]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serializers.disclosure_submission(s) for s in page], limit, offset, total
    )


@bp.route("/msrb/disclosure-submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    uid, role = require_auth()
    require_role(role, SUBMISSION_READ_ROLES)
    submission = store.disclosure_submissions.get(submission_id)
    if submission is None or not _visible(submission, uid, role):
        # Scoped reads outside the caller's visibility report not-found.
        raise ApiError(ERR_SUBMISSION_NOT_FOUND, "Disclosure submission not found.", 404)
    return ok(serializers.disclosure_submission(submission), 200)


@bp.route("/msrb/disclosure-submissions/<submission_id>/review-outcome", methods=["POST"])
def review_submission(submission_id):
    _uid, role = require_auth()
    require_role(role, ("PortalOperator",))
    body = get_body()
    outcome = req_enum(body, "outcome", ("PUBLISH", "DEFICIENT"))
    deficiency_reason = None
    if outcome == "DEFICIENT":
        deficiency_reason = req_nonempty_str(body, "deficiency_reason")
    submission = store.disclosure_submissions.get(submission_id)
    if submission is None:
        raise ApiError(ERR_SUBMISSION_NOT_FOUND, "Disclosure submission not found.", 404)
    if submission["status"] != "RECEIVED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a RECEIVED submission can be reviewed.",
            409,
        )
    if outcome == "PUBLISH":
        submission["status"] = "PUBLISHED"
    else:
        submission["status"] = "DEFICIENT"
        submission["deficiency_reason"] = deficiency_reason
    services.bump(submission)
    return ok(serializers.disclosure_submission(submission), 200)
