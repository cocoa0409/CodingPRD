"""Domain helpers: record lifecycle, entity lookups, shared cascades and sweeps."""
import random
import uuid
from datetime import timedelta

import calc
from errors import err
from store import DB, fmt_ts, parse_ts


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def pub(rec):
    """Public view of a record: strip internal (underscore-prefixed) keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def new_record(table, fields, common=True):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = DB.now_iso()
    if common:
        rec["updated_at"] = DB.now_iso()
        rec["version"] = 1
    rec["_seq"] = DB.next_seq()
    table[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (cascade mutations included)."""
    if "updated_at" in rec:
        rec["updated_at"] = DB.now_iso()
    if "version" in rec:
        rec["version"] += 1


# ---------------------------------------------------------------------------
# Entity lookups (resource-specific 404s, PRD §2.9)
# ---------------------------------------------------------------------------

def get_taxpayer(tid):
    t = DB.taxpayers.get(tid)
    if t is None:
        err("ERR_TAXPAYER_NOT_FOUND")
    return t


def get_return(rid):
    r = DB.returns.get(rid)
    if r is None:
        err("ERR_RETURN_NOT_FOUND")
    return r


def get_report(rid):
    r = DB.reports.get(rid)
    if r is None:
        err("ERR_REPORT_NOT_FOUND")
    return r


def get_case(cid):
    c = DB.cases.get(cid)
    if c is None:
        err("ERR_CASE_NOT_FOUND")
    return c


def get_conflict(cid):
    c = DB.conflicts.get(cid)
    if c is None:
        err("ERR_CONFLICT_NOT_FOUND")
    return c


def get_preparer(pid):
    p = DB.preparers.get(pid)
    if p is None:
        err("ERR_PREPARER_NOT_FOUND")
    return p


def get_alert(aid):
    a = DB.alerts.get(aid)
    if a is None:
        err("ERR_ALERT_NOT_FOUND")
    return a


def get_office(oid):
    o = DB.offices.get(oid)
    if o is None:
        err("ERR_OFFICE_NOT_FOUND")
    return o


def get_disbursement(did):
    d = DB.disbursements.get(did)
    if d is None:
        err("ERR_DISBURSEMENT_NOT_FOUND")
    return d


def get_config(cid):
    c = DB.configs.get(cid)
    if c is None:
        err("ERR_CONFIG_NOT_FOUND")
    return c


def get_hold(hid):
    h = DB.holds.get(hid)
    if h is None:
        err("ERR_HOLD_NOT_FOUND")
    return h


def get_advocate_case(aid):
    a = DB.advocate_cases.get(aid)
    if a is None:
        err("ERR_ADVOCATE_CASE_NOT_FOUND")
    return a


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def active_pin(taxpayer_id, tax_year):
    for p in DB.pins.values():
        if (p["taxpayer_id"] == taxpayer_id and p["tax_year"] == tax_year
                and p["status"] == "ACTIVE"):
            return p
    return None


def hold_for_return(return_id):
    for h in DB.holds.values():
        if h["return_id"] == return_id:
            return h
    return None


def open_hold_for_return(return_id):
    h = hold_for_return(return_id)
    if h is not None and h["status"] == "OPEN":
        return h
    return None


def open_case_for_return(return_id):
    for c in DB.cases.values():
        if c["return_id"] == return_id and c["status"] not in ("VERIFIED", "EXPIRED"):
            return c
    return None


def verified_case_for_return(return_id):
    for c in DB.cases.values():
        if c["return_id"] == return_id and c["status"] == "VERIFIED":
            return c
    return None


def disbursement_for_return(return_id):
    for d in DB.disbursements.values():
        if d["return_id"] == return_id:
            return d
    return None


def claim_for(return_id, dependent_tin):
    for c in DB.claims.values():
        if c["return_id"] == return_id and c["dependent_tin"] == dependent_tin:
            return c
    return None


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

def _mint_pin_value(taxpayer_id, tax_year):
    existing = {p["pin_value"] for p in DB.pins.values()
                if p["taxpayer_id"] == taxpayer_id and p["tax_year"] == tax_year}
    while True:
        value = "%06d" % random.randint(0, 999999)
        if value not in existing:
            return value


