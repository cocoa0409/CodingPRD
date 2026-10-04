"""Lazy time-based transitions and cross-entity cascades."""
from __future__ import annotations

from datetime import date

from db import db
from response import touch

# ---------------------------------------------------------------------------
# low-level queries
# ---------------------------------------------------------------------------

def grants_of_agreement(agreement_id):
    return [g for g in db.likeness_grants.values() if g["agreement_id"] == agreement_id]


def grants_of_athlete(athlete_id):
    return [g for g in db.likeness_grants.values() if g["athlete_id"] == athlete_id]


def athlete_has_granted(athlete_id):
    return any(g["grant_status"] == "GRANTED" for g in grants_of_athlete(athlete_id))


def athlete_eligibility_refresh(athlete_id):
    a = db.athletes.get(athlete_id)
    if not a:
        return
    new = "ELIGIBLE" if athlete_has_granted(athlete_id) else "INELIGIBLE"
    if a["athlete_status"] != new:
        a["athlete_status"] = new
        touch(a)


def seasons_of_agreement(agreement_id):
    return [s for s in db.seasons.values() if s["agreement_id"] == agreement_id]


def drops_of_season(season_id):
    return [d for d in db.content_drops.values() if d["season_id"] == season_id]


def drops_featuring(athlete_id):
    return [d for d in db.content_drops.values() if d.get("featured_athlete_id") == athlete_id]


def wallets_of_season(season_id):
    return [w for w in db.wallets.values() if w["season_id"] == season_id]


def programs_of_season(season_id):
    return [p for p in db.tournaments.values() if p["season_id"] == season_id]


def editions_of_season(season_id):
    return [e for e in db.editions.values() if e["season_id"] == season_id]


def statements_of_agreement(agreement_id):
    return [s for s in db.royalty_statements.values() if s["agreement_id"] == agreement_id]


def cases_of_agreement(agreement_id):
    return [c for c in db.audit_cases.values() if c["agreement_id"] == agreement_id]


def cases_of_statement(statement_id):
    return [c for c in db.audit_cases.values() if c["statement_id"] == statement_id]


def licenses_of_asset(asset_id):
    return [l for l in db.audio_licenses.values() if l["asset_id"] == asset_id]


def open_statement_for_agreement(agreement_id):
    """The 'open royalty statement' for held attribution: status OPEN, else most
    recent PROVISIONAL; else None."""
    stmts = statements_of_agreement(agreement_id)
    for st in sorted(stmts, key=lambda s: (s["created_at"], s["id"]), reverse=True):
        if st["statement_status"] == "OPEN":
            return st
    for st in sorted(stmts, key=lambda s: (s["created_at"], s["id"]), reverse=True):
        if st["statement_status"] == "PROVISIONAL":
            return st
    return None


# ---------------------------------------------------------------------------
# held royalty attribution (accrue first, then attribute holds; round half up)
# ---------------------------------------------------------------------------

def round_half_up_cents(numer: int, denom: int = 10000) -> int:
    # round_half_up(numer / denom) for numer >= 0
    return (2 * numer + denom) // (2 * denom)


def held_amount_for_grant(grant) -> int:
    st = open_statement_for_agreement(grant["agreement_id"])
    if st is None:
        return 0
    accrued = st.get("accrued_royalty_cents") or 0
    return round_half_up_cents(accrued * grant["royalty_share_bps"])


def increase_held(grant, amount: int):
    st = open_statement_for_agreement(grant["agreement_id"])
    if st is not None and amount:
        st["held_royalty_cents"] = (st.get("held_royalty_cents") or 0) + amount
        touch(st)


def decrease_held(grant, amount: int):
    st = open_statement_for_agreement(grant["agreement_id"])
    if st is not None and amount:
        st["held_royalty_cents"] = (st.get("held_royalty_cents") or 0) - amount
        touch(st)


# ---------------------------------------------------------------------------
# drop cascade helpers
# ---------------------------------------------------------------------------

def hold_drops_for_athlete(athlete_id):
    for d in drops_featuring(athlete_id):
        if d["drop_status"] == "RELEASED":
            d["drop_status"] = "HELD"
            d["_held_reason"] = "LIKENESS"
            touch(d)


def release_drops_for_athlete(athlete_id):
    if not athlete_has_granted(athlete_id):
        return
    for d in drops_featuring(athlete_id):
        if d["drop_status"] == "HELD" and d.get("_held_reason") == "LIKENESS":
            d["drop_status"] = "RELEASED"
            d["_held_reason"] = None
            touch(d)


def cancel_drops_for_athlete(athlete_id):
    for d in drops_featuring(athlete_id):
        if d["drop_status"] == "HELD":
            d["drop_status"] = "CANCELED"
            d["_held_reason"] = None
            touch(d)


# ---------------------------------------------------------------------------
# grant lifecycle primitives (used by direct endpoints and cascades)
# ---------------------------------------------------------------------------

