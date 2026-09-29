"""Item normalization and manual mapping (PRD §3.3)."""

from store import db, touch
from svc_common import (items_of_deal, lines_of_batch, lines_of_batch_ordered,
                        recompute_batch_cases)


def key_candidates(line):
    """All contracted items whose normalized_item_key equals the reported key."""
    key = line["normalized_item_key_reported"]
    return [i for i in db.items.values() if i["normalized_item_key"] == key]


def eligible_candidates(line, candidates=None):
    """Key candidates that are ACTIVE, under an ACTIVE deal covering the invoice date."""
    if candidates is None:
        candidates = key_candidates(line)
    out = []
    for item in candidates:
        if item["status"] != "ACTIVE":
            continue
        deal = db.deals.get(item["deal_id"])
        if deal is None or deal["status"] != "ACTIVE":
            continue
        if not (deal["effective_from"] <= line["invoice_date"]
                <= deal["effective_to"]):
            continue
        out.append(item)
    return out


def classify_line(line):
    """Set the line's match fields from its two candidate sets."""
    keyed = key_candidates(line)
    eligible = eligible_candidates(line, keyed)

    if len(eligible) == 1:
        line["contracted_item_id"] = eligible[0]["id"]
        line["match_status"] = "MATCHED"
        line["accrual_block_reason"] = "NONE"
    elif len(eligible) >= 2:
        # The server never picks among equally eligible candidates on its own.
        line["contracted_item_id"] = None
        line["match_status"] = "AMBIGUOUS"
        line["accrual_block_reason"] = "NONE"
    elif not keyed:
        # An item key nobody has contracted: leave it for a later run.
        line["contracted_item_id"] = None
        line["match_status"] = "UNMATCHED"
        line["accrual_block_reason"] = "NONE"
    else:
        line["contracted_item_id"] = None
        line["match_status"] = "EXCLUDED"
        if all(i["status"] == "DELISTED" for i in keyed):
            line["accrual_block_reason"] = "ITEM_DELISTED"
        else:
            line["accrual_block_reason"] = "DEAL_NOT_ACTIVE"
    touch(line)


def refresh_last_purchase_dates(deals):
    """last_purchase_date = greatest invoice_date among lines matched to the deal's items."""
    for deal in deals:
        item_ids = set(i["id"] for i in items_of_deal(deal))
        dates = [l["invoice_date"] for l in db.lines.values()
                 if l["match_status"] == "MATCHED"
                 and l["contracted_item_id"] in item_ids]
        if not dates:
            continue
        newest = max(dates)
        if deal["last_purchase_date"] != newest:
            deal["last_purchase_date"] = newest
            touch(deal)


def normalize_batch(batch):
    """Resolve the batch's UNMATCHED lines onto contracted items."""
    gained = {}
    for line in lines_of_batch_ordered(batch):
        if line["match_status"] != "UNMATCHED":
            continue
        classify_line(line)
        if line["match_status"] == "MATCHED":
            item = db.items.get(line["contracted_item_id"])
            deal = db.deals.get(item["deal_id"]) if item else None
            if deal is not None:
                gained[deal["id"]] = deal

    batch["normalization_status"] = "NORMALIZED"
    recompute_batch_cases(batch)
    refresh_last_purchase_dates(gained.values())


def renormalize_batch(batch):
    """Reset both dimensions' per-line figures back to the start of the pipeline."""
    for line in lines_of_batch(batch):
        line["match_status"] = "UNMATCHED"
        line["contracted_item_id"] = None
        line["accrual_block_reason"] = "NONE"
        line["overbilled_cents"] = 0
        touch(line)

    batch["normalization_status"] = "RECEIVED"
    batch["matched_cases"] = 0
    batch["unmatched_cases"] = batch["total_cases_ingested"]
    batch["accrued_by_user_id"] = None
    # The audit dimension resets too: NOT_AUDITED from AUDIT_CLEAN or AUDIT_OVERBILLED.
    batch["audit_status"] = "NOT_AUDITED"
    batch["overbilled_cents"] = 0
    touch(batch)
