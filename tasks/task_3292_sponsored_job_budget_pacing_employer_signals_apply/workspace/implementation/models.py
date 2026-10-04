"""Row factories and per-entity serializers.

Common fields follow PRD 2.4: the mutable families carry ``id``, ``created_at``,
``updated_at`` and ``version``; the two append-only families (ApplyEvent,
BudgetLedger) carry only ``id`` and ``created_at``.
"""

import hashlib
import uuid

from db import iso, store

MUTABLE = {
    "employers", "job_seekers", "campaigns", "sponsored_jobs", "job_postings",
    "job_posting_versions", "assessments", "applications", "job_alert_subscriptions",
    "sponsor_events", "pacing_holds",
}
APPEND_ONLY = {"apply_events", "budget_ledger"}


def new_id():
    return str(uuid.uuid4())


_NEXT_SEQ = [0]


def _next_seq():
    """Monotonic insertion counter — the deterministic tie-break for list order.

    The logical clock is frozen between advances, so many rows share a
    ``created_at``; insertion order is the resolution of those ties.
    """
    _NEXT_SEQ[0] += 1
    store.seq = _NEXT_SEQ[0]
    return _NEXT_SEQ[0]


def _new(table, **fields):
    row = {"id": new_id(), "_seq": _next_seq()}
    row.update(fields)
    row["created_at"] = iso(store.clock)
    if table in MUTABLE:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    getattr(store, table)[row["id"]] = row
    return row


def create(table, **fields):
    return _new(table, **fields)


def append(table, **fields):
    """Append-only row: id + created_at, never updated, never versioned."""
    row = {"id": new_id(), "_seq": _next_seq()}
    row.update(fields)
    row["created_at"] = iso(store.clock)
    getattr(store, table)[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version — the single mutation bookkeeping step."""
    row["updated_at"] = iso(store.clock)
    row["version"] = row.get("version", 1) + 1
    return row


def content_hash(title, description_text):
    return hashlib.sha256(
        (str(title).casefold() + str(description_text)).encode("utf-8")
    ).hexdigest()


def normalize_location(location):
    return " ".join(str(location or "").casefold().split())


def dedupe_key(title, location, external_posting_id):
    return "|".join([
        str(title).casefold().strip(),
        normalize_location(location),
        "" if external_posting_id is None else str(external_posting_id),
    ])


# --------------------------------------------------------------------- views

def employer_view(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "domain": row["domain"],
        "ats_provider": row["ats_provider"],
        "status": row["status"],
        "quality_score": row["quality_score"],
        "response_rate_bps": row["response_rate_bps"],
        "billing_status": row["billing_status"],
        "balance_cents": row["balance_cents"],
        "last_invoice_at": row["last_invoice_at"],
        "suspended_at": row["suspended_at"],
        "suspension_reason": row["suspension_reason"],
        **common(row),
    }


def seeker_view(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "location": row["location"],
        "status": row["status"],
        **common(row),
    }


def campaign_view(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "name": row["name"],
        "pricing_model": row["pricing_model"],
        "daily_budget_cents": row["daily_budget_cents"],
        "total_budget_cents": row["total_budget_cents"],
        "status": row["status"],
        "spent_cents": row["spent_cents"],
        "daily_spent_cents": row["daily_spent_cents"],
        "held_cents": row["held_cents"],
        "day_open_date": row["day_open_date"],
        **common(row),
    }


def sponsored_job_view(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "job_posting_id": row["job_posting_id"],
        "cpc_bid_cents": row["cpc_bid_cents"],
        "cpa_bid_cents": row["cpa_bid_cents"],
        "scheduled_pacing_multiplier": row["scheduled_pacing_multiplier"],
        "realized_pacing_multiplier": row["realized_pacing_multiplier"],
        "status": row["status"],
        "impressions": row["impressions"],
        "clicks": row["clicks"],
        "applications": row["applications"],
        **common(row),
    }


def job_posting_view(row):
    return {
        "id": row["id"],
        "employer_id": row["employer_id"],
        "title": row["title"],
        "location": row["location"],
        "description_text": row["description_text"],
        "state": row["state"],
        "current_freshness": row["current_freshness"],
        "apply_mode": row["apply_mode"],
        "apply_redirect_url": row["apply_redirect_url"],
        "posted_at": row["posted_at"],
        "apply_started_count": row["apply_started_count"],
        "apply_completed_count": row["apply_completed_count"],
        "dedupe_key": row["dedupe_key"],
        **common(row),
    }


def version_view(row):
    return {
        "id": row["id"],
        "job_posting_id": row["job_posting_id"],
        "content_hash": row["content_hash"],
        "external_posting_id": row["external_posting_id"],
        "ingested_at": row["ingested_at"],
        "freshness": row["freshness"],
        **common(row),
    }


def assessment_view(row):
    return {
        "id": row["id"],
        "job_posting_id": row["job_posting_id"],
        "questions": row["questions"],
        "pass_threshold": row["pass_threshold"],
        "status": row["status"],
        **common(row),
    }


def application_view(row):
    return {
        "id": row["id"],
        "job_posting_id": row["job_posting_id"],
        "job_seeker_id": row["job_seeker_id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "disposition": row["disposition"],
        "responded_at": row["responded_at"],
        "assessment_id": row["assessment_id"],
        "assessment_score": row["assessment_score"],
        **common(row),
    }


def apply_event_view(row):
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "kind": row["kind"],
        "source": row["source"],
        "occurred_at": row["occurred_at"],
        "created_at": row["created_at"],
    }


def alert_subscription_view(row):
    return {
        "id": row["id"],
        "job_seeker_id": row["job_seeker_id"],
        "keywords": row["keywords"],
        "location": row["location"],
        "status": row["status"],
        "last_notified_at": row["last_notified_at"],
        "notified_posting_ids": list(row["notified_posting_ids"]),
        **common(row),
    }


def sponsor_event_view(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "sponsored_job_id": row["sponsored_job_id"],
        "event_type": row["event_type"],
        "billable": row["billable"],
        "cost_cents": row["cost_cents"],
        "status": row["status"],
        "occurred_at": row["occurred_at"],
        "device_fingerprint": row["device_fingerprint"],
        "ip_hash": row["ip_hash"],
        **common(row),
    }


def ledger_view(row):
    return {
        "id": row["id"],
        "campaign_id": row["campaign_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "sponsor_event_id": row["sponsor_event_id"],
        "reference_code": row["reference_code"],
        "created_at": row["created_at"],
    }


def pacing_hold_view(row):
    return {
        "id": row["id"],
        "sponsored_job_id": row["sponsored_job_id"],
        "campaign_id": row["campaign_id"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "sponsor_event_id": row["sponsor_event_id"],
        **common(row),
    }


def common(row):
    return {
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }