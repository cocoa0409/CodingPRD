"""Revenue share statements: the two bases, finalize, reopen and pay (PRD 3.9)."""
from flask import Blueprint

import auth
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("statements", __name__)


def inclusion_set(statement):
    """The basis selects the inclusion set; both windows are half-open above."""
    start = statement["period_start"]
    end = statement["period_end"]
    rows = []
    for row in db.redemptions.values():
        if row["employer_id"] != statement["employer_id"]:
            continue
        if row["verification_status"] != "VERIFIED":
            continue
        if statement["basis"] == "ACCRUAL":
            # Regardless of fulfillment_status.
            stamp = row["verified_at"]
        else:
            if row["fulfillment_status"] != "FULFILLED":
                continue
            stamp = row["fulfilled_at"]
        if stamp is None:
            continue
        if start <= stamp < end:
            rows.append(row)
    return db.sorted_rows(rows)


@bp.post("/perks/revenue-share-statements")
def create_statement():
    auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN)
    body = validate.json_body()
    employer = support.resolve_fk(body, "employer_id", "employers")
    data = validate.fields(body, [
        {"name": "employer_id", "type": "str", "required": True},
        {"name": "period_start", "type": "datetime", "required": True},
        {"name": "period_end", "type": "datetime", "required": True},
        {"name": "basis", "type": "enum", "required": True,
         "values": ["ACCRUAL", "CASH"]},
    ])
    validate.window(data["period_start"], data["period_end"])
    # Nothing whatsoever is computed at creation.
    row = db.insert(db.statements, {
        "employer_id": employer["id"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "basis": data["basis"],
        "included_redemption_count": 0,
        "gross_commission_cents": 0,
        "employer_share_cents": 0,
        "provider_retained_cents": 0,
        "reversal_adjustment_cents": 0,
        "status": "DRAFT",
        "finalized_at": None,
        "reopened_at": None,
        "reopen_reason": None,
        "paid_at": None,
        "payment_reference": None,
    })
    return response.created(derive.statement_json(row))


@bp.get("/perks/revenue-share-statements/<row_id>")
def get_statement(row_id):
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    row = support.fetch("statements", row_id)
    auth.check_employer_scope(principal, row["employer_id"])
    return response.ok(derive.statement_json(row))


@bp.get("/perks/revenue-share-statements")
def list_statements():
    principal = auth.require(auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    employer_id = support.arg("employer_id")
    status = support.arg("status")
    basis = support.arg("basis")
    rows = []
    for row in db.statements.values():
        if principal.is_employer_admin and row["employer_id"] != principal.user_id:
            continue
        if not support.matches(row, "employer_id", employer_id):
            continue
        if not support.matches(row, "status", status):
            continue
        if not support.matches(row, "basis", basis):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.statement_json)


@bp.post("/perks/revenue-share-statements/<row_id>/finalize")
def finalize_statement(row_id):
    # Segregation of duties: the manager finalizes, the admin pays.
    auth.require(auth.PARTNER_MANAGER)
    row = support.fetch("statements", row_id)
    if row["status"] not in ("DRAFT", "REOPENED"):
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "Only a DRAFT or REOPENED statement can be finalized.")
    # State rules outrank temporal rules, so this check comes second.
    if not row["period_end"] < clock.now():
        raise ApiError("ERR_PERIOD_NOT_CLOSED", "The statement period is not yet closed.")
    included = inclusion_set(row)
    gross = 0
    share = 0
    for redemption in included:
        gross += int(redemption["commission_amount_cents"] or 0)
        # The already-rounded per-redemption share; never a rate over the sum.
        share += int(redemption["employer_share_cents"] or 0)
    reversal = 0
    for entry in db.ledger_entries.values():
        if entry["entry_type"] == "EMPLOYER_SHARE_REVERSAL" and entry["statement_id"] == row["id"]:
            reversal += int(entry["amount_cents"])
    row["included_redemption_count"] = len(included)
    row["gross_commission_cents"] = gross
    row["employer_share_cents"] = share
    row["provider_retained_cents"] = gross - share
    row["reversal_adjustment_cents"] = reversal
    row["status"] = "FINALIZED"
    row["finalized_at"] = clock.now()
    row["reopen_reason"] = None
    db.touch(row)
    for redemption in included:
        # A redemption already stamped keeps its original claim but still counts.
        if redemption["statement_id"] is None:
            redemption["statement_id"] = row["id"]
            db.touch(redemption)
    return response.ok(derive.statement_json(row))


@bp.post("/perks/revenue-share-statements/<row_id>/pay")
def pay_statement(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("statements", row_id)
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "payment_reference", "type": "str", "required": True},
    ])
    if row["status"] != "FINALIZED":
        raise ApiError("ERR_STATEMENT_INVALID_STATE",
                       "Only a FINALIZED statement can be paid.")
    # Paying writes no ledger entry: accrued_share_cents is a lifetime accrual.
    row["status"] = "PAID"
    row["paid_at"] = clock.now()
    row["payment_reference"] = data["payment_reference"]
    db.touch(row)
    return response.ok(derive.statement_json(row))
