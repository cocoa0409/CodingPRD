"""Membership tiers: the dues ladder and its monotonicity rule."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("tiers", __name__)

TIER_STATUSES = ["DRAFT", "OPEN", "CLOSED"]


@bp.route("/nil/collectives/<collective_id>/membership-tiers", methods=["POST"])
def create_tier(collective_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    # Nested addressing: the outer entity resolves before any body field is examined.
    collective = lookup.collective(collective_id)
    body = shape.body()
    tier_code = shape.string_field(body, "tier_code", required=True)
    tier_name = shape.string_field(body, "tier_name", required=True)
    dues = shape.int_field(body, "annual_dues_cents", required=True, positive=True)
    rank = shape.int_field(body, "benefit_rank", required=True, minimum=1, maximum=5)

    for existing in derive.tiers_of_collective(collective["id"]):
        if existing["tier_code"] == tier_code:
            raise ApiError("ERR_DUPLICATE_TIER_CODE")

    now = clock.now()
    row = {
        "id": store.new_id(),
        "collective_id": collective["id"],
        "tier_code": tier_code,
        "tier_name": tier_name,
        "annual_dues_cents": dues,
        "benefit_rank": rank,
        "tier_status": "DRAFT",
        "sequence_no": store.next_seq("membership_tier"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.membership_tiers[row["id"]] = row
    return envelope.object_response(serialize.membership_tier(row), 201)


@bp.route("/nil/collectives/<collective_id>/membership-tiers", methods=["GET"])
def list_tiers(collective_id):
    auth.authenticate(auth.ALL_ROLES)
    collective = lookup.collective(collective_id)
    limit, offset = envelope.read_pagination(request.args)
    status = envelope.enum_filter(request.args, "tier_status", TIER_STATUSES)
    rows = derive.tiers_of_collective(collective["id"])
    if status is not None:
        rows = [r for r in rows if r["tier_status"] == status]
    return envelope.list_response([serialize.membership_tier(r) for r in rows], limit, offset)


@bp.route("/nil/membership-tiers/<tier_id>", methods=["GET"])
def read_tier(tier_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.membership_tier(tier_id)
    return envelope.object_response(serialize.membership_tier(row))


@bp.route("/nil/membership-tiers/<tier_id>/transitions", methods=["POST"])
def transition_tier(tier_id):
    auth.authenticate([auth.COLLECTIVE_DIRECTOR])
    body = shape.body()
    action = shape.enum_field(body, "action", ["OPEN", "CLOSE"], required=True)
    tier = lookup.membership_tier(tier_id)

    if action == "OPEN":
        if tier["tier_status"] != "DRAFT":
            raise ApiError("ERR_TIER_NOT_DRAFT")
        for sibling in derive.tiers_of_collective(tier["collective_id"]):
            if sibling["id"] == tier["id"] or sibling["tier_status"] != "OPEN":
                continue
            if sibling["benefit_rank"] < tier["benefit_rank"]:
                if tier["annual_dues_cents"] <= sibling["annual_dues_cents"]:
                    raise ApiError("ERR_TIER_RANK_DUES_INVERSION")
            elif sibling["benefit_rank"] > tier["benefit_rank"]:
                if tier["annual_dues_cents"] >= sibling["annual_dues_cents"]:
                    raise ApiError("ERR_TIER_RANK_DUES_INVERSION")
        tier["tier_status"] = "OPEN"
    else:
        if tier["tier_status"] != "OPEN":
            raise ApiError("ERR_TIER_NOT_OPEN")
        tier["tier_status"] = "CLOSED"
    derive.touch(tier)
    return envelope.object_response(serialize.membership_tier(tier))
