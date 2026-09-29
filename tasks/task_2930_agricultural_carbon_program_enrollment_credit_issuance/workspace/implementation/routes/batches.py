"""Credit batch registry custody and the programme buffer pool (sections 3.8, 2.12)."""

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import common, serialize

bp = Blueprint("batches", __name__)

BATCH_FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "quantification_run_id": ("quantification_run_id", "str"),
    "supersedes_batch_id": ("supersedes_batch_id", "str"),
    "vintage_year": ("vintage_year", "int"),
    "issuance_status": ("issuance_status", "str"),
    "registry_status": ("registry_status", "str"),
    "risk_tier": ("risk_tier", "str"),
}

POOL_FILTERS = {
    "pool_code": ("pool_code", "str"),
    "pool_status": ("pool_status", "str"),
}

BATCH_READ_ROLES = (
    mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER,
)
POOL_READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_REGISTRY_OFFICER)


@bp.route("/credit-batches", methods=["GET"])
def list_batches():
    mw.authorize(*BATCH_READ_ROLES)
    rows = common.apply_filters(db.credit_batches.values(), BATCH_FILTERS)
    return resp.paginate(rows, serialize.credit_batch)


@bp.route("/credit-batches/<credit_batch_id>", methods=["GET"])
def read_batch(credit_batch_id):
    mw.authorize(*BATCH_READ_ROLES)
    row = common.get_credit_batch(credit_batch_id)
    mw.require_grower_owner(common.batch_grower_id(row))
    return resp.object_response(serialize.credit_batch(row))


@bp.route("/credit-batches/<credit_batch_id>/list", methods=["POST"])
def list_on_registry(credit_batch_id):
    mw.authorize(mw.ROLE_REGISTRY_OFFICER)
    batch = common.get_credit_batch(credit_batch_id)
    body = v.json_body()
    registry_account_ref = v.v_str(body, "registry_account_ref")

    if batch["registry_status"] != "UNLISTED" or batch["issuance_status"] != "ISSUED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an UNLISTED batch whose issuance_status is ISSUED may be listed.",
        )

    predecessor_id = batch["supersedes_batch_id"]
    if predecessor_id is not None:
        predecessor = db.credit_batches.get(predecessor_id)
        if predecessor is not None and predecessor["issuance_status"] != "CANCELLED":
            common.fail("ERR_SUPERSEDED_BATCH_NOT_CANCELLED")

    batch["registry_account_ref"] = registry_account_ref
    batch["registry_status"] = "LISTED"
    db.touch(batch)
    return resp.object_response(serialize.credit_batch(batch))


@bp.route("/credit-batches/<credit_batch_id>/retire", methods=["POST"])
def retire_batch(credit_batch_id):
    mw.authorize(mw.ROLE_REGISTRY_OFFICER)
    batch = common.get_credit_batch(credit_batch_id)
    body = v.json_body()
    retirement_beneficiary = v.v_str(body, "retirement_beneficiary")

    if batch["registry_status"] != "LISTED" or batch["issuance_status"] != "ISSUED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a LISTED batch whose issuance_status is ISSUED may be retired.",
        )

    for event in db.reversal_events.values():
        if event["credit_batch_id"] == batch["id"] and event["status"] in ("REPORTED", "ASSESSED"):
            common.fail("ERR_UNRESOLVED_REVERSAL")

    batch["retirement_beneficiary"] = retirement_beneficiary
    batch["registry_status"] = "RETIRED"
    db.touch(batch)

    pool = db.buffer_pool()
    pool["outstanding_issued_credits"] = (
        pool["outstanding_issued_credits"] - batch["issued_credits"]
    )
    common.recompute_pool(pool)
    db.touch(pool)

    return resp.object_response(serialize.credit_batch(batch))


@bp.route("/credit-batches/<credit_batch_id>/cancel", methods=["POST"])
def cancel_batch(credit_batch_id):
    mw.authorize(mw.ROLE_REGISTRY_OFFICER)
    batch = common.get_credit_batch(credit_batch_id)
    body = v.json_body()
    cancellation_reason = v.v_str(body, "cancellation_reason")
    expected_version = v.v_int(body, "expected_credit_batch_version")

    if batch["issuance_status"] != "ISSUED" or batch["registry_status"] == "RETIRED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Only an ISSUED batch that has not been retired may be cancelled.",
        )

    if expected_version != batch["version"]:
        common.fail("ERR_STALE_BATCH_VERSION")

    batch["cancellation_reason"] = cancellation_reason
    batch["issuance_status"] = "CANCELLED"
    db.touch(batch)

    # compensation hop 1 -- the pool, but never the serial cursor
    pool = db.buffer_pool()
    pool["released_total"] = pool["released_total"] + batch["buffer_credits"]
    pool["balance_credits"] = pool["balance_credits"] - batch["buffer_credits"]
    pool["contributed_total"] = pool["contributed_total"] - batch["buffer_credits"]
    pool["outstanding_issued_credits"] = (
        pool["outstanding_issued_credits"] - batch["issued_credits"]
    )
    common.recompute_pool(pool)
    db.touch(pool)

    # compensation hop 2 -- the credit aggregates
    enrollment = db.enrollments.get(batch["enrollment_id"])
    if enrollment is not None:
        grower = db.growers.get(enrollment["grower_id"])
        if grower is not None:
            grower["lifetime_credits_issued"] = (
                grower["lifetime_credits_issued"] - batch["issued_credits"]
            )
            db.touch(grower)
        enrollment["credits_issued_total"] = (
            enrollment["credits_issued_total"] - batch["issued_credits"]
        )
        db.touch(enrollment)

        # compensation hop 3 -- accrued payments naming this batch are voided
        for payment in common.enrollment_payments(enrollment["id"]):
            if payment["credit_batch_id"] != batch["id"] or payment["status"] != "ACCRUED":
                continue
            payment["status"] = "VOID"
            db.touch(payment)
            enrollment["accrued_payment_cents"] = (
                enrollment["accrued_payment_cents"] - payment["net_amount_cents"]
            )
            db.touch(enrollment)

    return resp.object_response(serialize.credit_batch(batch))


@bp.route("/buffer-accounts", methods=["GET"])
def list_pools():
    mw.authorize(*POOL_READ_ROLES)
    db.buffer_pool()
    rows = common.apply_filters(db.buffer_accounts.values(), POOL_FILTERS)
    return resp.paginate(rows, serialize.buffer_account)


@bp.route("/buffer-accounts/<buffer_account_id>", methods=["GET"])
def read_pool(buffer_account_id):
    mw.authorize(*POOL_READ_ROLES)
    row = common.get_buffer_account(buffer_account_id)
    return resp.object_response(serialize.buffer_account(row))
