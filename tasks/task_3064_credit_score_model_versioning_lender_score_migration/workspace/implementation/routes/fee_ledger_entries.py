"""Fee ledger entry read endpoints."""

from flask import Blueprint, request

from core import (
    DB, ok, ok_list, resolve_actor, fee_ledger_entry, read_pagination, paginate,
    ordered_rows, authenticate, authorize,
)
from errors import ApiError

bp = Blueprint("fee_ledger_entries", __name__)

READ_ROLES = ["BureauAdministrator", "ComplianceOfficer", "FairLendingOfficer", "ScoreConsumer"]


@bp.get("/fee-ledger-entries/<entry_id>")
def get_entry(entry_id):
    role, user_id = authenticate(request)
    authorize(role, READ_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    rec = fee_ledger_entry(entry_id)
    if role == "ScoreConsumer" and rec["license_id"] != user_id:
        raise ApiError("ERR_UNAUTHORIZED")
    return ok(rec)


@bp.get("/fee-ledger-entries")
def list_entries():
    role, user_id = authenticate(request)
    authorize(role, READ_ROLES)
    if role == "ScoreConsumer" and user_id not in DB["licenses"]:
        raise ApiError("ERR_UNAUTHORIZED")
    limit, offset = read_pagination(request)
    rows = ordered_rows("fee_ledger_entries")

    license_id = request.args.get("license_id")
    if license_id is not None:
        rows = [r for r in rows if r["license_id"] == license_id]
    score_result_id = request.args.get("score_result_id")
    if score_result_id is not None:
        rows = [r for r in rows if r["score_result_id"] == score_result_id]
    kind = request.args.get("kind")
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]

    if role == "ScoreConsumer":
        rows = [r for r in rows if r["license_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)