"""Derivations, cascades, conserved ledgers and the four-phase sweep.

PRD 2.9: every consequence of a request is applied inside that request,
transitively, and each affected row's updated_at is refreshed and its version
incremented.  Title.version is the documented exception: PRD 2.7 enumerates
exactly which operations bump it, so derived recomputations on a title rewrite
its figures without consuming an optimistic-concurrency token.
"""

from decimal import Decimal

from db import D0, db, dec, new_row, now, q2, rows, stamp_only, touch
from services import calc

# ---------------------------------------------------------------------------
# Title derivations
# ---------------------------------------------------------------------------


def recompute_readiness(title):
    provisional, certified = calc.readiness_scores(title["id"])
    title["readiness_score_provisional"] = provisional
    title["readiness_score_certified"] = certified


def recompute_locked_count(title):
    title["locked_ladder_count"] = len(
        [l for l in calc.title_ladders(title["id"]) if l["state"] == "LOCKED"]
    )


def recompute_budget(title):
    """encode_budget_remaining_usd is a derived ledger (PRD 3.9)."""
    committed = sum(
        (
            dec(job["cost_estimate_usd"])
            for job in calc.title_jobs(title["id"])
            if job["state"] in ("RUNNING", "COMPLETED")
        ),
        D0,
    )
    title["encode_budget_remaining_usd"] = q2(
        dec(title["encode_budget_usd"]) - q2(committed)
    )


def committed_total(title_id):
    return q2(
        sum(
            (
                dec(job["cost_estimate_usd"])
                for job in calc.title_jobs(title_id)
                if job["state"] in ("RUNNING", "COMPLETED")
            ),
            D0,
        )
    )


def close_active_windows(title):
    for window in calc.title_windows(title["id"]):
        if window["state"] == "ACTIVE":
            window["state"] = "CLOSED"
            window["closed_at"] = now()
            touch(window)


def packaging_stale_cascade(title):
    """Hop 5: a PUBLISHED title whose packaging just went STALE is taken down."""
    if title["availability_state"] != "PUBLISHED":
        return False
    title["availability_state"] = "TAKEN_DOWN"
    title["takedown_reason"] = "PACKAGING_STALE"
    close_active_windows(title)
    stamp_only(title)
    return True


def derive_packaging(title, cascade=True):
    """Fixed precedence; REVOKED packages are ignored by every branch."""
    previous = title["packaging_state"]
    packages = calc.title_packages(title["id"])
    if any(p["state"] == "STALE" for p in packages):
        current = "STALE"
    elif any(p["state"] == "PACKAGED" for p in packages):
        current = "PACKAGED"
    elif title["locked_ladder_count"] >= 1:
        current = "PACKAGING"
    else:
        current = "UNPACKAGED"
    title["packaging_state"] = current
    took_down = False
    if cascade and current == "STALE" and previous != "STALE":
        took_down = packaging_stale_cascade(title)
    return previous, current, took_down


# ---------------------------------------------------------------------------
# Ladder lineage
# ---------------------------------------------------------------------------


def supersede_ladder(ladder, replacement_id, title):
    """The SUPERSEDED transition always carries the same consequences."""
    ladder["state"] = "SUPERSEDED"
    ladder["superseded_by_ladder_id"] = replacement_id
    touch(ladder)
    for package in calc.title_packages(title["id"]):
        if package["ladder_id"] == ladder["id"] and package["state"] == "PACKAGED":
            package["state"] = "STALE"
            package["stale_reason"] = "LADDER_SUPERSEDED"
            touch(package)
    recompute_locked_count(title)


# ---------------------------------------------------------------------------
# Vendor ledgers, health and dependent steering
# ---------------------------------------------------------------------------


def refresh_vendor_reserved(vendor):
    vendor["reserved_gbps"] = calc.reserved_ledger(vendor["id"])
    touch(vendor)


def resteer_policy(policy, extra_exclusion=None):
    """Re-runs the selector; available from every policy state."""
    outgoing = policy.get("primary_vendor_id")
    if outgoing and outgoing not in policy["excluded_vendor_ids"]:
        policy["excluded_vendor_ids"].append(outgoing)
    if extra_exclusion and extra_exclusion not in policy["excluded_vendor_ids"]:
        policy["excluded_vendor_ids"].append(extra_exclusion)
    primary, backup, state, reason, _count = calc.select_vendors(
        policy["region_code"], policy["excluded_vendor_ids"], policy["steering_mode"]
    )
    policy["primary_vendor_id"] = primary
    policy["backup_vendor_id"] = backup
    policy["state"] = state
    policy["selection_reason_code"] = reason
    policy["resteer_count"] = policy["resteer_count"] + 1
    policy["projected_egress_cost_usd"] = calc.egress_projection(policy)
    touch(policy)


def refresh_vendor_health(vendor):
    """Rewrites both health variants, then runs the vendor state machine."""
    rolling, contract, breaches = calc.vendor_health(vendor["id"])
    vendor["health_score_rolling"] = rolling
    vendor["health_score_contract"] = contract
    vendor["breach_window_count"] = breaches
    previous = vendor["state"]
    current = previous
    # The drain arm is evaluated first.
    if breaches >= calc.BREACH_COUNT_DRAIN and previous in ("ACTIVE", "DEGRADED"):
        current = "DRAINED"
    elif previous == "ACTIVE" and rolling < calc.DEGRADE_FLOOR:
        current = "DEGRADED"
    elif previous == "DEGRADED" and rolling >= calc.RECOVERY_FLOOR:
        current = "ACTIVE"
    vendor["state"] = current
    touch(vendor)
    if current != previous and current in ("DEGRADED", "DRAINED"):
        for policy in rows(db.policies):
            if policy.get("primary_vendor_id") == vendor["id"]:
                resteer_policy(policy, extra_exclusion=vendor["id"])
    return previous, current


# ---------------------------------------------------------------------------
# Ladder construction shared by authoring and by job completion
# ---------------------------------------------------------------------------


def build_ladder(title_id, codec_family, rungs, derived_from_ladder_id, state,
                 validation_reason_code):
    ladder = new_row()
    ladder["title_id"] = title_id
    ladder["codec_family"] = codec_family
    ladder["rungs"] = [dict(r) for r in rungs]
    ladder["rung_count"] = len(rungs)
    ladder["peak_bitrate_kbps"] = max(r["bitrate_kbps"] for r in rungs)
    ladder["peak_height_px"] = max(r["height_px"] for r in rungs)
    ladder["state"] = state
    ladder["device_compat_score"] = q2(0)
    ladder["compatible_device_count"] = 0
    ladder["validation_reason_code"] = validation_reason_code
    ladder["derived_from_ladder_id"] = derived_from_ladder_id
    ladder["superseded_by_ladder_id"] = None
    db.ladders[ladder["id"]] = ladder
    return ladder


def complete_job(job):
    """Phase 3 completion: the depth-4 result-ladder cascade (PRD 3.9)."""
    title = db.titles[job["title_id"]]
    source = db.ladders.get(job["source_ladder_id"])
    result = build_ladder(
        title["id"], job["target_codec_family"], source["rungs"],
        source["id"], "LOCKED", "OK",
    )
    recompute_locked_count(title)
    supersede_ladder(source, result["id"], title)
    job["state"] = "COMPLETED"
    job["result_ladder_id"] = result["id"]
    touch(job)
    took_down = derive_packaging(title)[2]
    recompute_readiness(title)
    return took_down


def fail_job(job):
    """Phase 3 failure: the run debit is compensated, restoring the invariant."""
    title = db.titles[job["title_id"]]
    job["state"] = "FAILED"
    job["abort_reason"] = "ENCODE_FAILURE"
    job["committed_usd"] = q2(0)
    touch(job)
    recompute_budget(title)


# ---------------------------------------------------------------------------
# The four-phase availability sweep (PRD 2.5)
# ---------------------------------------------------------------------------


