"""Securitization pools: assignment, removal and settlement."""
from decimal import Decimal

from flask import Blueprint

from core import (ApiError, Field, authenticate, invalid, respond_created,
                  respond_object, raw_body, validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("pools", __name__)

POOL_READERS = ("SecuritizationAnalyst", "ChiefCreditOfficer", "PostCloseAuditor")
REMOVAL_REASONS = ("LOAN_INELIGIBLE", "ANALYST_DISCRETION", "SETTLEMENT_FINALIZED")


def pool_state(condition, message):
    if not condition:
        raise ApiError("ERR_POOL_STATE_INVALID", message)


@bp.post("/securitization-pools")
def create_pool():
    authenticate(("SecuritizationAnalyst",))
    values = validate_body([
        Field("pool_code", "str", True),
        Field("investor_code", "str", True),
        Field("target_balance_cents", "int", True),
    ])
    if values["target_balance_cents"] <= 0:
        invalid("target_balance_cents must be greater than zero")
    # priority 28
    for existing in db.rows("pools"):
        if existing["pool_code"] == values["pool_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "pool_code must be globally unique")

    row = db.insert("pools", {
        "pool_code": values["pool_code"],
        "investor_code": values["investor_code"],
        "target_balance_cents": values["target_balance_cents"],
        "status": "OPEN",
        "aggregate_scheduled_balance_cents": 0,
        "weighted_avg_coupon_pct": Decimal("0.0000"),
        "member_loan_count": 0,
    })
    return respond_created(row)


@bp.get("/securitization-pools/<ident>")
def read_pool(ident):
    authenticate(POOL_READERS)
    return respond_object(db.fetch("pools", ident))


@bp.post("/securitization-pools/<ident>/loans")
def assign_loan(ident):
    authenticate(("SecuritizationAnalyst",))
    pool = db.fetch("pools", ident)
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body([
        Field("loan_file_id", "str", True),
        Field("expected_pool_version", "int", True),
    ])
    # priority 9
    if int(values["expected_pool_version"]) != int(pool["version"]):
        raise ApiError("ERR_STALE_POOL_VERSION",
                       "expected_pool_version does not match the pool version")
    # priority 16
    pool_state(pool["status"] in ("OPEN", "REBALANCING"),
               "pool status %s accepts no membership write" % pool["status"])
    # priority 18
    if loan_file["points_and_fees_test_result"] == "FAIL":
        raise ApiError("ERR_HIGH_COST_LOAN_PROHIBITED",
                       "a high-cost loan may not be delivered into a pool")
    # priority 19
    if (loan_file["atr_documentation_status"] not in ("DOCUMENTED", "EXEMPT")
            or loan_file["safe_harbor_class"] == "NOT_EVALUATED"):
        raise ApiError("ERR_ATR_DOCUMENTATION_INCOMPLETE",
                       "ability-to-repay documentation is not complete")
    # priority 32
    if (loan_file["status"] != "CLOSED" or not loan_file["securitization_eligible"]
            or loan_file["investor_code"] != pool["investor_code"]):
        raise ApiError("ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE",
                       "the loan is not deliverable into this pool")
    # priority 33
    if loan_file.get("pool_id") is not None:
        raise ApiError("ERR_LOAN_ALREADY_POOLED", "the loan already sits in a pool")
    # priority 42
    projected = (int(pool["aggregate_scheduled_balance_cents"])
                 + int(loan_file["loan_amount_cents"]))
    if projected > int(pool["target_balance_cents"]):
        raise ApiError("ERR_POOL_BALANCE_CAP_EXCEEDED",
                       "the assignment would exceed the pool target balance")

    tx = Tx()
    tx.watch(pool)
    tx.bump(pool)
    tx.watch(loan_file)
    loan_file["pool_id"] = pool["id"]
    if pool["status"] == "REBALANCING":
        pool["status"] = "OPEN"
    services.pool_recompute(pool)
    tx.commit()
    return respond_object(pool)


@bp.post("/securitization-pools/<ident>/removals")
def remove_loan(ident):
    authenticate(("SecuritizationAnalyst",))
    pool = db.fetch("pools", ident)
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body([
        Field("removal_reason", "enum", True, REMOVAL_REASONS),
        Field("loan_file_id", "str"),
        Field("expected_pool_version", "int", True),
    ])
    reason = values["removal_reason"]
    if reason == "SETTLEMENT_FINALIZED":
        if "loan_file_id" in values:
            invalid("SETTLEMENT_FINALIZED must not name a loan_file_id")
    elif "loan_file_id" not in values:
        invalid("loan_file_id is required for this removal_reason")
    # priority 9
    if int(values["expected_pool_version"]) != int(pool["version"]):
        raise ApiError("ERR_STALE_POOL_VERSION",
                       "expected_pool_version does not match the pool version")
    # priority 16
    pool_state(pool["status"] in ("OPEN", "REBALANCING"),
               "pool status %s accepts no membership write" % pool["status"])
    if reason == "SETTLEMENT_FINALIZED":
        pool_state(pool["status"] == "OPEN" and int(pool["member_loan_count"]) == 0,
                   "settlement finalises an emptied pool")
    # priority 34
    if loan_file is not None and loan_file.get("pool_id") != pool["id"]:
        raise ApiError("ERR_LOAN_NOT_IN_POOL", "the loan is not a member of this pool")

    tx = Tx()
    tx.watch(pool)
    tx.bump(pool)
    if loan_file is not None:
        tx.watch(loan_file)
        loan_file["pool_id"] = None
    if reason == "SETTLEMENT_FINALIZED":
        pool["status"] = "SETTLED"
    services.pool_recompute(pool)
    tx.commit()
    return respond_object(pool)
