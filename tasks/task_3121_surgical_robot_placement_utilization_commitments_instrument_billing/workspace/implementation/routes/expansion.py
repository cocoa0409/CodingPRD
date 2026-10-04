"""Expansion reviews and the IDN utilisation credit pool."""

from flask import Blueprint

from db import DB, base_record, as_str, check_version, to_iso, touch
from errors import ApiError
from middleware import authenticate, check_region, check_segregation
from response import success
from routes import common
from serializers import (expansion_review as ser_expansion,
                         consumption_ledger as ser_ledger,
                         transfer_transaction as ser_transfer)
from services import calc, machines

bp = Blueprint("expansion", __name__)


# ---------------------------------------------------------------------------
# Expansion reviews
# ---------------------------------------------------------------------------

@bp.post("/api/expansion-reviews")
def create_expansion_review():
    """Open an expansion review, selecting the account's eligible system.

    One of the three operations guarded by a parent-version check: the
    eligible-system selector reads the account's systems and their service
    priorities, so a stale account view is a stale candidate set.
    """
    ctx = authenticate(["RegionalSalesDirector"])
    data = common.body()
    account = common.get_account(common.require_str(data, "hospital_account_id"))
    check_region(ctx, account)
    agreement = common.get_agreement(common.require_str(data, "placement_agreement_id"))
    if agreement.get("hospital_account_id") != account.get("id"):
        raise ApiError("ERR_REFERENTIAL_INTEGRITY_VIOLATION")
    ranking = common.require_int(data, "support_request_ranking")
    capacity = common.require_int(data, "requested_case_capacity")
    # Priority 40 — this guard runs last, so the referential checks above win.
    check_version(account, data, "expected_hospital_account_version")
    eligible = calc.select_eligible_system(account)
    record = base_record({
        "hospital_account_id": account.get("id"),
        "placement_agreement_id": agreement.get("id"),
        "eligible_system_id": eligible.get("id") if eligible else None,
        "eligible_system_utilization": 0,
        "requires_prior_reporting_period": False,
        "review_status": "DRAFT",
        "support_request_ranking": ranking,
        "requested_case_capacity": capacity,
        "reason": None,
        "decided_at_utc": None,
    })
    record["eligible_system_utilization"] = calc.eligible_system_utilization(record)
    record["requires_prior_reporting_period"] = calc.requires_prior_reporting_period(record)
    DB.expansion_reviews[record["id"]] = record
    touch(account)
    return success(ser_expansion(record)), 201


@bp.get("/api/expansion-reviews")
def list_expansion_reviews():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer"])
    records = list(DB.expansion_reviews.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    agreement_id = common.arg("placement_agreement_id")
    if agreement_id:
        records = [r for r in records if r.get("placement_agreement_id") == agreement_id]
    status = common.arg("review_status")
    if status:
        records = [r for r in records if r.get("review_status") == status]
    return common.paged(records, "expansion_reviews")


@bp.get("/api/expansion-reviews/<review_id>")
def get_expansion_review(review_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer",
                        "AccountOwner"])
    record = common.get_expansion_review(review_id)
    if ctx.role == "AccountOwner" and record.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return success(ser_expansion(record))