def suspend_grant(grant, reason: str):
    """GRANTED -> SUSPENDED with full cascade."""
    grant["grant_status"] = "SUSPENDED"
    grant["suspended_reason"] = reason
    amt = held_amount_for_grant(grant)
    grant["_held_amount"] = amt
    touch(grant)
    athlete_id = grant["athlete_id"]
    athlete_eligibility_refresh(athlete_id)
    if not athlete_has_granted(athlete_id):
        hold_drops_for_athlete(athlete_id)
    if amt:
        increase_held(grant, amt)


def reinstate_grant(grant):
    """SUSPENDED -> GRANTED with compensating cascade."""
    grant["grant_status"] = "GRANTED"
    grant["suspended_reason"] = None
    amt = grant.get("_held_amount") or 0
    grant["_held_amount"] = 0
    touch(grant)
    athlete_id = grant["athlete_id"]
    athlete_eligibility_refresh(athlete_id)
    release_drops_for_athlete(athlete_id)
    if amt:
        decrease_held(grant, amt)


def revoke_grant(grant):
    """SUSPENDED -> REVOKED (terminal)."""
    amt = grant.get("_held_amount") or 0
    grant["_held_amount"] = 0
    grant["grant_status"] = "REVOKED"
    grant["suspended_reason"] = None
    touch(grant)
    athlete_id = grant["athlete_id"]
    athlete_eligibility_refresh(athlete_id)
    if not athlete_has_granted(athlete_id):
        cancel_drops_for_athlete(athlete_id)
    if amt:
        decrease_held(grant, amt)


def expire_grant(grant):
    grant["grant_status"] = "EXPIRED"
    touch(grant)
    athlete_eligibility_refresh(grant["athlete_id"])


# ---------------------------------------------------------------------------
# wallet ledger primitives
# ---------------------------------------------------------------------------

def wallet_balance(wallet_id) -> int:
    bal = 0
    for le in db.ledger_entries.values():
        if le["wallet_id"] != wallet_id:
            continue
        if le["direction"] == "CREDIT":
            bal += le["amount_vc"]
        else:
            bal -= le["amount_vc"]
    return bal


def post_ledger(wallet_id, direction, amount_vc, reason_code, reference_id=None):
    """Append a POSTED ledger entry (assumes validations already done by caller)."""
    from response import stamp_new
    le = {
        "wallet_id": wallet_id,
        "direction": direction,
        "amount_vc": amount_vc,
        "reason_code": reason_code,
        "reference_id": reference_id,
        "entry_status": "POSTED",
    }
    stamp_new(le, common=False)
    db.ledger_entries[le["id"]] = le
    w = db.wallets.get(wallet_id)
    if w is not None:
        w["vc_balance"] = wallet_balance(wallet_id)
        touch(w)
    # REFUND credit referencing a TournamentEntry flips fee_paid to false
    if reason_code == "REFUND" and reference_id is not None:
        te = db.tournament_entries.get(reference_id)
        if te is not None:
            te["fee_paid"] = False
    return le


def refund_entry(entry, program):
    """Refund an entry's fee via a REFUND credit (when fee was paid)."""
    if entry["fee_paid"] and program["entry_fee_vc"] > 0:
        post_ledger(entry["wallet_id"], "CREDIT", program["entry_fee_vc"], "REFUND", entry["id"])
        entry["fee_paid"] = False
    if entry["entry_status"] in ("REGISTERED", "CONFIRMED"):
        entry["entry_status"] = "REFUNDED"


# ---------------------------------------------------------------------------
# prize pool projection
# ---------------------------------------------------------------------------

def entries_of_program(program_id):
    return [e for e in db.tournament_entries.values() if e["program_id"] == program_id]


def prizes_of_program(program_id):
    return [p for p in db.tournament_prizes.values() if p["program_id"] == program_id]


def compute_pool(program, variant: str) -> int:
    pool = 0
    for e in entries_of_program(program["id"]):
        if variant == "PROJECTED":
            if e["entry_status"] in ("REGISTERED", "CONFIRMED"):
                pool += program["entry_fee_vc"]
        else:  # FINAL
            if e["entry_status"] == "CONFIRMED":
                pool += program["entry_fee_vc"]
    return pool


def allocate_pool(pool: int, prizes):
    """floor per row (placement ASC), remainder to placement 1. Returns {prize_id: amount}."""
    rows = sorted(prizes, key=lambda p: p["placement"])
    amounts = {}
    allocated = 0
    for p in rows:
        amt = (pool * p["share_bps"]) // 10000
        amounts[p["id"]] = amt
        allocated += amt
    remainder = pool - allocated
    if rows and remainder:
        first = rows[0]
        amounts[first["id"]] = amounts[first["id"]] + remainder
    return amounts


def recompute_projections(program):
    pool = compute_pool(program, "PROJECTED")
    program["prize_pool_vc"] = pool
    prizes = [p for p in prizes_of_program(program["id"]) if p["prize_status"] in ("PLANNED", "PROJECTED")]
    amounts = allocate_pool(pool, prizes)
    for p in prizes:
        if p["prize_status"] == "PLANNED":
            p["prize_status"] = "PROJECTED"
        p["projected_amount_vc"] = amounts.get(p["id"], 0)
        touch(p)
    touch(program)


