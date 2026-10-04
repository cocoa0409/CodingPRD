"""Posting queue + matched/claim earnings helpers."""
import db
from calc import effective_active_shares, allocate_to_shares


def queue_matched_postings(line, report, line_type):
    """Queue per-share postings for a line that matched (or was claimed).
    line_type is MATCHED_EARNINGS or CLAIM_EARNINGS."""
    work = db.works.get(line.get("matched_work_id"))
    if work is None:
        return
    shares = effective_active_shares(work, report["reporting_month"])
    for share, cents in allocate_to_shares(line["royalties_cents"], shares):
        if cents == 0:
            continue
        db.postings.append({
            "member_id": share["claimant_member_id"],
            "period_month": report["reporting_month"],
            "usage_line_id": line["id"],
            "allocated_cents": cents,
            "line_type": line_type,
        })


def drop_postings_for_line(line_id, line_type):
    """Discard queued postings of a line (dispute resolved against claim)."""
    db.postings[:] = [
        p for p in db.postings
        if not (p["usage_line_id"] == line_id and p["line_type"] == line_type)
    ]


def recompute_report_totals(report):
    lines = [l for l in db.usage_lines.values() if l["report_id"] == report["id"]]
    report["total_usage_cents"] = sum(l["royalties_cents"] for l in lines)
    report["matched_usage_cents"] = sum(
        l["royalties_cents"] for l in lines if l["status"] == "MATCHED")
    report["unmatched_usage_cents"] = sum(
        l["royalties_cents"] for l in lines if l["status"] == "UNMATCHED")


def recompute_work_total_share(work):
    work["total_share_percent"] = sum(
        s["share_percent"] for s in db.work_shares.values()
        if s["work_id"] == work["id"] and s["status"] == "ACTIVE")
