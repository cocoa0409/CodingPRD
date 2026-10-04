"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

STORE_SEQ = {"n": 0}
RECEIPT_SEQ = {"n": 0}
PROGRAM_SEQ = {"n": 0}
ACCOUNT_SEQ = {"n": 0}
JOB_SEQ = {"n": 0}


def create_store_payload(**overrides) -> dict:
    STORE_SEQ["n"] += 1
    defaults = {
        "store_code": f"S-{STORE_SEQ['n']:04d}",
        "submission_window_days": 30,
        "certificate_validity_months": 1,
        "expected_breakage_rate": 0.25,
        "split_txn_window_hours": 2,
        "split_txn_min_receipts": 3,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    PROGRAM_SEQ["n"] += 1
    defaults = {
        "name": f"Week Program {PROGRAM_SEQ['n']}",
        "week_start_date": "2026-09-07",
        "week_end_date": "2026-09-14",
    }
    defaults.update(overrides)
    return defaults


def create_program_item_payload(**overrides) -> dict:
    defaults = {
        "sku": "AAA",
        "rebate_pct": 0.1,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    ACCOUNT_SEQ["n"] += 1
    defaults = {
        "owner_name": f"Owner {ACCOUNT_SEQ['n']}",
        "account_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_job_purchase_payload(**overrides) -> dict:
    JOB_SEQ["n"] += 1
    defaults = {"job_reference": f"JOB-{JOB_SEQ['n']}"}
    defaults.update(overrides)
    return defaults


def cash_line(line_number, sku, category, quantity, unit_price_cents,
              extra_tenders=None) -> dict:
    """A receipt line paid fully in CASH, plus any extra tender splits the
    caller wants layered in (the CASH amount auto-shrinks to keep the split
    sum equal to quantity * unit_price_cents)."""
    total = quantity * unit_price_cents
    tenders = []
    extra_sum = 0
    for t in (extra_tenders or []):
        tenders.append(t)
        extra_sum += t["amount_cents"]
    cash = total - extra_sum
    if cash > 0:
        tenders.insert(0, {"tender_type": "CASH", "amount_cents": cash})
    return {
        "line_number": line_number,
        "sku": sku,
        "category": category,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "tender_splits": tenders,
    }


def create_receipt_payload(account_id, lines, purchase_at="2026-09-08T10:00:00Z",
                           **overrides) -> dict:
    RECEIPT_SEQ["n"] += 1
    defaults = {
        "receipt_number": f"R-{RECEIPT_SEQ['n']:05d}",
        "account_id": account_id,
        "purchase_at": purchase_at,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(receipt_id) -> dict:
    return {"receipt_id": receipt_id}


def adjudicate_payload(decision="APPROVE", rejection_reason=None) -> dict:
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload


def redeem_payload(receipt_id, amount_cents) -> dict:
    return {"receipt_id": receipt_id, "amount_cents": amount_cents}


def return_payload(*line_quantities) -> dict:
    """return_payload((1, 2), (3, 1)) -> {"lines": [{line_number: 1,
    quantity: 2}, {line_number: 3, quantity: 1}]}"""
    return {
        "lines": [
            {"line_number": ln, "quantity": q} for ln, q in line_quantities
        ]
    }
