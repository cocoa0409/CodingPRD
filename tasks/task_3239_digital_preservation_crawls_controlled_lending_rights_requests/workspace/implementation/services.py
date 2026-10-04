"""Business services: waitlist promotion, loan cascades, work availability,
capture dedupe/storage cost, suppression coverage, grant recompute, sweep."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import db
from models import grant_counters, item_lendable, new_id, stamp_new, touch, work_availability
from response import iso_z

ESTIMATED_BYTES_PER_CAPTURE = 524288
TIER1_CAP_BYTES = 1_000_000_000


# ---- waitlist promotion (calculations.waitlist_promotion) ----

def run_promotion(work_id):
    """One promotion run: at most one offer per work per run. Returns the
    promoted entry or None."""
    candidates = [
        it for it in db.items.values()
        if it["work_id"] == work_id and item_lendable(it)
    ]
    if not candidates:
        return None
    open_entries = sorted(
        (e for e in db.waitlist_entries.values()
         if e["work_id"] == work_id and e["status"] == "OPEN"),
        key=lambda e: e["created_at"],
    )
    for entry in open_entries:
        p = db.patrons.get(entry["patron_id"])
        if p is None:
            continue
        if p["status"] != "ACTIVE":
            # Terminal ineligibility: cascade of patron standing.
            entry["status"] = "CANCELLED"
            touch(entry)
            continue
        max_loans = 50 if any(
            c["patron_id"] == p["id"] and c["status"] == "VERIFIED"
            for c in db.credentials.values()
        ) else 5
        if p["active_loan_count"] >= max_loans:
            continue  # transient skip
        entry["status"] = "OFFERED"
        entry["offered_at"] = iso_z(db.now())
        entry["offer_expires_at"] = iso_z(db.now() + timedelta(hours=48))
        touch(entry)
        return entry
    return None


# ---- loan lifecycle cascades ----

def end_loan(loan, new_status, retirement_trigger=False, defer_promotion=False):
    """Shared cascade for RETURNED / EXPIRED / REVOKED. Assumes loan is ACTIVE.
    Returns True if the patron was newly suspended by this cascade.

    When defer_promotion is True, the per-work promotion run is skipped; the
    caller (e.g. the availability recompute) runs promotion itself after any
    availability flip has taken effect, so promotion always sees the item's
    final `lendable` projection."""
    item = db.items.get(loan["item_id"])
    patron = db.patrons.get(loan["patron_id"])
    loan["status"] = new_status
    touch(loan)
    if item is not None:
        if retirement_trigger:
            item["status"] = "RETIRED"
        else:
            item["status"] = "LENDABLE"
        touch(item)
    if patron is not None:
        patron["active_loan_count"] = max(0, patron["active_loan_count"] - 1)
        touch(patron)
    work_id = item["work_id"] if item else None
    newly_suspended = False
    if new_status == "EXPIRED" and patron is not None:
        patron["strike_count"] = patron["strike_count"] + 1
        touch(patron)
        if patron["strike_count"] == 3 and patron["status"] == "ACTIVE":
            patron["status"] = "SUSPENDED"
            touch(patron)
            newly_suspended = True
            # Cascade hop 4: cancel the patron's OFFERED waitlist entries.
            for e in db.waitlist_entries.values():
                if e["patron_id"] == patron["id"] and e["status"] == "OFFERED":
                    e["status"] = "CANCELLED"
                    touch(e)
    if work_id is not None and not defer_promotion:
        run_promotion(work_id)
    return newly_suspended


# ---- work availability / rights cascades ----

def recompute_work_availability_and_effects(work_id):
    """Recompute availability from rights requests; apply side effects of
    hard withdrawal (loan revocation) and of recovery (item re-promotion)."""
    work = db.works.get(work_id)
    if work is None:
        return
    new_avail = work_availability(work)
    prev_avail = work.get("_availability_cache", "AVAILABLE")
    work["_availability_cache"] = new_avail
    touch(work)
    if new_avail == "WITHDRAWN" and prev_avail != "WITHDRAWN":
        # Hard withdrawal: revoke every ACTIVE loan on the work's items.
        # Promotion is deferred until after the availability cache flip above
        # so the supply check sees the withdrawn work (lendable leg false).
        for it in list(db.items.values()):
            if it["work_id"] != work_id:
                continue
            for loan in list(db.loans.values()):
                if loan["item_id"] == it["id"] and loan["status"] == "ACTIVE":
                    end_loan(loan, "REVOKED", defer_promotion=True)
        run_promotion(work_id)
    elif new_avail == "AVAILABLE" and prev_avail != "AVAILABLE":
        # Recovery: re-evaluate DEPOSITED items in sealed batches.
        for it in list(db.items.values()):
            if it["work_id"] != work_id or it["status"] != "DEPOSITED":
                continue
            batch = db.batches.get(it["batch_id"])
            lib = db.libraries.get(it["owning_library_id"])
            if batch and batch["status"] == "SEALED" and lib and lib["status"] == "ACTIVE":
                it["status"] = "LENDABLE"
                touch(it)
                run_promotion(work_id)


def withdraw_work_effects(work_id):
    """Force availability WITHDRAWN side effects (escalate-hold / uphold)."""
    recompute_work_availability_and_effects(work_id)


def capture_is_suppressed_by_rights(url):
    return any(
        r["subject_kind"] == "CAPTURE_URL_PREFIX"
        and r["status"] in ("LEGAL_HOLD", "UPHELD_REMOVED")
        and r.get("url_prefix")
        and url.startswith(r["url_prefix"])
        for r in db.rights_requests.values()
    )


def capture_is_suppressed_by_directive(url):
    return any(
        d["status"] == "ACTIVE"
        and d["scope"] in ("PLAYBACK_ONLY", "BOTH")
        and url.startswith(d["url_prefix"])
        for d in db.directives.values()
    )


def suppress_captures_by_prefix(url_prefix):
    count = 0
    for c in db.captures.values():
        if c["url"].startswith(url_prefix) and c["playback_status"] == "PLAYABLE":
            c["playback_status"] = "SUPPRESSED"
            count += 1
    return count


def restore_captures_after_retract(url_prefix):
    """After a directive retract: captures covered by that prefix flip back to
    PLAYABLE unless another active directive or upheld rights request covers."""
    for c in db.captures.values():
        if not c["url"].startswith(url_prefix):
            continue
        if c["playback_status"] != "SUPPRESSED":
            continue
        if capture_is_suppressed_by_directive(c["url"]):
            continue
        if capture_is_suppressed_by_rights(c["url"]):
            continue
        c["playback_status"] = "PLAYABLE"


def apply_rights_request_cascade(rr):
    """Apply subject effects when a request enters LEGAL_HOLD or
    UPHELD_REMOVED, or availability recovery on DISMISS."""
    if rr["subject_kind"] == "WORK":
        recompute_work_availability_and_effects(rr["work_id"])
    else:
        if rr["status"] in ("LEGAL_HOLD", "UPHELD_REMOVED"):
            suppress_captures_by_prefix(rr["url_prefix"])


# ---- capture dedupe & storage cost ----

def compute_storage_cost_cents(job):
    unique_count = sum(
        1 for c in db.captures.values() if c["crawl_job_id"] == job["id"]
    )
    bytes_total = unique_count * ESTIMATED_BYTES_PER_CAPTURE
    t1 = min(bytes_total, TIER1_CAP_BYTES)
    t2 = max(0, bytes_total - TIER1_CAP_BYTES)
    c1 = (Decimal(t1) * 3 / Decimal(1_000_000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    c2 = (Decimal(t2) * 1 / Decimal(1_000_000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(c1 + c2)


def refresh_job_metrics(job):
    job["captures_produced"] = sum(
        1 for c in db.captures.values() if c["crawl_job_id"] == job["id"]
    )
    job["storage_cost_cents"] = compute_storage_cost_cents(job)


# ---- grants ----

def recompute_grant(grant, bump_version=True):
    reserved, spent = grant_counters(grant["id"])
    grant["reserved_cents"] = reserved
    grant["spent_cents"] = spent
    if grant["status"] in ("OPEN", "EXHAUSTED"):
        grant["status"] = (
            "EXHAUSTED" if reserved + spent >= grant["amount_cents"] else "OPEN"
        )
    if bump_version:
        touch(grant)
