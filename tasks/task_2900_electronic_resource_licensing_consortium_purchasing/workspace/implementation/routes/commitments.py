"""Section 3.3 - pledging participation and consortium tier pricing."""

from flask import Blueprint, request

import auth
import calc
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("commitments", __name__)

LIVE_STATUSES = ("PLEDGED", "CONFIRMED")


@bp.post("/erm/products/<product_id>/commitments")
def create_commitment(product_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    product = auth.get_product(product_id)
    data = shape.body()
    member = None
    if shape.present(data, "member_id"):
        member = auth.get_member(data["member_id"])
        auth.require_member_scope(data["member_id"])
    member_id = shape.req_string(data, "member_id")

    # priority 9 - the acting member must be in good standing
    if member["standing"] != "IN_GOOD_STANDING":
        raise ApiError("ERR_MEMBER_OVER_COMMITTED")

    # priority 26 - one live pledge per package
    for existing in store.commitments.values():
        if existing["product_id"] == product["id"] \
                and existing["member_id"] == member_id \
                and existing["status"] in LIVE_STATUSES:
            raise ApiError("ERR_DUPLICATE_COMMITMENT")

    # the projection variant counts the row being created
    live = len(services.commitments_of_product(product["id"], LIVE_STATUSES)) + 1
    price, discount, participants = calc.member_tier_price_cents(member, product, live)

    # priority 32 - the ceiling check uses the projected price
    if member["annual_committed_cents"] + price > member["budget_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED")

    row = store.new_row({
        "product_id": product["id"],
        "member_id": member_id,
        "subscription_id": None,
        "status": "PLEDGED",
        "projected_price_cents": price,
        "tier_price_cents": None,
        "applied_discount_pct": discount,
        "participant_count_at_pricing": participants,
    })
    store.commitments[row["id"]] = row
    return envelope.object_response(store.serialize(row), 201)


@bp.get("/erm/commitments/<commitment_id>")
def read_commitment(commitment_id):
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_VENDOR_REP
    )
    row = auth.get_commitment(commitment_id)
    return envelope.object_response(store.serialize(row))


@bp.get("/erm/commitments")
def list_commitments():
    auth.require_roles(
        auth.ROLE_CONSORTIUM_ADMIN, auth.ROLE_MEMBER_LIBRARIAN, auth.ROLE_VENDOR_REP
    )
    rows = list(store.commitments.values())
    for field in ("product_id", "member_id", "subscription_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return envelope.paged(rows)


@bp.post("/erm/commitments/<commitment_id>/withdraw")
def withdraw_commitment(commitment_id):
    auth.require_roles(auth.ROLE_MEMBER_LIBRARIAN)
    commitment = auth.get_commitment(commitment_id)
    auth.require_member_scope(commitment["member_id"])

    status = commitment["status"]
    if status not in LIVE_STATUSES:
        raise ApiError("ERR_COMMITMENT_INVALID_STATE")

    if status == "PLEDGED":
        # a pledge never entered the ledger, so nothing unwinds
        store.mutate(commitment, {"status": "WITHDRAWN"})
        return envelope.object_response(store.serialize(commitment))

    subscription = store.subscriptions.get(commitment.get("subscription_id"))
    if subscription is None or subscription["contract_status"] not in (
        "PENDING_ACTIVATION", "ACTIVE"
    ):
        raise ApiError("ERR_COMMITMENT_INVALID_STATE")

    member = store.members[commitment["member_id"]]
    price = commitment.get("tier_price_cents") or 0
    store.mutate(commitment, {"status": "WITHDRAWN", "tier_price_cents": None})
    services.apply_ledger_delta(member, -price)
    return envelope.object_response(store.serialize(commitment))
