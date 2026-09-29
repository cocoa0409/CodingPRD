"""State transitions, cascades and derived-field recomputation.

Version bumps follow the scaffold's per-transition enumeration: a resource is
touched (updated_at + version) only where the specification says the operation
changes it.  Purely derived roll-ups on a resource the request does not name
(department aggregates, another lot's expected sell-through, partner counters)
are recomputed in full from current state without a version bump.
"""
from db import db, newest_first, ordered
from errors import ApiError
from records import (assignments_of_lot, assignments_of_pickup,
                     audits_of_department, department_of_lot, findings_of_audit,
                     item_of_lot, labels_of_lot, lots_of_department,
                     new_record, shrink_events_of_lot, touch)
import calc
from util import (D, POSTING_LAG_HOURS, WASTE_HANDLING_PCT, add_seconds,
                  fmt_instant, num, parse_instant, rhu_int)


# --- derived fields --------------------------------------------------------
def refresh_expected_sell_through(lot):
    lot["expected_sell_through_pct"] = calc.expected_sell_through(lot)


def recompute_liability(department):
    department["markdown_liability_cents"] = calc.markdown_liability_cents(
        department
    )


def recompute_shrink_ratio(department):
    department["shrink_cost_ratio_pct"] = calc.shrink_cost_ratio_pct(department)


def recompute_posture(department):
    """First matching clause wins (PRD 2.8)."""
    audits = audits_of_department(department["id"])
    for audit in audits:
        if audit["disposition_status"] == "ESCALATED":
            department["compliance_status"] = "BLOCKED"
            return
    for audit in audits:
        if (audit["severity"] in ("MAJOR", "CRITICAL")
                and audit["disposition_status"] != "REMEDIATED"):
            department["compliance_status"] = "WATCH"
            return
    if D(department["shrink_cost_ratio_pct"]) > D(department["shrink_budget_pct"]):
        department["compliance_status"] = "WATCH"
        return
    department["compliance_status"] = "COMPLIANT"


def recompute_open_finding_count(department):
    total = 0
    for audit in audits_of_department(department["id"]):
        for finding in findings_of_audit(audit["id"]):
            if finding["status"] == "OPEN":
                total += 1
    department["open_finding_count"] = total


def recompute_pickup_rollups(pickup):
    lines = assignments_of_pickup(pickup["id"])
    pickup["assignment_count"] = len(
        [a for a in lines if a["status"] in ("ASSIGNED", "PICKED_UP")]
    )
    pickup["units_picked_up_total"] = sum(
        a["quantity_units"] for a in lines if a["status"] == "PICKED_UP"
    )


def recompute_partner_rollups(partner):
    completed = [
        p for p in db.pickups.values()
        if p["partner_id"] == partner["id"]
        and p["logistics_status"] == "COMPLETED"
    ]
    partner["pickups_completed_count"] = len(completed)
    units = 0
    for pickup in completed:
        for line in assignments_of_pickup(pickup["id"]):
            if line["status"] == "PICKED_UP":
                units += line["quantity_units"]
    partner["units_received_total"] = units


# --- labels ----------------------------------------------------------------
def void_open_labels(lot):
    for label in labels_of_lot(lot["id"]):
        if label["status"] != "VOIDED":
            label["status"] = "VOIDED"
            touch(label)


def newest_open_label(lot):
    open_labels = [
        l for l in labels_of_lot(lot["id"]) if l["status"] != "VOIDED"
    ]
    if not open_labels:
        return None
    return newest_first(open_labels)[0]


# --- lot lifecycle ---------------------------------------------------------
def unwind_from_donation(lot):
    """DONATION_PENDING -> MARKED_DOWN or FRESH by current_rung_index, but only
    when the lot is not still pledged to a live manifest."""
    if lot["status"] != "DONATION_PENDING":
        return
    for line in assignments_of_lot(lot["id"]):
        if line["status"] != "ASSIGNED":
            continue
        pickup = db.pickups[line["pickup_id"]]
        if pickup["logistics_status"] in ("SCHEDULED", "CONFIRMED"):
            return
    lot["status"] = "MARKED_DOWN" if lot["current_rung_index"] >= 0 else "FRESH"
    touch(lot)


