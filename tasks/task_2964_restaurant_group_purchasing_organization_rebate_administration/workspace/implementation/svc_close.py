"""Period close: blended rebasing, payment and the admin-fee refreeze (PRD §3.9)."""

from store import db, touch
from svc_accrue import gross_for_line, split_gross
from svc_common import items_of_deal, tier_of_member


def accruals_of_deal_period(deal, period_start, period_end, statuses):
    """Accruals priced by this deal's items whose line invoice_date is in the period."""
    item_ids = set(i["id"] for i in items_of_deal(deal))
    out = []
    for accrual in db.accruals.values():
        if accrual["status"] not in statuses:
            continue
        card = db.rate_cards.get(accrual["rate_card_id"])
        if card is None or card["contracted_item_id"] not in item_ids:
            continue
        line = db.lines.get(accrual["purchase_line_id"])
        if line is None:
            continue
        if not (period_start <= line["invoice_date"] <= period_end):
            continue
        out.append(accrual)
    return out


def blended_case_total(member_id, item_id, period_start, period_end):
    """Total MATCHED cases for one (member, item) across every batch in the period."""
    total = 0
    for line in db.lines.values():
        if line["match_status"] != "MATCHED":
            continue
        if line["member_id"] != member_id:
            continue
        if line["contracted_item_id"] != item_id:
            continue
        if not (period_start <= line["invoice_date"] <= period_end):
            continue
        total += line["cases_shipped"]
    return total


def close_period(deal, period_start, period_end):
    """Rebase, pay and refreeze; returns nothing (the deal is the response record)."""
    touched = accruals_of_deal_period(
        deal, period_start, period_end, ("ACCRUED", "VALIDATED", "FLAGGED"))

    affected_members = {}
    for accrual in touched:
        card = db.rate_cards.get(accrual["rate_card_id"])
        line = db.lines.get(accrual["purchase_line_id"])
        member = db.members.get(accrual["member_id"])
        tier = tier_of_member(member) if member is not None else None
        if card is None or line is None or member is None or tier is None:
            continue
        affected_members[member["id"]] = member

        period_cases = blended_case_total(
            member["id"], card["contracted_item_id"], period_start, period_end)
        new_gross = gross_for_line(card, line, blended_total=period_cases)

        old_gross = accrual["gross_rebate_cents"]
        old_fee = accrual["admin_fee_cents"]
        old_share = accrual["member_share_cents"]
        old_retention = accrual["gpo_retention_cents"]

        # The band selection step is NOT re-run: the frozen admin_fee_bps_applied
        # is reused verbatim and only the four money fields are rewritten.
        fee, net, share, retention = split_gross(
            new_gross, accrual["admin_fee_bps_applied"], tier["member_share_bps"])

        accrual["gross_rebate_cents"] = new_gross
        accrual["final_adjustment_cents"] = new_gross - old_gross
        accrual["basis"] = "BLENDED_PERIOD"
        accrual["admin_fee_cents"] = fee
        accrual["net_distributable_cents"] = net
        accrual["member_share_cents"] = share
        accrual["gpo_retention_cents"] = retention
        touch(accrual)

        # Each counter moves by the signed delta between the new and old component.
        member["accrued_member_share_cents"] += share - old_share
        member["attributed_gpo_retention_cents"] += retention - old_retention
        member["attributed_admin_fee_cents"] += fee - old_fee
        touch(member)

    # Payment: only VALIDATED accruals of members without a payout hold.
    for accrual in touched:
        if accrual["status"] != "VALIDATED":
            continue
        member = db.members.get(accrual["member_id"])
        if member is None or member["payout_hold"]:
            continue
        accrual["status"] = "PAID"
        touch(accrual)

    # Refreeze the administration-fee band from the post-close attributed net.
    for member in affected_members.values():
        snapshot = (member["accrued_member_share_cents"]
                    + member["attributed_gpo_retention_cents"])
        if member["ytd_net_snapshot_cents"] != snapshot:
            member["ytd_net_snapshot_cents"] = snapshot
            touch(member)

    # The deal's status is unchanged by a close, but its version advances.
    touch(deal)
