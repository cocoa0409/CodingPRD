"""Member savings report: realized versus opportunity (PRD §3.9)."""

from money import floor_bps
from store import db

REALIZED_ACCRUAL_STATUSES = ("ACCRUED", "VALIDATED", "FLAGGED", "DISPUTED", "PAID")


def _period_lines(member_id, period_start, period_end):
    out = []
    for line in db.lines.values():
        if line["member_id"] != member_id:
            continue
        if not (period_start <= line["invoice_date"] <= period_end):
            continue
        out.append(line)
    return out


def _cheapest_item_for_key(key):
    """The item with the lowest contract_unit_cost_cents among those sharing the key."""
    candidates = [i for i in db.items.values() if i["normalized_item_key"] == key]
    if not candidates:
        return None
    return min(candidates, key=lambda i: (i["contract_unit_cost_cents"],
                                          i["created_at"], i["_seq"]))


def savings_report(member, period_start, period_end, basis):
    lines = _period_lines(member["id"], period_start, period_end)
    matched = [l for l in lines if l["match_status"] == "MATCHED"]

    # realized: hard price savings on matched lines...
    price_savings = 0
    for line in matched:
        item = db.items.get(line["contracted_item_id"])
        if item is None:
            continue
        price_savings += ((item["baseline_unit_cost_cents"]
                           - line["invoice_unit_cost_cents"])
                          * line["cases_shipped"])

    # ...plus the rebate the member actually earned in the period
    line_ids = set(l["id"] for l in lines)
    rebate = 0
    for accrual in db.accruals.values():
        if accrual["member_id"] != member["id"]:
            continue
        if accrual["status"] not in REALIZED_ACCRUAL_STATUSES:
            continue
        if accrual["purchase_line_id"] not in line_ids:
            continue
        rebate += accrual["member_share_cents"]

    realized = price_savings + rebate

    # opportunity over the basis line set
    opportunity = 0
    for line in matched:
        item = db.items.get(line["contracted_item_id"])
        if item is None:
            continue
        opportunity += ((item["baseline_unit_cost_cents"]
                         - item["contract_unit_cost_cents"])
                        * line["cases_shipped"])
    if basis == "FULL_BASKET":
        # FULL_BASKET prices the leakage of buying off contract.
        for line in lines:
            if line["match_status"] not in ("AMBIGUOUS", "EXCLUDED"):
                continue
            item = _cheapest_item_for_key(line["normalized_item_key_reported"])
            if item is None:
                continue
            opportunity += ((item["baseline_unit_cost_cents"]
                             - item["contract_unit_cost_cents"])
                            * line["cases_shipped"])

    missed = opportunity - realized
    if missed < 0:
        missed = 0
    capture = 0 if opportunity <= 0 else floor_bps(realized, opportunity)

    matched_cases = sum(l["cases_shipped"] for l in matched)
    unmatched_cases = sum(l["cases_shipped"] for l in lines
                          if l["match_status"] in ("UNMATCHED", "AMBIGUOUS",
                                                   "EXCLUDED"))
    invoice_spend = sum(l["invoice_extended_cents"] for l in lines)

    return {
        "member_id": member["id"],
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
        "matched_cases": matched_cases,
        "unmatched_cases": unmatched_cases,
        "invoice_spend_cents": invoice_spend,
        "realized_cents": realized,
        "opportunity_cents": opportunity,
        "missed_opportunity_cents": missed,
        "capture_rate_bps": capture,
        "rebate_member_share_cents": rebate,
        "recovery_credit_cents": member["recovery_credit_cents"],
    }
