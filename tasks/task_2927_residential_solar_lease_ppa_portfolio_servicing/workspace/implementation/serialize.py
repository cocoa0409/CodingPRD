"""Resource views. Derived, clock-dependent fields are refreshed on read."""
import calc
from core import public, store


def agreement_view(ag):
    """monitoring_status / open_outage_count / excused_downtime_minutes and
    current_contract_year are projections (PRD §2.8, §2.9, §3.1) and are
    re-derived on every read; no version is advanced by a read."""
    calc.derive_monitoring(ag)
    calc.derive_excused_downtime(ag)
    ag["current_contract_year"] = calc.current_contract_year(ag)
    return public(ag)


def homeowner_view(h):
    return public(h)


def tariff_view(t):
    return public(t)


def period_view(p):
    return public(p)


def true_up_view(t):
    return public(t)


def outage_view(e):
    """downtime_minutes and severity float against the clock while the event is
    open (PRD §3.5); once resolved both are frozen."""
    from core import clock, parse_instant
    if e["status"] in ("OPEN", "TRIAGED", "DISPATCHED"):
        detected = parse_instant(e["detected_at"])
        minutes = calc.elapsed_minutes(detected, clock.now())
        if minutes < 0:
            minutes = 0
        e["downtime_minutes"] = minutes
    return public(e)


def truck_roll_view(r):
    return public(r)


def roof_work_order_view(o):
    return public(o)


def transfer_case_view(c):
    return public(c)


def ucc_filing_view(f):
    return public(f)


def election_view(el):
    return public(el)


def warranty_claim_view(w):
    return public(w)
