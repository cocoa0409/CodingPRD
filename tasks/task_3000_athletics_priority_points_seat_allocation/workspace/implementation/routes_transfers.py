"""Point transfers between donors (PRD section 3.6)."""
from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid, invalid_state
from store import DB, check_version, get_body_ref, get_path, new_row, touch

bp = Blueprint("transfers", __name__)


def _check_amount_ceilings(transfer, source):
    """PRD section 2.8 step 26, re-checked at approval as well as at creation."""
    amount = num.dec(transfer["points_amount"])
    if amount > num.dec(transfer["max_transferable_points"]):
        raise err("ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE",
                  "'points_amount' exceeds max_transferable_points")
    if amount > num.dec(source["certified_points"]):
        raise err("ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE",
                  "'points_amount' exceeds the source donor's certified_points")


@bp.post("/athletics/point-transfers")
def create_transfer():
    auth.require(auth.OFFICE)
    body = v.body_dict()
    source_id = v.id_field(body, "source_donor_id")
    recipient_id = v.id_field(body, "recipient_donor_id")
    basis = v.enum_field(body, "basis", enums.TRANSFER_BASES)
    amount = v.num_field(body, "points_amount", exclusive_minimum=0)
    expected = v.version_field(body, "expected_source_donor_version")
    if source_id == recipient_id:
        raise invalid("'recipient_donor_id' must differ from 'source_donor_id'")
    source = get_body_ref("donor", source_id)
    recipient = get_body_ref("donor", recipient_id)
    check_version(source, expected, "source donor")
    cap = calc.transfer_pct_cap(basis)
    max_points = calc.max_transferable_points(source, basis)
    holds = calc.basis_precondition_holds(basis, source, recipient["id"])
    row = new_row(
        source_donor_id=source["id"],
        recipient_donor_id=recipient["id"],
        basis=basis,
        points_amount=amount,
        status="REQUESTED" if holds else "EXCEPTION_PENDING",
        transfer_pct_cap=cap,
        max_transferable_points=max_points,
        exception_required=not holds,
        exception_granted_by_user_id=None,
        approved_by_user_id=None,
        decision_note=None,
        reversed_at=None,
    )
    _check_amount_ceilings(row, source)
    DB.transfers[row["id"]] = row
    touch(source)
    return envelope.created(serial.transfer(row))


@bp.post("/athletics/point-transfers/<transfer_id>/policy-decision")
def decide_transfer_policy(transfer_id):
    caller = auth.require(auth.COMMITTEE_ONLY)
    transfer = get_path("transfer", transfer_id)
    body = v.body_dict()
    decision = v.enum_field(body, "decision", enums.POLICY_DECISIONS)
    note = v.str_field(body, "note", min_len=1, max_len=None)
    status = transfer["status"]
    if decision == "GRANT":
        if status != "EXCEPTION_PENDING":
            raise invalid_state(
                "only a transfer in EXCEPTION_PENDING may be granted an exception")
        transfer["status"] = "REQUESTED"
        transfer["exception_granted_by_user_id"] = caller.user_id
    else:
        if status not in ("EXCEPTION_PENDING", "REQUESTED"):
            raise invalid_state(
                "only a transfer in EXCEPTION_PENDING or REQUESTED may be refused")
        transfer["status"] = "DENIED"
    transfer["decision_note"] = note
    touch(transfer)
    return envelope.ok(serial.transfer(transfer))


@bp.post("/athletics/point-transfers/<transfer_id>/approve")
def approve_transfer(transfer_id):
    caller = auth.require(auth.CERTIFIER_ONLY)
    transfer = get_path("transfer", transfer_id)
    v.body_dict()
    status = transfer["status"]
    if status == "EXCEPTION_PENDING":
        raise err("ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED",
                  "this transfer needs a policy exception before it may be approved")
    if status != "REQUESTED":
        raise invalid_state("only a transfer in REQUESTED may be approved")
    source = DB.donors.get(transfer["source_donor_id"])
    recipient = DB.donors.get(transfer["recipient_donor_id"])
    _check_amount_ceilings(transfer, source)
    amount = num.dec(transfer["points_amount"])
    recipient["transferred_points_in"] = num.round2(
        num.dec(recipient["transferred_points_in"]) + amount)
    source["transferred_points_out"] = num.round2(
        num.dec(source["transferred_points_out"]) + amount)
    transfer["status"] = "APPROVED"
    transfer["approved_by_user_id"] = caller.user_id
    derive.recompute_certified_points(source)
    derive.recompute_certified_points(recipient)
    touch(source)
    touch(recipient)
    touch(transfer)
    return envelope.ok(serial.transfer(transfer))


@bp.post("/athletics/point-transfers/<transfer_id>/reverse")
def reverse_transfer(transfer_id):
    auth.require(auth.CERTIFIER_ONLY)
    transfer = get_path("transfer", transfer_id)
    body = v.body_dict()
    reason = v.str_field(body, "reason", min_len=1, max_len=None)
    if transfer["status"] != "APPROVED":
        raise invalid_state("only an APPROVED transfer may be reversed")
    source = DB.donors.get(transfer["source_donor_id"])
    recipient = DB.donors.get(transfer["recipient_donor_id"])
    amount = num.dec(transfer["points_amount"])
    recipient["transferred_points_in"] = num.round2(
        num.dec(recipient["transferred_points_in"]) - amount)
    source["transferred_points_out"] = num.round2(
        num.dec(source["transferred_points_out"]) - amount)
    transfer["status"] = "REVERSED"
    transfer["reversed_at"] = clock.now()
    transfer["decision_note"] = reason
    derive.recompute_certified_points(source)
    derive.recompute_certified_points(recipient)
    touch(source)
    touch(recipient)
    touch(transfer)
    return envelope.ok(serial.transfer(transfer))
