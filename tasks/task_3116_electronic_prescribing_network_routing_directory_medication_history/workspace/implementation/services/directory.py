"""Directory derivations: listing, reachability, reliability, service windows."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import ApiError, ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW

# reliability_factor constants (PRD §2.6)
RELIABILITY_WINDOW_N = 20
EWMA_ALPHA = Decimal("0.0670")
DEGRADE_BELOW = Decimal("0.90")
REACTIVATE_AT_LEAST = Decimal("0.95")

TERMINAL_OUTCOMES = ("ACKNOWLEDGED", "REJECTED", "UNDELIVERABLE")
LIVE_ENDPOINT_STATUSES = ("ACTIVE", "DEGRADED")


def round4(value):
    """Round half up to four decimal places."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# directory_listed (§2.4)
# --------------------------------------------------------------------------

def owns_live_endpoint(participant_id):
    return any(
        e["participant_id"] == participant_id and e["status"] in LIVE_ENDPOINT_STATUSES
        for e in db.all_rows("endpoints")
    )


def recompute_directory_listed(participant):
    listed = participant["certification_status"] == "CERTIFIED" and owns_live_endpoint(participant["id"])
    if participant.get("directory_listed") != listed:
        participant["directory_listed"] = listed
        db.touch(participant)
    return listed


def recompute_directory_listed_by_id(participant_id):
    participant = db.get("participants", participant_id)
    if participant is not None:
        return recompute_directory_listed(participant)
    return False


# --------------------------------------------------------------------------
# Service windows — half-open [effective_from, effective_to) (§2.6)
# --------------------------------------------------------------------------

def in_window(endpoint, at=None):
    at = at or clock.get_clock()
    start = endpoint.get("effective_from")
    if start is None:
        return False
    if start > at:
        return False
    end = endpoint.get("effective_to")
    if end is not None and at >= end:
        return False
    return True


def require_in_window(endpoint, at=None):
    if not in_window(endpoint, at):
        raise ApiError(ERR_ENDPOINT_OUT_OF_SERVICE_WINDOW)


# --------------------------------------------------------------------------
# delivery_reachability (§2.4)
# --------------------------------------------------------------------------

def reachability(participant_id):
    rows = [e for e in db.all_rows("endpoints") if e["participant_id"] == participant_id]
    total = len(rows)
    now = clock.get_clock()
    reachable = sum(
        1 for e in rows if e["status"] in LIVE_ENDPOINT_STATUSES and in_window(e, now)
    )
    if total == 0 or reachable == 0:
        label = "UNREACHABLE"
    elif reachable / total < 0.50:
        label = "AT_RISK"
    else:
        label = "FULL"
    return reachable, total, label


# --------------------------------------------------------------------------
# reliability_factor (§2.6) — dual variant over one outcome history
# --------------------------------------------------------------------------

def ordered_reports(endpoint_id):
    """The endpoint's reported history, oldest first.

    A back-up nomination re-points an in-flight attempt at the next-ranked
    endpoint, so the endpoint that just failed has to be folded back into the
    history the recompute reads. Those archived rows are merged in here, keyed
    by attempt id so an archived report is never counted twice.
    """
    history = [
        a for a in db.all_rows("routing_attempts")
        if a.get("target_endpoint_id") == endpoint_id and a.get("outcome") in TERMINAL_OUTCOMES
    ]
    seen = {a["id"] for a in history}
    for row in db.all_rows("report_snapshots"):
        if row.get("target_endpoint_id") != endpoint_id or row["id"] in seen:
            continue
        history.append(row)
    history.sort(key=lambda a: (
        a.get("reported_at") or "",
        a.get("attempt_no") or 0,
        a.get("_seq", 0),
    ))
    return history


def archive_report(attempt, endpoint_id):
    """Fold a re-pointed attempt's report into `endpoint_id`'s history."""
    if not endpoint_id:
        return
    snapshot = dict(attempt)
    snapshot["target_endpoint_id"] = endpoint_id
    db.add("report_snapshots", snapshot)


def reliability_of_history(ordered):
    window = ordered[-RELIABILITY_WINDOW_N:] if ordered else []
    if not window:
        ratio = 1.0
    else:
        ack = sum(1 for a in window if a["outcome"] == "ACKNOWLEDGED")
        ratio = round4(ack / len(window))
    ewma = Decimal("1.0000")
    for row in ordered:
        x = Decimal("1.0") if row["outcome"] == "ACKNOWLEDGED" else Decimal("0.0")
        ewma = (EWMA_ALPHA * x + (Decimal("1") - EWMA_ALPHA) * ewma).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    return ratio, float(ewma)


def recompute_endpoint_counters(endpoint):
    """Restamp reported/acknowledged counters and both reliability columns.

    A recomputation counts as a mutation, so the endpoint's updated_at is
    restamped and its version incremented (§2.5).
    """
    ordered = ordered_reports(endpoint["id"])
    ratio, ewma = reliability_of_history(ordered)
    endpoint["reported_attempt_count"] = len(ordered)
    endpoint["acknowledged_count"] = sum(1 for a in ordered if a["outcome"] == "ACKNOWLEDGED")
    endpoint["reliability_ratio"] = ratio
    endpoint["reliability_ratio_ewma"] = ewma
    db.touch(endpoint)
    return ratio


# --------------------------------------------------------------------------
# Coverage invariant (§2.6) — share of ACTIVE-only endpoints
# --------------------------------------------------------------------------

def active_share_after_degrade(endpoint):
    """The participant's ACTIVE share once `endpoint` leaves ACTIVE.

    A directory of one is exempt: the invariant exists to stop a participant
    "quietly degrading its last working endpoint" while others remain, and a
    participant that holds only the one contract has no share left to protect — its
    orders are carried by the fallback channel instead (§3.5).
    """
    siblings = [e for e in db.all_rows("endpoints") if e["participant_id"] == endpoint["participant_id"]]
    total = len(siblings)
    if total <= 1:
        return 1.0
    # A `DEGRADED` endpoint is still reachable — §2.4 counts it among the endpoints
    # that make a participant reachable, and §3.4 still nominates it — so it counts
    # toward the share the invariant protects.
    active_after = sum(
        1 for e in siblings
        if e["id"] != endpoint["id"] and e["status"] in ("ACTIVE", "DEGRADED")
    )
    return active_after / total


def degrade_allowed(endpoint):
    return active_share_after_degrade(endpoint) >= 0.50