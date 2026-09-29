"""Readiness item endpoints (PRD 3.1)."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("items", __name__)

REQUIRED_BY_TYPE = {
    "CONTENT_EXAM": ("exam_score",),
    "COURSEWORK_BLOCK": ("credits",),
    "BACKGROUND_CLEARANCE": ("clearance_scope", "expires_on"),
}
POLYMORPHIC_FIELDS = ("exam_score", "credits", "clearance_scope", "expires_on")


@bp.post("/epp/readiness-items")
@endpoint(["CredentialAnalyst"])
def create_item():
    body = shapes.body_of(request)
    candidate_id = shapes.req_str(body, "candidate_id", 1, None)
    item_type = shapes.req_enum(body, "item_type", shapes.ITEM_TYPES)
    issued_on = shapes.req_date(body, "issued_on")

    required = REQUIRED_BY_TYPE[item_type]
    for field in POLYMORPHIC_FIELDS:
        if field in required:
            if field not in body or body[field] is None:
                raise shapes.bad(
                    "Field '%s' is required for item_type %s."
                    % (field, item_type))
        elif field in body:
            raise shapes.bad(
                "Field '%s' must be omitted for item_type %s."
                % (field, item_type))

    exam_score = None
    credits = None
    clearance_scope = None
    expires_on = None
    if item_type == "CONTENT_EXAM":
        exam_score = shapes.req_int(body, "exam_score", 0, 300)
    elif item_type == "COURSEWORK_BLOCK":
        credits = shapes.req_number(body, "credits", 0, 60, "0.5")
    else:
        clearance_scope = shapes.req_enum(body, "clearance_scope",
                                          shapes.CLEARANCE_SCOPES)
        expires_on = shapes.req_date(body, "expires_on")

    candidate = store.get_candidate(candidate_id)

    if expires_on is not None and not expires_on > issued_on:
        raise ApiError("ERR_INVALID_WINDOW",
                       "expires_on must be strictly later than issued_on.")

    row = store.new_row({
        "candidate_id": candidate["id"],
        "item_type": item_type,
        "status": "PENDING_VERIFICATION",
        "exam_score": exam_score,
        "credits": credits,
        "clearance_scope": clearance_scope,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "verified_by_user_id": None,
        "verified_at": None,
        "rejection_note": None,
    })
    store.ITEMS[row["id"]] = row
    return envelope.created(views.dump(row, views.READINESS_ITEM))


@bp.get("/epp/readiness-items/<item_id>")
@endpoint(["CredentialAnalyst", "ProgramAdmin", "CandidateUser"])
def read_item(item_id):
    row = store.get_item(item_id)
    derive.expire_item(row)
    return envelope.ok(views.dump(row, views.READINESS_ITEM))


@bp.get("/epp/readiness-items")
@endpoint(["CredentialAnalyst", "ProgramAdmin"])
def list_items():
    page, page_size = shapes.pagination(request.args)
    candidate_id = request.args.get("candidate_id") or None
    item_type = shapes.query_enum(request.args, "item_type", shapes.ITEM_TYPES)
    status = shapes.query_enum(request.args, "status", shapes.ITEM_STATUSES)
    rows = []
    for row in store.all_of(store.ITEMS):
        if candidate_id is not None and row["candidate_id"] != candidate_id:
            continue
        if item_type is not None and row["item_type"] != item_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.READINESS_ITEM),
                            page, page_size, total)


@bp.post("/epp/readiness-items/<item_id>/verify")
@endpoint(["CredentialAnalyst"])
def verify_item(item_id):
    row = store.get_item(item_id)
    body = shapes.body_of(request)
    decision = shapes.req_enum(body, "decision", ("VERIFIED", "REJECTED"))
    rejection_note = shapes.opt_str(body, "rejection_note", 1, None)

    if row["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_ITEM_STATE_INVALID",
                       "Only a PENDING_VERIFICATION item may be decided.")

    if (decision == "VERIFIED" and row["item_type"] == "BACKGROUND_CLEARANCE"
            and row["expires_on"] is not None
            and row["expires_on"] < clock.today()):
        raise ApiError("ERR_INVALID_WINDOW",
                       "The clearance has already lapsed and cannot be "
                       "verified.")

    row["status"] = decision
    row["verified_by_user_id"] = auth.user_id()
    row["verified_at"] = clock.now()
    if decision == "REJECTED":
        row["rejection_note"] = rejection_note
    store.touch(row)

    candidate = store.CANDIDATES.get(row["candidate_id"])
    if candidate is not None:
        derive.evaluate_readiness(candidate, "STRICT", force_touch=True)
    return envelope.ok(views.dump(row, views.READINESS_ITEM))
