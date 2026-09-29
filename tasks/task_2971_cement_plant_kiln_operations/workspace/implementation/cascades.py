"""Multi-hop cascades (PRD 2.12, 3.6, 3.8, 3.9).

Every hop is applied in the order PRD states, because later hops read the
figures earlier hops leave behind, and every row a hop touches has its `version`
incremented and its `updated_at` refreshed (PRD 2.12).
"""

from core import D, r2, now, get_row, rows, ordered, touch
import calc


# ---------------------------------------------------------------------------
# feed reconciliation — hops two and three of the release cascade (PRD 3.6),
# reused verbatim by silo unblocking (PRD 3.8)
# ---------------------------------------------------------------------------
def _planned_batches_on(clinker_silo_id):
    return ordered([
        b for b in rows("batches")
        if b["clinker_silo_id"] == clinker_silo_id and b["status"] == "PLANNED"
    ])


def reconcile_feed_up(silo):
    """FEED_SHORT batches recover in created_at ASC while headroom lasts."""
    for batch in _planned_batches_on(silo["id"]):
        if batch["feed_state"] != "FEED_SHORT":
            continue
        if D(batch["clinker_tonnes_drawn"]) <= D(calc.silo_available(silo)):
            batch["feed_state"] = "FEED_READY"
            touch(batch)
            silo["reserved_tonnes"] = r2(
                D(silo["reserved_tonnes"]) + D(batch["clinker_tonnes_drawn"])
            )
            touch(silo)


def withdraw_feed_down(silo):
    """PLANNED batches whose draw no longer fits lose their reservation."""
    for batch in _planned_batches_on(silo["id"]):
        if batch["feed_state"] != "FEED_READY":
            continue
        if D(batch["clinker_tonnes_drawn"]) > D(calc.silo_available(silo)):
            batch["feed_state"] = "FEED_SHORT"
            touch(batch)
            silo["reserved_tonnes"] = r2(
                D(silo["reserved_tonnes"]) - D(batch["clinker_tonnes_drawn"])
            )
            touch(silo)


# ---------------------------------------------------------------------------
# clinker release / re-quarantine (PRD 3.6)
# ---------------------------------------------------------------------------
def release_clinker_cascade(run, silo):
    """Hop one: unreleased shrinks. Hop two: FEED_SHORT batches recover.
    Hop three: posture returns to NORMAL (a computed summary)."""
    silo["unreleased_tonnes"] = r2(
        D(silo["unreleased_tonnes"]) - D(run["clinker_tonnes"])
    )
    touch(silo)
    reconcile_feed_up(silo)


def requarantine_cascade(run, silo):
    """Hop one: unreleased grows again. Hop two: over-promised batches fall to
    FEED_SHORT. Hop three: posture becomes CONSTRAINED (computed)."""
    silo["unreleased_tonnes"] = r2(
        D(silo["unreleased_tonnes"]) + D(run["clinker_tonnes"])
    )
    touch(silo)
    withdraw_feed_down(silo)


# ---------------------------------------------------------------------------
# silo blocking / unblocking (PRD 3.8)
# ---------------------------------------------------------------------------
def cancel_orders_on_silo(silo, reason):
    """Open orders on a blocked CEMENT silo become CANCELLED_BY_QUALITY."""
    affected_customers = []
    for order in ordered([o for o in rows("orders")
                          if o["cement_silo_id"] == silo["id"]]):
        if order["status"] not in ("RESERVED", "LOADING"):
            continue
        order["status"] = "CANCELLED_BY_QUALITY"
        order["void_reason"] = reason
        touch(order)
        silo["reserved_tonnes"] = r2(D(silo["reserved_tonnes"]) - D(order["tonnes"]))
        touch(silo)
        if order["customer_id"] not in affected_customers:
            affected_customers.append(order["customer_id"])
    for customer_id in affected_customers:
        customer = get_row("customers", customer_id)
        if customer is not None:
            touch(customer)


