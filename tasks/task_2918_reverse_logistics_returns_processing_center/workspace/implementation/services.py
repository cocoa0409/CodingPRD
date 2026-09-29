"""Shared domain services: lookups, fraud checks, refunds, cascades, selectors."""

from decimal import Decimal

import aggregates
import calc
import constants as K
import db
import refs
from errors import ApiError


# ------------------------------------------------------------------- lookups

def must(table, key, error_id):
    row = db.get(table, key)
    if row is None:
        raise ApiError(error_id)
    return row


def must_client(key):
    return must("clients", key, "ERR_CLIENT_NOT_FOUND")


def must_item(key):
    return must("catalog_items", key, "ERR_CATALOG_ITEM_NOT_FOUND")


def must_bay(key):
    return must("processing_bays", key, "ERR_BAY_NOT_FOUND")


def must_channel(key):
    return must("channels", key, "ERR_CHANNEL_NOT_FOUND")


def must_rma(key):
    return must("rmas", key, "ERR_RMA_NOT_FOUND")


def must_rma_line(key):
    return must("rma_lines", key, "ERR_RMA_LINE_NOT_FOUND")


def must_receipt(key):
    return must("receipts", key, "ERR_RECEIPT_NOT_FOUND")


def must_return_line(key):
    return must("return_lines", key, "ERR_RETURN_LINE_NOT_FOUND")


def must_work_order(key):
    return must("work_orders", key, "ERR_WORK_ORDER_NOT_FOUND")


def must_order(key):
    return must("disposition_orders", key, "ERR_DISPOSITION_ORDER_NOT_FOUND")


def must_refund(key):
    return must("refund_releases", key, "ERR_REFUND_RELEASE_NOT_FOUND")


def must_fraud_check(key):
    return must("fraud_checks", key, "ERR_FRAUD_CHECK_NOT_FOUND")


def must_feedback(key):
    return must("pricing_feedback", key, "ERR_PRICING_FEEDBACK_NOT_FOUND")


def must_ledger_entry(key):
    return must("shrink_ledger_entries", key, "ERR_SHRINK_LEDGER_ENTRY_NOT_FOUND")


def require_active(client):
    if client["status"] != "ACTIVE":
        raise ApiError("ERR_CLIENT_SUSPENDED")


# ------------------------------------------------------------- fraud checks

def append_fraud_check(line, check_type, outcome, evidence, stage):
    row = {
        "id": db.new_id(),
        "return_line_id": line["id"],
        "check_type": check_type,
        "outcome": outcome,
        "weight_points": calc.fraud_points(check_type, outcome),
        "evidence": evidence,
        "evaluated_stage": stage,
    }
    db.stamp_new(row, versioned=False)
    return db.insert("fraud_checks", row)


def run_receipt_fraud_checks(line, receipt, rma_line, item):
    empty_box_failed = bool(receipt["empty_box_suspected"])
    append_fraud_check(
        line,
        "EMPTY_BOX",
        "FAIL" if empty_box_failed else "PASS",
        "gross_weight_grams=%d expected_weight_grams=%d"
        % (receipt["gross_weight_grams"], receipt["expected_weight_grams"]),
        "RECEIPT",
    )
    if item["serialized"]:
        mismatch = line["scanned_serial"] != rma_line["declared_serial"]
        evidence = "declared_serial=%s scanned_serial=%s" % (
            rma_line["declared_serial"],
            line["scanned_serial"],
        )
    else:
        mismatch = False
        evidence = "item is not serialized"
    append_fraud_check(
        line, "SERIAL_MISMATCH", "FAIL" if mismatch else "PASS", evidence, "RECEIPT"
    )
    line["fraud_score_receipt"] = calc.score(
        refs.fraud_checks_of_line(line["id"]), ("RECEIPT",)
    )


def repeat_returner_count(client_id, customer_reference):
    total = 0
    for rma in db.all_rows("rmas"):
        if rma["client_id"] != client_id:
            continue
        if rma["customer_reference"] != customer_reference:
            continue
        if rma["status"] in ("VOID", "SUPERSEDED"):
            continue
        total += 1
    return total


