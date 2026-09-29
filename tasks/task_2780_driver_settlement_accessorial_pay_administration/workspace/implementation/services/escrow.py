"""The append-only maintenance-escrow ledger and the balance-driven escrow axis
(PRD section 3.3)."""
import clock
import db
import queries


def append(
    driver,
    txn_type,
    amount_cents,
    reason_code,
    recorded_by_user_id,
    settlement_id=None,
    reverses_transaction_id=None,
    document_ref=None,
):
    """Append a ledger entry and record the balance observed right after it."""
    entry = {
        "driver_id": driver["id"],
        "settlement_id": settlement_id,
        "reverses_transaction_id": reverses_transaction_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
        "reason_code": reason_code,
        "document_ref": document_ref,
        "recorded_by_user_id": recorded_by_user_id,
        "balance_after_cents": 0,
    }
    db.stamp_log(entry)
    db.escrow_transactions[entry["id"]] = entry
    entry["balance_after_cents"] = queries.escrow_balance(driver["id"])
    return entry


def drive_axis(driver):
    """The balance itself drives COLLECTING <-> FUNDED, a cycle in both directions.

    Returns the number of extra version bumps the transition earned (0 or 1); the
    caller owns the bump for its own operation.
    """
    balance = queries.escrow_balance(driver["id"])
    target = driver.get("escrow_target_cents") or 0
    status = driver.get("escrow_status")

    if status == "COLLECTING" and balance >= target:
        driver["escrow_status"] = "FUNDED"
        driver["escrow_funded_at"] = clock.now()
        return 1
    if status == "FUNDED" and balance < target:
        driver["escrow_status"] = "COLLECTING"
        driver["escrow_funded_at"] = None
        return 1
    return 0