def block_silo(silo, reason):
    silo["status"] = "BLOCKED"
    silo["block_reason"] = reason
    touch(silo)
    if silo["material_kind"] == "CEMENT":
        cancel_orders_on_silo(silo, reason)
    else:
        withdraw_feed_down(silo)


def unblock_silo(silo):
    silo["status"] = "OPEN"
    silo["block_reason"] = None
    touch(silo)
    if silo["material_kind"] == "CLINKER":
        reconcile_feed_up(silo)


# ---------------------------------------------------------------------------
# certificate revocation — the four-hop chain (PRD 3.9)
# ---------------------------------------------------------------------------
def revoke_cascade(certificate):
    batch = get_row("batches", certificate["cement_batch_id"])
    if batch is None:
        return
    # Hop one: the batch is decertified; its allocation drops to 0.00.
    if batch["status"] == "CERTIFIED":
        batch["status"] = "DECERTIFIED"
        touch(batch)
    silo = get_row("silos", batch["cement_silo_id"])
    if silo is None:
        return
    # Hop two: the batch's cement silo is blocked with DECERTIFIED_CEMENT.
    if silo["status"] == "OPEN":
        silo["status"] = "BLOCKED"
        silo["block_reason"] = "DECERTIFIED_CEMENT"
        touch(silo)
    # Hops three and four: open orders are cancelled, customers recomputed.
    cancel_orders_on_silo(silo, "DECERTIFIED_CEMENT")


# ---------------------------------------------------------------------------
# laboratory-driven quality transitions (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
def apply_free_lime_result(run, plant, value):
    """A free-lime reading drives the run's quality dimension directly."""
    ceiling = D(plant["clinker_free_lime_max_pct"])
    reading = D(value)
    if reading > ceiling:
        if run["quality_state"] == "PENDING_LAB":
            run["quality_state"] = "QUARANTINED"
            touch(run)
        elif run["quality_state"] == "RELEASED":
            run["quality_state"] = "QUARANTINED"
            touch(run)
            silo = get_row("silos", run["clinker_silo_id"])
            if silo is not None:
                requarantine_cascade(run, silo)
    else:
        if run["quality_state"] == "QUARANTINED":
            run["quality_state"] = "PENDING_LAB"
            touch(run)


def _qualify_join(batch):
    """The join fires only when the SECOND branch reaches PASSED."""
    if (batch["strength_branch_state"] == "PASSED"
            and batch["fineness_branch_state"] == "PASSED"
            and batch["status"] == "GROUND"):
        batch["status"] = "QUALIFIED"
        batch["qualified_at"] = now()
        touch(batch)
        silo = get_row("silos", batch["cement_silo_id"])
        if silo is not None:
            silo["unreleased_tonnes"] = r2(
                D(silo["unreleased_tonnes"]) - D(batch["cement_tonnes"])
            )
            touch(silo)


def _reject_batch(batch, reason):
    batch["status"] = "REJECTED"
    batch["rejection_reason"] = reason
    touch(batch)


def apply_cement_result(batch, test_type, in_spec):
    """BLAINE and 28-day strength drive the two independent branches."""
    if batch["status"] != "GROUND":
        return
    if test_type == "COMPRESSIVE_STRENGTH_28D":
        if batch["strength_branch_state"] != "PENDING":
            return
        batch["strength_branch_state"] = "PASSED" if in_spec else "FAILED"
        touch(batch)
        if not in_spec:
            _reject_batch(batch, "STRENGTH_OUT_OF_SPEC")
            return
    else:
        if batch["fineness_branch_state"] != "PENDING":
            return
        batch["fineness_branch_state"] = "PASSED" if in_spec else "FAILED"
        touch(batch)
        if not in_spec:
            _reject_batch(batch, "FINENESS_OUT_OF_SPEC")
            return
    _qualify_join(batch)
