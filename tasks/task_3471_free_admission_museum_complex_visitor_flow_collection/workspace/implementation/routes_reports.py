"""Condition reports (PRD 3.5): file (superseding a prior DISPUTED report of
the same kind), list, read, decide."""

from flask import Blueprint

import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("condition_reports", __name__)

REPORT_FILE_ROLES = ["LoansOfficer", "BorrowerRep"]
REPORT_READ_ROLES = ["PlatformAdmin", "Registrar", "LoansOfficer", "BorrowerRep"]


@bp.post("/campus/loan-agreements/<lid>/condition-reports")
def create_report(lid):
    _uid, role = auth()
    require_role(role, REPORT_FILE_ROLES)
    loan = get_or_404("loan_agreements", lid, "LoanAgreement")  # (3)
    b = util.body()
    # (9) request shape
    report_kind = util.req_enum(b, "report_kind", constants.REPORT_KINDS)
    condition_summary = util.req_str(b, "condition_summary")
    damage_noted = util.req_bool(b, "damage_noted")
    # Supersede: a fresh report of the same kind moves any earlier DISPUTED
    # report of that kind for this loan to SUPERSEDED.
    for r in db.STORE["condition_reports"].values():
        if (
            r["loan_id"] == loan["id"]
            and r["report_kind"] == report_kind
            and r["status"] == "DISPUTED"
        ):
            r["status"] = "SUPERSEDED"
            db.touch(r)
    r = db.new_entity(
        {
            "loan_id": loan["id"],
            "report_kind": report_kind,
            "condition_summary": condition_summary,
            "damage_noted": damage_noted,
            "status": "SUBMITTED",
        }
    )
    db.STORE["condition_reports"][r["id"]] = r
    return success(serializers.condition_report(r), 201)


@bp.get("/campus/condition-reports")
def list_reports():
    _uid, role = auth()
    require_role(role, REPORT_READ_ROLES)
    limit, offset = util.pagination()
    f_loan = util.request.args.get("loan_id")
    rows = []
    for r in db.all_sorted("condition_reports"):
        if f_loan is not None and r["loan_id"] != f_loan:
            continue
        rows.append(r)
    page = rows[offset : offset + limit]
    return listing([serializers.condition_report(r) for r in page], limit, offset, len(rows))


@bp.get("/campus/condition-reports/<rid>")
def get_report(rid):
    _uid, role = auth()
    require_role(role, REPORT_READ_ROLES)
    r = get_or_404("condition_reports", rid, "ConditionReport")
    return success(serializers.condition_report(r))


@bp.post("/campus/condition-reports/<rid>/decide")
def decide_report(rid):
    _uid, role = auth()
    require_role(role, ["LoansOfficer"])
    r = get_or_404("condition_reports", rid, "ConditionReport")
    # (5) transition legality
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report can be decided")
    b = util.body()
    # (9) request shape
    outcome = util.req_enum(b, "outcome", ("ACCEPTED", "DISPUTED"))
    # Reports are decidable only while the parent loan is live (AGREED/ACTIVE).
    loan = db.STORE["loan_agreements"].get(r["loan_id"])
    if loan is None or loan["status"] not in ("AGREED", "ACTIVE"):
        fail("ERR_INVALID_STATE", "The parent loan is not in a decidable state")
    r["status"] = outcome
    db.touch(r)
    return success(serializers.condition_report(r))