def run_grading_fraud_checks(line, item, client, rma):
    declared_total = item["declared_value_cents"] * line["quantity"]
    gap = declared_total - line["recovery_value_cents"]
    anomaly = gap > client["fraud_tolerance_cents"]
    append_fraud_check(
        line,
        "VALUE_ANOMALY",
        "FAIL" if anomaly else "PASS",
        "declared_total=%d recovery_value_cents=%d fraud_tolerance_cents=%d"
        % (declared_total, line["recovery_value_cents"], client["fraud_tolerance_cents"]),
        "GRADING",
    )
    count = repeat_returner_count(client["id"], rma["customer_reference"])
    repeat = count >= K.REPEAT_RETURNER_THRESHOLD
    append_fraud_check(
        line,
        "REPEAT_RETURNER",
        "FAIL" if repeat else "PASS",
        "customer_reference=%s authorization_count=%d" % (rma["customer_reference"], count),
        "GRADING",
    )
    refresh_release_score(line)


def refresh_release_score(line):
    computed = calc.score(refs.fraud_checks_of_line(line["id"]), ("RECEIPT", "GRADING"))
    current = line["fraud_score_release"] or 0
    if computed > current:
        line["fraud_score_release"] = computed
    else:
        line["fraud_score_release"] = current
    return line["fraud_score_release"]


# ------------------------------------------------------------------- refunds

def refund_hold_hours_for(client):
    if client["service_level"] == "SL_WHITE_GLOVE":
        return 0
    return client["refund_hold_hours"]


def build_refund(line, item, client):
    fee_pct = calc.restocking_fee_pct(
        line["reason_code"],
        client["service_level"],
        line["condition_grade"],
        line["days_since_order"],
    )
    gross, fee, net = calc.refund_amounts(
        item["declared_value_cents"], line["quantity"], fee_pct
    )
    row = {
        "id": db.new_id(),
        "return_line_id": line["id"],
        "client_id": client["id"],
        "gross_refund_cents": gross,
        "restocking_fee_pct": fee_pct,
        "restocking_fee_cents": fee,
        "net_refund_cents": net,
        "release_eligible_at": None,
        "released_at": None,
        "released_by_user_id": None,
        "reversed_at": None,
        "denial_reason": None,
    }
    db.stamp_new(row)
    return db.insert("refund_releases", row)


def recompute_refund(line, item, client):
    refund = refs.refund_of_line(line["id"])
    if refund is None:
        return None
    fee_pct = calc.restocking_fee_pct(
        line["reason_code"],
        client["service_level"],
        line["condition_grade"],
        line["days_since_order"],
    )
    gross, fee, net = calc.refund_amounts(
        item["declared_value_cents"], line["quantity"], fee_pct
    )
    refund["gross_refund_cents"] = gross
    refund["restocking_fee_pct"] = fee_pct
    refund["restocking_fee_cents"] = fee
    refund["net_refund_cents"] = net
    db.touch(refund)
    return refund


def stamp_release_eligible(line, client, executed_at):
    refund = refs.refund_of_line(line["id"])
    if refund is None or executed_at is None:
        return None
    eligible = db.add_hours(executed_at, refund_hold_hours_for(client))
    refund["release_eligible_at"] = db.fmt_instant(eligible)
    db.touch(refund)
    return refund


def executed_order_of_line(line_id):
    for order in refs.orders_of_line(line_id):
        if order["status"] == "EXECUTED":
            return order
    return None


# ------------------------------------------------------- disposition matrix runs

def refurb_available(line, item):
    if not item["refurb_eligible"]:
        return False
    return not line.get("_refurb_forfeited", False)


def run_matrix(line, item, client):
    line["disposition"] = calc.decide_disposition(
        client,
        item,
        line["condition_grade"],
        line["quantity"],
        line["recovery_value_cents"],
        refurb_available(line, item),
    )
    return line["disposition"]


def cancel_drifted_orders(line):
    """System cancellation sweep in created_at ascending order."""
    for order in refs.orders_of_line(line["id"]):
        if order["status"] not in ("PROPOSED", "APPROVED"):
            continue
        if order["disposition"] == line["disposition"]:
            continue
        order["status"] = "CANCELLED"
        db.touch(order)


def cancel_all_open_orders(line):
    """Recall link two: every PROPOSED or APPROVED order of the line is cancelled."""
    for order in refs.orders_of_line(line["id"]):
        if order["status"] in ("PROPOSED", "APPROVED"):
            order["status"] = "CANCELLED"
            db.touch(order)