def reject_open_lines(pickup):
    """REJECT every ASSIGNED line and unwind its lot."""
    touched_departments = {}
    for line in ordered(assignments_of_pickup(pickup["id"])):
        if line["status"] != "ASSIGNED":
            continue
        line["status"] = "REJECTED"
        touch(line)
        lot = db.lots[line["lot_id"]]
        unwind_from_donation(lot)
        department = department_of_lot(lot)
        touched_departments[department["id"]] = department
    recompute_pickup_rollups(pickup)
    return touched_departments


def synthesise_withdrawal_shrink(lot, quantity, actor_user_id):
    item = item_of_lot(lot)
    unit_cost = item["unit_cost_cents"]
    stamp = fmt_instant(db.now())
    return new_record(db.shrink_events, {
        "lot_id": lot["id"],
        "cause_code": "SPOILAGE",
        "quantity_units": quantity,
        "note": None,
        "unit_cost_cents_snapshot": unit_cost,
        "cost_value_cents": rhu_int(
            D(quantity) * D(unit_cost) * (D(1) + WASTE_HANDLING_PCT / D(100))
        ),
        "retail_value_cents": quantity * lot["current_price_cents"],
        "recorded_by_user_id": actor_user_id,
        "verified_by_user_id": "system",
        "origin": "WITHDRAWAL_AUTO",
        "status": "VERIFIED",
        "verified_at": stamp,
        "posted_at": None,
    })


def withdraw_lot(lot, actor_user_id):
    """The pinned six-step withdrawal cascade (PRD 3.5)."""
    department = department_of_lot(lot)
    remaining = lot["quantity_on_hand"]
    # step 1: synthesise the WITHDRAWAL_AUTO shrink event for the balance
    if remaining > 0:
        synthesise_withdrawal_shrink(lot, remaining, actor_user_id)
        # step 2: move the units so unit conservation still balances
        lot["units_shrunk"] = lot["units_shrunk"] + remaining
        lot["quantity_on_hand"] = 0
    # step 3: void the tags, refresh the lot's derived figures
    void_open_labels(lot)
    refresh_expected_sell_through(lot)
    # step 5: release the lot from every live manifest line
    for line in ordered(assignments_of_lot(lot["id"])):
        if line["status"] != "ASSIGNED":
            continue
        line["status"] = "REJECTED"
        touch(line)
        pickup = db.pickups[line["pickup_id"]]
        recompute_pickup_rollups(pickup)
        revalue_manifest(pickup, "ASSIGNED", write_lines=False)
    # step 6: the lot itself
    lot["status"] = "WITHDRAWN"
    touch(lot)
    # steps 3 and 4: department aggregates and posture
    recompute_liability(department)
    recompute_shrink_ratio(department)
    recompute_posture(department)
    return lot


def deplete_if_empty(lot):
    if lot["quantity_on_hand"] <= 0 and lot["status"] in (
            "FRESH", "MARKED_DOWN"):
        lot["status"] = "DEPLETED"
        void_open_labels(lot)
        return True
    return False


# --- donation manifest valuation ------------------------------------------
def revalue_manifest(pickup, line_status, write_lines=True):
    """The four pinned steps of calculations.donation_manifest_valuation."""
    lines = ordered([
        a for a in assignments_of_pickup(pickup["id"])
        if a["status"] == line_status
    ])
    provisional = sum(
        line["quantity_units"] * line["unit_price_cents_snapshot"]
        for line in lines
    )
    pickup["provisional_value_cents"] = provisional
    if not write_lines:
        return
    rate = calc.credit_rate_for(provisional)
    pickup["credit_rate_pct"] = num(rate)
    total = 0
    for line in lines:
        credit = rhu_int(
            D(line["quantity_units"]) * D(line["unit_price_cents_snapshot"])
            * rate / D(100)
        )
        line["line_credit_cents"] = credit
        total += credit
    pickup["manifest_credit_cents"] = total


