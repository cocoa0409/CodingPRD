"""Reputation ledger (calculation reputation_delta, PRD §3.3).

reputation_lifetime = max(0, 100 + SUM(all unreversed deltas))
reputation_rolling180 = max(0, 100 + SUM(unreversed deltas with
    occurred_at >= now - 180 days, boundary inclusive))
tier: ELITE >= 500, ESTABLISHED >= 250, else NOVICE (inclusive).
"""
from datetime import timedelta

import clock
import db


def _events(researcher_id):
    return db.reputation_ledger.setdefault(researcher_id, [])


def apply_delta(researcher, delta, kind):
    _events(researcher["id"]).append(
        {"delta": delta, "occurred_at": clock.now(), "reversed": False, "kind": kind}
    )
    refresh_reputation(researcher)


def refresh_reputation(researcher):
    events = _events(researcher["id"])
    lifetime = 100 + sum(e["delta"] for e in events if not e["reversed"])
    lifetime = max(0, lifetime)
    cutoff = clock.now() - timedelta(days=180)
    rolling = 100 + sum(
        e["delta"] for e in events if not e["reversed"] and e["occurred_at"] >= cutoff
    )
    rolling = max(0, rolling)
    researcher["reputation_lifetime"] = lifetime
    researcher["reputation_rolling180"] = rolling
    researcher["tier"] = tier_of(rolling)


def tier_of(rolling):
    if rolling >= 500:
        return "ELITE"
    if rolling >= 250:
        return "ESTABLISHED"
    return "NOVICE"


RESOLUTION_DELTAS = {"CRITICAL": 100, "HIGH": 50, "MEDIUM": 20, "LOW": 5, "NONE": 0}


def apply_resolution_delta(researcher, severity_final):
    apply_delta(researcher, RESOLUTION_DELTAS[severity_final], "resolution")