# --------------------------------------------------------------- work order cost

def abandon_work_order(work_order, line):
    work_order["packaging_cost_cents"] = 0
    work_order["total_cost_cents"] = calc.refurb_total_cost(
        work_order["labor_minutes_total"], work_order["parts_cost_cents"], 0
    )
    work_order["status"] = "ABANDONED"
    db.touch(work_order)
    if work_order["total_cost_cents"] != 0:
        aggregates.append_entry(
            refs.client_id_of_return_line(line),
            line["id"],
            "REFURB_COST",
            -work_order["total_cost_cents"],
            "refurbishment abandoned",
        )
    return work_order


# --------------------------------------------------------------- execute cascade

def execute_cascade(order, line, item, client):
    """The five-link cascade of §2.9, in the pinned order."""
    # Link one — the line settles physically and its recovery estimate goes final.
    line["disposition_state"] = "DISPOSITIONED"
    line["recovery_value_cents"] = order["net_recovery_cents"]
    db.touch(line)

    # Link two — exactly one settlement entry for the line.
    disposition = order["disposition"]
    if disposition in ("RESTOCK", "LIQUIDATE"):
        entry_type = "RECOVERY_CREDIT"
        amount = calc.recovery_credit_amount(order["net_recovery_cents"])
    elif disposition == "DONATE":
        entry_type = "DONATION_WRITE_OFF"
        amount = calc.donation_write_off_amount(item["declared_value_cents"], order["quantity"])
    else:
        entry_type = "DESTRUCTION_WRITE_OFF"
        amount = calc.destruction_write_off_amount(
            item["declared_value_cents"], order["quantity"]
        )
    # Links three and four — the client's figures are re-derived and the exposure
    # floor is re-tested inside the append.
    aggregates.append_entry(
        client["id"], line["id"], entry_type, amount, "disposition executed"
    )

    # Link five — the authorization closes once every sibling line has settled.
    rma = refs.rma_of_return_line(line)
    if rma is not None and rma["status"] == "RECEIVED":
        siblings = refs.lines_of_rma(rma)
        if siblings and all(s["disposition_state"] == "DISPOSITIONED" for s in siblings):
            rma["status"] = "CLOSED"
            db.touch(rma)


# ---------------------------------------------------------------- recall cascade

def recall_cascade(item):
    """The four-link mandatory-recall cascade of §3.8."""
    affected = []
    for line in db.sorted_rows(db.all_rows("return_lines")):
        line_item = refs.item_of_return_line(line)
        if line_item is None or line_item["id"] != item["id"]:
            continue
        if line["disposition_state"] not in (
            "RECEIVED_UNGRADED",
            "QUARANTINED",
            "DISPOSITION_ASSIGNED",
            "IN_REFURB",
        ):
            continue
        affected.append(line)

    # Link one.
    for line in affected:
        line["disposition"] = "DESTROY"
        db.touch(line)

    # Link two.
    for line in affected:
        cancel_all_open_orders(line)

    # Link three — swept in created_at ascending order across all affected lines.
    affected_ids = set(line["id"] for line in affected)
    work_orders = [
        w for w in db.sorted_rows(db.all_rows("work_orders"))
        if w["return_line_id"] in affected_ids
        and w["status"] in ("IN_TEST", "TEST_FAILED", "PASSED_QA")
    ]
    for work_order in work_orders:
        swept_line = db.get("return_lines", work_order["return_line_id"])
        abandon_work_order(work_order, swept_line)
        # §2.9: "a line routed to refurbishment leaves DISPOSITION_ASSIGNED for
        # IN_REFURB and comes back to DISPOSITION_ASSIGNED when the work order
        # closes"; §3.5 abandonment: "The line returns from IN_REFURB to
        # DISPOSITION_ASSIGNED ... with refurbishment availability forced to
        # false". Link one has already pinned the disposition to DESTROY.
        if swept_line is not None and swept_line["disposition_state"] == "IN_REFURB":
            swept_line["_refurb_forfeited"] = True
            swept_line["disposition_state"] = "DISPOSITION_ASSIGNED"
            db.touch(swept_line)

    # Link four — the client figures are derived on read, so nothing to store.
    return affected


