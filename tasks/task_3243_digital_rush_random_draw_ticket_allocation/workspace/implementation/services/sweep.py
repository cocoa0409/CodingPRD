"""The operational epoch sweep: the fixed stage order that closes the day's books."""

from clock import CLOCK, parse_iso
from db import DB
from services import calc, engine
from state import epoch_index

ADMISSION_WINDOW_MINUTES = 20


def _holds_expired():
    count = 0
    for hold in DB.all("seat_hold"):
        if hold["status"] not in ("HELD", "ORPHANED"):
            continue
        end = hold.get("effective_to")
        if end is None:
            continue
        if parse_iso(end) < CLOCK.now:
            hold["status"] = "EXPIRED"
            DB.touch("seat_hold", hold)
            count += 1
    return count


def _rush_allocation(performance_id):
    for allocation in DB.all("allocation"):
        if allocation["performance_id"] != performance_id:
            continue
        if allocation["ticket_type"] in ("RUSH", "RUSH_PREMIUM"):
            return allocation
    return None


def _admissions_issued():
    count = 0
    for performance in DB.all("performance"):
        allocation = _rush_allocation(performance["id"])
        if allocation is None or allocation["status"] != "RELEASED":
            continue
        active = [
            q
            for q in DB.all("queue_position")
            if q["performance_id"] == performance["id"] and q["status"] == "WAITING"
        ]
        if not active:
            continue
        active.sort(key=lambda q: (q.get("joined_at") or "", q.get("created_at") or ""))
        admitted_so_far = len(
            [
                q
                for q in DB.all("queue_position")
                if q["performance_id"] == performance["id"] and q["status"] == "ADMITTED"
            ]
        )
        quota = calc.queue_admit_quota(
            admitted_so_far, int(allocation.get("daily_release_cap") or 0)
        )
        for position in active[:quota]:
            position["status"] = "ADMITTED"
            position["admit_at"] = CLOCK.stamp()
            position["admit_expires_at"] = CLOCK.plus_minutes(ADMISSION_WINDOW_MINUTES)
            DB.touch("queue_position", position)
            count += 1
    return count


def _draw_winners():
    count = 0
    for allocation in DB.all("allocation"):
        if allocation["ticket_type"] != "DRAW":
            continue
        if allocation["status"] != "RELEASED":
            continue
        eligible = calc.winner_selection(allocation["id"])
        if not eligible:
            continue
        cap = int(allocation.get("daily_release_cap") or 0)
        winner_count = cap
        waitlist_count = calc.waitlist_count_for(cap)
        for index, entry in enumerate(eligible):
            if index < winner_count:
                entry["status"] = "WINNER"
                entry["notified_at"] = CLOCK.stamp()
                entry["claim_deadline_at"] = CLOCK.plus_minutes(
                    int(allocation.get("claim_window_minutes") or 0)
                )
                count += 1
            elif index < winner_count + waitlist_count:
                entry["status"] = "WAITLISTED"
            else:
                entry["status"] = "LOSER"
            DB.touch("draw_entry", entry)
    return count


def _forfeit_and_promote():
    forfeited = 0
    promoted = 0
    freed = {}
    for entry in DB.all("draw_entry"):
        if entry["status"] != "WINNER":
            continue
        deadline = entry.get("claim_deadline_at")
        if deadline is None or CLOCK.now < parse_iso(deadline):
            continue
        entry["status"] = "FORFEITED"
        DB.touch("draw_entry", entry)
        engine.bump_violations(DB.get("patron", entry["patron_id"]), +1)
        forfeited += 1
        freed[entry["allocation_id"]] = freed.get(entry["allocation_id"], 0) + 1

    for allocation_id, free_seats in freed.items():
        candidates = [
            e
            for e in DB.all("draw_entry")
            if e["allocation_id"] == allocation_id and e["status"] == "WAITLISTED"
        ]
        candidates.sort(key=lambda e: (e.get("entered_at") or "", e.get("created_at") or ""))
        allocation = DB.get("allocation", allocation_id)
        for entry in candidates[:free_seats]:
            entry["status"] = "WINNER"
            if allocation is not None:
                entry["notified_at"] = CLOCK.stamp()
                entry["claim_deadline_at"] = CLOCK.plus_minutes(
                    int(allocation.get("claim_window_minutes") or 0)
                )
            DB.touch("draw_entry", entry)
            engine.bump_violations(DB.get("patron", entry["patron_id"]), -1)
            promoted += 1
    return forfeited, promoted


