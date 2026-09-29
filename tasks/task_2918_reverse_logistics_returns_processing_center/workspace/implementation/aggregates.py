"""Derived client / authorization figures, the shrink ledger, and auto-suspension."""

import calc
import constants as K
import db
import refs


# ------------------------------------------------------------------ ledger reads

def entries_of_client(client_id):
    return db.sorted_rows(
        [e for e in db.all_rows("shrink_ledger_entries") if e["client_id"] == client_id]
    )


def settlement_balance(client_id):
    return sum(e["amount_cents"] for e in entries_of_client(client_id))


def shrink_ledger(client_id):
    return sum(
        e["amount_cents"]
        for e in entries_of_client(client_id)
        if e["entry_type"] in K.LOSS_ENTRY_TYPES
    )


def next_sequence_no(client_id):
    highest = 0
    for entry in db.all_rows("shrink_ledger_entries"):
        if entry["client_id"] == client_id and entry["sequence_no"] > highest:
            highest = entry["sequence_no"]
    return highest + 1


def append_entry(client_id, return_line_id, entry_type, amount_cents, memo):
    row = {
        "id": db.new_id(),
        "client_id": client_id,
        "return_line_id": return_line_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
        "sequence_no": next_sequence_no(client_id),
    }
    db.stamp_new(row, versioned=False)
    db.insert("shrink_ledger_entries", row)
    auto_suspend(db.get("clients", client_id))
    return row


def auto_suspend(client):
    """§2.10: a ledger append that drives the balance below the negated cap suspends."""
    if client is None or client["status"] != "ACTIVE":
        return
    if settlement_balance(client["id"]) < -client["max_refund_exposure_cents"]:
        client["status"] = "SUSPENDED"
        db.touch(client)


def auto_reinstate(client):
    """§2.10: a reversal that lifts the balance back to the cap reinstates."""
    if client is None or client["status"] != "SUSPENDED":
        return
    if settlement_balance(client["id"]) >= -client["max_refund_exposure_cents"]:
        client["status"] = "ACTIVE"
        db.touch(client)


# ------------------------------------------------------------------ unit buckets

def lines_of_client(client_id):
    return refs.return_lines_of_client(client_id)


def unit_buckets(client_id):
    lines = lines_of_client(client_id)
    line_ids = set(line["id"] for line in lines)
    received = sum(line["quantity"] for line in lines)
    dispositioned = sum(
        line["quantity"] for line in lines if line["disposition_state"] == "DISPOSITIONED"
    )
    reserved = 0
    for order in db.all_rows("disposition_orders"):
        if order["return_line_id"] in line_ids and order["status"] in ("PROPOSED", "APPROVED"):
            reserved += order["quantity"]
    return {
        "units_received": received,
        "units_reserved_for_disposition": reserved,
        "units_dispositioned": dispositioned,
        "units_in_process": received - reserved - dispositioned,
    }


def open_rma_count(client_id):
    total = 0
    for rma in db.all_rows("rmas"):
        if rma["client_id"] == client_id and rma["status"] in (
            "ISSUED",
            "PARTIALLY_RECEIVED",
            "RECEIVED",
        ):
            total += 1
    return total


# ----------------------------------------------------------- projected balances

def projected_order_amount(order):
    line = refs.return_line_of_order(order)
    item = refs.item_of_return_line(line)
    channel = db.get("channels", order["channel_id"]) if order["channel_id"] else None
    gross, _fee_pct, _fee, net = calc.lot_economics(
        channel, order["unit_price_cents"], order["quantity"], order["refurb_cost_cents"]
    )
    disposition = order["disposition"]
    if disposition == "DONATE":
        return calc.donation_write_off_amount(item["declared_value_cents"], order["quantity"])
    if disposition == "DESTROY":
        return calc.destruction_write_off_amount(item["declared_value_cents"], order["quantity"])
    return calc.recovery_credit_amount(net)


def projected_settlement_balance(client_id):
    total = settlement_balance(client_id)
    line_ids = set(line["id"] for line in lines_of_client(client_id))
    for order in db.sorted_rows(db.all_rows("disposition_orders")):
        if order["return_line_id"] in line_ids and order["status"] in ("PROPOSED", "APPROVED"):
            total += projected_order_amount(order)
    for refund in db.sorted_rows(db.all_rows("refund_releases")):
        if refund["client_id"] != client_id:
            continue
        line = db.get("return_lines", refund["return_line_id"])
        if line is not None and line["financial_state"] == "RELEASE_PENDING":
            total -= refund["net_refund_cents"]
    return total


# ------------------------------------------------------- authorization rollups

def rma_line_received_quantity(rma_line_id):
    return sum(
        line["quantity"]
        for line in db.all_rows("return_lines")
        if line["rma_line_id"] == rma_line_id
    )


def rma_rollups(rma):
    lines = refs.rma_lines_of(rma)
    declared_line_count = len(lines)
    authorized_unit_total = sum(line["authorized_quantity"] for line in lines)
    received_unit_total = sum(rma_line_received_quantity(line["id"]) for line in lines)
    fraud_flag_count = 0
    for return_line in refs.lines_of_rma(rma):
        for check in refs.fraud_checks_of_line(return_line["id"]):
            if check["outcome"] == "FAIL":
                fraud_flag_count += 1
    return {
        "declared_line_count": declared_line_count,
        "authorized_unit_total": authorized_unit_total,
        "received_unit_total": received_unit_total,
        "fraud_flag_count": fraud_flag_count,
    }


def rederive_rma_status(rma):
    """Re-derive ISSUED / PARTIALLY_RECEIVED / RECEIVED from the line rollups."""
    rollups = rma_rollups(rma)
    received = rollups["received_unit_total"]
    authorized = rollups["authorized_unit_total"]
    if rma["status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
        return rma["status"]
    if received >= authorized and authorized > 0:
        rma["status"] = "RECEIVED"
    elif received > 0:
        rma["status"] = "PARTIALLY_RECEIVED"
    return rma["status"]


def void_shrink_consequence(rma, memo):
    """A void or expiry writes the RECEIPT_VARIANCE shortfall for every line."""
    for rma_line in refs.rma_lines_of(rma):
        item = refs.item_of_rma_line(rma_line)
        if item is None:
            continue
        received = rma_line_received_quantity(rma_line["id"])
        shortfall = rma_line["authorized_quantity"] - received
        if shortfall <= 0:
            continue
        amount = calc.receipt_variance_amount(
            rma_line["authorized_quantity"], received, item["declared_value_cents"]
        )
        append_entry(rma["client_id"], None, "RECEIPT_VARIANCE", amount, memo)
