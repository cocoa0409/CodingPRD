"""Dual agency disclosures and their acknowledgements (PRD 3.5)."""

from flask import Blueprint

from authz import (BROKER, BUYER, PLATFORM_ADMIN, REGULATOR, SELLER, agreement_or_404,
                   authenticate, disclosure_or_404, require_brokerage, require_buyer,
                   require_seller)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import bump, db, make_record, now, public, public_list, sorted_by_created
from validation import F, json_body, validate

bp = Blueprint("disclosures", __name__)

PARTIES = ("BUYER", "SELLER")


@bp.route("/dual-agency-disclosures", methods=["POST"])
def create_disclosure():
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(), [
        F("agreement_id", "string"),
        F("represents_seller", "boolean"),
        F("represents_buyer", "boolean"),
        F("disclosure_text_ref", "string", required=False, default=None),
    ])
    agreement = agreement_or_404(data["agreement_id"])
    require_brokerage(user_id, role, agreement["brokerage_id"])
    brokerage = db.brokerages.get(agreement["brokerage_id"])
    dual = data["represents_seller"] and data["represents_buyer"]
    if dual and brokerage is not None and brokerage["dual_agency_policy"] == "PROHIBITED":
        raise ApiError("ERR_DUAL_AGENCY_PROHIBITED",
                       "This brokerage may not represent both sides of an agreement.")
    if not data["represents_seller"] and not data["represents_buyer"]:
        raise ApiError("ERR_PARTY_NOT_REPRESENTED",
                       "A disclosure must assert at least one representation.")
    disclosure = make_record({
        "agreement_id": agreement["id"],
        "represents_seller": data["represents_seller"],
        "represents_buyer": data["represents_buyer"],
        "disclosure_text_ref": data["disclosure_text_ref"],
        "seller_ack_at": None,
        "buyer_ack_at": None,
        "status": "PENDING_ACKS",
    })
    db.disclosures[disclosure["id"]] = disclosure
    return created(public(disclosure))


@bp.route("/dual-agency-disclosures/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, SELLER, REGULATOR))
    return ok(public(disclosure_or_404(disclosure_id)))


@bp.route("/dual-agency-disclosures", methods=["GET"])
def list_disclosures():
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, SELLER, REGULATOR))
    limit, offset = pagination_args()
    rows = apply_filters(db.disclosures.values(), {
        "agreement_id": "agreement_id",
        "status": "status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/dual-agency-disclosures/<disclosure_id>/acknowledge", methods=["POST"])
def acknowledge_disclosure(disclosure_id):
    user_id, role = authenticate((BUYER, SELLER))
    data = validate(json_body(), [F("party", "enum", values=PARTIES)])
    disclosure = disclosure_or_404(disclosure_id)
    agreement = agreement_or_404(disclosure["agreement_id"])
    require_buyer(user_id, role, agreement["buyer_id"])
    require_seller(user_id, role, agreement["seller_id"])
    party = data["party"]
    if (role == BUYER and party != "BUYER") or (role == SELLER and party != "SELLER"):
        raise ApiError("ERR_PARTY_NOT_REPRESENTED",
                       "The caller may not acknowledge on behalf of that party.")
    if party == "BUYER" and not disclosure["represents_buyer"]:
        raise ApiError("ERR_PARTY_NOT_REPRESENTED",
                       "The disclosure does not represent the buyer.")
    if party == "SELLER" and not disclosure["represents_seller"]:
        raise ApiError("ERR_PARTY_NOT_REPRESENTED",
                       "The disclosure does not represent the seller.")
    field = "buyer_ack_at" if party == "BUYER" else "seller_ack_at"
    if disclosure[field] is not None:
        raise ApiError("ERR_ALREADY_ACKNOWLEDGED", "That party has already acknowledged.")
    disclosure[field] = now()
    complete = True
    if disclosure["represents_buyer"] and disclosure["buyer_ack_at"] is None:
        complete = False
    if disclosure["represents_seller"] and disclosure["seller_ack_at"] is None:
        complete = False
    if complete and disclosure["status"] == "PENDING_ACKS":
        disclosure["status"] = "FULLY_ACKED"
    bump(disclosure)
    return ok(public(disclosure))