def _admissions_expired():
    count = 0
    for position in DB.all("queue_position"):
        if position["status"] != "ADMITTED":
            continue
        expires = position.get("admit_expires_at")
        if expires is None:
            continue
        if parse_iso(expires) < CLOCK.now:
            position["status"] = "EXPIRED"
            DB.touch("queue_position", position)
            count += 1
    return count


def _compensate_open_epoch():
    """Reverse money movements and seat swaps made in the epoch now closing."""
    epoch = epoch_index.get()
    # Money moved since the last sweep has not been stamped with an epoch index
    # yet: every sweep stamps and then advances its own index, so the window now
    # closing is the half-open [index, index + 1) named by the current index.
    open_epoch = (epoch, epoch + 1)
    for refund in DB.all("refund"):
        if refund["status"] != "PROCESSING":
            continue
        purchase = DB.get("purchase", refund["purchase_id"])
        if purchase is None or purchase.get("settlement_epoch") not in open_epoch:
            continue
        refund["status"] = "COMPENSATED"
        DB.touch("refund", refund)
        purchase["payment_status"] = "SETTLED"
        purchase["refunded_cents"] = refund.get("pre_settlement_refunded_cents") or 0
        DB.touch("purchase", purchase)
        allocation = DB.get("allocation", purchase["allocation_id"])
        if allocation is not None:
            allocation["quantity_sold_today"] = int(
                allocation.get("quantity_sold_today") or 0
            ) + int(purchase.get("quantity") or 0)
            DB.touch("allocation", allocation)

    for exchange in DB.all("exchange"):
        if exchange["status"] != "APPLIED":
            continue
        purchase = DB.get("purchase", exchange["purchase_id"])
        if purchase is None or (exchange.get("exchange_epoch") or purchase.get("exchange_epoch")) not in open_epoch:
            continue
        exchange["status"] = "COMPENSATED"
        DB.touch("exchange", exchange)
        purchase["refunded_cents"] = exchange.get("pre_application_refunded_cents") or 0
        DB.touch("purchase", purchase)
        for allocation_id in (exchange.get("source_allocation_id"), exchange.get("target_allocation_id")):
            allocation = DB.get("allocation", allocation_id)
            if allocation is None:
                continue
            allocation["quantity_sold_today"] = int(
                allocation.get("quantity_sold_today") or 0
            ) - int(purchase.get("quantity") or 0)
            DB.touch("allocation", allocation)


def run(as_of_iso8601):
    """Advance to the named instant and settle the stages in the fixed order."""
    CLOCK.advance_to(as_of_iso8601)
    holds_expired = _holds_expired()
    admissions_issued = _admissions_issued()
    winners_notified = _draw_winners()
    forfeited, promoted = _forfeit_and_promote()
    admissions_expired = _admissions_expired()
    _compensate_open_epoch()
    desks_reset = engine.reset_desks()
    epoch_index.bump()
    return {
        "opened_epoch_iso8601": CLOCK.stamp(),
        "winners_notified_count": winners_notified,
        "waitlisted_promoted_count": promoted,
        "forfeited_count": forfeited,
        "admissions_issued_count": admissions_issued,
        "admissions_expired_count": admissions_expired,
        "holds_expired_count": holds_expired,
        "desks_reset_count": desks_reset,
    }