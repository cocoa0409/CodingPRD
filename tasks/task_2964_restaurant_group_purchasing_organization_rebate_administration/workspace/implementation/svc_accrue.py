"""Rate selection, gross rebate, the split waterfall and accrual posting (PRD §3.4)."""

from money import (ADMIN_FEE_BAND_BREAK_CENTS, BPS_DENOMINATOR, apply_bps)
from store import db, new_record, touch
from svc_common import (accruals_of_batch, cards_of_item,
                        lines_of_batch_by_invoice_date, retract_accrual_from_member,
                        post_accrual_to_member, tier_of_member)


# --------------------------------------------------------------------------
# rate card selection
# --------------------------------------------------------------------------

def select_rate_card(item_id, invoice_date):
    """The APPROVED card whose closed range covers the invoice date.

    Ordered by effective_from DESC (the latest-starting card wins as the most
    recently negotiated pricing), ties broken by created_at ASC -- never by id.
    """
    item = db.items.get(item_id)
    if item is None:
        return None
    candidates = [c for c in cards_of_item(item)
                  if c["status"] == "APPROVED"
                  and c["effective_from"] <= invoice_date <= c["effective_to"]]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["created_at"], c["_seq"]))
    candidates.sort(key=lambda c: c["effective_from"], reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------
# tiered-volume ladders
# --------------------------------------------------------------------------

def _sorted_breaks(card):
    return sorted(card["tier_breaks"], key=lambda t: t["min_cases"])


def _rate_for_position(breaks, position):
    """Rate for the case sitting on cumulative volume `position` before itself.

    A tier's `min_cases` is the cumulative case count at which the tier is
    reached, so the case that carries the ladder from below the threshold to at
    or above it is the first one paid at the higher rate: cases falling below
    the threshold earn the lower tier's rate and cases at or above it the
    higher tier's.  The blended selection below compares the period-wide total
    to `min_cases` directly and is unaffected.
    """
    rate = breaks[0]["rate_cents_per_case"]
    for entry in breaks:
        if entry["min_cases"] <= position:
            rate = entry["rate_cents_per_case"]
        else:
            break
    return rate


def tiered_marginal(card, prior_cases, cases):
    """Marginal ladder: a line straddling a break is split, each slice at its own rate."""
    breaks = _sorted_breaks(card)
    total = 0
    for offset in range(cases):
        total += _rate_for_position(breaks, prior_cases + offset)
    return total


def tiered_blended(card, period_total_cases, cases):
    """Blended ladder: one rate chosen on the period-wide total, applied to all cases."""
    breaks = _sorted_breaks(card)
    rate = breaks[0]["rate_cents_per_case"]
    for entry in breaks:
        if entry["min_cases"] <= period_total_cases:
            rate = entry["rate_cents_per_case"]
        else:
            break
    return rate * cases


def gross_for_line(card, line, cumulative_prior=0, blended_total=None):
    """The manufacturer-funded gross rebate on one matched line."""
    if card["rate_type"] == "PER_CASE":
        return line["cases_shipped"] * card["flat_rate_cents_per_case"]
    if card["rate_type"] == "PERCENT_OF_SPEND":
        return apply_bps(line["invoice_extended_cents"], card["percent_bps"])
    if blended_total is None:
        return tiered_marginal(card, cumulative_prior, line["cases_shipped"])
    return tiered_blended(card, blended_total, line["cases_shipped"])


# --------------------------------------------------------------------------
# the five-step split waterfall
# --------------------------------------------------------------------------

def select_admin_fee_bps(member, tier):
    """Step one: the band reads the FROZEN ytd snapshot, never the live totals."""
    if member["ytd_net_snapshot_cents"] < ADMIN_FEE_BAND_BREAK_CENTS:
        return tier["admin_fee_bps_low"]
    return tier["admin_fee_bps_high"]


def split_gross(gross, admin_fee_bps, member_share_bps):
    """Steps two through five, in the pinned order; retention absorbs the residual."""
    admin_fee = apply_bps(gross, admin_fee_bps)
    net = gross - admin_fee
    member_share = apply_bps(net, member_share_bps)
    retention = net - member_share
    return admin_fee, net, member_share, retention


# --------------------------------------------------------------------------
# accrual run
# --------------------------------------------------------------------------

def accruable_lines(batch):
    """MATCHED lines of the batch that resolve an APPROVED card for their own date."""
    out = []
    for line in lines_of_batch_by_invoice_date(batch):
        if line["match_status"] != "MATCHED":
            continue
        card = select_rate_card(line["contracted_item_id"], line["invoice_date"])
        if card is not None:
            out.append((line, card))
    return out


def accrue_batch(batch, caller):
    """Create one accrual per accruable line using the MARGINAL_BATCH variant."""
    cumulative = {}
    created = []
    for line in lines_of_batch_by_invoice_date(batch):
        if line["match_status"] != "MATCHED":
            continue
        item_id = line["contracted_item_id"]
        prior = cumulative.get(item_id, 0)
        # Every MATCHED line of the batch for this item lays its cases into the
        # ladder, whether or not it resolved a card of its own.
        cumulative[item_id] = prior + line["cases_shipped"]

        card = select_rate_card(item_id, line["invoice_date"])
        if card is None:
            line["accrual_block_reason"] = "NO_RATE_CARD"
            touch(line)
            continue

        member = db.members.get(line["member_id"])
        tier = tier_of_member(member)
        gross = gross_for_line(card, line, cumulative_prior=prior)
        admin_fee_bps = select_admin_fee_bps(member, tier)
        admin_fee, net, member_share, retention = split_gross(
            gross, admin_fee_bps, tier["member_share_bps"])

        accrual = new_record("RebateAccrual", {
            "purchase_line_id": line["id"],
            "member_id": line["member_id"],
            "rate_card_id": card["id"],
            "basis": "MARGINAL_BATCH",
            "accrued_cases": line["cases_shipped"],
            "gross_rebate_cents": gross,
            "admin_fee_bps_applied": admin_fee_bps,
            "admin_fee_cents": admin_fee,
            "net_distributable_cents": net,
            "member_share_cents": member_share,
            "gpo_retention_cents": retention,
            "final_adjustment_cents": 0,
            "status": "ACCRUED",
            "reversal_reason": "NONE",
            "validated_by_user_id": None,
        })
        db.accruals[accrual["id"]] = accrual
        post_accrual_to_member(member, accrual)
        created.append(accrual)

    batch["normalization_status"] = "ACCRUED"
    batch["accrued_by_user_id"] = caller.user_id
    touch(batch)
    return created


def reverse_batch_accruals(batch, reason):
    """Retract every open accrual of the batch, component by exact component."""
    for accrual in accruals_of_batch(batch):
        if accrual["status"] not in ("ACCRUED", "FLAGGED"):
            continue
        accrual["status"] = "REVERSED"
        accrual["reversal_reason"] = reason
        touch(accrual)
        member = db.members.get(accrual["member_id"])
        if member is not None:
            retract_accrual_from_member(member, accrual)
