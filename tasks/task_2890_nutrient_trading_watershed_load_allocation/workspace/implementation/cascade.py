"""Multi-resource cascades: transaction voiding, project revocation and the
watershed unwinding run by suspension, termination and an OFF_TRACK review."""
from calc import (
    batches_of_project,
    credit_applied_total,
    reconcile,
    rows_where,
    watershed_of_project,
)
from store import D0, ZERO2, db, dec, now_iso, q2, q4, sorted_rows, touch


def watershed_of_batch(batch):
    project = db.practice_projects.get(batch["practice_project_id"])
    return watershed_of_project(project) if project else None


def open_transactions_of_batch(batch_id):
    rows = [
        t
        for t in db.credit_transactions.values()
        if t["credit_batch_id"] == batch_id and t["status"] in ("PROPOSED", "APPROVED")
    ]
    return sorted_rows(rows)


def void_transaction(txn, void_reason, touched):
    """Void one transaction and unwind its batch, watershed and permit effects."""
    prior = txn["status"]
    batch = db.credit_batches.get(txn["credit_batch_id"])
    permit = db.permits.get(txn["permit_id"])
    watershed = watershed_of_batch(batch) if batch else None

    txn["status"] = "VOIDED"
    txn["void_reason"] = void_reason
    txn["voided_at"] = now_iso()
    touch(txn, touched)

    invalidated = void_reason == "BATCH_INVALIDATED"

    if prior == "PROPOSED":
        if batch is not None and not invalidated:
            requested = dec(txn["requested_gross_lbs"])
            batch["reserved_lbs"] = q2(dec(batch["reserved_lbs"]) - requested)
            batch["available_lbs"] = q2(dec(batch["available_lbs"]) + requested)
            touch(batch, touched)
        return txn

    if prior == "APPROVED":
        settled = dec(txn["settled_gross_lbs"] or 0)
        if batch is not None:
            batch["retired_lbs"] = q2(dec(batch["retired_lbs"]) - settled)
            if invalidated:
                batch["invalidated_lbs"] = q2(dec(batch["invalidated_lbs"]) + settled)
            else:
                batch["available_lbs"] = q2(dec(batch["available_lbs"]) + settled)
            touch(batch, touched)
        if watershed is not None:
            watershed["reserve_pool_lbs"] = q2(
                dec(watershed["reserve_pool_lbs"]) - dec(txn["retired_to_reserve_lbs"])
            )
            touch(watershed, touched)
        if permit is not None:
            reconcile(
                permit,
                "void_invalidated" if invalidated else "void_release",
                touched,
            )
    return txn


# --------------------------------------------------------------------------
# reverification effects on the registry
# --------------------------------------------------------------------------
def restate_verified_ratio(project, ratio, touched):
    for batch in batches_of_project(project["id"], ("ISSUED", "LISTED")):
        batch["verified_ratio"] = q4(ratio)
        touch(batch, touched)


def revoke_project_cascade(project, touched):
    """The four-link cascade run by a failing reverification finding."""
    batches = batches_of_project(project["id"], ("ISSUED", "LISTED"))
    for batch in batches:
        batch["invalidated_lbs"] = q2(
            dec(batch["invalidated_lbs"]) + dec(batch["available_lbs"]) + dec(batch["reserved_lbs"])
        )
        batch["available_lbs"] = ZERO2
        batch["reserved_lbs"] = ZERO2
        batch["status"] = "INVALIDATED"
        touch(batch, touched)

    victims = []
    for batch in batches:
        victims.extend(open_transactions_of_batch(batch["id"]))
    for txn in sorted_rows(victims):
        void_transaction(txn, "BATCH_INVALIDATED", touched)
    return len(victims)


# --------------------------------------------------------------------------
# watershed unwinding
# --------------------------------------------------------------------------
def unwind_watershed(watershed, touched):
    """Voids every open and settled trade whose buyer permit sits here."""
    permit_ids = set(p["id"] for p in rows_where(db.permits, watershed_id=watershed["id"]))
    victims = [
        t
        for t in db.credit_transactions.values()
        if t["permit_id"] in permit_ids and t["status"] in ("PROPOSED", "APPROVED")
    ]
    victims = sorted_rows(victims)
    for txn in victims:
        void_transaction(txn, "ADAPTIVE_HOLD", touched)
    return len(victims)
