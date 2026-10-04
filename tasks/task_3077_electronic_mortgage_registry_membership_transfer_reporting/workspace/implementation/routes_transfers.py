"""Transfer reporting, timeliness fees, and the match protocol."""
from flask import Blueprint, request

from db import store, iso
from domain import (
    TRANSFER_TYPES, base_record, compute_days_late, compute_late_fee, err,
    find_loan, find_transfer, get_body, new_exception as _unused, paginate,  # noqa: F401
    req_enum, req_int, req_iso, req_str, sorted_items, touch,
)
from middleware import require_member_active, require_role
from response import success
from views import match_view, transfer_view

bp = Blueprint("transfers", __name__)


@bp.post("/transfers")
def create_transfer():
    body = get_body()
    user_id, _role = require_role("MemberRep")
    loan_id = req_str(body, "loan_id")
    to_member_id = req_str(body, "to_member_id")
    transfer_type = req_enum(body, "transfer_type", TRANSFER_TYPES)
    effective_date = req_iso(body, "effective_date")
    idempotency_key = req_str(body, "idempotency_key")
    expected_loan_version = req_int(body, "expected_loan_version")

    loan = find_loan(loan_id)
    to_member = store.members.get(to_member_id)
    if to_member is None:
        raise err("ERR_MEMBER_NOT_FOUND", f"Member {to_member_id} not found")
    member = store.members.get(user_id)
    if member is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Acting member does not exist")

    # Tier 6: member state (acting, then receiving).
    require_member_active(member)
    require_member_active(to_member)
    # Tier 7: resource state.
    if loan["status"] != "ACTIVE":
        raise err("ERR_LOAN_NOT_ACTIVE", "Loan must be ACTIVE for a transfer")
    # Tier 11: clock discipline.
    if effective_date > store.clock:
        raise err("ERR_FUTURE_EFFECTIVE_DATE",
                  "effective_date is after the current logical clock")
    # Tier 12: live idempotency-key uniqueness.
    for t in store.transfers.values():
        if t["idempotency_key"] == idempotency_key and t["status"] != "REJECTED":
            raise err("ERR_DUPLICATE_IDEMPOTENCY_KEY",
                      "idempotency_key already used by a non-REJECTED transfer")
    # Tier 13: transfer semantics.
    moves_beneficial = transfer_type in ("BENEFICIAL", "BOTH")
    moves_servicing = transfer_type in ("SERVICING", "BOTH")
    holds_beneficial = loan["current_investor_id"] == member["id"]
    holds_servicing = loan["current_servicer_id"] == member["id"]
    if moves_beneficial and not holds_beneficial:
        raise err("ERR_NOT_RIGHTS_HOLDER",
                  "Acting member does not hold the beneficial right being moved")
    if moves_servicing and not holds_servicing:
        raise err("ERR_NOT_RIGHTS_HOLDER",
                  "Acting member does not hold the servicing right being moved")
    if moves_beneficial and to_member_id == loan["current_investor_id"]:
        raise err("ERR_SELF_TRANSFER",
                  "to_member is already the current investor of the loan")
    if moves_servicing and to_member_id == loan["current_servicer_id"]:
        raise err("ERR_SELF_TRANSFER",
                  "to_member is already the current servicer of the loan")
    # Tier 16: OCC.
    if expected_loan_version != loan["version"]:
        raise err("ERR_STALE_LOAN_VERSION",
                  "expected_loan_version does not match the loan's current version")

    from_member_id = (loan["current_investor_id"] if moves_beneficial
                      else loan["current_servicer_id"])
    days_late = compute_days_late(store.clock, effective_date)
    late_fee = compute_late_fee(days_late)

    rec = base_record()
    rec.update({
        "loan_id": loan["id"],
        "from_member_id": from_member_id,
        "to_member_id": to_member_id,
        "transfer_type": transfer_type,
        "effective_date": iso(effective_date),
        "idempotency_key": idempotency_key,
        "days_late": days_late,
        "late_fee_cents": late_fee,
        "status": "CONFIRMED",
    })
    store.transfers[rec["id"]] = rec

    # Move the rights; advance the loan version.
    if moves_beneficial:
        loan["current_investor_id"] = to_member_id
    if moves_servicing:
        loan["current_servicer_id"] = to_member_id
    touch(loan)

    # Open the match protocol on the from side.
    match = base_record()
    match.update({
        "transfer_id": rec["id"],
        "reported_by_member_id": from_member_id,
        "reported_at": iso(store.clock),
        "status": "PENDING",
    })
    store.matches[match["id"]] = match

    return success(transfer_view(rec), status=201)


@bp.get("/transfers")
def list_transfers():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    items = sorted_items(store.transfers)
    for field in ("loan_id", "from_member_id", "to_member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [t for t in items if t[field] == value]
    page, meta = paginate(items)
    return success([transfer_view(t) for t in page], is_list=True, pagination=meta)


@bp.get("/transfers/<transferId>")
def get_transfer(transferId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    return success(transfer_view(find_transfer(transferId)))


def _match_for_transfer(transfer_id):
    return next((m for m in store.matches.values()
                 if m["transfer_id"] == transfer_id), None)


def _answer_match(transferId, outcome):
    user_id, _role = require_role("MemberRep")
    transfer = find_transfer(transferId)
    match = _match_for_transfer(transfer["id"])
    member = store.members.get(user_id)
    if member is None:
        raise err("ERR_MEMBER_NOT_FOUND", "Acting member does not exist")
    require_member_active(member)
    if transfer["from_member_id"] != user_id:
        raise err("ERR_NOT_MATCH_PARTY",
                  "Only the transfer's from-side member may answer the match")
    if match is None or match["status"] != "PENDING":
        raise err("ERR_MATCH_NOT_PENDING", "Transfer match is not PENDING")

    if outcome == "confirm":
        match["status"] = "MATCHED"
        touch(match)
        return match

    # reject: transfer flips REJECTED, match EXPIRED, rights NOT rolled back.
    transfer["status"] = "REJECTED"
    touch(transfer)
    match["status"] = "EXPIRED"
    touch(match)
    # Escalate to QA: an auto finding lands on a DRAFT review of the from side.
    draft = next((r for r in store.reviews.values()
                  if r["member_id"] == transfer["from_member_id"]
                  and r["status"] == "DRAFT"), None)
    if draft is not None:
        finding = base_record()
        finding.update({
            "review_id": draft["id"],
            "loan_id": transfer["loan_id"],
            "field_name": "CURRENT_SERVICER",
            "expected_value": transfer["from_member_id"],
            "actual_value": transfer["to_member_id"],
            "severity": "MAJOR",
        })
        store.findings[finding["id"]] = finding
    return match


@bp.post("/transfers/<transferId>/match-confirm")
def match_confirm(transferId):
    get_body()
    match = _answer_match(transferId, "confirm")
    return success(match_view(match))


@bp.post("/transfers/<transferId>/reject-match")
def reject_match(transferId):
    get_body()
    match = _answer_match(transferId, "reject")
    return success(match_view(match))


@bp.get("/transfer-matches")
def list_matches():
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    items = sorted_items(store.matches)
    for field in ("transfer_id", "reported_by_member_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [m for m in items if m[field] == value]
    page, meta = paginate(items)
    return success([match_view(m) for m in page], is_list=True, pagination=meta)


@bp.get("/transfer-matches/<matchId>")
def get_match(matchId):
    require_role("RegistryAdmin", "MemberRep", "QAAuditor")
    match = store.matches.get(matchId)
    if match is None:
        raise err("ERR_TRANSFER_NOT_FOUND", f"TransferMatch {matchId} not found")
    return success(match_view(match))
