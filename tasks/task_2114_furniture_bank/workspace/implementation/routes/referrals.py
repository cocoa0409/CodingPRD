"""Referral intake, revision rounds and adjudication (PRD 3.2)."""

from flask import Blueprint

from auth import authenticate, require_agency_scope, resolve
from core import CATEGORIES, MAX_REVISIONS, REFERRAL_VALID_DAYS, clock, days
from db import db, new_entity, serialize, touch
from envelope import object_response
from errors import ApiError
from routes._common import filtered, respond_list
from services.calc import intake_score
from validation import Field, pagination_params, validate_body

bp = Blueprint("referrals", __name__)

URGENCIES = ("ROUTINE", "PRIORITY", "EMERGENCY")
DECISIONS = ("APPROVE", "RETURN", "DENY")


@bp.route("/referrals", methods=["POST"])
def create_referral():
    actor = authenticate(["CaseManager"])
    payload = validate_body([
        Field("client_id", "string"),
        Field("agency_id", "string"),
        Field("requested_categories", "enum_array", members=CATEGORIES, non_empty_array=True),
        Field("urgency", "enum", members=URGENCIES),
        Field("home_visit_completed", "boolean", required=False, default=False),
        Field("bed_bug_attestation", "boolean"),
    ])
    client = resolve("client", payload["client_id"])
    agency = resolve("agency", payload["agency_id"])
    require_agency_scope(actor, agency["id"])
    # The referral's agency must equal the household's own agency.
    require_agency_scope(actor, client["agency_id"])

    referral = new_entity(
        client_id=client["id"],
        agency_id=agency["id"],
        requested_categories=list(payload["requested_categories"]),
        urgency=payload["urgency"],
        home_visit_completed=bool(payload["home_visit_completed"]),
        bed_bug_attestation=bool(payload["bed_bug_attestation"]),
        status="DRAFT",
        revision_count=0,
        priority_score=0.0,
        approved_at=None,
        expires_at=None,
        approved_epoch=None,
        review_note=None,
    )
    db.referrals[referral["id"]] = referral
    return object_response(serialize(referral), 201)


@bp.route("/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    actor = authenticate(["CaseManager", "PlatformAdmin"])
    referral = resolve("referral", referral_id)
    require_agency_scope(actor, referral["agency_id"])
    return object_response(serialize(referral))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    authenticate(["CaseManager", "PlatformAdmin"])
    limit, offset = pagination_params()
    rows = filtered(list(db.referrals.values()), {
        "client_id": "client_id",
        "agency_id": "agency_id",
        "status": "status",
    })
    return respond_list(rows, limit, offset)


@bp.route("/referrals/<referral_id>/submit", methods=["POST"])
def submit_referral(referral_id):
    actor = authenticate(["CaseManager"])
    validate_body([])
    referral = resolve("referral", referral_id)
    require_agency_scope(actor, referral["agency_id"])

    client = db.clients.get(referral["client_id"])
    agency = db.agencies.get(referral["agency_id"])

    # (11) state gate
    if referral["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_REFERRAL_NOT_SUBMITTED",
                       "Only a DRAFT or RETURNED referral may be submitted.")
    # (12) revision limit
    if referral["status"] == "RETURNED" and referral["revision_count"] >= MAX_REVISIONS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED",
                       "This referral has used all of its revision rounds.")
    # (13) bed-bug block
    if client["bed_bug_status"] == "CONFIRMED":
        raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                       "The household is under a confirmed bed-bug infestation.")
    # (14) the household must be eligible
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_DELIVERY_BANNED", "The household is ON_HOLD.")
    # the case manager must have attested that there is no active infestation
    if not referral["bed_bug_attestation"]:
        raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                       "The case manager has not attested that the residence is clear.")
    # (27) agency standing
    if agency["standing"] == "SUSPENDED":
        raise ApiError("ERR_AGENCY_SUSPENDED",
                       "A SUSPENDED agency may not submit referrals.")

    if referral["status"] == "RETURNED":
        referral["revision_count"] += 1
    referral["status"] = "SUBMITTED"
    referral["priority_score"] = intake_score(referral, client)
    touch(referral)
    return object_response(serialize(referral))


@bp.route("/referrals/<referral_id>/review", methods=["POST"])
def review_referral(referral_id):
    authenticate(["PlatformAdmin"])
    payload = validate_body([
        Field("decision", "enum", members=DECISIONS),
        Field("note", "string", required=False, default=None),
    ])
    referral = resolve("referral", referral_id)
    decision = payload["decision"]
    client = db.clients.get(referral["client_id"])
    agency = db.agencies.get(referral["agency_id"])

    # (11) state gate
    if decision == "DENY":
        allowed = referral["status"] in ("SUBMITTED", "RETURNED")
    else:
        allowed = referral["status"] == "SUBMITTED"
    if not allowed:
        raise ApiError("ERR_REFERRAL_NOT_SUBMITTED",
                       "This referral has no outgoing edge for that decision.")

    if decision == "APPROVE":
        # (13) bed-bug block, (27) standing, (28) quota
        if client["bed_bug_status"] == "CONFIRMED":
            raise ApiError("ERR_CLIENT_BED_BUG_BLOCK",
                           "The household is under a confirmed bed-bug infestation.")
        if agency["standing"] == "SUSPENDED":
            raise ApiError("ERR_AGENCY_SUSPENDED",
                           "A SUSPENDED agency may not have a referral approved.")
        if agency["quota_used"] >= agency["quarterly_voucher_quota"]:
            raise ApiError("ERR_AGENCY_QUOTA_EXHAUSTED",
                           "The agency has spent its quarterly voucher quota.")
        now = clock.now()
        referral["status"] = "APPROVED"
        referral["approved_at"] = now
        referral["expires_at"] = now + days(REFERRAL_VALID_DAYS)
        referral["approved_epoch"] = agency["quota_epoch"]
        # Only RETURN and DENY store the reviewer note.
        touch(referral)
        agency["quota_used"] += 1
        touch(agency)
    elif decision == "RETURN":
        referral["status"] = "RETURNED"
        referral["review_note"] = payload["note"]
        touch(referral)
    else:
        referral["status"] = "DENIED"
        referral["review_note"] = payload["note"]
        touch(referral)

    return object_response(serialize(referral))
