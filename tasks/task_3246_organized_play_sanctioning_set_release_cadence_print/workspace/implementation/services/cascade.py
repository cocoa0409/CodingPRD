"""Shared cascade and allocation-mutation helpers (§3.1, §3.5, §3.7, §3.8).

Row creation during a multi-entity side effect does not call `touch()`: a new
row already carries its own timestamps and version 1 at creation. Only rows
that are *modified* by a cascade are touched, so each affected child gets its
own `updated_at` refresh and its own version bump.
"""

import db as store
import computed as calcs


# --------------------------------------------------------------------------
# Pool counters
# --------------------------------------------------------------------------

def rederive_allocation(allocation):
    """Authoritative re-derivation of the pool's restored total.

    Used by the close and suspend cascades only. total_drawn_tp is left exactly
    where it was — a close is a compensating restore, not a settlement that
    unwinds the draw. total_restored_tp is re-derived from the full set of
    voided distributions, filed/overdue reports and disbursed grants rather
    than incremented, so ALLOC_INVARIANT returns to its pre-draw figure: for a
    pool released by suspension that figure is exactly 0 unless a physical
    grant had previously been disbursed, and re-deriving twice is idempotent.
    """
    drawn = allocation["total_drawn_tp"]
    allocation["total_restored_tp"] = calcs.rederived_restored_total(
        allocation["id"], allocation["tier"])
    allocation["remaining_tp"] = allocation["base_tp"] - drawn + allocation["total_restored_tp"]
    store.touch(allocation)


def refresh_allocation(allocation):
    """Alias kept for the close/suspend paths."""
    rederive_allocation(allocation)


def void_passed_distributions(allocation_id):
    """Void every still-PASSED distribution under a pool.

    Returns the rows that changed; each is touched individually so it carries
    its own timestamp and concurrency bump.
    """
    changed = []
    for dist in store.distributions_of(allocation_id):
        if dist["status"] == "PASSED":
            store.touch(dist, status="VOIDED")
            changed.append(dist)
    return changed


# --------------------------------------------------------------------------
# Synthesized reports — the two closure devices
# --------------------------------------------------------------------------

def synthesize_report(application, allocation_id):
    """Create a zero-value PrizeReport for an application with no report yet.

    Both closure devices use this: set-release retirement and format rotation.
    Each synthesizes restores only, and unclaimed_tp is zero, so no pool's
    drawn total moves and no balance changes. The new report's identifier is
    recorded on the application as prize_report_id, because a synthesized
    report is a filed report in every respect — it just declares nothing.
    """
    if application.get("prize_report_id"):
        return None
    if store.reports_for_application(application["id"]):
        return None
    report = store.insert_prize_report(application["id"], allocation_id, 0, 0, status="FILED")
    application["prize_report_id"] = report["id"]
    return report


# --------------------------------------------------------------------------
# Store suspension — the program's nuclear option (§3.1)
# --------------------------------------------------------------------------

def suspend_store(store_row):
    """Deny the store's live applications and release its open pools.

    Applications in SUBMITTED / APPROVED / COMPLETED are denied outright, and
    each keeps whatever prizing_report_status it already held rather than being
    reset. Reinstatement reverses none of this.
    """
    for application in store.applications_of_store(store_row["id"]):
        if application["status"] in ("SUBMITTED", "APPROVED", "COMPLETED"):
            store.touch(application, status="DENIED")

    for allocation in store.allocations_of_store(store_row["id"]):
        if allocation["status"] == "OPEN":
            store.touch(allocation, status="RELEASED")
            void_passed_distributions(allocation["id"])
            refresh_allocation(allocation)


# --------------------------------------------------------------------------
# Set-release retirement (§3.7)
# --------------------------------------------------------------------------

def retire_set_release(release):
    """Close out everything still hanging on the retiring release.

    SUBMITTED / APPROVED applications move to COMPLETED; DUE or NOT_DUE
    reporting columns move to SUBMITTED with a synthesized zero-value report.
    Pools citing the release close, voiding their passed distributions.
    """
    for application in store.applications_of_set_release(release["id"]):
        if application["status"] in ("SUBMITTED", "APPROVED"):
            store.touch(application, status="COMPLETED")
        if application["prizing_report_status"] in ("DUE", "NOT_DUE"):
            allocation_id = application.get("prize_allocation_id")
            if allocation_id:
                synthesize_report(application, allocation_id)
            # The synthesized report's id lands on the application as part of
            # the same column flip, so it is not lost by a later touch.
            store.touch(application, prizing_report_status="SUBMITTED")

    for allocation in store.db.prize_allocations.values():
        if allocation["status"] != "OPEN":
            continue
        parent = store.db.event_applications.get(allocation["event_application_id"])
        if parent is None or parent["set_release_id"] != release["id"]:
            continue
        store.touch(allocation, status="CLOSED")
        void_passed_distributions(allocation["id"])
        refresh_allocation(allocation)


