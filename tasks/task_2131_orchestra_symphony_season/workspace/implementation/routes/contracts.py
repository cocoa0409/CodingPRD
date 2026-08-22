"""Guest artist and conductor contracts (a genuinely cyclic negotiation)."""

from flask import Blueprint, request

from db import db
from domain import (base_fields, recompute_readiness, serialize, touch,
                    try_promote_lock)
from errors import raise_err
from middleware import endpoint, own
from response import ok, ok_list
from validate import (body, check_body_fks, paginate, req_enum, req_int,
                      req_str)

bp = Blueprint("contracts", __name__)

ROLE_TYPES = ("SOLOIST", "CONDUCTOR")


def get_contract_or_404(contract_id):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise_err("ERR_CONTRACT_NOT_FOUND")
    return contract


@bp.route("/orchestra/guest-contracts", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def create_contract():
    data = body()
    check_body_fks(data, ["concert_id"])
    concert = db.concerts.get(data.get("concert_id"))
    if concert is None:
        req_str(data, "concert_id")
        raise_err("ERR_CONCERT_NOT_FOUND")

    artist_name = req_str(data, "artist_name")
    role_type = req_enum(data, "role_type", ROLE_TYPES)
    offered_fee = req_int(data, "offered_fee_cents", minv=0)

    contract = base_fields()
    contract.update({
        "concert_id": concert["id"],
        "artist_name": artist_name,
        "role_type": role_type,
        "offered_fee_cents": offered_fee,
        "countered_fee_cents": None,
        "agreed_fee_cents": None,
        "negotiation_round": 1,
        "status": "OFFERED",
    })
    db.contracts[contract["id"]] = contract
    return ok(serialize(contract), 201)


@bp.route("/orchestra/guest-contracts/<contract_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "GuestArtist"])
def read_contract(contract_id):
    return ok(serialize(get_contract_or_404(contract_id)))


@bp.route("/orchestra/guest-contracts", methods=["GET"])
@endpoint(["ArtisticAdmin", "GuestArtist"])
def list_contracts():
    concert_id = request.args.get("concert_id")
    status = request.args.get("status")
    records = []
    for contract in db.contracts.values():
        if concert_id is not None and contract["concert_id"] != concert_id:
            continue
        if status is not None and contract["status"] != status:
            continue
        records.append(contract)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/guest-contracts/<contract_id>/counter", methods=["POST"])
@endpoint(["GuestArtist"])
def counter_contract(contract_id):
    contract = get_contract_or_404(contract_id)            # rung 3
    own(contract["id"], "GuestArtist")                     # rung 5
    data = body()
    countered_fee = req_int(data, "countered_fee_cents", minv=0)   # rung 6
    if contract["status"] != "OFFERED":                    # rung 7
        raise_err("ERR_CONTRACT_NOT_NEGOTIABLE")

    with touch(contract):
        contract["status"] = "COUNTERED"
        contract["countered_fee_cents"] = countered_fee

    concert = db.concerts.get(contract["concert_id"])
    if concert is not None:
        with touch(concert):
            recompute_readiness(concert)
    return ok(serialize(contract))


@bp.route("/orchestra/guest-contracts/<contract_id>/revise-offer", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def revise_offer(contract_id):
    contract = get_contract_or_404(contract_id)
    data = body()
    offered_fee = req_int(data, "offered_fee_cents", minv=0)      # rung 6
    if contract["status"] != "COUNTERED":                         # rung 7
        raise_err("ERR_CONTRACT_NOT_NEGOTIABLE")
    if contract["negotiation_round"] >= 3:                        # rung 16
        raise_err("ERR_NEGOTIATION_ROUND_LIMIT")

    with touch(contract):
        contract["status"] = "OFFERED"
        contract["offered_fee_cents"] = offered_fee
        contract["negotiation_round"] += 1
    return ok(serialize(contract))


@bp.route("/orchestra/guest-contracts/<contract_id>/sign", methods=["POST"])
@endpoint(["ArtisticAdmin", "GuestArtist"])
def sign_contract(contract_id):
    contract = get_contract_or_404(contract_id)            # rung 3
    own(contract["id"], "GuestArtist")                     # rung 5
    if contract["status"] not in ("OFFERED", "COUNTERED"):  # rung 7
        raise_err("ERR_CONTRACT_NOT_NEGOTIABLE")
    concert = db.concerts.get(contract["concert_id"])
    if concert is None or concert["programming_status"] not in ("PROGRAMMED", "LOCKED"):
        raise_err("ERR_CONCERT_NOT_PROGRAMMED")            # rung 8

    from_state = contract["status"]
    with touch(contract):
        if from_state == "OFFERED":
            contract["agreed_fee_cents"] = contract["offered_fee_cents"]
        else:
            contract["agreed_fee_cents"] = contract["countered_fee_cents"]
        contract["status"] = "SIGNED"

    with touch(concert):
        try_promote_lock(concert)
        recompute_readiness(concert)
    return ok(serialize(contract))
