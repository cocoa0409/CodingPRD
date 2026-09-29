"""Cascade discipline of PRD 2.10: immediate, synchronous, every touched row's
updated_at refreshed and version incremented by 1.

Two chains dominate: the four-hop replenishment chain (shelf ledger -> site posture
-> account posture -> price adjustments) and the four-hop cancellation chain
(placements -> sites -> scheduled visits, with DRAFT invoices voided in the pass).
"""
from datetime import timedelta

import calc
from store import bump, db, now, ordered, snapshot, touch

ESCALATION_TRIGGER_SITES = 2
TERMINAL_OR_BILLED_PLACEMENT = ("RETRIEVED", "UNRETURNED_BILLED", "SUPERSEDED")


def account_of_site(site):
    return db.accounts.get(site["account_id"])


# --------------------------------------------------- hop four: price adjustments

def _defer_proposed_adjustments(account):
    for adj in ordered([a for a in db.price_adjustments.values()
                        if a["account_id"] == account["id"]]):
        if adj["adj_status"] == "PROPOSED":
            adj["adj_status"] = "DEFERRED"
            bump(adj)


def _restore_deferred_adjustments(account):
    for adj in ordered([a for a in db.price_adjustments.values()
                        if a["account_id"] == account["id"]]):
        if adj["adj_status"] == "DEFERRED":
            adj["adj_status"] = "PROPOSED"
            bump(adj)


# ------------------------------------------------------- hop three: the account

def recompute_escalated_site_count(account):
    """PRD 3.1: inclusive going up (two escalated sites is enough), strict coming
    down (one escalated site restores the account)."""
    if account is None:
        return
    before = snapshot(account)
    count = sum(1 for s in calc.account_sites(account["id"])
                if s["service_posture"] == "ESCALATED")
    account["escalated_site_count"] = count
    if count >= ESCALATION_TRIGGER_SITES and account["program_posture"] == "ACTIVE":
        account["program_posture"] = "AT_RISK"
        _defer_proposed_adjustments(account)
    elif count < ESCALATION_TRIGGER_SITES and account["program_posture"] == "AT_RISK":
        account["program_posture"] = "ACTIVE"
        _restore_deferred_adjustments(account)
    touch(account, before)


# --------------------------------------------------------- hop two: the site

def apply_site_posture(site, version_only_on_posture_change=False, before=None):
    """Recompute escalation_score and apply the ACTIVE <-> ESCALATED transition, then
    carry the change up into the account. Returns True when the posture moved."""
    if before is None:
        before = snapshot(site)
    score = calc.escalation_score(site)
    site["escalation_score"] = calc.score_to_number(score)
    posture_changed = False
    if score >= calc.ESCALATION_THRESHOLD and site["service_posture"] == "ACTIVE":
        site["service_posture"] = "ESCALATED"
        posture_changed = True
    elif score < calc.ESCALATION_THRESHOLD and site["service_posture"] == "ESCALATED":
        site["service_posture"] = "ACTIVE"
        posture_changed = True
    if version_only_on_posture_change:
        if posture_changed:
            bump(site)
    else:
        touch(site, before)
    recompute_escalated_site_count(account_of_site(site))
    return posture_changed


# ---------------------------------------------------- account closure (PRD 3.1)

def maybe_close_account(account):
    """The program closes only when the equipment is accounted for."""
    if account is None or account["program_posture"] != "CANCELLATION_PENDING":
        return False
    placements = calc.account_placements(account["id"])
    if any(p["placement_status"] not in TERMINAL_OR_BILLED_PLACEMENT for p in placements):
        return False
    account["program_posture"] = "CLOSED"
    bump(account)
    for site in ordered(calc.account_sites(account["id"])):
        if site["service_posture"] == "SUSPENDED":
            site["service_posture"] = "CLOSED"
            bump(site)
    return True


# --------------------------------------------- cancellation cascade (PRD 3.1)

def cancel_account(account, cancel_reason, retrieval_due_by):
    current = now()
    account["program_posture"] = "CANCELLATION_PENDING"
    account["cancel_reason"] = cancel_reason
    account["retrieval_due_by"] = retrieval_due_by
    account["cancelled_at"] = current

    affected_site_ids = []
    # Hop one: ACTIVE placements of every site of this account.
    for placement in ordered(calc.account_placements(account["id"])):
        if placement["placement_status"] != "ACTIVE":
            continue
        placement["placement_status"] = "RETRIEVAL_SCHEDULED"
        placement["retrieval_due_by"] = retrieval_due_by
        bump(placement)
        if placement["site_id"] not in affected_site_ids:
            affected_site_ids.append(placement["site_id"])

    # Hop two: each site owning one of those placements is suspended.
    for site_id in affected_site_ids:
        site = db.sites.get(site_id)
        if site is None or site["service_posture"] == "SUSPENDED":
            continue
        site["service_posture"] = "SUSPENDED"
        bump(site)

    # Hop three: SCHEDULED visits of those sites are cancelled, releasing minutes.
    for site_id in affected_site_ids:
        for visit in ordered([v for v in db.service_visits.values()
                              if v["site_id"] == site_id]):
            if visit["visit_status"] != "SCHEDULED":
                continue
            visit["visit_status"] = "CANCELLED"
            bump(visit)
            route = db.routes.get(visit["route_id"])
            if route is not None:
                route["booked_minutes_total"] = (route["booked_minutes_total"]
                                                 - visit["planned_minutes"])
                bump(route)

    # Same pass: DRAFT invoices of the account are voided.
    for invoice in ordered([i for i in db.invoices.values()
                            if i["account_id"] == account["id"]]):
        if invoice["invoice_status"] == "DRAFT":
            invoice["invoice_status"] = "VOID"
            bump(invoice)

    # A suspended site no longer counts as escalated.
    count = sum(1 for s in calc.account_sites(account["id"])
                if s["service_posture"] == "ESCALATED")
    account["escalated_site_count"] = count
    bump(account)


# --------------------------------------------- lazy fleet promotions (PRD 3.3)

def lazy_release_reconditioning(asset):
    """A RECONDITIONING asset whose hold has expired becomes IN_STOCK again with
    reconditioning_until cleared - evaluated when a business call reaches for it."""
    if asset["asset_status"] != "RECONDITIONING":
        return
    hold = asset.get("reconditioning_until")
    if hold is not None and hold > now():
        return
    asset["asset_status"] = "IN_STOCK"
    asset["reconditioning_until"] = None
    bump(asset)


def enter_reconditioning(asset, from_instant):
    """The sanitation hold is one calendar day long."""
    asset["asset_status"] = "RECONDITIONING"
    asset["reconditioning_until"] = from_instant + timedelta(days=1)
    bump(asset)
