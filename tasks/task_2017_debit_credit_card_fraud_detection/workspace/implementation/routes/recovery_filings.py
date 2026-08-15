"""RecoveryFiling endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("recovery_filings", __name__)

VALID_OUTCOMES = {"ACCEPTED", "REJECTED", "PAID", "REVERSED"}


@bp.route("/fraudops/recovery-filings", methods=["POST"])
def create_filing():
    user_id, _ = middleware.require_role("RecoverySpecialist")
    body = request.get_json(silent=True) or {}
    loss_entry_id = body.get("loss_entry_id")
    network_reference = body.get("network_reference")
    claimed_cents = body.get("claimed_cents")

    if not isinstance(loss_entry_id, str) or not loss_entry_id:
        raise errors.err_invalid_request("loss_entry_id is required")
    if not isinstance(network_reference, str) or not network_reference:
        raise errors.err_invalid_request("network_reference is required")
    if not isinstance(claimed_cents, int) or isinstance(claimed_cents, bool) or claimed_cents < 1:
        raise errors.err_invalid_request("claimed_cents must be >= 1")

    loss = db.loss_entries.get(loss_entry_id)
    if not loss:
        raise errors.err_not_found("LossEntry not found")

    for f in db.recovery_filings.values():
        if f["network_reference"] == network_reference:
            raise errors.err_invalid_request("network_reference already exists")

    if loss["loss_status"] not in ("FINALIZED", "PARTIALLY_RECOVERED"):
        raise errors.err_invalid_state("Loss must be FINALIZED or PARTIALLY_RECOVERED")

    # segregation of duties
    if loss.get("booked_by_user_id") == user_id:
        raise errors.err_segregation_of_duties("Filer must differ from loss booker")

    if claimed_cents > loss["outstanding_cents"]:
        raise errors.err_recovery_exceeds_outstanding()

    rec = middleware.stamp_new(
        {
            "loss_entry_id": loss_entry_id,
            "network_reference": network_reference,
            "claimed_cents": claimed_cents,
            "paid_cents": None,
            "filing_status": "FILED",
            "filed_by_user_id": user_id,
        }
    )
    db.recovery_filings[rec["id"]] = rec
    return response.success(domain.ser_filing(rec), status_code=201)


@bp.route("/fraudops/recovery-filings", methods=["GET"])
def list_filings():
    middleware.require_role("RecoverySpecialist", "LossAccountant", "FraudOpsManager")
    args = request.args
    items = sorted(db.recovery_filings.values(), key=lambda f: (f["created_at"], f["id"]))
    for key in ("loss_entry_id", "filing_status"):
        v = args.get(key)
        if v:
            items = [f for f in items if f.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_filing(f) for f in sliced], pagination=pg)


@bp.route("/fraudops/recovery-filings/<fid>", methods=["GET"])
def get_filing(fid):
    middleware.require_role("RecoverySpecialist", "LossAccountant", "FraudOpsManager")
    f = db.recovery_filings.get(fid)
    if not f:
        raise errors.err_not_found("RecoveryFiling not found")
    return response.success(domain.ser_filing(f))


@bp.route("/fraudops/recovery-filings/<fid>/mark-outcome", methods=["POST"])
def mark_outcome(fid):
    middleware.require_role("RecoverySpecialist")
    f = db.recovery_filings.get(fid)
    if not f:
        raise errors.err_not_found("RecoveryFiling not found")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    paid_cents = body.get("paid_cents")
    if outcome not in VALID_OUTCOMES:
        raise errors.err_invalid_request("outcome must be ACCEPTED, REJECTED, PAID, or REVERSED")

    if outcome in ("ACCEPTED", "REJECTED"):
        if f["filing_status"] != "FILED":
            raise errors.err_invalid_state(f"Cannot mark {outcome} from {f['filing_status']}")
        f["filing_status"] = outcome
        middleware.touch(f)
    elif outcome == "PAID":
        if f["filing_status"] != "ACCEPTED":
            raise errors.err_invalid_state("Can only mark PAID from ACCEPTED")
        if paid_cents is None or not isinstance(paid_cents, int) or isinstance(paid_cents, bool) or paid_cents < 1:
            raise errors.err_invalid_request("paid_cents must be present and >= 1")
        loss = db.loss_entries[f["loss_entry_id"]]
        if paid_cents > f["claimed_cents"]:
            raise errors.err_recovery_exceeds_outstanding()
        if paid_cents > loss["outstanding_cents"]:
            raise errors.err_recovery_exceeds_outstanding()
        f["paid_cents"] = paid_cents
        f["filing_status"] = "PAID"
        middleware.touch(f)
        domain.recompute_loss_outstanding(loss)
    else:  # REVERSED
        if f["filing_status"] != "PAID":
            raise errors.err_invalid_state("Can only mark REVERSED from PAID")
        f["filing_status"] = "REVERSED"
        middleware.touch(f)
        loss = db.loss_entries[f["loss_entry_id"]]
        domain.recompute_loss_outstanding(loss)

    return response.success(domain.ser_filing(f))