# ----------------------------------------------------------------- expiry sweep

def expiry_sweep(new_now):
    """Every ISSUED or PARTIALLY_RECEIVED authorization due at or before the new clock."""
    for rma in db.sorted_rows(db.all_rows("rmas")):
        if rma["status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
            continue
        expires_at = db.parse_instant(rma["expires_at"])
        if expires_at is None or expires_at > new_now:
            continue
        rma["status"] = "EXPIRED"
        db.touch(rma)
        aggregates.void_shrink_consequence(rma, "authorization expired")


# ------------------------------------------------------------- window overlaps

def overlaps_half_open(new_start, new_end, existing_start, existing_end):
    return new_start < existing_end and existing_start < new_end


def overlaps_closed(new_start, new_end, existing_start, existing_end):
    return new_start <= existing_end and existing_start <= new_end


def check_quarantine_window(bay, line, start_at, end_at):
    for other in db.sorted_rows(db.all_rows("return_lines")):
        if other["id"] == line["id"]:
            continue
        if other["bay_id"] != bay["id"]:
            continue
        other_start = db.parse_instant(other["quarantine_start_at"])
        other_end = db.parse_instant(other["quarantine_end_at"])
        if other_start is None or other_end is None:
            continue
        if overlaps_half_open(start_at, end_at, other_start, other_end):
            raise ApiError("ERR_BAY_WINDOW_CONFLICT")


def check_test_window(bay, work_order, start_at, end_at):
    buffer_delta = bay["buffer_minutes"]
    for other in db.sorted_rows(db.all_rows("work_orders")):
        if other["id"] == work_order["id"]:
            continue
        if other["bay_id"] != bay["id"]:
            continue
        other_start = db.parse_instant(other["test_window_start_at"])
        other_end = db.parse_instant(other["test_window_end_at"])
        if other_start is None or other_end is None:
            continue
        widened_start = db.add_hours(other_start, 0) - _minutes(buffer_delta)
        widened_end = db.add_hours(other_end, 0) + _minutes(buffer_delta)
        if overlaps_half_open(start_at, end_at, widened_start, widened_end):
            raise ApiError("ERR_BAY_BUFFER_VIOLATION")


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)


# --------------------------------------------------------------- channel policy

def channel_window_count(channel, start_at, end_at, exclude_order_id=None):
    total = 0
    for order in db.all_rows("disposition_orders"):
        if order["channel_id"] != channel["id"]:
            continue
        if order["status"] not in ("PROPOSED", "APPROVED"):
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        other_start = db.parse_instant(order["channel_window_start_at"])
        other_end = db.parse_instant(order["channel_window_end_at"])
        if other_start is None or other_end is None:
            continue
        if overlaps_closed(start_at, end_at, other_start, other_end):
            total += 1
    return total


def window_admits(channel, start_at, end_at):
    return (1 + channel_window_count(channel, start_at, end_at)) <= channel[
        "concurrent_lot_capacity"
    ]


def channel_serves(channel, disposition):
    return K.CHANNEL_TYPE_DISPOSITION[channel["channel_type"]] == disposition


def select_channel(line, item, disposition, start_at, end_at):
    """The channel selector policy of §3.6. Returns the winning channel or None."""
    candidates = []
    for channel in db.sorted_rows(db.all_rows("channels")):
        if channel["status"] != "ACTIVE":
            continue
        if not channel_serves(channel, disposition):
            continue
        if line["condition_grade"] not in channel["accepted_grades"]:
            continue
        if item["hazard_class"] != "NONE" and not channel["hazard_certified"]:
            continue
        if item["recall_status"] == "MANDATORY" and not channel["recall_certified"]:
            continue
        unit_price = calc.unit_price_cents(
            disposition, line["recovery_value_cents"], line["quantity"], channel, item
        )
        projected = calc.projected_net_recovery(channel, unit_price, line["quantity"])
        if projected < channel["min_lot_value_cents"]:
            continue
        if not window_admits(channel, start_at, end_at):
            continue
        candidates.append((projected, channel))
    if not candidates:
        return None
    candidates.sort(
        key=lambda pair: (
            -pair[0],
            pair[1]["fee_pct"],
            pair[1]["min_lot_value_cents"],
            pair[1]["channel_code"],
        )
    )
    return candidates[0][1]