def create_pin(taxpayer, tax_year, delivery_channel):
    """Mint an ACTIVE pin; supersede any prior ACTIVE pin of the same pair."""
    prior = active_pin(taxpayer["id"], tax_year)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    return new_record(DB.pins, {
        "taxpayer_id": taxpayer["id"],
        "tax_year": tax_year,
        "pin_value": _mint_pin_value(taxpayer["id"], tax_year),
        "delivery_channel": delivery_channel,
        "status": "ACTIVE",
    })


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------

def create_hold(ret, zone, reason_codes):
    return new_record(DB.holds, {
        "return_id": ret["id"],
        "risk_score": ret["risk_score"],
        "model_version": ret["scoring_model_version"],
        "zone": zone,
        "reason_codes": list(reason_codes),
        "priority_review": False,
        "status": "OPEN",
    })


# ---------------------------------------------------------------------------
# Dependent-conflict resolution and the adjustment cascade
# ---------------------------------------------------------------------------

def apply_dependent_adjustment(loser):
    """dependent_conflict_adjustment: strip one credit from the losing return."""
    delta = min(calc.DEPENDENT_CREDIT_CENTS, loser["claimed_refund_cents"])
    loser["claimed_refund_cents"] -= delta
    loser["adjustment_cents"] -= delta
    touch(loser)
    if loser["status"] == "REFUND_SCHEDULED":
        d = disbursement_for_return(loser["id"])
        if d is not None and d["status"] == "SCHEDULED":
            d["_adj_events"].append({"delta": -delta, "date": DB.now().date().isoformat()})
            d["base_cents"] = loser["claimed_refund_cents"] + loser["adjustment_cents"]
            d["provisional_interest_cents"] = calc.provisional_interest(
                loser, d["base_cents"], d["scheduled_at"])
            d["amount_cents"] = d["base_cents"] + d["provisional_interest_cents"]
            touch(d)


def resolve_conflict(conflict, resolution, reason):
    """Apply a conflict resolution: winner claim SUSTAINED, loser DISALLOWED.

    ANALYST_DECISION / DEFAULT_NO_EVIDENCE also run the adjustment cascade on
    the losing return; FRAUD_FORFEIT applies no adjustment (the fraud cascade
    already disallowed the losing claim and denied the whole refund).
    """
    conflict["resolution"] = resolution
    conflict["resolved_reason"] = reason
    conflict["status"] = "RESOLVED"
    touch(conflict)
    if resolution == "FIRST_FILER":
        win_ret_id, lose_ret_id = conflict["return_a_id"], conflict["return_b_id"]
    else:
        win_ret_id, lose_ret_id = conflict["return_b_id"], conflict["return_a_id"]
    win_claim = claim_for(win_ret_id, conflict["dependent_tin"])
    lose_claim = claim_for(lose_ret_id, conflict["dependent_tin"])
    if win_claim is not None and win_claim["status"] == "CONTESTED":
        win_claim["status"] = "SUSTAINED"
        touch(win_claim)
    if lose_claim is not None and lose_claim["status"] == "CONTESTED":
        lose_claim["status"] = "DISALLOWED"
        touch(lose_claim)
    if reason != "FRAUD_FORFEIT":
        loser = DB.returns.get(lose_ret_id)
        if loser is not None:
            apply_dependent_adjustment(loser)


# ---------------------------------------------------------------------------
# Fraud-confirmation cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def fraud_cascade(ret):
    """Side effects of TaxReturn -> FRAUD_CONFIRMED (status already set)."""
    hold = open_hold_for_return(ret["id"])
    if hold is not None:
        hold["status"] = "RESOLVED_FRAUD"
        touch(hold)
    for c in DB.cases.values():
        if c["return_id"] == ret["id"] and c["status"] not in ("VERIFIED", "EXPIRED"):
            c["status"] = "EXPIRED"
            touch(c)
    for cl in DB.claims.values():
        if cl["return_id"] == ret["id"] and cl["status"] in ("CLAIMED", "CONTESTED"):
            cl["status"] = "DISALLOWED"
            touch(cl)
    for cf in list(DB.conflicts.values()):
        if cf["status"] != "OPEN":
            continue
        if cf["return_a_id"] == ret["id"] or cf["return_b_id"] == ret["id"]:
            winner = "SECOND_FILER" if cf["return_a_id"] == ret["id"] else "FIRST_FILER"
            resolve_conflict(cf, winner, "FRAUD_FORFEIT")


