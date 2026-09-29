"""Contract compliance reviews and the deal-loss cascade (PRD §3.8)."""

from money import (BPS_DENOMINATOR, DAYS_PER_YEAR, WARN_BAND_BPS, floor_bps,
                   round_half_up_div)
from store import db, days_between, touch
from svc_common import (cards_of_item, items_of_deal, recompute_batch_cases,
                        tier_of_member)


def matched_spend(deal, period_start, period_end, member_id=None):
    """Sum invoice_extended_cents over MATCHED lines resolved to this deal's items."""
    item_ids = set(i["id"] for i in items_of_deal(deal))
    total = 0
    for line in db.lines.values():
        if line["match_status"] != "MATCHED":
            continue
        if line["contracted_item_id"] not in item_ids:
            continue
        if not (period_start <= line["invoice_date"] <= period_end):
            continue
        if member_id is not None and line["member_id"] != member_id:
            continue
        total += line["invoice_extended_cents"]
    return total


def compute_review(member, deal, window_start, window_end):
    """The six frozen figures plus the verdict, in the PRD's fixed branch order."""
    tier = tier_of_member(member)
    window_days = days_between(window_start, window_end) + 1  # both ends counted
    prorated = round_half_up_div(
        member["committed_annual_spend_cents"] * window_days, DAYS_PER_YEAR)
    contracted = matched_spend(deal, window_start, window_end, member["id"])
    deal_wide = matched_spend(deal, window_start, window_end)

    if prorated == 0:
        ratio = 0
    else:
        ratio = floor_bps(contracted, prorated)

    minimum = tier["compliance_min_ratio_bps"]
    # The deal-loss branch is evaluated FIRST so an abandoned deal is never
    # masked by a member's own shortfall.
    if (deal_wide == 0
            and window_days >= deal["required_purchase_window_days"]
            and deal["status"] == "ACTIVE"):
        result = "DEAL_LOST"
    elif ratio >= minimum:
        result = "PASS"
    elif ratio >= minimum - WARN_BAND_BPS:
        result = "WARN"
    else:
        result = "BREACH"

    return {
        "window_days": window_days,
        "committed_spend_prorated_cents": prorated,
        "contracted_spend_cents": contracted,
        "deal_wide_contracted_spend_cents": deal_wide,
        "purchase_ratio_bps": ratio,
        "result": result,
    }


def apply_breach(member):
    """A BREACH costs the member its standing: ACTIVE -> SUSPENDED with a hold."""
    if member["enrollment_status"] != "ACTIVE":
        return
    member["enrollment_status"] = "SUSPENDED"
    member["payout_hold"] = True
    touch(member)


def apply_deal_loss(deal):
    """The four-hop cascade that follows a DEAL_LOST verdict."""
    # hop 1 - the deal leaves ACTIVE for its terminal state
    deal["status"] = "LOST"
    touch(deal)

    # hop 2 - every ACTIVE contracted item of the deal is delisted
    delisted = []
    for item in items_of_deal(deal):
        if item["status"] != "ACTIVE":
            continue
        item["status"] = "DELISTED"
        delisted.append(item)
        touch(item)
    deal["contracted_item_count"] = 0
    touch(deal)

    # hop 3 - their PROPOSED and APPROVED rate cards expire
    for item in delisted:
        for card in cards_of_item(item):
            if card["status"] in ("PROPOSED", "APPROVED"):
                card["status"] = "EXPIRED"
                touch(card)
        item["approved_rate_card_count"] = 0
        touch(item)

    # hop 3b - matched lines on still-NORMALIZED batches lose their item
    delisted_ids = set(i["id"] for i in delisted)
    affected_batches = {}
    for line in db.lines.values():
        if line["match_status"] != "MATCHED":
            continue
        if line["contracted_item_id"] not in delisted_ids:
            continue
        batch = db.batches.get(line["purchase_batch_id"])
        if batch is None or batch["normalization_status"] != "NORMALIZED":
            continue
        line["match_status"] = "EXCLUDED"
        line["accrual_block_reason"] = "ITEM_DELISTED"
        line["contracted_item_id"] = None
        touch(line)
        affected_batches[batch["id"]] = batch

    # hop 4 - each affected batch recomputes its case counters
    for batch in affected_batches.values():
        recompute_batch_cases(batch)
