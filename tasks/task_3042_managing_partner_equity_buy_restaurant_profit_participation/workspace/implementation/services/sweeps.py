"""Logical-clock sweeps (PRD §2.4, §3.1, §3.2, §3.3, §3.9, §3.10).

Setting the clock fires every time-based sweep: contract funding lapse, contract
expiry at term end, market partner agreement expiry, grant vesting, partner
training extension, and dispute escalation. Each mutation bumps the entity's own
version and refreshes its own updated_at; cascades never reuse a parent's bump.
"""

from datetime import date as _date, timedelta

import db
from services import domain
from util import touch


def forfeit_grants_on_withdrawal(partner):
    """§3.7/§3.10 cascade: every EARNED/VESTING grant of a withdrawn partner is
    FORFEITED and its units credited back to the program pool."""
    for g in db.award_grants.values():
        if g["partner_id"] == partner["id"] and g["status"] in ("EARNED", "VESTING"):
            g["status"] = "FORFEITED"
            touch(g)
            program = db.award_programs.get(g["program_id"])
            if program is not None:
                program["units_reserved"] = program["units_reserved"] - g["units_awarded"]
                touch(program)


def withdraw_partner(partner):
    """Move a partner to WITHDRAWN and fire the grant-forfeiture cascade."""
    partner["status"] = "WITHDRAWN"
    touch(partner)
    forfeit_grants_on_withdrawal(partner)


def run_sweeps():
    """Fire all clock-driven sweeps against the current logical clock.

    Returns the number of sweeps applied (each entity that changed state counts).
    """
    now = db.clock_now()
    today = now.date()
    applied = 0

    # Contract funding lapse: PENDING_FUNDING -> LAPSED when the funding window has run out.
    for c in db.contracts.values():
        if c["status"] != "PENDING_FUNDING":
            continue
        deadline = c["submitted_at"] + timedelta(days=domain.FUNDING_WINDOW_DAYS)
        if now >= deadline:
            for pay in db.buy_in_payments.values():
                if pay["contract_id"] == c["id"] and pay["status"] == "POSTED":
                    pay["status"] = "REFUNDED"
                    touch(pay)
            c["buy_in_escrow_cents"] = 0
            c["status"] = "LAPSED"
            touch(c)
            partner = db.partners.get(c["partner_id"])
            if partner is not None and partner["status"] != "WITHDRAWN":
                withdraw_partner(partner)
            applied += 1

    # Contract expiry: ACTIVE or RENEWAL_OFFERED -> EXPIRED at term end (exclusive).
    for c in db.contracts.values():
        if c["status"] not in ("ACTIVE", "RENEWAL_OFFERED"):
            continue
        term_end = _date.fromisoformat(c["term_end_date"])
        if today >= term_end:
            c["status"] = "EXPIRED"
            touch(c)
            partner = db.partners.get(c["partner_id"])
            if partner is not None and partner["status"] == "PLACED":
                partner["status"] = "CERTIFIED"
                partner["placed_restaurant_id"] = None
                touch(partner)
            applied += 1

    # Agreement expiry: ACTIVE -> EXPIRED once the clock date passes coverage_end_date.
    for a in db.agreements.values():
        if a["status"] != "ACTIVE":
            continue
        coverage_end = _date.fromisoformat(a["coverage_end_date"])
        if today > coverage_end:
            a["status"] = "EXPIRED"
            touch(a)
            applied += 1

    # Grant vesting: VESTING -> VESTED once the logical clock's date reaches
    # the grant's created_at date plus VESTING_DAYS (PRD §3.10 — a date-based
    # comparison; the creation time of day is irrelevant).
    for g in db.award_grants.values():
        if g["status"] != "VESTING":
            continue
        created_date = _date.fromisoformat(g["created_at"][:10])
        if today >= created_date + timedelta(days=domain.VESTING_DAYS):
            g["status"] = "VESTED"
            touch(g)
            applied += 1

    # Partner training extension: IN_TRAINING -> TRAINING_EXTENDED past MAX_TRAINING_WEEKS.
    for p in db.partners.values():
        if p["status"] != "IN_TRAINING":
            continue
        if domain.training_weeks_accrued(p) > domain.MAX_TRAINING_WEEKS:
            p["status"] = "TRAINING_EXTENDED"
            touch(p)
            applied += 1

    # Dispute escalation: EVIDENCE_REQUESTED -> ESCALATED past filed_at + escalation days.
    for d in db.disputes.values():
        if d["status"] != "EVIDENCE_REQUESTED":
            continue
        if now > d["filed_at"] + timedelta(days=domain.DISPUTE_ESCALATION_DAYS):
            d["status"] = "ESCALATED"
            touch(d)
            applied += 1

    return applied
