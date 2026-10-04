"""Invoice/ledger minting, effective-schedule resolution, accreditation math.

Appended to services.py namespace via import * from this module in services2
consumers; here we extend services by importing this file from services.
"""
from datetime import timedelta
from decimal import Decimal

import db
import clock
import services as S
from util import fmt_iso, parse_iso, add_years, round_half_up_cents, is_leap_year


def mint_ledger(registrar_id, invoice_id, amount_cents, entry_type):
    now = clock.now()
    e = {
        "id": db.new_id(),
        "registrar_id": registrar_id,
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "entry_type": entry_type,
        "created_at": fmt_iso(now),
    }
    db.ledger_entries[e["id"]] = e
    return e


def mint_invoice(registrar_id, domain_id, kind, base_cents, premium_surcharge_cents,
                 price_schedule_id):
    now = clock.now()
    total = base_cents + premium_surcharge_cents
    inv = db.new_common(now)
    inv.update({
        "registrar_id": registrar_id,
        "domain_id": domain_id,
        "kind": kind,
        "base_cents": base_cents,
        "premium_surcharge_cents": premium_surcharge_cents,
        "total_cents": total,
        "price_schedule_id": price_schedule_id,
        "status": "OPEN",
    })
    db.invoices[inv["id"]] = inv
    mint_ledger(registrar_id, inv["id"], -total, "DEBIT")
    return inv


def void_invoice(inv):
    if inv["status"] != "OPEN":
        return
    inv["status"] = "VOIDED"
    db.touch(inv, clock.now())
    mint_ledger(inv["registrar_id"], inv["id"], inv["total_cents"], "VOID_CREDIT")


def effective_schedule_for_registrar(registrar_id):
    """Greatest effective_on <= now among EFFECTIVE rows, subject to version pinning."""
    now = clock.now()
    registrar = db.registrars.get(registrar_id)
    candidates = [s for s in db.price_schedules.values() if s["status"] == "EFFECTIVE"]
    if registrar is not None and registrar.get("accredited_version") is not None:
        av = registrar["accredited_version"]
        pinned = [s for s in candidates if av < s["version"]]
        pool = pinned if pinned else candidates
    else:
        pool = candidates
    if not pool:
        return None
    return max(pool, key=lambda s: parse_iso(s["effective_on"]))


def effective_schedule_at(instant):
    """The schedule in force at the given instant: greatest effective_on <= instant."""
    chosen = None
    for s in db.price_schedules.values():
        if parse_iso(s["effective_on"]) <= instant:
            if chosen is None or parse_iso(s["effective_on"]) > parse_iso(chosen["effective_on"]):
                chosen = s
    return chosen


def lifecycle_invoice(registrar_id, domain, kind, years):
    """Mint a lifecycle invoice per calculations.lifecycle_invoice."""
    sched = effective_schedule_for_registrar(registrar_id)
    if kind == "CREATE":
        base = sched["create_fee_cents"] * years
    elif kind == "RENEW":
        base = sched["renew_fee_cents"] * years
    elif kind == "AUTO_RENEW":
        base = sched["renew_fee_cents"]
    elif kind == "RESTORE":
        base = sched["renew_fee_cents"] + sched["restore_fee_cents"]
    elif kind == "TRANSFER":
        base = sched["transfer_fee_cents"]
    else:
        raise ValueError("bad kind")
    if domain is not None and domain.get("premium"):
        surcharge = round_half_up_cents(Decimal(base) * S.PREMIUM_SURCHARGE_RATE)
    else:
        surcharge = 0
    return mint_invoice(registrar_id,
                        domain["id"] if domain else None,
                        kind, base, surcharge, sched["id"])


def accreditation_cost_provisional(reg):
    accredited_on = parse_iso(reg["accredited_on"])
    year = accredited_on.year
    days_in_year = 366 if is_leap_year(year) else 365
    dec31 = accredited_on.replace(month=12, day=31)
    remaining_days = (dec31.date() - accredited_on.date()).days + 1
    prorated = round_half_up_cents(
        Decimal(reg["annual_fee_cents"]) * Decimal(remaining_days) / Decimal(days_in_year))
    return reg["application_fee_cents"] + prorated + reg["escrow_deposit_cents"]


def accreditation_cost_audit(reg):
    return reg["application_fee_cents"] + reg["annual_fee_cents"] + reg["escrow_deposit_cents"]


def emit_notice(registrar_id, price_schedule_id, kind):
    now = clock.now()
    n = {
        "id": db.new_id(),
        "registrar_id": registrar_id,
        "price_schedule_id": price_schedule_id,
        "notice_kind": kind,
        "sent_at": fmt_iso(now),
        "created_at": fmt_iso(now),
    }
    db.notices[n["id"]] = n
    return n


def emit_announced_notices(schedule):
    for r in sorted(db.registrars.values(), key=lambda x: x["created_at"]):
        if r["status"] in ("ACTIVE", "SUSPENDED"):
            emit_notice(r["id"], schedule["id"], "PRICE_INCREASE_ANNOUNCED")


def emit_effective_notices(schedule):
    for r in sorted(db.registrars.values(), key=lambda x: x["created_at"]):
        if r["status"] in ("ACTIVE", "SUSPENDED"):
            av = r.get("accredited_version")
            if av is not None and av < schedule["version"]:
                emit_notice(r["id"], schedule["id"], "PRICE_INCREASE_EFFECTIVE")
