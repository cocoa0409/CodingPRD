"""Cost-plus markup audit and overbilling recovery allocation (PRD §3.7)."""

from money import apply_bps, floor_div
from store import db, touch
from svc_common import (lines_of_batch, lines_of_batch_by_invoice_date,
                        tier_of_member)


def _auditable(line, batch):
    """Pricing may only be inspected under a PURCHASE_DATA_AND_PRICING letter."""
    for letter in db.letters.values():
        if letter["status"] != "ACTIVE":
            continue
        if letter["scope"] != "PURCHASE_DATA_AND_PRICING":
            continue
        if letter["member_id"] != line["member_id"]:
            continue
        if letter["distributor_id"] != batch["distributor_id"]:
            continue
        return True
    return False


def audit_batch_markup(batch):
    """Compute per-line and batch overbilling; returns the batch total."""
    distributor = db.distributors.get(batch["distributor_id"])
    total = 0
    for line in lines_of_batch_by_invoice_date(batch):
        # Visited regardless of match_status: overbilling is a pricing question.
        if not _auditable(line, batch):
            line["overbilled_cents"] = 0
            touch(line)
            continue

        member = db.members.get(line["member_id"])
        tier = tier_of_member(member) if member is not None else None
        ceilings = [distributor["contracted_markup_bps"]]
        if tier is not None:
            ceilings.append(tier["markup_cap_bps"])
        allowed_bps = min(ceilings)

        base = line["distributor_base_cost_cents"]
        # The half-up rounding lands on each line's allowed markup, before the
        # multiplication by cases -- never on a batch-level total.
        allowed_unit = base + apply_bps(base, allowed_bps)
        excess_per_case = line["invoice_unit_cost_cents"] - allowed_unit
        if excess_per_case < 0:
            excess_per_case = 0
        line["overbilled_cents"] = excess_per_case * line["cases_shipped"]
        touch(line)
        total += line["overbilled_cents"]

    batch["overbilled_cents"] = total
    batch["audit_status"] = "AUDIT_CLEAN" if total == 0 else "AUDIT_OVERBILLED"
    touch(batch)
    return total


def allocate_recovery(batch, recovered_cents):
    """Proportional waterfall with a one-cent-at-a-time residual rule."""
    if recovered_cents <= 0 or batch["overbilled_cents"] <= 0:
        return

    totals = {}
    for line in lines_of_batch(batch):
        if line["overbilled_cents"] > 0:
            key = line["member_id"]
            totals[key] = totals.get(key, 0) + line["overbilled_cents"]

    participants = []
    for member_id, member_total in totals.items():
        member = db.members.get(member_id)
        if member is None or member_total <= 0:
            continue
        participants.append((member, member_total))
    if not participants:
        return

    slices = {}
    assigned = 0
    for member, member_total in participants:
        provisional = floor_div(recovered_cents * member_total,
                               batch["overbilled_cents"])
        slices[member["id"]] = provisional
        assigned += provisional

    # Remainder cents go one at a time, overbilling total DESC then created_at ASC.
    remainder = recovered_cents - assigned
    ordered = sorted(participants,
                     key=lambda p: (-p[1], p[0]["created_at"], p[0]["_seq"]))
    index = 0
    while remainder > 0 and ordered:
        member = ordered[index % len(ordered)][0]
        slices[member["id"]] += 1
        remainder -= 1
        index += 1

    for member, _total in participants:
        member["recovery_credit_cents"] += slices[member["id"]]
        touch(member)
