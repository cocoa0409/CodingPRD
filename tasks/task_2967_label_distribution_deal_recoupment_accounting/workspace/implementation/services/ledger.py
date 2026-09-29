"""Shared ledger recomputations used from more than one route module."""

from services import lookups


def committed_marketing(deal, exclude_spend_id=None, override=None):
    """The deal's committed marketing total (PRD section 3.4).

    A SETTLED spend contributes its settled amount, an APPROVED spend its
    approved amount, and every other status contributes nothing.  `override`
    lets the settlement ceiling revalue the spend being settled.
    """
    total = 0
    for spend in lookups.spends_of_deal(deal["id"]):
        if exclude_spend_id is not None and spend["id"] == exclude_spend_id:
            continue
        if spend["status"] == "APPROVED":
            total += spend.get("amount_cents") or 0
        elif spend["status"] == "SETTLED":
            total += spend.get("settled_amount_cents") or 0
    if override is not None:
        total += override
    return total


def recompute_marketing_committed(deal):
    deal["marketing_committed_cents"] = committed_marketing(deal)
    return deal["marketing_committed_cents"]