# ---------------------------------------------------------------------------
# Scheme detection scans (calculations.preparer_velocity_scan)
# ---------------------------------------------------------------------------

def create_alert(pattern_type, preparer_id, evidence):
    return new_record(DB.alerts, {
        "preparer_id": preparer_id,
        "pattern_type": pattern_type,
        "evidence": evidence,
        "confirmed_by_user_id": None,
        "status": "FLAGGED",
    })


def _windowed_return_ids(rows):
    ordered = sorted(rows, key=lambda r: (r["received_at"], r["created_at"], r["_seq"]))
    return [r["id"] for r in ordered]


def velocity_scans(new_ret):
    """Run after a successful return intake. Counts compare with >= (a count
    exactly at the threshold fires)."""
    now = DB.now()
    # Scan A: PREPARER_NETWORK_VELOCITY
    if new_ret["preparer_id"] is not None and new_ret["bank_product"] == "REFUND_TRANSFER":
        pid = new_ret["preparer_id"]
        flagged = any(a["preparer_id"] == pid and a["status"] == "FLAGGED"
                      for a in DB.alerts.values())
        matching = [r for r in DB.returns.values()
                    if r["preparer_id"] == pid
                    and r["bank_product"] == "REFUND_TRANSFER"
                    and calc.in_velocity_window(r["received_at"], now)]
        if len(matching) >= calc.VELOCITY_THRESHOLD and not flagged:
            create_alert("PREPARER_NETWORK_VELOCITY", pid, {
                "return_ids": _windowed_return_ids(matching),
                "window_days": calc.VELOCITY_WINDOW_DAYS,
                "match_count": len(matching),
            })
    # Scan B: BANK_PRODUCT_CLUSTER
    fp = new_ret["bank_account_fingerprint"]
    if fp is not None:
        flagged = any(a["status"] == "FLAGGED" and a["evidence"].get("fingerprint") == fp
                      for a in DB.alerts.values())
        matching = [r for r in DB.returns.values()
                    if r["bank_account_fingerprint"] == fp
                    and calc.in_velocity_window(r["received_at"], now)]
        distinct_taxpayers = {r["taxpayer_id"] for r in matching}
        if len(distinct_taxpayers) >= calc.ROUTING_THRESHOLD and not flagged:
            create_alert("BANK_PRODUCT_CLUSTER", None, {
                "return_ids": _windowed_return_ids(matching),
                "window_days": calc.VELOCITY_WINDOW_DAYS,
                "match_count": len(distinct_taxpayers),
                "fingerprint": fp,
            })


# ---------------------------------------------------------------------------
# Logical-clock sweeps (PRD §2.4): conflicts past their evidence window
# auto-resolve; appointments past end_at complete. Verification cases are
# deliberately NOT swept.
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    now = DB.now()
    for cf in list(DB.conflicts.values()):
        if cf["status"] != "OPEN":
            continue
        if parse_ts(cf["evidence_window_ends_at"]) < now:
            if cf["evidence_b_submitted"] and not cf["evidence_a_submitted"]:
                resolution = "SECOND_FILER"
            else:
                resolution = "FIRST_FILER"
            resolve_conflict(cf, resolution, "DEFAULT_NO_EVIDENCE")
    for appt in DB.appointments.values():
        if appt["status"] == "BOOKED" and parse_ts(appt["end_at"]) < now:
            appt["status"] = "COMPLETED"
            touch(appt)


def deadline_plus(days):
    return fmt_ts(DB.now() + timedelta(days=days))
