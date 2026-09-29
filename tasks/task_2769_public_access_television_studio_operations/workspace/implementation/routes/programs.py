"""Programs, attestation clearance and content review (PRD 3.3)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import db
import middleware
import support
import validation
from errors import ApiError, bad_request, invalid_transition, not_found
from util import add_days

bp = Blueprint("programs", __name__)

PROGRAM_READ_ROLES = (
    C.ROLE_CENTER_ADMIN,
    C.ROLE_CONTENT_REVIEWER,
    C.ROLE_SCHEDULING_COORDINATOR,
    C.ROLE_PRODUCER,
)
ATTESTATION_READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_CONTENT_REVIEWER, C.ROLE_PRODUCER)
DECISIONS = ["APPROVE", "REQUEST_CHANGES", "REJECT"]


@bp.post("/programs")
def create_program():
    user_id, role = middleware.authorize(C.ROLE_PRODUCER)
    body = validation.body()
    producer_id = validation.req_id(body, "producer_id")
    title = validation.req_string(body, "title")
    runtime_seconds = validation.req_int(body, "runtime_seconds", minimum=60)
    is_live = validation.req_bool(body, "is_live")
    required_crew_roles = validation.req_enum_list(body, "required_crew_roles", C.CREW_ROLES)
    series_id = validation.opt_id(body, "series_id")
    episode_number = validation.opt_int(body, "episode_number", minimum=1)
    if not is_live and required_crew_roles:
        raise bad_request("required_crew_roles must be empty when is_live is false")
    producer = db.get("producers", producer_id)
    if producer is None:
        raise not_found("producer", producer_id)
    series = None
    if series_id is not None:
        series = db.get("series", series_id)
        if series is None:
            raise not_found("series", series_id)
    middleware.require_owner(producer_id, user_id, role)
    # priority 16
    if is_live and calc.certification_level(producer) != "LIVE":
        raise ApiError(
            "ERR_CERTIFICATION_INSUFFICIENT", "A LIVE certification is required for live production"
        )
    # priority 34
    if series is not None and series["producer_id"] != producer_id:
        raise ApiError(
            "ERR_SERIES_NOT_OWNED_BY_PRODUCER", "The series belongs to a different producer"
        )
    row = db.new_row(
        "programs",
        {
            "producer_id": producer_id,
            "series_id": series_id,
            "title": title,
            "episode_number": episode_number,
            "runtime_seconds": runtime_seconds,
            "is_live": is_live,
            "required_crew_roles": required_crew_roles,
            "review_status": "DRAFT",
            "clearance_status": "INCOMPLETE",
            "reviewed_by_user_id": None,
            "finding_category": None,
            "finding_notes": None,
            "revision_round": 0,
            "attestation_sequence_high": 0,
            "withdrawn_reason": None,
        },
    )
    return support.created("programs", row)


@bp.get("/programs/<program_id>")
def read_program(program_id):
    middleware.authorize(*PROGRAM_READ_ROLES)
    row = support.must_exist("programs", program_id)
    return support.single("programs", row)


@bp.get("/programs")
def list_programs():
    middleware.authorize(*PROGRAM_READ_ROLES)
    producer_id = validation.query_string("producer_id")
    series_id = validation.query_string("series_id")
    review_status = validation.query_enum("review_status", C.REVIEW_STATUSES)
    clearance_status = validation.query_enum("clearance_status", C.CLEARANCE_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "programs",
        [
            ("producer_id", producer_id),
            ("series_id", series_id),
            ("review_status", review_status),
            ("clearance_status", clearance_status),
        ],
    )
    return support.collection_response("programs", rows)


# --------------------------------------------------------------------------- #
# attestations
# --------------------------------------------------------------------------- #
@bp.post("/programs/<program_id>/attestations")
def append_attestation(program_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER)
    body = validation.body()
    attestation_kind = validation.req_enum(body, "attestation_kind", C.ATTESTATION_KINDS)
    statement_version = validation.req_string(body, "statement_version")
    third_party_material = validation.req_bool(body, "third_party_material")
    license_reference = validation.opt_string(body, "license_reference")
    program = support.must_exist("programs", program_id)
    middleware.require_owner(program["producer_id"], user_id, role)
    # priority 39
    if (
        attestation_kind == "COPYRIGHT_CLEARANCE"
        and third_party_material
        and (license_reference is None or license_reference.strip() == "")
    ):
        raise ApiError(
            "ERR_LICENSE_REFERENCE_REQUIRED",
            "A license_reference is required when third-party material is declared",
        )
    instant = db.now()
    previous = cascades.latest_attestation(program_id, attestation_kind)
    if previous is not None:
        # the closing stamp is the one exception to attestation immutability
        previous["effective_until"] = instant
    sequence_number = program["attestation_sequence_high"] + 1
    program["attestation_sequence_high"] = sequence_number
    effective_until = None
    if attestation_kind == "INDEMNIFICATION":
        effective_until = add_days(instant, C.INDEMNIFICATION_TERM_DAYS)
    row = db.new_row(
        "attestations",
        {
            "program_id": program_id,
            "signed_by_producer_id": program["producer_id"],
            "attestation_kind": attestation_kind,
            "statement_version": statement_version,
            "third_party_material": third_party_material,
            "license_reference": license_reference,
            "sequence_number": sequence_number,
            "effective_from": instant,
            "effective_until": effective_until,
        },
    )
    if attestation_kind == "INDEMNIFICATION":
        producer = db.get("producers", program["producer_id"])
        if producer is not None:
            producer["indemnification_expires_at"] = add_days(instant, C.INDEMNIFICATION_TERM_DAYS)
            db.bump(producer)
    cascades.refresh_clearance(program)
    db.bump(program)
    return support.created("attestations", row)


@bp.get("/attestations/<attestation_id>")
def read_attestation(attestation_id):
    middleware.authorize(*ATTESTATION_READ_ROLES)
    row = support.must_exist("attestations", attestation_id)
    return support.single("attestations", row)


@bp.get("/attestations")
def list_attestations():
    middleware.authorize(*ATTESTATION_READ_ROLES)
    program_id = validation.query_string("program_id")
    signed_by_producer_id = validation.query_string("signed_by_producer_id")
    attestation_kind = validation.query_enum("attestation_kind", C.ATTESTATION_KINDS)
    validation.pagination()
    rows = support.filter_rows(
        "attestations",
        [
            ("program_id", program_id),
            ("signed_by_producer_id", signed_by_producer_id),
            ("attestation_kind", attestation_kind),
        ],
    )
    return support.collection_response("attestations", rows)


# --------------------------------------------------------------------------- #
# review pipeline
# --------------------------------------------------------------------------- #
@bp.post("/programs/<program_id>/submit")
def submit_program(program_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER)
    validation.body()
    program = support.must_exist("programs", program_id)
    middleware.require_owner(program["producer_id"], user_id, role)
    if program["review_status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise invalid_transition("Only a draft or changes-requested program may be submitted")
    producer = db.get("producers", program["producer_id"])
    # priority 10
    if producer is None or producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The owning producer is not active")
    # priority 12
    if program["clearance_status"] != "CLEARED":
        raise ApiError("ERR_ATTESTATION_INCOMPLETE", "The program's attestations are incomplete")
    # priority 13
    if program["series_id"]:
        series = db.get("series", program["series_id"])
        if series is None or series["status"] != "ACTIVE":
            raise ApiError("ERR_SERIES_NOT_ACTIVE", "The program's series is not active")
    # priority 22
    if program["revision_round"] > C.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED", "The revision budget for this program is spent")
    # priority 25
    expires_at = producer["indemnification_expires_at"]
    if expires_at is None or expires_at <= db.now():
        raise ApiError("ERR_INDEMNIFICATION_EXPIRED", "The producer's indemnification is not in force")
    program["review_status"] = "SUBMITTED"
    program["reviewed_by_user_id"] = None
    db.bump(program)
    return support.single("programs", program)


@bp.post("/programs/<program_id>/review-claim")
def claim_program(program_id):
    user_id, _role = middleware.authorize(C.ROLE_CONTENT_REVIEWER)
    validation.body()
    program = support.must_exist("programs", program_id)
    if program["review_status"] != "SUBMITTED":
        raise invalid_transition("Only a submitted program may be claimed")
    program["review_status"] = "UNDER_REVIEW"
    program["reviewed_by_user_id"] = user_id
    db.bump(program)
    return support.single("programs", program)


@bp.post("/programs/<program_id>/review-decision")
def decide_program(program_id):
    user_id, _role = middleware.authorize(C.ROLE_CONTENT_REVIEWER)
    body = validation.body()
    decision = validation.req_enum(body, "decision", DECISIONS)
    finding_category = validation.opt_string(body, "finding_category")
    finding_notes = validation.opt_string(body, "finding_notes")
    program = support.must_exist("programs", program_id)
    # the claiming reviewer is the only one who may decide (PRD 2.1 / 3.3)
    if program["review_status"] != "UNDER_REVIEW" or program["reviewed_by_user_id"] != user_id:
        raise invalid_transition("Only the claiming reviewer may decide a program under review")
    # priority 21
    if decision == "APPROVE":
        if finding_category is not None:
            raise ApiError(
                "ERR_FINDING_CATEGORY_NOT_PERMITTED", "An approval may not carry a finding category"
            )
    else:
        if finding_category is None or finding_category not in C.UNPROTECTED_FINDING_CATEGORIES:
            raise ApiError(
                "ERR_FINDING_CATEGORY_NOT_PERMITTED",
                "A refusal must cite one of the legally unprotected finding categories",
            )
    if decision == "APPROVE":
        program["review_status"] = "APPROVED"
        program["finding_category"] = None
        program["finding_notes"] = None
        db.bump(program)
    elif decision == "REQUEST_CHANGES":
        program["review_status"] = "CHANGES_REQUESTED"
        program["revision_round"] = program["revision_round"] + 1
        program["finding_category"] = finding_category
        program["finding_notes"] = finding_notes
        db.bump(program)
    else:
        program["review_status"] = "REJECTED"
        program["finding_category"] = finding_category
        program["finding_notes"] = finding_notes
        db.bump(program)
        cascades.withdraw_program_slots(program)
    return support.single("programs", program)


@bp.post("/programs/<program_id>/withdraw")
def withdraw_program(program_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_CENTER_ADMIN)
    body = validation.body()
    withdrawn_reason = validation.req_string(body, "withdrawn_reason")
    program = support.must_exist("programs", program_id)
    middleware.require_owner(program["producer_id"], user_id, role)
    if program["review_status"] in ("REJECTED", "WITHDRAWN"):
        raise invalid_transition("The program is already in a terminal review state")
    program["review_status"] = "WITHDRAWN"
    program["withdrawn_reason"] = withdrawn_reason
    db.bump(program)
    cascades.withdraw_program_slots(program)
    cascades.withdraw_published_assets(program)
    return support.single("programs", program)