def run_sweep():
    moment = now()
    counts = {
        "windows_activated": 0,
        "windows_closed": 0,
        "reservations_started": 0,
        "reservations_ended": 0,
        "jobs_completed": 0,
        "jobs_failed": 0,
        "titles_published": 0,
        "titles_taken_down": 0,
        "titles_expired": 0,
    }
    settled = set()

    # Phase 1 -- licensing windows.
    for window in rows(db.windows):
        state = window["state"]
        if state == "SCHEDULED" and window["window_end_at"] <= moment:
            window["state"] = "CLOSED"
            window["closed_at"] = moment
            touch(window)
            counts["windows_closed"] += 1
        elif state == "SCHEDULED" and window["window_start_at"] <= moment < window["window_end_at"]:
            window["state"] = "ACTIVE"
            window["activated_at"] = moment
            touch(window)
            counts["windows_activated"] += 1
        elif state == "ACTIVE" and window["window_end_at"] <= moment:
            window["state"] = "CLOSED"
            window["closed_at"] = moment
            touch(window)
            counts["windows_closed"] += 1

    # Phase 2 -- live reservations.  A RESERVED reservation is never started.
    for reservation in rows(db.reservations):
        state = reservation["state"]
        if state == "ARMED" and reservation["window_start_at"] <= moment < reservation["window_end_at"]:
            reservation["state"] = "LIVE"
            touch(reservation)
            counts["reservations_started"] += 1
        elif state in ("LIVE", "FAILED_OVER") and reservation["window_end_at"] <= moment:
            reservation["state"] = "ENDED"
            reservation["released_gbps"] = q2(reservation["reserved_gbps"])
            touch(reservation)
            carrier = db.vendors.get(reservation["active_vendor_id"])
            if carrier is not None:
                refresh_vendor_reserved(carrier)
            counts["reservations_ended"] += 1

    # Phase 3 -- reprocessing jobs.
    for job in rows(db.jobs):
        if job["state"] != "RUNNING":
            continue
        source = db.ladders.get(job["source_ladder_id"])
        if source is not None and source["state"] == "LOCKED":
            if complete_job(job):
                counts["titles_taken_down"] += 1
                settled.add(job["title_id"])
            counts["jobs_completed"] += 1
        else:
            fail_job(job)
            counts["jobs_failed"] += 1

    # Phase 4 -- at most one availability transition per title.
    for title in rows(db.titles):
        if title["id"] in settled:
            continue
        windows = calc.title_windows(title["id"])
        has_active = any(w["state"] == "ACTIVE" for w in windows)
        packaged = title["packaging_state"] == "PACKAGED"
        certified_ok = dec(title["readiness_score_certified"]) >= calc.READINESS_GATE
        expirable = (
            len(windows) >= 1
            and all(w["state"] in ("CLOSED", "CANCELLED") for w in windows)
            and moment >= max(w["window_end_at"] for w in windows)
        )
        state = title["availability_state"]
        fired = None
        if state == "SCHEDULED":
            if has_active and packaged and certified_ok:
                title["availability_state"] = "PUBLISHED"
                title["takedown_reason"] = "NONE"
                fired = "titles_published"
            elif expirable:
                title["availability_state"] = "EXPIRED"
                fired = "titles_expired"
        elif state == "PUBLISHED":
            if not has_active and packaged:
                title["availability_state"] = "TAKEN_DOWN"
                title["takedown_reason"] = "CONTRACT_END"
                fired = "titles_taken_down"
        elif state == "TAKEN_DOWN":
            if title["takedown_reason"] != "MANUAL_LEGAL" and has_active and packaged and certified_ok:
                title["availability_state"] = "PUBLISHED"
                title["takedown_reason"] = "NONE"
                fired = "titles_published"
            elif expirable:
                title["availability_state"] = "EXPIRED"
                fired = "titles_expired"
        if fired:
            title["last_sweep_at"] = moment
            stamp_only(title)
            counts[fired] += 1
    return counts
