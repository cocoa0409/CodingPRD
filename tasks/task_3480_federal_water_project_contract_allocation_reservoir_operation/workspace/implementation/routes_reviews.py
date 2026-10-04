"""ImpactReviews: third-party district review of transfers (PRD section 3.8).

The filing district comes from the caller's X-User-ID, must exist, must be
neither transfer party, and may file only once per transfer. On an APPROVED
transfer, filing at or after objection_window_end fails. A SUSTAINED resolution
voids a non-terminal transfer.
"""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, invalid_quantity, not_found
from serial import review_view
from store import DB, clock_now, new_record, touch
from validate import as_enum, as_int, as_str, get_body, required

bp = Blueprint("impact_reviews", __name__)

BASES = ("JUNIOR_IMPAIRMENT", "RETURN_FLOW", "ENVIRONMENTAL")
OUTCOMES = ("SUSTAINED", "DISMISSED")
VOIDABLE_STATES = ("UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED")


@bp.post("/water/transfer-requests/<string:transfer_id>/impact-reviews")
def file_impact_review(transfer_id):
    user_id, _role = authenticate(["DistrictManager"])
    body = get_body()
    claimed = as_int(required(body, "claimed_impact_af"), "claimed_impact_af")
    basis = as_enum(required(body, "basis"), "basis", BASES)
    # existence: path id, then the filing reviewer district from X-User-ID
    transfer = DB["transfers"].get(transfer_id)
    if transfer is None:
        not_found("TransferRequest")
    if user_id not in DB["districts"]:
        not_found("District")
    # segregation of duties: the filer must be neither transfer party
    from_contract = DB["contracts"][transfer["from_contract_id"]]
    to_contract = DB["contracts"][transfer["to_contract_id"]]
    if user_id in (from_contract["district_id"], to_contract["district_id"]):
        raise ApiError("ERR_REVIEWER_CONFLICT", 403,
                       "a transfer party cannot file an impact review on it")
    # business: one review per district per transfer, then positive quantity
    for review in DB["impact_reviews"].values():
        if (review["transfer_request_id"] == transfer["id"]
                and review["reviewer_district_id"] == user_id):
            raise ApiError("ERR_DUPLICATE_REVIEW", 409,
                           "this district has already filed a review on this transfer")
    if claimed <= 0:
        invalid_quantity("claimed_impact_af must be > 0")
    # temporal: filing on an APPROVED transfer closes at objection_window_end
    if (transfer["status"] == "APPROVED"
            and clock_now() >= transfer["objection_window_end"]):
        raise ApiError("ERR_OBJECTION_WINDOW_CLOSED", 409,
                       "the objection window has closed")
    rec = new_record()
    rec.update({
        "transfer_request_id": transfer["id"],
        "reviewer_district_id": user_id,
        "claimed_impact_af": claimed,
        "basis": basis,
        "status": "FILED",
        "resolution_rationale": None,
    })
    DB["impact_reviews"][rec["id"]] = rec
    return success(review_view(rec), 201)


@bp.get("/water/impact-reviews")
def list_impact_reviews():
    authenticate(ALL_ROLES)
    filters = {
        "transfer_request_id": request.args.get("transfer_request_id"),
        "reviewer_district_id": request.args.get("reviewer_district_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB["impact_reviews"].values()), review_view, filters)


@bp.get("/water/impact-reviews/<string:review_id>")
def get_impact_review(review_id):
    authenticate(ALL_ROLES)
    review = DB["impact_reviews"].get(review_id)
    if review is None:
        not_found("ImpactReview")
    return success(review_view(review))


@bp.post("/water/impact-reviews/<string:review_id>/resolve")
def resolve_impact_review(review_id):
    authenticate(["RegionalDirector"])
    body = get_body()
    outcome = as_enum(required(body, "outcome"), "outcome", OUTCOMES)
    rationale = None
    if body.get("rationale") is not None:
        rationale = as_str(body["rationale"], "rationale")
    review = DB["impact_reviews"].get(review_id)
    if review is None:
        not_found("ImpactReview")
    if review["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a FILED impact review can be resolved")
    review["status"] = outcome
    review["resolution_rationale"] = rationale
    touch(review)
    if outcome == "SUSTAINED":
        transfer = DB["transfers"].get(review["transfer_request_id"])
        if transfer is not None and transfer["status"] in VOIDABLE_STATES:
            transfer["status"] = "VOIDED"
            touch(transfer)
    return success(review_view(review), 200)