# ---------------------------------------------------------------------------
# season-level cascades
# ---------------------------------------------------------------------------

def cascade_season_sunset(season):
    for d in drops_of_season(season["id"]):
        if d["drop_status"] == "RELEASED":
            d["drop_status"] = "ENDED"
            touch(d)
    for w in wallets_of_season(season["id"]):
        if w["wallet_status"] == "OPEN":
            w["wallet_status"] = "FROZEN"
            touch(w)
    for p in programs_of_season(season["id"]):
        if p["program_status"] in ("ANNOUNCED", "REGISTRATION_OPEN"):
            cancel_program(p)


def cancel_program(program):
    program["program_status"] = "CANCELED"
    for e in entries_of_program(program["id"]):
        refund_entry(e, program)
    for p in prizes_of_program(program["id"]):
        if p["prize_status"] in ("PLANNED", "PROJECTED"):
            p["prize_status"] = "VOIDED"
            touch(p)
    touch(program)


def cascade_agreement_expire(agreement):
    agreement["agreement_status"] = "EXPIRED"
    touch(agreement)
    for s in seasons_of_agreement(agreement["id"]):
        if s["season_status"] == "LIVE":
            s["season_status"] = "SUNSET"
            touch(s)
            cascade_season_sunset(s)
    for g in grants_of_agreement(agreement["id"]):
        if g["grant_status"] == "GRANTED":
            expire_grant(g)


def cascade_agreement_terminate(agreement):
    for g in grants_of_agreement(agreement["id"]):
        if g["grant_status"] in ("PENDING", "GRANTED", "SUSPENDED"):
            if g["grant_status"] == "SUSPENDED":
                amt = g.get("_held_amount") or 0
                g["_held_amount"] = 0
                if amt:
                    decrease_held(g, amt)
            g["grant_status"] = "REVOKED"
            g["suspended_reason"] = None
            touch(g)
            athlete_eligibility_refresh(g["athlete_id"])
    for s in seasons_of_agreement(agreement["id"]):
        if s["season_status"] in ("PRELAUNCH", "LIVE"):
            s["season_status"] = "ARCHIVED"
            touch(s)
            for d in drops_of_season(s["id"]):
                if d["drop_status"] not in ("ENDED", "CANCELED"):
                    d["drop_status"] = "CANCELED"
                    touch(d)
    # drops under this agreement's seasons not already terminal -> CANCELED
    # (covered above for PRELAUNCH/LIVE seasons; also handle SUNSET seasons)
    for s in seasons_of_agreement(agreement["id"]):
        for d in drops_of_season(s["id"]):
            if d["drop_status"] not in ("ENDED", "CANCELED"):
                d["drop_status"] = "CANCELED"
                touch(d)


def maybe_block_asset(asset_id):
    """Move asset CLEARED -> BLOCKED when no other ACTIVE license covers it."""
    asset = db.audio_assets.get(asset_id)
    if asset is None:
        return
    others = [l for l in licenses_of_asset(asset_id) if l["license_status"] == "ACTIVE"]
    if not others and asset["asset_status"] == "CLEARED":
        asset["asset_status"] = "BLOCKED"
        touch(asset)


# ---------------------------------------------------------------------------
# lazy clock-driven evaluation (no version bumps, per spec only listed ones do)
# ---------------------------------------------------------------------------

def lazy_eval():
    today = db.now_date()
    now_dt = db.now()
    # agreements: ACTIVE past term_end_on -> EXPIRED
    for ag in list(db.agreements.values()):
        if ag["agreement_status"] == "ACTIVE" and today > ag["_term_end"]:
            cascade_agreement_expire(ag)
    # likeness grants: GRANTED past term_end_on -> EXPIRED
    for g in list(db.likeness_grants.values()):
        if g["grant_status"] == "GRANTED" and today > g["_term_end"]:
            expire_grant(g)
    # audio licenses: ACTIVE past term_end_on -> LAPSED
    for lic in list(db.audio_licenses.values()):
        if lic["license_status"] == "ACTIVE" and today > lic["_term_end"]:
            lic["license_status"] = "LAPSED"
            touch(lic)
            maybe_block_asset(lic["asset_id"])
    # content drops: RELEASED at/past scheduled_end_at -> ENDED
    for d in list(db.content_drops.values()):
        if d["drop_status"] == "RELEASED" and now_dt >= d["_sched_end"]:
            d["drop_status"] = "ENDED"
            touch(d)
    # tournaments: REGISTRATION_OPEN at/past registration_closes_at -> close
    for p in list(db.tournaments.values()):
        if p["program_status"] == "REGISTRATION_OPEN" and now_dt >= p["_reg_closes"]:
            close_registration(p)


def close_registration(program):
    program["program_status"] = "REGISTRATION_CLOSED"
    for e in entries_of_program(program["id"]):
        if e["entry_status"] == "REGISTERED":
            e["entry_status"] = "CONFIRMED" if e["fee_paid"] else "REFUNDED"
    touch(program)
