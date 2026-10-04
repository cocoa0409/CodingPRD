"""Match allocation and clawback (SCAFFOLD match_allocation /
campaign_budget_invariant). Per-donation round-half-up FIRST, then
accumulate; clawbacks move exactly the same cents back."""
from decimal import Decimal, ROUND_HALF_UP

import store


def compute_match(amount_cents, campaign):
    raw = Decimal(amount_cents) * Decimal(str(campaign["match_ratio"]))
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(rounded, campaign["remaining_budget_cents"])


def apply_match(donation, campaign):
    matched = compute_match(donation["amount_cents"], campaign)
    donation["matched_cents"] = matched
    if matched > 0:
        campaign["matched_so_far_cents"] += matched
        campaign["remaining_budget_cents"] -= matched
        if campaign["remaining_budget_cents"] == 0 and campaign["status"] == "ACTIVE":
            campaign["status"] = "EXHAUSTED"
        store.touch(campaign)
    return matched


def clawback_match(donation, now):
    """Return the donation's matched_cents to its campaign and zero the
    donation's match. EXHAUSTED flips back to ACTIVE while the half-open
    window still covers now."""
    matched = donation["matched_cents"]
    if matched and donation["match_campaign_id"]:
        campaign = store.match_campaigns.get(donation["match_campaign_id"])
        if campaign is not None:
            campaign["matched_so_far_cents"] -= matched
            campaign["remaining_budget_cents"] += matched
            if (
                campaign["status"] == "EXHAUSTED"
                and campaign["remaining_budget_cents"] > 0
                and campaign["starts_at"] <= now < campaign["ends_at"]
            ):
                campaign["status"] = "ACTIVE"
            store.touch(campaign)
    donation["matched_cents"] = 0
