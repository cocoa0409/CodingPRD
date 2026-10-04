"""Allocation lines (reads) and disbursements (request, certify, release)."""
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

bp = Blueprint("lines_disbursements", __name__, url_prefix="/multistate")

AG_ROLES = ("ParticipatingStateAG", "LeadStateAG")
USE_CODES = ("PROGRAM", "GENERAL_FUND", "RESTITUTION_ADMIN")


@bp.route("/allocation-lines/<line_id>", methods=["GET"])
def get_allocation_line(line_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    line = validate.get_line_or_404(line_id)
    return envelope.success_object(serialize.serialize("line", line))


@bp.route("/settlements/<settlement_id>/allocation-lines", methods=["GET"])
def list_settlement_lines(settlement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_settlement_or_404(settlement_id)
    items = services.settlement_lines(settlement_id)
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(serialize.serialize_list("line", page), limit, offset, total)


@bp.route("/allocation-lines/<line_id>/disbursements", methods=["POST"])
def create_disbursement(line_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, AG_ROLES)
    body = validate.body_json()
    amount = validate.req_int(body, "amount_cents")
    use_code = validate.req_enum(body, "use_code", USE_CODES)
    line = validate.get_line_or_404(line_id)
    # Rung 5: office-ownership.
    auth.require_own_office(line, uid)
    st = db.settlements.get(line["settlement_id"])
    office = db.offices.get(line["state_office_id"])
    # Rung 6: state gates.
    if line["status"] not in ("ELIGIBLE", "DISBURSING"):
        raise errors.ApiError(
            "ERR_LINE_NOT_DISBURSABLE", 409, "Allocation line is not ELIGIBLE or DISBURSING"
        )
    if st is None or st["fund_status"] not in ("PARTIALLY_FUNDED", "FUNDED", "DISBURSING"):
        raise errors.ApiError(
            "ERR_SETTLEMENT_NOT_FUNDED", 409, "Settlement fund is not at least partially funded"
        )
    # Rung 8: compliance hold.
    if st["compliance_hold"]:
        raise errors.ApiError(
            "ERR_COMPLIANCE_HOLD_ACTIVE", 409, "Compliance hold blocks disbursement creation"
        )
    # Rung 12: fiscal bounds.
    if amount <= 0 or amount > line["remaining_cents"]:
        raise errors.ApiError(
            "ERR_AMOUNT_EXCEEDS_REMAINING",
            422,
            "Disbursement amount is not in (0, line.remaining_cents]",
        )
    if (
        office is not None
        and office["appropriation_rule"] == "GENERAL_FUND_ONLY"
        and use_code != "GENERAL_FUND"
    ):
        raise errors.ApiError(
            "ERR_USE_CODE_NOT_PERMITTED",
            422,
            "GENERAL_FUND_ONLY offices may only request use_code GENERAL_FUND",
        )
    now = db.now()
    auto_certified = office is not None and office["appropriation_rule"] == "PREAPPROPRIATED"
    disb = db.new_entity(db.disbursements)
    disb.update(
        {
            "allocation_line_id": line["id"],
            "amount_cents": amount,
            "use_code": use_code,
            "status": "CERTIFIED" if auto_certified else "REQUESTED",
            "requested_at": now,
            "certified_at": now if auto_certified else None,
            "released_at": None,
        }
    )
    if line["status"] == "ELIGIBLE":
        line["status"] = "DISBURSING"
        db.touch(line)
    return envelope.success_object(serialize.serialize("disbursement", disb), 201)


@bp.route("/allocation-lines/<line_id>/disbursements", methods=["GET"])
def list_line_disbursements(line_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_line_or_404(line_id)
    items = [d for d in db.disbursements.values() if d["allocation_line_id"] == line_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("disbursement", page), limit, offset, total
    )


@bp.route("/disbursements/<disbursement_id>/certify", methods=["POST"])
def certify_disbursement(disbursement_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, ("StateLegislature",))
    disb = validate.get_disbursement_or_404(disbursement_id)
    line = db.lines.get(disb["allocation_line_id"])
    # Rung 5: the legislature certifies for its own state only.
    auth.require_own_office(line, uid)
    if disb["status"] != "REQUESTED":
        raise errors.invalid_state("Disbursement is not REQUESTED")
    st = db.settlements.get(line["settlement_id"]) if line is not None else None
    deadline = st["executed_at"] + timedelta(days=calc.APPROPRIATION_WINDOW_DAYS)
    if db.now() > deadline:
        raise errors.ApiError(
            "ERR_CERTIFICATION_WINDOW_CLOSED",
            422,
            "Certification attempted after executed_at + APPROPRIATION_WINDOW_DAYS",
        )
    disb["status"] = "CERTIFIED"
    disb["certified_at"] = db.now()
    db.touch(disb)
    return envelope.success_object(serialize.serialize("disbursement", disb))


@bp.route("/disbursements/<disbursement_id>/release", methods=["POST"])
def release_disbursement(disbursement_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("FundAdministrator",))
    disb = validate.get_disbursement_or_404(disbursement_id)
    line = db.lines.get(disb["allocation_line_id"])
    st = db.settlements.get(line["settlement_id"]) if line is not None else None
    if disb["status"] != "CERTIFIED":
        raise errors.invalid_state("Disbursement is not CERTIFIED")
    if st is not None and st["compliance_hold"]:
        raise errors.ApiError(
            "ERR_COMPLIANCE_HOLD_ACTIVE", 409, "Compliance hold blocks disbursement release"
        )
    amount = disb["amount_cents"]
    if st["deposited_cents"] - st["released_cents"] < amount:
        raise errors.ApiError(
            "ERR_INSUFFICIENT_FUND_BALANCE",
            422,
            "Release exceeds the settlement's undisbursed deposited balance",
        )
    now = db.now()
    disb["status"] = "RELEASED"
    disb["released_at"] = now
    db.touch(disb)
    st["released_cents"] += amount
    line["disbursed_cents"] += amount
    line["remaining_cents"] = (
        line["gross_share_cents"] - line["disbursed_cents"] - line["reverted_cents"]
    )
    if line["disbursed_cents"] == line["gross_share_cents"]:
        line["status"] = "DISBURSED"
    db.touch(line)
    if st["fund_status"] in ("FUNDED", "PARTIALLY_FUNDED"):
        st["fund_status"] = "DISBURSING"
    services.maybe_mark_fund_disbursed(st)
    db.touch(st)
    return envelope.success_object(serialize.serialize("disbursement", disb))
