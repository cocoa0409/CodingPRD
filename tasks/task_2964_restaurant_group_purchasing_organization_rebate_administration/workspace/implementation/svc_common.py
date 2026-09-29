"""Shared lookups and derived-counter recomputation (PRD §2.10).

Derived counters are never adjusted by guesswork: each recompute rewrites the
counter from the current facts, as the count or sum its definition names.
"""

from store import db, sort_asc, touch


# --------------------------------------------------------------------------
# navigation
# --------------------------------------------------------------------------

def tier_of_member(member):
    return db.program_tiers.get(member["tier_id"])


def deal_of_item(item):
    return db.deals.get(item["deal_id"])


def item_of_line(line):
    if line.get("contracted_item_id") is None:
        return None
    return db.items.get(line["contracted_item_id"])


def batch_of_line(line):
    return db.batches.get(line["purchase_batch_id"])


def lines_of_batch(batch):
    return [l for l in db.lines.values() if l["purchase_batch_id"] == batch["id"]]


def lines_of_batch_ordered(batch):
    """Batch lines in ascending created_at (insertion sequence breaks ties)."""
    return sort_asc(lines_of_batch(batch))


def lines_of_batch_by_invoice_date(batch):
    """Batch lines in ascending invoice_date, created_at ascending on a tie."""
    return sorted(
        lines_of_batch(batch),
        key=lambda l: (l["invoice_date"], l["created_at"], l["_seq"]),
    )


def accruals_of_batch(batch):
    ids = set(l["id"] for l in lines_of_batch(batch))
    return [a for a in db.accruals.values() if a["purchase_line_id"] in ids]


def line_of_accrual(accrual):
    return db.lines.get(accrual["purchase_line_id"])


def item_of_accrual(accrual):
    card = db.rate_cards.get(accrual["rate_card_id"])
    if card is None:
        return None
    return db.items.get(card["contracted_item_id"])


def deal_of_accrual(accrual):
    item = item_of_accrual(accrual)
    if item is None:
        return None
    return deal_of_item(item)


def items_of_deal(deal):
    return [i for i in db.items.values() if i["deal_id"] == deal["id"]]


def cards_of_item(item):
    return [c for c in db.rate_cards.values() if c["contracted_item_id"] == item["id"]]


# --------------------------------------------------------------------------
# authorization-letter helpers
# --------------------------------------------------------------------------

def active_letters(member_id=None, distributor_id=None):
    out = []
    for letter in db.letters.values():
        if letter["status"] != "ACTIVE":
            continue
        if member_id is not None and letter["member_id"] != member_id:
            continue
        if distributor_id is not None and letter["distributor_id"] != distributor_id:
            continue
        out.append(letter)
    return out


def recompute_member_letter_count(member):
    count = len(active_letters(member_id=member["id"]))
    if member["active_letter_count"] != count:
        member["active_letter_count"] = count
        touch(member)


def recompute_distributor_letter_count(distributor):
    count = len(active_letters(distributor_id=distributor["id"]))
    if distributor["active_letter_count"] != count:
        distributor["active_letter_count"] = count
        touch(distributor)


# --------------------------------------------------------------------------
# batch / deal / item counters
# --------------------------------------------------------------------------

def recompute_batch_cases(batch):
    """matched_cases = sum over MATCHED lines; unmatched = total - matched."""
    matched = sum(
        l["cases_shipped"] for l in lines_of_batch(batch)
        if l["match_status"] == "MATCHED"
    )
    batch["matched_cases"] = matched
    batch["unmatched_cases"] = batch["total_cases_ingested"] - matched
    touch(batch)


def recompute_deal_item_count(deal):
    deal["contracted_item_count"] = len(
        [i for i in items_of_deal(deal) if i["status"] == "ACTIVE"]
    )
    touch(deal)


def recompute_item_approved_card_count(item):
    item["approved_rate_card_count"] = len(
        [c for c in cards_of_item(item) if c["status"] == "APPROVED"]
    )
    touch(item)


# --------------------------------------------------------------------------
# member money ledger
# --------------------------------------------------------------------------

def post_accrual_to_member(member, accrual):
    member["accrued_member_share_cents"] += accrual["member_share_cents"]
    member["attributed_gpo_retention_cents"] += accrual["gpo_retention_cents"]
    member["attributed_admin_fee_cents"] += accrual["admin_fee_cents"]
    touch(member)


def retract_accrual_from_member(member, accrual):
    """Subtract the exact stored components -- the arithmetic inverse of posting."""
    member["accrued_member_share_cents"] -= accrual["member_share_cents"]
    member["attributed_gpo_retention_cents"] -= accrual["gpo_retention_cents"]
    member["attributed_admin_fee_cents"] -= accrual["admin_fee_cents"]
    touch(member)


# --------------------------------------------------------------------------
# period overlap helpers
# --------------------------------------------------------------------------

def periods_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap on calendar dates."""
    return a_start <= b_end and b_start <= a_end


def batches_blocking_period(period_start, period_end):
    """Batches whose own period overlaps and are still RECEIVED or NORMALIZED."""
    out = []
    for batch in db.batches.values():
        if batch["normalization_status"] not in ("RECEIVED", "NORMALIZED"):
            continue
        if periods_overlap(batch["period_start"], batch["period_end"],
                           period_start, period_end):
            out.append(batch)
    return out
