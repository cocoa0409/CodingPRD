"""Placement agreements: the fee ladder, acceptance cascade and termination."""

from flask import Blueprint

from db import DB, base_record, as_int, as_str, check_version, touch
from errors import ApiError
from middleware import authenticate, check_region
from response import success
from routes import common
from serializers import agreement as ser_agreement
from services import calc, machines

bp = Blueprint("agreements", __name__)

ARRANGEMENT_TYPES = ("PURCHASE", "LEASE", "USAGE_BASED")


@bp.post("/api/placement-agreements")
def create_agreement():
    """Draft a placement agreement against a passed readiness review.

    The account advances READINESS → CONTRACTED after the row is created.
    """
    ctx = authenticate(["RegionalSalesDirector"])
    data = common.body()
    account = common.get_account(common.require_str(data, "hospital_account_id"))
    check_region(ctx, account)
    config = common.get_config(common.require_str(data, "system_configuration_id"))
    review = common.get_review(common.require_str(data, "site_readiness_review_id"))
    # Referential integrity: the review must belong to the same account.
    if review.get("hospital_account_id") != account.get("id"):
        raise ApiError("ERR_REFERENTIAL_INTEGRITY_VIOLATION")
    arrangement = common.require_str(data, "arrangement_type").upper()
    if arrangement not in ARRANGEMENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST")
    record = base_record({
        "hospital_account_id": account.get("id"),
        "system_configuration_id": config.get("id"),
        "site_readiness_review_id": review.get("id"),
        "arrangement_type": arrangement,
        "base_monthly_fee_cents": as_int(data.get("base_monthly_fee_cents"), 0),
        "minimum_procedures_per_cycle": as_int(data.get("minimum_procedures_per_cycle"), 0),
        "interval_months": as_int(data.get("interval_months"), 1),
        "placement_fee_cents": as_int(data.get("placement_fee_cents"), 0)
                              if data.get("placement_fee_cents") is not None else None,
        "lease_monthly_amount_cents": as_int(data.get("lease_monthly_amount_cents"), 0)
                                      if data.get("lease_monthly_amount_cents") is not None else None,
        "usage_rate_basis_points": as_int(data.get("usage_rate_basis_points"), 0)
                                   if data.get("usage_rate_basis_points") is not None else None,
        "committed_cases": 0,
        "cycle_start_utc": None,
        "cycle_end_utc": None,
        "shortfall_procedures": 0,
        "synthesized_system_id": None,
        "synthesized_system_version": None,
        "synthesized_service_contract_id": None,
        "net_placement_fee_cents": None,
        "last_shortfall_fee_cents": 0,
        "is_shortfall_waived": False,
        "compliance_status": "MEETS_COMMITMENT",
        "agreement_status": "DRAFT",
        "acceptance_expires_utc": None,
        "activated_at_utc": None,
        "shortfall_reason": None,
    })
    DB.placement_agreements[record["id"]] = record
    # READINESS → CONTRACTED is evaluated after the freshly drafted row exists.
    machines.advance_readiness_to_contracted(account)
    return success(ser_agreement(record)), 201


@bp.get("/api/placement-agreements")
def list_agreements():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer",
                  "IDNCoordinator"])
    records = list(DB.placement_agreements.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    config_id = common.arg("system_configuration_id")
    if config_id:
        records = [r for r in records if r.get("system_configuration_id") == config_id]
    review_id = common.arg("site_readiness_review_id")
    if review_id:
        records = [r for r in records if r.get("site_readiness_review_id") == review_id]
    status = common.arg("agreement_status")
    if status:
        records = [r for r in records if r.get("agreement_status") == status]
    return common.paged(records, "placement_agreements")


@bp.get("/api/placement-agreements/<agreement_id>")
def get_agreement(agreement_id):
    ctx = authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer",
                        "IDNCoordinator", "AccountOwner"])
    record = common.get_agreement(agreement_id)
    if ctx.role == "AccountOwner" and record.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return success(ser_agreement(record))


