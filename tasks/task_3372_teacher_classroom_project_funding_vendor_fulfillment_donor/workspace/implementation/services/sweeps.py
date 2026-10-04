"""The four-phase expiration sweep (SCAFFOLD expiration_sweep). Fixed order:
1. FUNDING projects at/past deadline -> EXPIRED (funding_started_at ASC, then
   created_at ASC); CAPTURED donations -> CHOICE_PENDING with match clawback.
2. CHOICE_PENDING donations at/past choice_deadline -> REFUNDED/EXPIRED_AUTO
   (choice_deadline ASC, then created_at ASC).
3. ACTIVE/EXHAUSTED campaigns with ends_at <= now -> CLOSED.
4. ACTIVE/DEPLETED equity funds with window_end < now -> CLOSED.
Boundaries: project deadline equality expires; choice_deadline equality
auto-refunds; fund window_end must be strictly before now.
"""
from datetime import timedelta

import store
from services import matching

CHOICE_WINDOW_DAYS = 14


def expiration_run(now):
    expired_project_ids = []
    choice_pending_donation_ids = []
    auto_refunded_donation_ids = []
    closed_match_campaign_ids = []
    closed_equity_fund_ids = []

    # Phase 1: project expiry.
    projects = [
        p for p in store.projects.values()
        if p["status"] == "FUNDING" and p["funding_deadline"] is not None
        and p["funding_deadline"] <= now
    ]
    projects.sort(key=lambda p: (p["funding_started_at"], p["created_at"], p["_seq"]))
    for project in projects:
        project["status"] = "EXPIRED"
        store.touch(project)
        expired_project_ids.append(project["id"])
        donations = [
            d for d in store.donations.values()
            if d["project_id"] == project["id"] and d["status"] == "CAPTURED"
        ]
        donations.sort(key=lambda d: (d["created_at"], d["_seq"]))
        for donation in donations:
            donation["status"] = "CHOICE_PENDING"
            donation["choice_deadline"] = now + timedelta(days=CHOICE_WINDOW_DAYS)
            matching.clawback_match(donation, now)
            store.touch(donation)
            choice_pending_donation_ids.append(donation["id"])

    # Phase 2: choice auto-refund.
    pending = [
        d for d in store.donations.values()
        if d["status"] == "CHOICE_PENDING" and d["choice_deadline"] is not None
        and d["choice_deadline"] <= now
    ]
    pending.sort(key=lambda d: (d["choice_deadline"], d["created_at"], d["_seq"]))
    for donation in pending:
        donation["status"] = "REFUNDED"
        donation["refund_reason"] = "EXPIRED_AUTO"
        donor = store.donors.get(donation["donor_id"]) if donation["donor_id"] else None
        if donor is not None:
            donor["lifetime_refunded_cents"] += donation["amount_cents"]
            store.touch(donor)
        store.touch(donation)
        auto_refunded_donation_ids.append(donation["id"])

    # Phase 3: campaign closeout (ends_at at or before now).
    campaigns = [
        c for c in store.match_campaigns.values()
        if c["status"] in ("ACTIVE", "EXHAUSTED") and c["ends_at"] <= now
    ]
    campaigns.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for campaign in campaigns:
        campaign["status"] = "CLOSED"
        store.touch(campaign)
        closed_match_campaign_ids.append(campaign["id"])

    # Phase 4: equity fund closeout (window_end strictly before now).
    funds = [
        f for f in store.equity_funds.values()
        if f["status"] in ("ACTIVE", "DEPLETED") and f["window_end"] < now
    ]
    funds.sort(key=lambda f: (f["created_at"], f["_seq"]))
    for fund in funds:
        fund["status"] = "CLOSED"
        store.touch(fund)
        closed_equity_fund_ids.append(fund["id"])

    return {
        "expired_project_ids": expired_project_ids,
        "choice_pending_donation_ids": choice_pending_donation_ids,
        "auto_refunded_donation_ids": auto_refunded_donation_ids,
        "closed_match_campaign_ids": closed_match_campaign_ids,
        "closed_equity_fund_ids": closed_equity_fund_ids,
    }