@bp.post("/api/expansion-reviews/<review_id>/submit")
def submit_expansion_review(review_id):
    ctx = authenticate(["RegionalSalesDirector", "AccountOwner"])
    record = common.get_expansion_review(review_id)
    account = common.get_account(record.get("hospital_account_id"))
    check_region(ctx, account)
    if ctx.role == "AccountOwner" and account.get("id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    data = common.body()
    if record.get("review_status") != "DRAFT":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(record, data, "expected_review_version")
    record["review_status"] = "SUBMITTED"
    touch(record)
    return success(ser_expansion(record))


@bp.post("/api/expansion-reviews/<review_id>/approve")
def approve_expansion_review(review_id):
    """Approve a submitted review.

    Subject to the segregation-of-duties rule: the approving ComplianceOfficer
    may not be the owning account's hospital_owner_user_id.
    """
    ctx = authenticate(["ComplianceOfficer"])
    record = common.get_expansion_review(review_id)
    account = common.get_account(record.get("hospital_account_id"))
    data = common.body()
    if record.get("review_status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_segregation(ctx, account)
    check_version(record, data, "expected_review_version")
    record["review_status"] = "APPROVED"
    record["decided_at_utc"] = to_iso(DB.clock)
    touch(record)
    machines.refresh_posture(account)
    return success(ser_expansion(record))


@bp.post("/api/expansion-reviews/<review_id>/reject")
def reject_expansion_review(review_id):
    ctx = authenticate(["ComplianceOfficer"])
    record = common.get_expansion_review(review_id)
    account = common.get_account(record.get("hospital_account_id"))
    data = common.body()
    if record.get("review_status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_REQUEST")
    reason = common.require_str(data, "reason")
    check_segregation(ctx, account)
    check_version(record, data, "expected_review_version")
    record["review_status"] = "REJECTED"
    record["reason"] = reason
    record["decided_at_utc"] = to_iso(DB.clock)
    touch(record)
    return success(ser_expansion(record))


# ---------------------------------------------------------------------------
# IDN utilisation credit pool
# ---------------------------------------------------------------------------

@bp.get("/api/utilisation-consumption-ledgers")
def list_ledgers():
    authenticate(["PlatformAdmin", "IDNCoordinator"])
    records = list(DB.consumption_ledgers.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    return common.paged(records, "consumption_ledgers")


@bp.get("/api/utilisation-consumption-ledgers/<ledger_id>")
def get_ledger(ledger_id):
    authenticate(["PlatformAdmin", "IDNCoordinator"])
    return success(ser_ledger(common.get_ledger(ledger_id)))


@bp.post("/api/utilisation-consumption-ledgers/<ledger_id>/bootstrap-decrement")
def bootstrap_decrement(ledger_id):
    """Seed the account's opening unused consumption.

    The pool-subscription rule and the transfer-window rule both apply here, so
    a bootstrap that would push aggregate utilisation to the ceiling is refused
    like any other consumption.
    """
    ctx = authenticate(["IDNCoordinator"])
    ledger = common.get_ledger(ledger_id)
    account = common.get_account(ledger.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    consumed = common.require_int(data, "consumed_procedure_units")
    check_version(ledger, data, "expected_ledger_version")
    # Priority 36 — the pool ceiling applies to this path as well.
    if calc.pool_saturated(account):
        raise ApiError("ERR_IDN_POOL_SATURATED")
    ledger["consumed_procedure_units"] = max(0, consumed)
    touch(ledger)
    return success(ser_ledger(ledger))


@bp.get("/api/utilisation-transfer-transactions")
def list_transfers():
    authenticate(["PlatformAdmin", "IDNCoordinator"])
    records = list(DB.transfer_transactions.values())
    source_id = common.arg("source_account_id")
    if source_id:
        records = [r for r in records if r.get("source_account_id") == source_id]
    destination_id = common.arg("destination_account_id")
    if destination_id:
        records = [r for r in records if r.get("destination_account_id") == destination_id]
    status = common.arg("transaction_status")
    if status:
        records = [r for r in records if r.get("transaction_status") == status]
    return common.paged(records, "transfer_transactions")


@bp.get("/api/utilisation-transfer-transactions/<transaction_id>")
def get_transfer(transaction_id):
    authenticate(["PlatformAdmin", "IDNCoordinator"])
    return success(ser_transfer(common.get_transfer(transaction_id)))


@bp.post("/api/utilisation-transfer-transactions")
def create_transfer():
    """Move committed-procedure credit between IDN member accounts."""
    ctx = authenticate(["IDNCoordinator"])
    data = common.body()
    source = common.get_account(common.require_str(data, "source_account_id"))
    destination = common.get_account(common.require_str(data, "destination_account_id"))
    check_region(ctx, source)
    units = common.require_int(data, "procedure_units")
    window_start = common.require_dt(data, "transfer_window_start_utc")
    window_end = common.require_dt(data, "transfer_window_end_utc")

    source_ledger = None
    for candidate in calc.ledgers_of_account(source.get("id")):
        source_ledger = candidate
        break
    destination_ledger = None
    for candidate in calc.ledgers_of_account(destination.get("id")):
        destination_ledger = candidate
        break

    # Priority 37 — the source must hold enough remaining credit units.
    if source_ledger is None or calc.remaining_credit_units(source_ledger) < units:
        raise ApiError("ERR_INSUFFICIENT_UTILISATION_CREDIT")
    # Priority 22 — closed-window overlap on the destination at day granularity.
    # A start date inside the 3-day merge grace is merged into the existing
    # window instead of rejected, the merged window spanning both; only a
    # genuine closed-range overlap conflicts.
    merge_target = calc.transfer_merge_target(window_start, destination.get("id"),
                                              DB.transfer_transactions.values())
    if merge_target is not None:
        existing_start = calc.parse_iso(merge_target.get("transfer_window_start_utc"))
        existing_end = calc.parse_iso(merge_target.get("transfer_window_end_utc"))
        if existing_start is not None and window_start < existing_start:
            merge_target["transfer_window_start_utc"] = to_iso(window_start)
        if existing_end is not None and window_end > existing_end:
            merge_target["transfer_window_end_utc"] = to_iso(window_end)
        touch(merge_target)
    elif calc.transfer_conflict(window_start, window_end, destination.get("id"),
                                DB.transfer_transactions.values()):
        raise ApiError("ERR_TRANSFER_WINDOW_CONFLICT")
    # Priority 36 — the pool ceiling.
    if calc.pool_saturated(destination):
        raise ApiError("ERR_IDN_POOL_SATURATED")
    # The sum of the source's non-reversed transfers may not exceed its
    # maximum procedure commitment.
    maximum = int(source_ledger.get("maximum_procedure_commitment") or 0)
    supplied = calc.source_window_supply(source.get("id"), DB.transfer_transactions.values())
    if maximum > 0 and supplied + units > maximum:
        raise ApiError("ERR_INSUFFICIENT_UTILISATION_CREDIT")

    record = base_record({
        "source_account_id": source.get("id"),
        "destination_account_id": destination.get("id"),
        "procedure_units": units,
        "transfer_window_start_utc": to_iso(window_start),
        "transfer_window_end_utc": to_iso(window_end),
        "transaction_status": "COMMITTED",
        "reversal_reason": None,
        "settlement_certified_at_utc": None,
    })
    DB.transfer_transactions[record["id"]] = record
    source_ledger["supplied_procedure_units"] = int(
        source_ledger.get("supplied_procedure_units") or 0) + units
    if destination_ledger is not None:
        destination_ledger["consumed_procedure_units"] = int(
            destination_ledger.get("consumed_procedure_units") or 0) + units
        destination_ledger["donor_idn_group_code"] = source.get("idn_group_code")
        touch(destination_ledger)
    touch(source_ledger)
    return success(ser_transfer(record)), 201


@bp.post("/api/utilisation-transfer-transactions/<transaction_id>/settle")
def settle_transfer(transaction_id):
    ctx = authenticate(["IDNCoordinator"])
    record = common.get_transfer(transaction_id)
    common.get_account(record.get("source_account_id"))
    data = common.body()
    if record.get("transaction_status") != "COMMITTED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(record, data, "expected_transfer_version")
    record["transaction_status"] = "SETTLED"
    record["settlement_certified_at_utc"] = to_iso(DB.clock)
    touch(record)
    return success(ser_transfer(record))


@bp.post("/api/utilisation-transfer-transactions/<transaction_id>/reverse")
def reverse_transfer(transaction_id):
    """Reverse a transfer, restoring the conserved pool exactly."""
    ctx = authenticate(["IDNCoordinator"])
    record = common.get_transfer(transaction_id)
    source = common.get_account(record.get("source_account_id"))
    destination = common.get_account(record.get("destination_account_id"))
    check_region(ctx, source)
    data = common.body()
    if record.get("transaction_status") not in ("COMMITTED", "SETTLED"):
        raise ApiError("ERR_INVALID_REQUEST")
    units = int(record.get("procedure_units") or 0)
    record["transaction_status"] = "REVERSED"
    if data.get("reversal_reason") is not None:
        record["reversal_reason"] = as_str(data.get("reversal_reason"))
    for ledger in calc.ledgers_of_account(source.get("id")):
        ledger["supplied_procedure_units"] = max(
            0, int(ledger.get("supplied_procedure_units") or 0) - units)
        touch(ledger)
    for ledger in calc.ledgers_of_account(destination.get("id")):
        ledger["consumed_procedure_units"] = max(
            0, int(ledger.get("consumed_procedure_units") or 0) - units)
        touch(ledger)
    touch(record)
    return success(ser_transfer(record))