# --- markdown application -------------------------------------------------
def apply_markdown(lot, item, to_price_cents, discount_pct, rung_index, reason,
                   approved_by_user_id):
    """Rewrite the lot's live price and cut the label."""
    from_price = lot["current_price_cents"]
    supersedes = None
    if lot["status"] == "MARKED_DOWN":
        previous = newest_open_label(lot)
        if previous is not None:
            supersedes = previous["id"]
            previous["status"] = "VOIDED"
            touch(previous)
    lot["current_price_cents"] = to_price_cents
    lot["current_rung_index"] = rung_index
    lot["total_discount_pct"] = discount_pct
    lot["status"] = "MARKED_DOWN"
    label = new_record(db.labels, {
        "lot_id": lot["id"],
        "supersedes_label_id": supersedes,
        "rung_index": rung_index,
        "reason": reason,
        "from_price_cents": from_price,
        "to_price_cents": to_price_cents,
        "discount_pct": discount_pct,
        "barcode": "MD-%s-%05d" % (item["upc"], to_price_cents),
        "approved_by_user_id": approved_by_user_id,
        "status": "QUEUED",
        "printed_at": None,
        "applied_at": None,
    })
    refresh_expected_sell_through(lot)
    touch(lot)
    recompute_liability(department_of_lot(lot))
    return label


# --- nightly operations run ------------------------------------------------
def run_department_sweep(department):
    """The five pinned steps of POST /fresh/departments/{id}/run-date-code-sweep."""
    from records import ladder_of_department

    now = db.now()
    department["sweep_epoch"] = department["sweep_epoch"] + 1
    lots = ordered(lots_of_department(department["id"]))

    # step 1: flag every lot the clock has carried past its sell-by while it
    # still holds units
    lots_flagged = 0
    for lot in lots:
        if lot["quantity_on_hand"] <= 0:
            continue
        if now < parse_instant(lot["sell_by_at"]):
            continue
        if not lot["past_date_flag"]:
            lot["past_date_flag"] = True
            lots_flagged += 1

    # step 2: auto-mark-down under the LADDER_DAYS reading
    ladder = ladder_of_department(department)
    lots_marked = 0
    if ladder is not None and ladder["status"] == "ACTIVE":
        for lot in lots:
            if lot["status"] not in ("FRESH", "MARKED_DOWN"):
                continue
            if lot["quantity_on_hand"] <= 0:
                continue
            index = calc.base_rung_index(ladder, calc.days_remaining(lot))
            if index < 0 or index <= lot["current_rung_index"]:
                continue
            item = item_of_lot(lot)
            to_price, discount = calc.price_at_rung(item, ladder, index)
            if D(discount) > D(ladder["max_total_discount_pct"]):
                continue
            reason = "RE_LADDER" if lot["current_rung_index"] >= 0 else "LADDER_AUTO"
            apply_markdown(lot, item, to_price, discount, index, reason, None)
            lots_marked += 1

    # step 3: post every VERIFIED shrink event at least 24 hours old
    events_posted = 0
    for lot in lots:
        for event in ordered(shrink_events_of_lot(lot["id"])):
            if event["status"] != "VERIFIED":
                continue
            verified_at = event.get("verified_at")
            if not verified_at:
                continue
            due = add_seconds(parse_instant(verified_at),
                              POSTING_LAG_HOURS * 3600)
            if now >= due:
                event["status"] = "POSTED"
                event["posted_at"] = fmt_instant(now)
                touch(event)
                events_posted += 1

    # step 4: MISS every lapsed live pickup of this department's store
    pickups_missed = 0
    store_pickups = ordered([
        p for p in db.pickups.values()
        if p["store_id"] == department["store_id"]
    ])
    for pickup in store_pickups:
        if pickup["logistics_status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if now <= parse_instant(pickup["scheduled_window_end"]):
            continue
        pickup["logistics_status"] = "MISSED"
        touch(pickup)
        affected = reject_open_lines(pickup)
        for dept in affected.values():
            recompute_liability(dept)
        pickups_missed += 1

    # step 5: recompute the department's aggregates and posture
    for lot in lots_of_department(department["id"]):
        refresh_expected_sell_through(lot)
    recompute_liability(department)
    recompute_shrink_ratio(department)
    recompute_posture(department)

    return {
        "department_id": department["id"],
        "sweep_epoch": department["sweep_epoch"],
        "lots_flagged_past_date": lots_flagged,
        "lots_auto_marked_down": lots_marked,
        "shrink_events_posted": events_posted,
        "pickups_missed": pickups_missed,
        "markdown_liability_cents": department["markdown_liability_cents"],
        "shrink_cost_ratio_pct": department["shrink_cost_ratio_pct"],
        "compliance_status": department["compliance_status"],
    }
