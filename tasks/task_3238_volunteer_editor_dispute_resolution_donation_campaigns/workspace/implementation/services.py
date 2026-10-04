"""Domain services: scores, eligibility, protection expiry, dispute derivation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, _parse_iso, _format_iso
from helpers import touch


def days_ago(n):
    return db.now() - timedelta(days=n)


def confirmed_reports(editor_id, within_days):
    """VandalismReports for revisions authored by editor_id, CONFIRMED, in window."""
    cutoff = days_ago(within_days)
    out = []
    for r in db.vandalism_reports.values():
        if r["status"] != "CONFIRMED":
            continue
        rev = db.revisions.get(r["revision_id"])
        if rev is None or rev["editor_id"] != editor_id:
            continue
        if _parse_iso(r["created_at"]) >= cutoff:
            out.append(r)
    return out


def recompute_rollback_eligible(editor):
    """rollback_eligible is true exactly when the editor has zero confirmed
    vandalism reports in the last ninety days (PRD 3.6)."""
    editor["rollback_eligible"] = len(confirmed_reports(editor["id"], 90)) == 0


def has_prior_confirmed_vandalism(editor_id):
    for r in db.vandalism_reports.values():
        if r["status"] != "CONFIRMED":
            continue
        rev = db.revisions.get(r["revision_id"])
        if rev is not None and rev["editor_id"] == editor_id:
            return True
    return False


def compute_vandalism_score(page, editor, content_text):
    """PRD 3.2: base + keyword + pattern + history, capped at 100."""
    base = 10 if page.get("current_revision_id") is None else 5
    keyword = 30 if _spam_keywords(content_text) else 0
    pattern = 40 if _mass_blanking(content_text) else 0
    history = 20 if has_prior_confirmed_vandalism(editor["id"]) else 0
    return min(100, base + keyword + pattern + history)


_SPAM_WORDS = ("spam", "viagra", "casino", "buy now", "free money")


def _spam_keywords(text):
    t = (text or "").lower()
    return any(w in t for w in _SPAM_WORDS)


def _mass_blanking(text):
    return text is None or str(text).strip() == ""


def recompute_content_score(page):
    """PRD 3.12: 0.4*avg(source) + 0.4*avg(neutrality) + 0.2*stability_bonus,
    over ACCEPTED revisions of the last 30 days; round half-up to int 0-100."""
    cutoff = days_ago(30)
    accepted = [r for r in db.revisions.values()
                if r["page_id"] == page["id"] and r["status"] == "ACCEPTED"
                and _parse_iso(r["updated_at"]) >= cutoff]
    if not accepted:
        page["content_score"] = 0
        return
    avg_src = sum(r["source_quality_score"] for r in accepted) / len(accepted)
    avg_neu = sum(r["neutrality_score"] for r in accepted) / len(accepted)
    page_disputes = [d for d in db.disputes.values()
                     if d["page_id"] == page["id"]
                     and _parse_iso(d["opened_at"]) >= cutoff]
    if not page_disputes:
        stability = 100
    elif all(d["level"] == "TALK" for d in page_disputes):
        stability = 50
    else:
        stability = 0
    raw = 0.4 * avg_src + 0.4 * avg_neu + 0.2 * stability
    page["content_score"] = int(
        Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_dispute_level(page):
    """dispute_level derived from open disputes: NONE | TALK | NOTICE | ARB."""
    open_ds = [d for d in db.disputes.values()
               if d["page_id"] == page["id"] and d["status"] in ("OPEN", "ESCALATED")]
    if not open_ds:
        page["dispute_level"] = "NONE"
    elif any(d["level"] == "ARBITRATION" for d in open_ds):
        page["dispute_level"] = "ARB"
    elif any(d["level"] == "NOTICE" for d in open_ds):
        page["dispute_level"] = "NOTICE"
    else:
        page["dispute_level"] = "TALK"


def has_open_arbitration(page_id):
    return any(d for d in db.disputes.values()
               if d["page_id"] == page_id and d["level"] == "ARBITRATION"
               and d["status"] in ("OPEN", "ESCALATED"))


def protection_permits(page, role, editor):
    """NONE: any; SEMI: account_age >= 4 days; FULL: Administrator only."""
    level = page["protection_level"]
    if role == "Administrator":
        return True
    if level == "NONE":
        return True
    if level == "SEMI":
        if editor is None:
            return False
        age = db.now() - _parse_iso(editor["created_at"])
        return age >= timedelta(days=4)
    # FULL
    return False


def expire_protections():
    """System transition: APPROVED protection requests whose expires_at has
    been reached transition to EXPIRED and revert page protection to prior
    level (or NONE)."""
    now = db.now()
    for pr in db.protection_requests.values():
        if pr["status"] != "APPROVED" or not pr.get("expires_at"):
            continue
        if _parse_iso(pr["expires_at"]) <= now:
            page = db.pages.get(pr["page_id"])
            pr["status"] = "EXPIRED"
            touch(pr, bump_version=False)
            if page is not None:
                page["protection_level"] = pr.get("prior_protection_level") or "NONE"
                touch(page)


def conversion_rate_bp_truncated(banner):
    impressions = max(banner["impression_count"], 1)
    return (banner["conversion_count"] * 10000) // impressions


def conversion_rate_bp_rounded(banner):
    impressions = max(banner["impression_count"], 1)
    raw = Decimal(banner["conversion_count"] * 10000) / Decimal(impressions)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def net_revenue_allocation(campaign_id):
    """Per-banner round-then-sum 3% fee allocation (PRD 3.9)."""
    banners = [b for b in db.banners.values() if b["campaign_id"] == campaign_id]
    per_banner = []
    total_net = 0
    for b in sorted(banners, key=lambda x: (x["created_at"], x["id"])):
        attributed = sum(d["amount_cents"] for d in db.donations.values()
                         if d["banner_id"] == b["id"] and d["status"] == "COMPLETED")
        fee = int((Decimal(attributed) * Decimal("0.03")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        net = attributed - fee
        total_net += net
        per_banner.append({
            "banner_id": b["id"],
            "attributed_cents": attributed,
            "fee_cents": fee,
            "net_cents": net,
        })
    return per_banner, total_net
