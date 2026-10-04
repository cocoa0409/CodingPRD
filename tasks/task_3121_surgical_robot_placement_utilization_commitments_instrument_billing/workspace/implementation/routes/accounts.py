"""Hospital accounts, account state machine and account-scoped list endpoints."""

from flask import Blueprint

from db import DB, base_record, as_int
from errors import ApiError
from middleware import authenticate, check_region
from response import success
from routes import common
from serializers import (account as ser_account,
                         consumption_ledger as ser_ledger)
from services import calc, machines

bp = Blueprint("accounts", __name__)


@bp.post("/api/accounts")
def create_account():
    ctx = authenticate(["RegionalSalesDirector"])
    data = common.body()
    region = common.require_str(data, "region_code")
    record = base_record({
        "account_name": common.require_str(data, "account_name"),
        "idn_group_code": common.require_str(data, "idn_group_code"),
        "region_code": region,
        "account_status": "PROSPECT",
        "placement_cap": as_int(data.get("placement_cap"), 0),
        "maximum_procedure_commitment": as_int(data.get("maximum_procedure_commitment"), 0),
        "dormant_since_utc": None,
        "hospital_owner_user_id": ctx.user_id,
    })
    record["account_posture"] = calc.account_posture(record)
    DB.hospital_accounts[record["id"]] = record
    return success(ser_account(record)), 201


@bp.get("/api/accounts")
def list_accounts():
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "IDNCoordinator",
                        "AccountOwner"])
    records = list(DB.hospital_accounts.values())
    if ctx.role == "AccountOwner":
        records = [r for r in records if r.get("id") == ctx.user_id]
    code = common.arg("idn_group_code")
    if code:
        records = [r for r in records if r.get("idn_group_code") == code]
    status = common.arg("account_status")
    if status:
        records = [r for r in records if r.get("account_status") == status]
    return common.paged(records, "hospital_accounts")


@bp.get("/api/accounts/<account_id>")
def get_account(account_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "IDNCoordinator",
                        "AccountOwner"])
    record = common.get_account(account_id)
    check_region(ctx, record)
    if ctx.role == "AccountOwner" and record.get("id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return success(ser_account(record))


@bp.post("/api/accounts/<account_id>/close")
def close_account(account_id):
    authenticate(["PlatformAdmin"])
    record = common.get_account(account_id)
    data = common.body()
    if record.get("account_status") not in ("ACTIVE", "DORMANT"):
        raise ApiError("ERR_ACCOUNT_NOT_CLOSABLE")
    for agreement in calc.agreements_of_account(account_id):
        if agreement.get("agreement_status") in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_ACTIVE_AGREEMENT_EXISTS")
    from db import check_version
    check_version(record, data, "expected_account_version")
    machines.account_close(record)
    return success(ser_account(record))


@bp.post("/api/households/<account_id>/reactivate")
def reactivate_account(account_id):
    ctx = authenticate(["RegionalSalesDirector"])
    record = common.get_account(account_id)
    check_region(ctx, record)
    data = common.body()
    if record.get("account_status") != "DORMANT":
        raise ApiError("ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE")
    from db import check_version
    check_version(record, data, "expected_account_version")
    machines.account_reactivate(record)
    return success(ser_account(record))


@bp.post("/api/account-readiness-reviews/<review_id>/activate")
def activate_account(review_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    review = common.get_review(review_id)
    account = common.get_account(review.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if account.get("account_status") != "PROSPECT":
        raise ApiError("ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE")
    if not calc.reviews_of_account(account.get("id")):
        raise ApiError("ERR_READINESS_REVIEW_REQUIRED")
    if not calc.training_records_of_account(account.get("id")):
        raise ApiError("ERR_TRAINING_PATH_UNINITIALIZED")
    from db import check_version
    check_version(account, data, "expected_account_version")
    machines.account_prospect_to_readiness(account)
    return success(ser_account(account))


# ---------------------------------------------------------------------------
# Account-scoped child collections
# ---------------------------------------------------------------------------

@bp.get("/api/accounts/<account_id>/placement-agreements")
def list_account_agreements(account_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    records = calc.agreements_of_account(account_id)
    status = common.arg("agreement_status")
    if status:
        records = [r for r in records if r.get("agreement_status") == status]
    return common.paged(records, "placement_agreements")


@bp.get("/api/accounts/<account_id>/robot-systems")
def list_account_systems(account_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ServiceEngineer",
                        "AccountOwner"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    if ctx.role == "AccountOwner" and account.get("id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    records = calc.systems_of_account(account_id)
    status = common.arg("service_status")
    if status:
        records = [r for r in records if r.get("service_status") == status]
    return common.paged(records, "robot_systems")


@bp.get("/api/accounts/<account_id>/expansion-reviews")
def list_account_expansion_reviews(account_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    records = calc.reviews_of_account_expansion(account_id)
    status = common.arg("review_status")
    if status:
        records = [r for r in records if r.get("review_status") == status]
    return common.paged(records, "expansion_reviews")


@bp.get("/api/accounts/<account_id>/utilisation-transfer-transactions")
def list_account_transfers(account_id):
    ctx = authenticate(["PlatformAdmin", "IDNCoordinator"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    records = [r for r in DB.transfer_transactions.values()
               if r.get("source_account_id") == account_id]
    status = common.arg("transaction_status")
    if status:
        records = [r for r in records if r.get("transaction_status") == status]
    return common.paged(records, "transfer_transactions")


@bp.post("/api/accounts/<account_id>/consumption-ledgers")
def create_ledger(account_id):
    ctx = authenticate(["IDNCoordinator"])
    account = common.get_account(account_id)
    check_region(ctx, account)
    data = common.body()
    record = base_record({
        "hospital_account_id": account_id,
        "donor_idn_group_code": account.get("idn_group_code"),
        "consumed_procedure_units": 0,
        "supplied_procedure_units": 0,
        "maximum_procedure_commitment": common.require_int(
            data, "maximum_procedure_commitment", 0),
    })
    DB.consumption_ledgers[record["id"]] = record
    return success(ser_ledger(record)), 201