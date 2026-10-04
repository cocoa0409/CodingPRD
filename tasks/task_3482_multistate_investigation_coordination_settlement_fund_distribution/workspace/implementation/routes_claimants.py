"""Consumer restitution: claimant registration, validation, restitution compute."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import db
import envelope
import errors
import serialize
import services
import validate

bp = Blueprint("claimants", __name__, url_prefix="/multistate")


@bp.route("/settlements/<settlement_id>/claimants", methods=["POST"])
def register_claimant(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("FundAdministrator",))
    body = validate.body_json()
    state_code = validate.req_str(body, "state_code")
    contact_ref = validate.req_str(body, "contact_ref")
    claimed = validate.req_int(body, "claimed_loss_cents")
    if claimed <= 0:
        raise errors.invalid_request("claimed_loss_cents must be greater than zero")
    st = validate.get_settlement_or_404(settlement_id)
    if st["term_status"] != "EXECUTED":
        raise errors.invalid_state("Claimants may register only against an EXECUTED settlement")
    claim_deadline = st["executed_at"] + timedelta(days=calc.CLAIM_WINDOW_DAYS)
    if db.now() > claim_deadline:
        raise errors.ApiError(
            "ERR_CLAIM_WINDOW_CLOSED",
            422,
            "Claimant registration is past executed_at + CLAIM_WINDOW_DAYS",
        )
    claimant = db.new_entity(db.claimants)
    claimant.update(
        {
            "settlement_id": st["id"],
            "state_code": state_code,
            "contact_ref": contact_ref,
            "claimed_loss_cents": claimed,
            "validated_loss_cents": None,
            "estimated_payout_cents": None,
            "payout_cents": None,
            "status": "REGISTERED",
        }
    )
    return envelope.success_object(serialize.serialize("claimant", claimant), 201)


@bp.route("/settlements/<settlement_id>/claimants", methods=["GET"])
def list_claimants(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_settlement_or_404(settlement_id)
    items = [c for c in db.claimants.values() if c["settlement_id"] == settlement_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("claimant", page), limit, offset, total
    )


@bp.route("/claimants/<claimant_id>/validate", methods=["POST"])
def validate_claimant(claimant_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("FundAdministrator",))
    body = validate.body_json()
    decision = validate.req_enum(body, "decision", ("VALIDATED", "DENIED"))
    vloss = validate.opt_int(body, "validated_loss_cents")
    if decision == "VALIDATED" and vloss is None:
        raise errors.invalid_request("validated_loss_cents is required for a VALIDATED decision")
    claimant = validate.get_claimant_or_404(claimant_id)
    if claimant["status"] != "REGISTERED":
        raise errors.invalid_state("Claimant is not REGISTERED")
    if decision == "VALIDATED":
        if vloss <= 0 or vloss > claimant["claimed_loss_cents"]:
            raise errors.ApiError(
                "ERR_VALIDATION_EXCEEDS_CLAIM",
                422,
                "validated_loss_cents is not in (0, claimed_loss_cents]",
            )
        claimant["validated_loss_cents"] = vloss
        claimant["estimated_payout_cents"] = vloss
        claimant["status"] = "VALIDATED"
    else:
        claimant["status"] = "DENIED"
    db.touch(claimant)
    return envelope.success_object(serialize.serialize("claimant", claimant))


@bp.route("/settlements/<settlement_id>/restitution-compute", methods=["POST"])
def restitution_compute(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("FundAdministrator",))
    st = validate.get_settlement_or_404(settlement_id)
    if st["restitution_computed"]:
        raise errors.ApiError(
            "ERR_RESTITUTION_LOCKED", 409, "Restitution already computed for this settlement"
        )
    if st["executed_at"] is None:
        raise errors.invalid_state("Settlement has not been EXECUTED; no claim window exists")
    now = db.now()
    claim_deadline = st["executed_at"] + timedelta(days=calc.CLAIM_WINDOW_DAYS)
    if now <= claim_deadline:
        raise errors.ApiError(
            "ERR_CLAIM_WINDOW_CLOSED",
            422,
            "Restitution compute is lawful only strictly after the claim window",
        )
    # Phase 1 — appropriation reversion sweep (chronological requested_at ASC).
    cert_deadline = st["executed_at"] + timedelta(days=calc.APPROPRIATION_WINDOW_DAYS)
    lines_by_id = {l["id"]: l for l in services.settlement_lines(st["id"])}
    stale = [
        d
        for d in services.settlement_disbursements(st["id"])
        if d["status"] == "REQUESTED" and now > cert_deadline
    ]
    stale.sort(key=lambda d: (d["requested_at"], d["_seq"]))
    for disb in stale:
        disb["status"] = "REVERTED"
        db.touch(disb)
        line = lines_by_id[disb["allocation_line_id"]]
        line["reverted_cents"] += disb["amount_cents"]
        line["remaining_cents"] = (
            line["gross_share_cents"] - line["disbursed_cents"] - line["reverted_cents"]
        )
        if line["remaining_cents"] == 0 and line["status"] in ("ELIGIBLE", "DISBURSING"):
            line["status"] = "REVERTED"
        db.touch(line)
        st["reverted_cents"] += disb["amount_cents"]
        st["restitution_reserve_balance_cents"] += disb["amount_cents"]
    services.maybe_mark_fund_disbursed(st)
    # Phase 2 — lapse unvalidated claims, then pro-rate payouts.
    claims = [c for c in db.claimants.values() if c["settlement_id"] == st["id"]]
    claims.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for claimant in claims:
        if claimant["status"] == "REGISTERED":
            claimant["status"] = "LAPSED"
            db.touch(claimant)
    validated = [c for c in claims if c["status"] == "VALIDATED"]
    pool = st["restitution_reserve_balance_cents"]
    total_validated = sum(c["validated_loss_cents"] for c in validated)
    if validated and total_validated > pool:
        for claimant in validated:
            claimant["payout_cents"] = (
                pool * claimant["validated_loss_cents"]
            ) // total_validated
        leftover = pool - sum(c["payout_cents"] for c in validated)
        order = sorted(
            validated,
            key=lambda c: (-c["validated_loss_cents"], c["created_at"], c["_seq"]),
        )
        i = 0
        while leftover > 0:
            order[i % len(order)]["payout_cents"] += 1
            leftover -= 1
            i += 1
    else:
        for claimant in validated:
            claimant["payout_cents"] = claimant["validated_loss_cents"]
    for claimant in validated:
        claimant["status"] = "PAID"
        st["restitution_reserve_balance_cents"] -= claimant["payout_cents"]
        db.touch(claimant)
    st["restitution_remainder_cents"] = st["restitution_reserve_balance_cents"]
    st["restitution_computed"] = True
    db.touch(st)
    return envelope.success_object(serialize.serialize("settlement", st))
