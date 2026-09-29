"""Reference-chain helpers: resolve owners and parents of any row."""

import db


def rma_of_line(rma_line):
    return db.get("rmas", rma_line["rma_id"]) if rma_line else None


def receipt_of(return_line):
    return db.get("receipts", return_line["receipt_id"]) if return_line else None


def rma_of_receipt(receipt):
    return db.get("rmas", receipt["rma_id"]) if receipt else None


def rma_line_of(return_line):
    return db.get("rma_lines", return_line["rma_line_id"]) if return_line else None


def item_of_rma_line(rma_line):
    return db.get("catalog_items", rma_line["catalog_item_id"]) if rma_line else None


def item_of_return_line(return_line):
    return item_of_rma_line(rma_line_of(return_line))


def rma_of_return_line(return_line):
    return rma_of_receipt(receipt_of(return_line))


def client_of_rma(rma):
    return db.get("clients", rma["client_id"]) if rma else None


def client_of_return_line(return_line):
    return client_of_rma(rma_of_return_line(return_line))


def client_id_of_return_line(return_line):
    rma = rma_of_return_line(return_line)
    return rma["client_id"] if rma else None


def client_id_of_receipt(receipt):
    rma = rma_of_receipt(receipt)
    return rma["client_id"] if rma else None


def client_id_of_rma_line(rma_line):
    rma = rma_of_line(rma_line)
    return rma["client_id"] if rma else None


def return_line_of_work_order(work_order):
    return db.get("return_lines", work_order["return_line_id"]) if work_order else None


def return_line_of_order(order):
    return db.get("return_lines", order["return_line_id"]) if order else None


def client_id_of_work_order(work_order):
    return client_id_of_return_line(return_line_of_work_order(work_order))


def client_id_of_order(order):
    return client_id_of_return_line(return_line_of_order(order))


def lines_of_rma(rma):
    out = []
    for receipt in db.all_rows("receipts"):
        if receipt["rma_id"] != rma["id"]:
            continue
        for line in db.all_rows("return_lines"):
            if line["receipt_id"] == receipt["id"]:
                out.append(line)
    return db.sorted_rows(out)


def rma_lines_of(rma):
    return db.sorted_rows([r for r in db.all_rows("rma_lines") if r["rma_id"] == rma["id"]])


def receipts_of(rma):
    return db.sorted_rows([r for r in db.all_rows("receipts") if r["rma_id"] == rma["id"]])


def return_lines_of_client(client_id):
    return [ln for ln in db.all_rows("return_lines") if client_id_of_return_line(ln) == client_id]


def orders_of_line(line_id):
    return db.sorted_rows(
        [o for o in db.all_rows("disposition_orders") if o["return_line_id"] == line_id]
    )


def work_orders_of_line(line_id):
    return db.sorted_rows(
        [w for w in db.all_rows("work_orders") if w["return_line_id"] == line_id]
    )


def refund_of_line(line_id):
    matches = db.sorted_rows(
        [r for r in db.all_rows("refund_releases") if r["return_line_id"] == line_id]
    )
    return matches[-1] if matches else None


def fraud_checks_of_line(line_id):
    return db.sorted_rows(
        [f for f in db.all_rows("fraud_checks") if f["return_line_id"] == line_id]
    )
