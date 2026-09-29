"""MDU owner access agreements (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import listing
import serialize
import shape
from errors import ApiError
from store import bump, insert, must_find, new_row, now, ordered, rows

bp = Blueprint("mdu", __name__)

READ_ROLES = ("ProgramManager", "InstallCoordinator", "Subscriber", "MduOwner")


@bp.post("/mdu-agreements")
def create_agreement():
    auth.gate(("ProgramManager",))
    data = shape.body()
    address = listing.resolve(data, "service_address_id", "service_addresses")
    owner = listing.resolve(data, "owner_account_id", "accounts")
    shape.req_id(data, "service_address_id")
    shape.req_id(data, "owner_account_id")
    access_fee = shape.req_int(data, "access_fee_cents", 0)
    expires_at = shape.req_dt(data, "expires_at")
    max_counter_rounds = shape.opt_int(data, "max_counter_rounds", 0, 5, 2)
    if address["dwelling_type"] != "MDU":
        raise ApiError(
            "ERR_ADDRESS_LINKAGE_MISMATCH",
            "an access agreement requires an MDU address",
        )
    row = new_row(
        {
            "service_address_id": address["id"],
            "owner_account_id": owner["id"],
            "status": "DRAFT",
            "access_fee_cents": access_fee,
            "countered_fee_cents": None,
            "offer_round": 0,
            "counter_round": 0,
            "max_counter_rounds": max_counter_rounds,
            "expires_at": expires_at,
            "signed_at": None,
        }
    )
    insert("mdu_agreements", row)
    return envelope.created(serialize.mdu_agreement(row))


@bp.get("/mdu-agreements/<agreement_id>")
def read_agreement(agreement_id):
    auth.gate(READ_ROLES)
    row = must_find("mdu_agreements", agreement_id)
    cascades.expire_agreement(row)
    return envelope.ok(serialize.mdu_agreement(row))


@bp.get("/mdu-agreements")
def list_agreements():
    auth.gate(READ_ROLES)
    items = ordered(rows("mdu_agreements"))
    for row in items:
        cascades.expire_agreement(row)
    items = listing.apply_filters(
        items,
        (
            listing.fk("service_address_id", "service_address_id", "service_addresses"),
            listing.fk("owner_account_id", "owner_account_id", "accounts"),
            listing.enum("status", "status", calc.MDU_STATUSES),
        ),
    )
    return envelope.list_response(items, serialize.mdu_agreement)


@bp.post("/mdu-agreements/<agreement_id>/offers")
def send_offer(agreement_id):
    auth.gate(("ProgramManager",))
    agreement = must_find("mdu_agreements", agreement_id)
    data = shape.body()
    access_fee = shape.req_int(data, "access_fee_cents", 0)
    cascades.expire_agreement(agreement)
    if agreement["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError(
            "ERR_MDU_AGREEMENT_STATE_INVALID",
            "an offer may only be sent from DRAFT or COUNTERED",
        )
    if now() >= agreement["expires_at"]:
        raise ApiError("ERR_MDU_AGREEMENT_STATE_INVALID", "this negotiation has expired")
    agreement["status"] = "SENT"
    agreement["access_fee_cents"] = access_fee
    agreement["offer_round"] += 1
    bump(agreement)
    return envelope.ok(serialize.mdu_agreement(agreement))


@bp.post("/mdu-agreements/<agreement_id>/owner-response")
def owner_response(agreement_id):
    user_id, role = auth.gate(("MduOwner",))
    agreement = must_find("mdu_agreements", agreement_id)
    auth.own(user_id, role, agreement["owner_account_id"], roles=("MduOwner",))
    data = shape.body()
    response = shape.req_enum(data, "response", calc.OWNER_RESPONSES)
    countered_fee = shape.opt_int(data, "countered_fee_cents", 0)
    if response == "COUNTER" and countered_fee is None:
        shape.bad("countered_fee_cents", "is required for a counter")
    cascades.expire_agreement(agreement)
    status = agreement["status"]
    if response == "COUNTER":
        if status != "SENT":
            raise ApiError(
                "ERR_MDU_AGREEMENT_STATE_INVALID", "a counter is only admissible from SENT"
            )
        if agreement["counter_round"] >= agreement["max_counter_rounds"]:
            raise ApiError("ERR_COUNTER_LIMIT_REACHED", "the counter allowance is exhausted")
        agreement["status"] = "COUNTERED"
        agreement["countered_fee_cents"] = countered_fee
        agreement["counter_round"] += 1
        bump(agreement)
    else:
        if status not in ("SENT", "COUNTERED"):
            raise ApiError(
                "ERR_MDU_AGREEMENT_STATE_INVALID",
                "the owner may only respond to a standing offer",
            )
        if response == "SIGN":
            agreement["status"] = "SIGNED"
            agreement["signed_at"] = now()
            bump(agreement)
            cascades.sign_cascade(agreement)
        else:
            agreement["status"] = "DECLINED"
            bump(agreement)
            cascades.withdrawn_cascade(agreement)
    return envelope.ok(serialize.mdu_agreement(agreement))