# --------------------------------------------------------------------------
# Format rotation and list updates (§3.8)
# --------------------------------------------------------------------------

def close_denied_application_pools(format_id):
    """Deny every APPROVED application citing the format and close its pool."""
    for application in store.applications_of_format(format_id):
        if application["status"] != "APPROVED":
            continue
        store.touch(application, status="DENIED")
        allocation_id = application.get("prize_allocation_id")
        if not allocation_id:
            continue
        allocation = store.db.prize_allocations.get(allocation_id)
        if allocation is None or allocation["status"] != "OPEN":
            continue
        store.touch(allocation, status="CLOSED")
        void_passed_distributions(allocation["id"])
        refresh_allocation(allocation)


def rotate_format(format_row):
    """Reject the format's approved reprint plans and close out unreported events.

    A rotation pulls any COMPLETED application citing the format that is still
    NOT_DUE straight to SUBMITTED / REPORTED with a synthesized zero-value
    report, then re-derives the owning store's reporting tier.
    """
    format_row["current_epoch"] = format_row["current_epoch"] + 1
    store.touch(format_row)

    for plan in store.plans_of_format(format_row["id"]):
        if plan["status"] == "APPROVED":
            store.touch(plan, status="REJECTED")

    touched_stores = []
    for application in store.applications_of_format(format_row["id"]):
        if application["status"] != "COMPLETED":
            continue
        if application["prizing_report_status"] != "NOT_DUE":
            continue
        allocation_id = application.get("prize_allocation_id")
        if allocation_id:
            synthesize_report(application, allocation_id)
        store.touch(application, status="REPORTED", prizing_report_status="SUBMITTED")
        touched_stores.append(application["store_id"])

    for store_id in touched_stores:
        derive_store_tier(store_id)


# --------------------------------------------------------------------------
# Store reporting tier (§3.1)
# --------------------------------------------------------------------------

def derive_store_tier(store_id):
    """Re-derive Store.reporting_tier. Returns the new tier, or None."""
    store_row = store.db.stores.get(store_id)
    if store_row is None:
        return None
    tier = calcs.store_reporting_tier(store_id)
    if store_row["reporting_tier"] != tier:
        store.touch(store_row, reporting_tier=tier)
    return tier


# --------------------------------------------------------------------------
# Physical grant disbursement (§3.11)
# --------------------------------------------------------------------------

def disburse_physical_grant(redemption, application, allocation):
    """Move the grant's floored value on both sides at once.

    total_drawn_tp += floor(card_value) and total_restored_tp += the identical
    floored amount in one transaction, so the conserved invariant over the pool
    is bit-for-bit what it was before the disbursement.
    """
    grant_value = calcs.physical_grant_value(allocation["tier"])
    allocation["total_drawn_tp"] = allocation["total_drawn_tp"] + grant_value
    allocation["total_restored_tp"] = allocation["total_restored_tp"] + grant_value
    return grant_value


# --------------------------------------------------------------------------
# Street-date settlement (§3.7)
# --------------------------------------------------------------------------

def settle_street_date(release, applications):
    """Street-date settlement: no draw-down on any pool.

    `applications` are the applications on this release at the instant the
    clock crossed the street date. Every non-LOCAL APPROVED application has its
    reporting deadline stamped from the street date, and every APPROVED
    application whose prizing_report_status is still NOT_DUE is moved to DUE,
    opening its reporting window. In every case total_drawn_tp stays 0 and
    every allocation created before the street date still satisfies
    remaining_tp == base_tp.
    """
    for application in applications:
        if application["status"] != "APPROVED":
            continue
        if application["tier"] != "LOCAL":
            application["reporting_due_by"] = calcs.reporting_due_by(
                application["tier"], release["street_date"])
            store.touch(application)
        if application["prizing_report_status"] == "NOT_DUE":
            store.touch(application, prizing_report_status="DUE")