@bp.post("/api/placement-agreements/<agreement_id>/submit")
def submit_agreement(agreement_id):
    ctx = authenticate(["RegionalSalesDirector"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    check_region(ctx, account)
    review = DB.site_readiness_reviews.get(agreement.get("site_readiness_review_id"))
    config = DB.system_configurations.get(agreement.get("system_configuration_id"))
    data = common.body()
    if agreement.get("agreement_status") != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    if review is None or review.get("readiness_status") != "PASSED":
        raise ApiError("ERR_READINESS_REVIEW_NOT_PASSED")
    if calc.account_posture(account) != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_submit(agreement, account, review, config)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/accept")
def accept_agreement(agreement_id):
    """Hospital acceptance: activates the agreement and mints the system and
    its coverage contract."""
    ctx = authenticate(["HospitalProcurementOfficer"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    check_region(ctx, account)
    review = DB.site_readiness_reviews.get(agreement.get("site_readiness_review_id"))
    config = DB.system_configurations.get(agreement.get("system_configuration_id"))
    data = common.body()
    if agreement.get("agreement_status") != "PENDING_ACCEPTANCE":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    # Priority 28 — the acceptance window is exclusive.
    from db import parse_iso8601
    expires = parse_iso8601(agreement.get("acceptance_expires_utc"))
    if expires is not None and DB.clock >= expires:
        raise ApiError("ERR_ACCEPTANCE_WINDOW_EXPIRED")
    if calc.account_posture(account) != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")
    # Priority 40 — the two pinned parent-version guards run last.
    check_version(account, data, "expected_hospital_account_version")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_accept(agreement, account, review, config)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    authenticate(["PlatformAdmin"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    data = common.body()
    if agreement.get("agreement_status") != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    if agreement.get("compliance_status") != "NON_COMPLIANT":
        raise ApiError("ERR_AGREEMENT_NOT_SUSPENDABLE")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_suspend(agreement, account)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/reinstate")
def reinstate_agreement(agreement_id):
    ctx = authenticate(["RegionalSalesDirector"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if agreement.get("agreement_status") != "SUSPENDED":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_reinstate(agreement, account)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/reject")
def reject_agreement(agreement_id):
    ctx = authenticate(["HospitalProcurementOfficer"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if agreement.get("agreement_status") not in ("DRAFT", "PENDING_ACCEPTANCE", "ACTIVE"):
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_reject(agreement, account)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    authenticate(["PlatformAdmin"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    data = common.body()
    if agreement.get("agreement_status") not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_AGREEMENT_NOT_TERMINABLE")
    check_version(agreement, data, "expected_agreement_version")
    machines.agreement_terminate(agreement, account)
    return success(ser_agreement(agreement))


@bp.post("/api/placement-agreements/<agreement_id>/waive-shortfall")
def waive_shortfall(agreement_id):
    """Waive the current interval's shortfall, recording the operator's reason."""
    authenticate(["ComplianceOfficer"])
    agreement = common.get_agreement(agreement_id)
    account = common.get_account(agreement.get("hospital_account_id"))
    data = common.body()
    reason = data.get("reason")
    agreement["is_shortfall_waived"] = True
    agreement["shortfall_reason"] = as_str(reason) if reason is not None else None
    agreement["last_shortfall_fee_cents"] = 0
    machines.refresh_commitment(agreement)
    touch(agreement)
    machines.refresh_posture(account)
    return success(ser_agreement(agreement))


# ---------------------------------------------------------------------------
# Agreement-scoped child collections
# ---------------------------------------------------------------------------

@bp.get("/api/placement-agreements/<agreement_id>/robot-systems")
def list_agreement_systems(agreement_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ServiceEngineer"])
    agreement = common.get_agreement(agreement_id)
    records = machines.systems_of_agreement(agreement)
    status = common.arg("service_status")
    if status:
        records = [r for r in records if r.get("service_status") == status]
    return common.paged(records, "robot_systems")


@bp.get("/api/placement-agreements/<agreement_id>/utilization-cycles")
def list_agreement_cycles(agreement_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer"])
    common.get_agreement(agreement_id)
    return common.paged(calc.cycles_of_agreement(agreement_id), "utilization_cycles")