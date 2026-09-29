"""Payment releases: withholding, the queue-or-release fork, and reversal."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import lookup
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("releases", __name__)

RELEASE_KINDS = ["DELIVERABLE_PAYOUT", "CONTRACT_ADVANCE"]
RELEASE_STATUSES = ["QUEUED", "RELEASED", "REVERSED", "VOIDED"]
WITHHOLDING_BASES = ["NONE", "BACKUP", "NRA_STATUTORY"]
REVERSAL_REASONS = ["ERRONEOUS_PAYMENT", "CLAWBACK"]


@bp.route("/nil/payment-releases", methods=["POST"])
def create_release():
    _, user_id = auth.authenticate([auth.TREASURY_OFFICER])
    body = shape.body()
    contract_id = shape.string_field(body, "deal_contract_id", required=True)
    release_kind = shape.enum_field(body, "release_kind", RELEASE_KINDS, required=True)
    requested = shape.int_field(body, "requested_amount_cents", required=True, positive=True)
    expected = shape.int_field(body, "expected_deal_contract_version", required=True)
    deliverable_id = shape.string_field(body, "deliverable_id")
    if release_kind == "DELIVERABLE_PAYOUT":
        if deliverable_id is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "deliverable_id is required when release_kind is DELIVERABLE_PAYOUT.")
    elif deliverable_id is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "deliverable_id must be absent when release_kind is CONTRACT_ADVANCE.")

    contract = lookup.deal_contract(contract_id)
    deliverable = lookup.deliverable(deliverable_id) if deliverable_id is not None else None

    if deliverable is not None and deliverable["deal_contract_id"] != contract["id"]:
        raise ApiError("ERR_DELIVERABLE_CONTRACT_MISMATCH")

    if contract["lifecycle_status"] in derive.TERMINAL_LIFECYCLE:
        raise ApiError("ERR_CONTRACT_TERMINAL")
    if contract["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")

    if deliverable is not None and deliverable["verified_by_user_id"] is not None:
        if deliverable["verified_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    collective = store.collectives.get(contract["collective_id"])
    if collective is not None and collective["funding_posture"] == "FROZEN":
        raise ApiError("ERR_COLLECTIVE_FUNDING_FROZEN")

    if deliverable is not None and deliverable["status"] not in ("VERIFIED", "WAIVED"):
        raise ApiError("ERR_DELIVERABLE_NOT_VERIFIED")

    if requested + derive.contract_released_total(contract) > contract["total_value_cents"]:
        raise ApiError("ERR_RELEASE_EXCEEDS_CONTRACT_VALUE")

    designation = contract["funding_designation"]
    if not derive.has_settled_designation(contract["collective_id"], designation):
        raise ApiError("ERR_FUNDING_DESIGNATION_MISMATCH")
    if requested > derive.designated_pool(contract["collective_id"], designation):
        raise ApiError("ERR_INSUFFICIENT_DESIGNATED_FUNDS")

    athlete = store.athletes.get(contract["athlete_id"])
    if athlete is not None and athlete["tax_person_kind"] == "NONRESIDENT_ALIEN":
        if athlete["taxpayer_doc_on_file"] != "W8BEN":
            raise ApiError("ERR_TAXPAYER_DOC_REQUIRED")

    if deliverable is not None:
        eligible = derive.deliverable_payout_eligible(deliverable, contract)
        if requested > eligible:
            raise ApiError("ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE")

    basis, withheld = calc.withholding(
        requested,
        athlete["tax_person_kind"] if athlete is not None else "US_PERSON",
        athlete["taxpayer_doc_on_file"] if athlete is not None else "NONE",
        athlete["treaty_exempt_claimed"] if athlete is not None else False)

    now = clock.now()
    row = {
        "id": store.new_id(),
        "deal_contract_id": contract["id"],
        "deliverable_id": deliverable["id"] if deliverable is not None else None,
        "release_kind": release_kind,
        "requested_amount_cents": requested,
        "withholding_basis": basis,
        "withholding_amount_cents": withheld,
        "net_payable_cents": requested - withheld,
        "status": "QUEUED",
        "initiated_by_user_id": user_id,
        "released_at": None,
        "reversal_reason": "NONE",
        "sequence_no": store.next_seq("payment_release"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.payment_releases[row["id"]] = row
    derive.bump(contract)

    if athlete is not None and athlete["eligibility_status"] == "ENROLLED":
        derive.release_payment(row, contract, collective)
    return envelope.object_response(serialize.payment_release(row), 201)


@bp.route("/nil/payment-releases/<release_id>", methods=["GET"])
def read_release(release_id):
    auth.authenticate(auth.ALL_ROLES)
    row = lookup.payment_release(release_id)
    return envelope.object_response(serialize.payment_release(row))


@bp.route("/nil/payment-releases", methods=["GET"])
def list_releases():
    auth.authenticate(auth.ALL_ROLES)
    limit, offset = envelope.read_pagination(request.args)
    contract_id = envelope.id_filter(request.args, "deal_contract_id")
    deliverable_id = envelope.id_filter(request.args, "deliverable_id")
    status = envelope.enum_filter(request.args, "status", RELEASE_STATUSES)
    kind = envelope.enum_filter(request.args, "release_kind", RELEASE_KINDS)
    basis = envelope.enum_filter(request.args, "withholding_basis", WITHHOLDING_BASES)
    rows = store.ordered(store.payment_releases.values())
    if contract_id is not None:
        rows = [r for r in rows if r["deal_contract_id"] == contract_id]
    if deliverable_id is not None:
        rows = [r for r in rows if r["deliverable_id"] == deliverable_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if kind is not None:
        rows = [r for r in rows if r["release_kind"] == kind]
    if basis is not None:
        rows = [r for r in rows if r["withholding_basis"] == basis]
    return envelope.list_response([serialize.payment_release(r) for r in rows], limit, offset)


@bp.route("/nil/payment-releases/<release_id>/reversals", methods=["POST"])
def reverse_release(release_id):
    auth.authenticate([auth.TREASURY_OFFICER])
    body = shape.body()
    reason = shape.enum_field(body, "reversal_reason", REVERSAL_REASONS, required=True)
    release = lookup.payment_release(release_id)

    if release["status"] != "RELEASED":
        raise ApiError("ERR_RELEASE_NOT_RELEASED")
    if clock.tax_year(release["released_at"]) != clock.tax_year():
        raise ApiError("ERR_REVERSAL_ACROSS_TAX_YEARS")

    release["status"] = "REVERSED"
    release["reversal_reason"] = reason
    derive.touch(release)

    contract = store.deal_contracts.get(release["deal_contract_id"])
    if contract is not None:
        derive.bump(contract)
        derive.resync_payment_status(contract)
        collective = store.collectives.get(contract["collective_id"])
        if collective is not None:
            derive.sync_collective(collective)
    return envelope.object_response(serialize.payment_release(release))
