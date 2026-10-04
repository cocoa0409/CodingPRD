"""Routes: line addition requests and underwriting review.

Gate order on review follows the PRD 3.6 narrative (which overrides the scaffold's
validation indices): state -> credit class (BLOCKED) -> line ceiling -> deposit.
"""

from flask import Blueprint, request

import calculations
import clock
import errors
import lookups
import middleware
import models
import response
import storage

bp = Blueprint("additions", __name__, url_prefix="/portability")

READERS = ("PlatformAdmin", "CustomerService", "CreditAnalyst")
WRITERS = ("CustomerService", "PlatformAdmin")
LINE_CEILING = 10


@bp.post("/line-addition-requests")
@middleware.require_roles(*WRITERS)
def create_addition(caller):
    data = middleware.body()
    account_id = middleware.required_str(data, "account_id")
    lookups.account(account_id)

    line_count = middleware.required_int(data, "line_count")
    if line_count < 1 or line_count > LINE_CEILING:
        errors.fail("ERR_LINE_COUNT_OUT_OF_RANGE",
                    "line_count must be between 1 and 10 inclusive.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "account_id": account_id,
        "parent_account_id": account_id,
        "line_count": line_count,
        "requested_mdn": middleware.optional_str(data, "requested_mdn", None),
        "determined_credit_class": None,
        "required_deposit_cents": 0,
        "request_state": "SUBMITTED",
        "decision_note": None,
        "submitted_at": clock.fmt_now(),
    }
    storage.db.add("line_addition_requests", record)
    return response.ok(models.addition_out(record), 201)


@bp.get("/accounts/<account_id>/line-addition-requests")
@middleware.require_roles(*READERS)
def list_account_additions(caller, account_id):
    lookups.account(account_id)
    rows = [
        r for r in storage.db.all("line_addition_requests") if r["account_id"] == account_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.addition_out(r) for r in page], limit, offset, total)


def _derived_note(credit_class, deposit_cents):
    if credit_class == "BLOCKED":
        return "Credit class BLOCKED: the payment history score is below the underwriting floor."
    if deposit_cents > 0:
        return "Credit class %s requires a deposit of %d cents." % (credit_class, deposit_cents)
    return "Credit class %s requires no deposit." % credit_class


@bp.post("/line-addition-requests/<addition_id>/review")
@middleware.require_roles("CreditAnalyst")
def review_addition(caller, addition_id):
    data = middleware.body()
    record = lookups.addition(addition_id)
    account = lookups.account(record["account_id"])

    if record["request_state"] != "SUBMITTED":
        errors.fail("ERR_INVALID_STATE",
                    "Only a SUBMITTED addition request can be reviewed.")

    decision = data.get("decision")
    if decision not in ("APPROVE", "DECLINE"):
        errors.fail("ERR_INVALID_REQUEST", "decision must be APPROVE or DECLINE.")

    # Review variant: evaluated against the account's active lines as observed now.
    determined, deposit = calculations.credit_class_determination(
        account["payment_history_score"], account["active_line_count"], record["line_count"]
    )
    record["determined_credit_class"] = determined
    record["required_deposit_cents"] = deposit

    supplied_note = data.get("decision_note")
    if supplied_note is not None and not isinstance(supplied_note, str):
        errors.fail("ERR_INVALID_REQUEST", "decision_note must be a string.")
    record["decision_note"] = (
        supplied_note if supplied_note is not None else _derived_note(determined, deposit)
    )

    if decision == "APPROVE":
        # Gate 1: the determined class must not be BLOCKED.
        if determined == "BLOCKED":
            errors.fail("ERR_CREDIT_CLASS_BLOCKED",
                        "The determined credit class is BLOCKED.")
        # Gate 2: the post-addition line count must stay within the ceiling.
        lines_after = account["active_line_count"] + record["line_count"]
        if lines_after > LINE_CEILING:
            errors.fail("ERR_LINE_LIMIT_EXCEEDED",
                        "The account would exceed the line ceiling.")
        # Gate 3: the deposit already on file must cover the required deposit.
        if account["existing_deposit_cents"] < deposit:
            errors.fail("ERR_DEPOSIT_REQUIRED",
                        "The existing deposit does not cover the required deposit.")

        record["request_state"] = "APPROVED"
        models.touch(record)
        account["active_line_count"] = models.active_line_count(account["id"])
        account["credit_class"] = determined
        account["deposit_required_cents"] = deposit
        models.touch(account)
    else:
        record["request_state"] = "DECLINED"
        models.touch(record)
        account["active_line_count"] = models.active_line_count(account["id"])
        # The single conditional account-level effect of a decline.
        if determined == "BLOCKED":
            account["credit_class"] = "BLOCKED"
        models.touch(account)

    return response.ok(models.addition_out(record))