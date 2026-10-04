"""Clock sweep and cascade helpers."""
from datetime import timedelta

import clock
import db
from helpers import touch
from services import reputation as rep_svc


def decline_pending_invitations_for_researcher(researcher_id):
    for inv in db.invitations.values():
        if inv["researcher_id"] == researcher_id and inv["status"] == "PENDING":
            inv["status"] = "DECLINED"
            touch(inv)


def decline_pending_invitations_for_program(program_id):
    for inv in db.invitations.values():
        if inv["program_id"] == program_id and inv["status"] == "PENDING":
            inv["status"] = "DECLINED"
            touch(inv)


def sweep(now):
    """Clock sweep effects (PRD §2.8). Returns (invitations_expired,
    researchers_reinstated)."""
    invitations_expired = 0
    for inv in db.invitations.values():
        if inv["status"] == "PENDING" and now > clock.parse_iso(inv["expires_at"]):
            inv["status"] = "EXPIRED"
            touch(inv)
            invitations_expired += 1
    researchers_reinstated = 0
    for r in db.researchers.values():
        if r["status"] == "SUSPENDED" and r.get("suspension_ends_at"):
            if now >= clock.parse_iso(r["suspension_ends_at"]):
                r["status"] = "ACTIVE"
                r["suspension_ends_at"] = None
                touch(r)
                researchers_reinstated += 1
    for r in db.researchers.values():
        rep_svc.refresh_reputation(r)
    return invitations_expired, researchers_reinstated


def apply_conduct_action(researcher, action, reason):
    """Conduct enforcement (PRD §3.3). Returns nothing; mutates researcher."""
    deltas = {"WARNING": -5, "STRIKE": -50, "BAN": -200}
    log = researcher["conduct_log"]
    now = clock.now()

    if action == "REVERSE_LAST":
        latest = None
        for entry in reversed(log):
            if not entry["reversed"]:
                latest = entry
                break
        if latest is None:
            # nothing to reverse; still recompute standing
            _recompute_standing(researcher)
            touch(researcher)
            return
        latest["reversed"] = True
        # exact compensation: remove its delta from the ledger
        for ev in reversed(db.reputation_ledger.get(researcher["id"], [])):
            if ev.get("conduct_seq") == latest["seq"] and not ev["reversed"]:
                ev["reversed"] = True
                break
        if latest["action"] == "STRIKE":
            researcher["strike_count"] = max(0, researcher["strike_count"] - 1)
        _recompute_standing(researcher)
        rep_svc.refresh_reputation(researcher)
        touch(researcher)
        return

    seq = (log[-1]["seq"] + 1) if log else 1
    log.append(
        {
            "seq": seq,
            "action": action,
            "reason": reason,
            "applied_at": clock.iso(now),
            "reversed": False,
        }
    )
    # ledger event tagged with conduct seq so REVERSE_LAST undoes it exactly
    db.reputation_ledger.setdefault(researcher["id"], []).append(
        {
            "delta": deltas[action],
            "occurred_at": now,
            "reversed": False,
            "kind": "conduct",
            "conduct_seq": seq,
        }
    )
    if action == "STRIKE":
        researcher["strike_count"] += 1
    _recompute_standing(researcher)
    rep_svc.refresh_reputation(researcher)
    touch(researcher)


def _recompute_standing(researcher):
    """Derive status from unreversed conduct log per PRD §3.3."""
    if researcher["status"] == "BANNED":
        return  # terminal
    log = researcher["conduct_log"]
    unreversed = [e for e in log if not e["reversed"]]
    has_ban = any(e["action"] == "BAN" for e in unreversed)
    strikes = sum(1 for e in unreversed if e["action"] == "STRIKE")
    now = clock.now()
    if has_ban or strikes >= 3:
        researcher["status"] = "BANNED"
        researcher["suspension_ends_at"] = None
        decline_pending_invitations_for_researcher(researcher["id"])
    elif strikes == 2:
        # last strike time + 14 days * strike_count
        last_strike = max(
            clock.parse_iso(e["applied_at"]) for e in unreversed if e["action"] == "STRIKE"
        )
        researcher["status"] = "SUSPENDED"
        researcher["suspension_ends_at"] = clock.iso(
            last_strike + timedelta(days=14 * strikes)
        )
        decline_pending_invitations_for_researcher(researcher["id"])
    else:
        if researcher["status"] == "SUSPENDED":
            researcher["status"] = "ACTIVE"
        researcher["suspension_ends_at"] = None
