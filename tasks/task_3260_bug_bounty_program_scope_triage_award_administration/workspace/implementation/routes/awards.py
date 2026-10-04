"""Award endpoints: propose, read/list, approve, pay, void."""
from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_BOUNTY_ALREADY_EXISTS, ERR_AWARD_AMOUNT_CAP, ERR_POOL_EXHAUSTED,
    ERR_AWARD_NOT_PAYABLE, ERR_SANCTIONED_COUNTRY, ERR_TAX_DOC_REQUIRED,
    ERR_REPORT_NOT_RESOLVED,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import award_out
from services import calculations as calc

bp = Blueprint("awards", __name__)

CREATE_FIELDS = {"report_id", "award_type", "amount_cents"}
AWARD_TYPES = {"BOUNTY", "BONUS", "RETEST"}
SANCTIONED = {"KP", "IR", "CU", "SY"}
TAX_BLOCK_THRESHOLD = 60000


def _get_award(aid):
    a = db.awards.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Award {aid} not found")
    return a


def _program_of(award):
    report = db.reports[award["report_id"]]
    return db.programs[report["program_id"]]


@bp.route("/api/awards", methods=["POST"])
def propose_award():
    require_roles({"Triager"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["report_id", "award_type"])
    report = db.reports.get(body["report_id"])
    if report is None:
        raise_err(ERR_NOT_FOUND, f"Report {body['report_id']} not found")
    award_type = body["award_type"]
    if award_type not in AWARD_TYPES:
        raise_err(ERR_INVALID_REQUEST, "Invalid award_type")
    program = db.programs[report["program_id"]]

    amount = None
    capped = False
    if award_type == "BOUNTY":
        if report["status"] not in ("VALIDATED", "RESOLVED"):
            raise_err(ERR_INVALID_STATE, "BOUNTY requires a VALIDATED or RESOLVED report")
        if report["severity_final"] == "NONE":
            raise_err(ERR_INVALID_STATE, "BOUNTY requires severity_final != NONE")
        for a in db.awards.values():
            if (a["report_id"] == report["id"] and a["award_type"] == "BOUNTY"
                    and a["status"] != "VOID"):
                raise_err(ERR_BOUNTY_ALREADY_EXISTS, "A non-VOID BOUNTY already exists")
        available = (program["bounty_pool_cents"] - program["bounty_reserved_cents"]
                     - program["bounty_paid_cents"])
        asset = db.assets[report["asset_id"]]
        amount, capped = calc.bounty_amount(
            report["severity_final"], asset["criticality"],
            bool(report["is_first_validated_report"]),
            program["first_report_bonus_pct"],
            report["tier_at_validation"], available,
        )
    elif award_type == "BONUS":
        if "amount_cents" not in body or body["amount_cents"] is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field: amount_cents")
        if isinstance(body["amount_cents"], bool) or not isinstance(body["amount_cents"], int):
            raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer")
        amount = body["amount_cents"]
        if amount > program["bonus_cap_cents"]:
            raise_err(ERR_AWARD_AMOUNT_CAP, "BONUS exceeds program bonus_cap_cents")
    else:  # RETEST
        if report["status"] != "RESOLVED":
            raise_err(ERR_REPORT_NOT_RESOLVED, "RETEST requires a RESOLVED report")
        for a in db.awards.values():
            if (a["report_id"] == report["id"] and a["award_type"] == "RETEST"
                    and a["status"] != "VOID"):
                raise_err(ERR_INVALID_STATE, "A non-VOID RETEST already exists")
        amount = program["retest_award_cents"]

    a = base_entity()
    a.update(
        {
            "report_id": report["id"],
            "researcher_id": report["researcher_id"],
            "award_type": award_type,
            "status": "PROPOSED",
            "amount_cents": amount,
            "capped_by_pool": capped,
            "block_reason": None,
            "withheld_cents": 0,
            "net_paid_cents": 0,
            "proposed_at": clock.iso_now(),
            "approved_at": None,
            "paid_at": None,
        }
    )
    db.awards[a["id"]] = a
    return success_object(award_out(a), 201)


@bp.route("/api/awards/<award_id>", methods=["GET"])
def read_award(award_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(award_out(_get_award(award_id)))


@bp.route("/api/awards", methods=["GET"])
def list_awards():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.awards.values())
    for f in ("report_id", "researcher_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [a for a in items if str(a.get(f)) == val]
    items.sort(key=lambda a: a["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([award_out(a) for a in page], limit, offset, total)


@bp.route("/api/awards/<award_id>/approve", methods=["POST"])
def approve_award(award_id):
    require_roles({"ProgramAdmin"})
    a = _get_award(award_id)
    if a["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, f"Cannot approve award in {a['status']}")
    program = _program_of(a)
    if (program["bounty_reserved_cents"] + a["amount_cents"]
            > program["bounty_pool_cents"] - program["bounty_paid_cents"]):
        raise_err(ERR_POOL_EXHAUSTED, "Insufficient pool to reserve this award")
    program["bounty_reserved_cents"] += a["amount_cents"]
    touch(program)
    a["status"] = "APPROVED"
    a["approved_at"] = clock.iso_now()
    touch(a)
    return success_object(award_out(a))


@bp.route("/api/awards/<award_id>/pay", methods=["POST"])
def pay_award(award_id):
    require_roles({"PlatformAdmin"})
    a = _get_award(award_id)
    if a["status"] == "PROPOSED":
        raise_err(ERR_AWARD_NOT_PAYABLE, "Award must be APPROVED before payment")
    if a["status"] not in ("APPROVED", "BLOCKED"):
        raise_err(ERR_INVALID_STATE, f"Cannot pay award in {a['status']}")
    program = _program_of(a)
    researcher = db.researchers[a["researcher_id"]]

    if a["status"] == "BLOCKED":
        # Retry traverses the same payment path (PRD §3.9): sanctions are
        # screened first and have no cure path, so a sanction-blocked retry
        # surfaces ERR_SANCTIONED_COUNTRY again. Only a TAX_DOCUMENT block
        # may be cured (tax_document_status SUBMITTED or VERIFIED).
        if a["block_reason"] == "SANCTIONED_COUNTRY":
            raise_err(ERR_SANCTIONED_COUNTRY, "Researcher resident in a sanctioned country")
        if a["block_reason"] != "TAX_DOCUMENT":
            raise_err(ERR_INVALID_STATE, "Award block cannot be retried")
        if researcher["tax_document_status"] not in ("SUBMITTED", "VERIFIED"):
            raise_err(ERR_TAX_DOC_REQUIRED, "Tax document still missing")
        # cured: fall through to payment

    # sanctions first
    if researcher["country_code"] in SANCTIONED:
        if a["status"] == "APPROVED":
            a["status"] = "BLOCKED"
            a["block_reason"] = "SANCTIONED_COUNTRY"
            touch(a)
        raise_err(ERR_SANCTIONED_COUNTRY, "Researcher resident in a sanctioned country")
    # tax gate
    if (researcher["tax_document_status"] == "MISSING"
            and a["amount_cents"] >= TAX_BLOCK_THRESHOLD):
        if a["status"] == "APPROVED":
            a["status"] = "BLOCKED"
            a["block_reason"] = "TAX_DOCUMENT"
            touch(a)
        raise_err(ERR_TAX_DOC_REQUIRED, "Tax document required for this amount")

    withheld, net = calc.withholding(
        a["amount_cents"], researcher["tax_document_status"], researcher["country_code"]
    )
    a["withheld_cents"] = withheld
    a["net_paid_cents"] = net
    a["status"] = "PAID"
    a["block_reason"] = None
    a["paid_at"] = clock.iso_now()
    touch(a)
    program["bounty_reserved_cents"] -= a["amount_cents"]
    program["bounty_paid_cents"] += a["amount_cents"]
    program["total_withheld_cents"] += withheld
    touch(program)
    return success_object(award_out(a))


@bp.route("/api/awards/<award_id>/void", methods=["POST"])
def void_award(award_id):
    require_roles({"ProgramAdmin"})
    a = _get_award(award_id)
    if a["status"] not in ("PROPOSED", "APPROVED"):
        raise_err(ERR_INVALID_STATE, f"Cannot void award in {a['status']}")
    if a["status"] == "APPROVED":
        program = _program_of(a)
        program["bounty_reserved_cents"] -= a["amount_cents"]
        touch(program)
    a["status"] = "VOID"
    touch(a)
    return success_object(award_out(a))
